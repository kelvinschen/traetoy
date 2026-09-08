//! One authenticated, encrypted request/response stream over CoreBluetooth GATT.
use aes_gcm::{
    aead::{Aead, KeyInit},
    Aes256Gcm, Nonce,
};
use anyhow::{bail, Context, Result};
use hmac::{Hmac, Mac};
use serde::Deserialize;
use sha2::Sha256;
use std::{
    ffi::CString,
    path::Path,
    time::{Duration, Instant},
};
unsafe extern "C" {
    fn passport_ble_call(
        op: i32,
        name: *const std::ffi::c_char,
        data: *const u8,
        length: usize,
        out: *mut u8,
        capacity: usize,
        error: *mut std::ffi::c_char,
        error_size: usize,
        timeout_ms: u32,
    ) -> i32;
    fn passport_ble_disconnect();
}
#[derive(Clone, Deserialize)]
pub struct Pairing {
    pub device_id: String,
    pub key: String,
}
impl Pairing {
    pub fn load(path: &Path) -> Result<Self> {
        let p: Self = serde_json::from_slice(&std::fs::read(path)?)?;
        if hex::decode(&p.device_id)?.len() != 6 || hex::decode(&p.key)?.len() != 32 {
            bail!("invalid BLE pairing file");
        }
        Ok(p)
    }
}
fn call(op: i32, name: Option<&str>, data: &[u8], timeout: u32) -> Result<Vec<u8>> {
    let c = name.map(CString::new).transpose()?;
    let mut out = vec![0u8; 512];
    let mut error = [0i8; 512];
    let n = unsafe {
        passport_ble_call(
            op,
            c.as_ref().map_or(std::ptr::null(), |s| s.as_ptr()),
            data.as_ptr(),
            data.len(),
            out.as_mut_ptr(),
            out.len(),
            error.as_mut_ptr(),
            error.len(),
            timeout,
        )
    };
    if n < 0 {
        let e = unsafe { std::ffi::CStr::from_ptr(error.as_ptr()) }.to_string_lossy();
        bail!("{e}");
    }
    out.truncate(n as usize);
    Ok(out)
}
fn derive(key: &[u8], challenge: &[u8], label: &[u8]) -> [u8; 32] {
    let mut h = <Hmac<Sha256> as Mac>::new_from_slice(key).expect("HMAC key");
    h.update(label);
    h.update(challenge);
    h.finalize().into_bytes().into()
}
fn nonce(counter: u32) -> [u8; 12] {
    let mut n = [0; 12];
    n[8..].copy_from_slice(&counter.to_be_bytes());
    n
}
fn pack(s: &[u8]) -> Vec<u8> {
    let mut r = vec![1, (s.len() >> 8) as u8, s.len() as u8];
    let mut i = 0;
    while i < s.len() {
        let mut n = 1;
        while i + n < s.len() && n < 255 && s[i + n] == s[i] {
            n += 1;
        }
        r.extend([n as u8, s[i]]);
        i += n;
    }
    if r.len() > s.len() {
        let mut raw = vec![0];
        raw.extend(s);
        raw
    } else {
        r
    }
}
pub struct Ble {
    rx: Aes256Gcm,
    tx: Aes256Gcm,
    counter: u32,
    mtu: usize,
}
impl Ble {
    pub fn connect(pair: &Pairing, timeout: u32) -> Result<Self> {
        let info = match call(
            0,
            Some(&format!("Codex-{}", &pair.device_id[6..])),
            &[],
            timeout,
        ) {
            Ok(info) => info,
            Err(e) => {
                unsafe { passport_ble_disconnect() };
                return Err(e);
            }
        };
        if info.len() != 28 || &info[..4] != b"CPB1" || hex::encode(&info[4..10]) != pair.device_id
        {
            unsafe { passport_ble_disconnect() };
            bail!("BLE device identity/protocol mismatch");
        }
        let psk = hex::decode(&pair.key)?;
        let challenge = &info[10..26];
        let rx =
            Aes256Gcm::new_from_slice(&derive(&psk, challenge, b"passport-ble-v1-rx")).unwrap();
        let tx =
            Aes256Gcm::new_from_slice(&derive(&psk, challenge, b"passport-ble-v1-tx")).unwrap();
        let mtu = u16::from_be_bytes(info[26..28].try_into().unwrap()) as usize;
        if !(23..=517).contains(&mtu) {
            unsafe { passport_ble_disconnect() };
            bail!("invalid ATT MTU");
        }
        let mut ble = Self {
            rx,
            tx,
            counter: 0,
            mtu,
        };
        // A small authenticated no-op proves key possession before USB handover,
        // and establishes the session before a large first bitmap on a small MTU.
        if ble.exchange("CDXQ|END")? != "CDX_ERR invalid_or_busy" {
            bail!("unexpected BLE authentication probe response");
        }
        crate::log(&format!(
            "BLE authenticated: device={} ATT MTU={mtu}",
            pair.device_id
        ));
        Ok(ble)
    }
    fn encode(&mut self, line: &str) -> Result<Vec<u8>> {
        self.counter = self
            .counter
            .checked_add(1)
            .context("BLE counter exhausted")?;
        let counter = self.counter;
        let iv = nonce(counter);
        let raw = line.trim_end_matches(['\r', '\n']).as_bytes();
        if raw.is_empty() || raw.len() >= 7168 {
            bail!("BLE command length");
        }
        let ciphertext = self
            .rx
            .encrypt(Nonce::from_slice(&iv), pack(raw).as_ref())
            .map_err(|_| anyhow::anyhow!("BLE encryption failed"))?;
        let mut wire = counter.to_be_bytes().to_vec();
        wire.extend(ciphertext);
        Ok(wire)
    }
    fn write_wire(&self, wire: &[u8]) -> Result<()> {
        let counter = u32::from_be_bytes(wire[..4].try_into().unwrap());
        let id = ((counter - 1) % 65535 + 1) as u16;
        let max = (self.mtu - 3).min(244);
        let mut offset = 0;
        while offset < wire.len() {
            let end = (offset + max - 6).min(wire.len());
            let mut chunk = id.to_le_bytes().to_vec();
            chunk.extend((wire.len() as u16).to_le_bytes());
            chunk.extend((offset as u16).to_le_bytes());
            chunk.extend(&wire[offset..end]);
            call(1, None, &chunk, 2500)?;
            offset = end;
        }
        Ok(())
    }
    fn read_reply(&self, counter: u32) -> Result<String> {
        let iv = nonce(counter);
        let until = Instant::now() + Duration::from_secs(3);
        while Instant::now() < until {
            let reply = call(2, None, &[], 1500)?;
            if reply.len() >= 20 && reply[..4] == counter.to_be_bytes() {
                let plain = self
                    .tx
                    .decrypt(Nonce::from_slice(&iv), &reply[4..])
                    .map_err(|_| anyhow::anyhow!("BLE reply authentication failed"))?;
                return Ok(String::from_utf8(plain)?);
            }
            std::thread::sleep(Duration::from_millis(40));
        }
        bail!("BLE application acknowledgment timeout")
    }
    pub fn exchange(&mut self, line: &str) -> Result<String> {
        let wire = self.encode(line)?;
        self.write_wire(&wire)?;
        self.read_reply(self.counter)
    }
}
impl Drop for Ble {
    fn drop(&mut self) {
        unsafe { passport_ble_disconnect() };
    }
}
/// Live negative tests use an intentionally unsupported command, so the screen is untouched.
pub fn self_test(pair: &Pairing) -> Result<()> {
    let mut ble = Ble::connect(pair, 8000)?;
    let wire = ble.encode("CDXQ|END")?;
    ble.write_wire(&wire)?;
    if ble.read_reply(ble.counter)? != "CDX_ERR invalid_or_busy" {
        bail!("unexpected diagnostic response");
    }
    crate::log("BLE CHECK encrypted request/reply PASS");
    if ble.write_wire(&wire).is_ok() {
        bail!("replay accepted");
    }
    crate::log("BLE CHECK replay rejection PASS");
    let mut corrupt = ble.encode("CDXQ|END")?;
    *corrupt.last_mut().unwrap() ^= 1;
    if ble.write_wire(&corrupt).is_ok() {
        bail!("tampered tag accepted");
    }
    crate::log("BLE CHECK tamper rejection PASS");
    ble.exchange("CDXQ|END")?;
    let wire = ble.encode("CDXQ|END")?;
    let mut partial = vec![9, 0];
    partial.extend((wire.len() as u16).to_le_bytes());
    partial.extend([0, 0, wire[0]]);
    call(1, None, &partial, 2500)?;
    drop(ble);
    std::thread::sleep(Duration::from_millis(500));
    let mut ble = Ble::connect(pair, 8000)?;
    ble.exchange("CDXQ|END")?;
    drop(ble);
    crate::log("BLE CHECK partial-frame disconnect/reconnect PASS");
    std::thread::sleep(Duration::from_millis(500));
    let mut wrong = pair.clone();
    wrong.key = hex::encode([0x55; 32]);
    if Ble::connect(&wrong, 8000).is_ok() {
        bail!("wrong key accepted");
    }
    crate::log("BLE CHECK wrong-key rejection PASS");
    std::thread::sleep(Duration::from_millis(500));
    let mut ble = Ble::connect(pair, 8000)?;
    ble.exchange("CDXQ|END")?;
    crate::log("BLE CHECK final authenticated recovery PASS");
    Ok(())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn directional_keys_prevent_reflection_and_tag_rejects_tamper() {
        let key = [7; 32];
        let challenge = [9; 16];
        let a = derive(&key, &challenge, b"passport-ble-v1-rx");
        let b = derive(&key, &challenge, b"passport-ble-v1-tx");
        assert_ne!(a, b);
        let aes = Aes256Gcm::new_from_slice(&a).unwrap();
        let iv = nonce(1);
        let mut c = aes
            .encrypt(Nonce::from_slice(&iv), b"hello".as_ref())
            .unwrap();
        assert_eq!(
            aes.decrypt(Nonce::from_slice(&iv), c.as_ref()).unwrap(),
            b"hello"
        );
        c[0] ^= 1;
        assert!(aes.decrypt(Nonce::from_slice(&iv), c.as_ref()).is_err());
        assert_ne!(a, derive(&key, &[8; 16], b"passport-ble-v1-rx"));
    }
    #[test]
    fn payload_compression_has_bounded_raw_fallback() {
        assert_eq!(pack(b"abc"), b"\0abc");
        assert_eq!(pack(&[b'0'; 100]), [1, 0, 100, 100, b'0']);
    }
}
