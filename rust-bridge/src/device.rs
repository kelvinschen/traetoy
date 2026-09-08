use crate::ble::{Ble, Pairing};
use anyhow::{bail, Context, Result};
#[derive(Clone, Copy, PartialEq)]
pub enum Mode {
    Auto,
    Ble,
    Usb,
}
impl std::str::FromStr for Mode {
    type Err = anyhow::Error;
    fn from_str(s: &str) -> Result<Self> {
        match s {
            "auto" => Ok(Self::Auto),
            "ble" => Ok(Self::Ble),
            "usb" => Ok(Self::Usb),
            _ => bail!("transport must be auto, ble or usb"),
        }
    }
}
use serialport::{SerialPort, SerialPortType};
use std::{
    io::{Read, Write},
    time::{Duration, Instant},
};
pub struct Device {
    pub cancel: Option<std::sync::Arc<std::sync::atomic::AtomicBool>>,
    pub generation: u64,
    pub firmware: Option<crate::firmware::Firmware>,
    pub compatibility: String,
    identity_at: Option<Instant>,
    mode: Mode,
    pairing: Option<Pairing>,
    ble: Option<Ble>,
    fallback_until: Instant,
    usb_retry_at: Instant,
    path: Option<String>,
    port: Option<Box<dyn SerialPort>>,
}
impl Device {
    pub fn new(path: Option<String>, mode: Mode, pairing: Option<Pairing>) -> Self {
        Self {
            cancel: None,
            generation: 0,
            firmware: None,
            compatibility: "disconnected".into(),
            identity_at: None,
            mode,
            pairing,
            ble: None,
            fallback_until: Instant::now(),
            usb_retry_at: Instant::now(),
            path,
            port: None,
        }
    }
    pub fn close(&mut self) {
        // Graceful release avoids a stale USB lease when another client takes over.
        if self.port.is_some() {
            let _ = self.usb_exchange("CDXB|RELEASE|END\n", "CDX_RELEASE_ACK", false);
        }
        self.ble = None;
        self.port = None;
        self.invalidate_identity();
    }
    pub fn recover(&mut self) {
        self.invalidate_identity();
        if self.port.take().is_some() {
            // Close the failed USB endpoint before BLE fallback. Avoid retrying
            // a present but broken serial endpoint on every pending transaction.
            self.usb_retry_at = Instant::now() + Duration::from_secs(15);
        } else if self.ble.take().is_some() || Instant::now() >= self.fallback_until {
            self.fallback_until = Instant::now() + Duration::from_secs(5);
        }
    }
    fn usb_connect(&mut self) -> Result<()> {
        if self.port.is_some() {
            return Ok(());
        }
        let path = if let Some(p) = &self.path {
            p.clone()
        } else {
            let ports: Vec<_> = serialport::available_ports()?
                .into_iter()
                .filter(|p| !cfg!(target_os = "macos") || p.port_name.starts_with("/dev/cu."))
                .filter(|p| matches!(&p.port_type,SerialPortType::UsbPort(u) if u.vid==0x303a))
                .collect();
            if ports.len() != 1 {
                bail!("connect one Espressif device or specify --port");
            }
            ports[0].port_name.clone()
        };
        // A missing candidate must not interrupt working BLE on every retry.
        std::fs::metadata(&path).context("USB endpoint unavailable")?;
        if self.ble.take().is_some() {
            self.invalidate_identity();
            crate::log("BLE disconnected for USB takeover");
        }
        // Native USB Serial/JTAG interprets DTR/RTS transitions as reset
        // commands. Preserve them so USB takeover cannot reboot the device
        // and destroy device state or unread alerts.
        let port = serialport::new(&path, 115200)
            .timeout(Duration::from_millis(150))
            .preserve_dtr_on_open()
            .open()?;
        self.port = Some(port);
        self.invalidate_identity();
        crate::log(&format!("USB connected {path}"));
        Ok(())
    }
    fn usb_exchange(&mut self, packet: &str, expected: &str, prefix: bool) -> Result<String> {
        self.usb_connect()?;
        let port = self.port.as_mut().unwrap();
        for _ in 0..2 {
            port.write_all(packet.as_bytes())?;
            port.flush()?;
            let until = Instant::now() + Duration::from_secs(3);
            let mut line = Vec::new();
            while Instant::now() < until {
                let mut byte = [0u8];
                match port.read(&mut byte) {
                    Ok(1) => {
                        if byte[0] == b'\n' {
                            let s = String::from_utf8_lossy(&line).trim().to_string();
                            line.clear();
                            if if prefix {
                                s.starts_with(expected)
                            } else {
                                s == expected
                            } {
                                return Ok(s);
                            }
                            if s.starts_with("CDX_VIEW ") || s.starts_with("CDX_AUDIO_DONE") {
                                crate::log(&s);
                            }
                        } else if line.len() < 7168 {
                            line.push(byte[0]);
                        }
                    }
                    Err(e) if e.kind() == std::io::ErrorKind::TimedOut => {}
                    Err(e) => return Err(e.into()),
                    _ => {}
                }
            }
        }
        bail!("USB acknowledgment timeout")
    }
    fn connect(&mut self) -> Result<()> {
        if self.mode == Mode::Usb {
            return self.usb_connect();
        }
        if self.mode == Mode::Auto {
            if self.port.is_some() {
                return Ok(());
            }
            if Instant::now() >= self.usb_retry_at {
                // USB takes priority; usb_connect releases BLE before opening it.
                self.usb_retry_at = Instant::now() + Duration::from_secs(3);
                if self.usb_connect().is_ok() {
                    self.invalidate_identity();
                    return Ok(());
                }
            }
        }
        if self.ble.is_some() {
            return Ok(());
        }
        let pair = self
            .pairing
            .as_ref()
            .context("BLE pairing unavailable; connect USB or run scripts/pair-ble.py")?;
        if Instant::now() < self.fallback_until {
            bail!("waiting to reconnect BLE");
        }
        self.ble = Some(Ble::connect(pair, 6000)?);
        self.invalidate_identity();
        Ok(())
    }
    pub fn exchange(&mut self, packet: &str, expected: &str, prefix: bool) -> Result<String> {
        if self.cancel.as_ref().is_some_and(|s| crate::stopping(s)) {
            bail!("stopping");
        }
        if self.port.is_some() {
            return self.usb_exchange(packet, expected, prefix);
        }
        if let Some(ble) = self.ble.as_mut() {
            let result = ble.exchange(packet)?;
            if if prefix {
                result.starts_with(expected)
            } else {
                result == expected
            } {
                return Ok(result);
            }
            bail!("BLE command rejected: {result}");
        }
        bail!("no connected transport")
    }
    fn invalidate_identity(&mut self) {
        self.generation = self.generation.wrapping_add(1);
        self.firmware = None;
        self.identity_at = None;
        self.compatibility = "disconnected".into();
    }
    pub fn transport(&self) -> &str {
        if self.port.is_some() {
            "usb"
        } else if self.ble.is_some() {
            "ble"
        } else {
            "none"
        }
    }
    pub fn ready(&mut self, supports: fn(&crate::firmware::Firmware) -> bool) -> Result<bool> {
        self.connect()?;
        if self.identity_at.is_none_or(|t| {
            self.compatibility != "compatible" && t.elapsed() >= Duration::from_secs(30)
        }) {
            self.identity_at = Some(Instant::now());
            match self
                .exchange("PASSPORT?|END\n", "PASSPORT|", true)
                .and_then(|s| crate::firmware::Firmware::parse(&s))
            {
                Ok(f) => {
                    self.compatibility = if supports(&f) {
                        "compatible"
                    } else {
                        "unsupported"
                    }
                    .into();
                    self.firmware = Some(f);
                }
                Err(_) => {
                    self.compatibility = "update_required".into();
                    self.firmware = None;
                }
            }
        }
        Ok(self.compatibility == "compatible")
    }
}

/// Exercise the actual title/metadata/state protocol without ringing or creating alerts.
pub fn self_test(path: Option<String>, mode: Mode, pairing: Option<Pairing>) -> Result<()> {
    use crate::{
        display::{snapshot, Account},
        state::{Batch, State, Task},
    };
    let dbpath = std::env::temp_dir().join(format!(
        "passport-device-check-{}.sqlite3",
        std::process::id()
    ));
    let mut state = State::open(&dbpath)?;
    state.register("check", crate::now())?;
    let mut sender = crate::codex_wire::Sender::default();
    let mut device = Device::new(path, mode, pairing);
    let mut account = Account::default();
    let outcome = (|| -> Result<()> {
        for (round, count) in [0, 1, 2, 16, 16, 2, 0].into_iter().enumerate() {
            let remaining = [0, 1, 50, 96, 100, 96, -1][round];
            account.windows[0] = crate::display::Window {
                left: remaining,
                minutes: if remaining < 0 { 0 } else { 10080 },
                reset: "3h 07m".into(),
            };
            account.windows[1] = crate::display::Window {
                left: if round == 4 { 42 } else { -1 },
                minutes: if round == 4 { 300 } else { 0 },
                reset: "59m".into(),
            };
            account.quota_at = if round == 5 { 0. } else { crate::now() };
            account.reset_cards =
                [Some(0), Some(1), Some(3), Some(999), None, Some(3), None][round];
            account.cards = crate::info::cards(&serde_json::json!({"rateLimitResetCredits":{
                "credits": if round==0 { serde_json::Value::Null } else { serde_json::json!([
                    {"title":"Full reset","status":"available","grantedAt":1787356801i64,
                     "expiresAt":1789948801i64,"description":"Thanks for using Codex.","resetType":"codexRateLimits"}
                ]) }
            }}));
            if round == 4 {
                let card = account.cards.rows[0].clone();
                account.cards.rows = vec![card; 6];
            }
            let expected_resets = if round >= 5 {
                -1
            } else {
                account.reset_cards.unwrap_or(-1)
            };
            let expected_span = if round >= 5 {
                0
            } else {
                (270 * remaining + 50) / 100
            };
            let today = chrono::Local::now().date_naive();
            let rows: Vec<_> = (0..7)
                .filter(|i| round != 2 || i % 3 == 0)
                .map(|i| {
                    serde_json::json!({"startDate":(today-chrono::Duration::days(6-i)).to_string(),
                    "tokens": if round == 0 { 0 } else { (i+1)*1_000_000 }})
                })
                .collect();
            account.usage = crate::display::usage(&serde_json::json!({"dailyUsageBuckets":rows}));
            account.usage_at = if round >= 5 { 0. } else { crate::now() };
            let expected_points = if round >= 5 {
                0
            } else if round == 2 {
                3
            } else {
                7
            };
            let active = (0..count)
                .map(|i| Task {
                    source: "check".into(),
                    thread: format!("check-{i}"),
                    title: if round == 4 {
                        format!("不同标题 {i:02} 替换缓存并验证内存释放")
                    } else {
                        format!("BLE 验证任务 {i:02} 中文标题与传输完整性 {round}")
                    },
                    project: format!("project-{i} · devbox"),
                    turn: "check".into(),
                    started: Some(crate::now() - 120.),
                })
                .collect();
            state.apply(Batch {
                source: "check".into(),
                active,
                completed: vec![],
                checkpoint: crate::now(),
            })?;
            let tx = snapshot(&state, &account, 1_900_000_000 + round as i64, None, None)?;
            let began = Instant::now();
            let ack = sender.send(&mut device, &tx)?;
            if !ack.contains(&format!("tasks={count} ")) {
                bail!("task count mismatch: {ack}");
            }
            if !ack.contains(&format!("chart={expected_points}")) {
                bail!("chart point count mismatch: {ack}");
            }
            if !ack.contains(&format!("daily={expected_points}")) {
                bail!("daily label count mismatch: {ack}");
            }
            if !ack.contains(&format!("gauge={expected_span}")) {
                bail!("quota ring span mismatch: {ack}");
            }
            if !ack.contains(&format!("resets={expected_resets}")) {
                bail!("reset card count mismatch: {ack}");
            }
            if !ack.contains(&format!("cards={} ", account.cards.rows.len())) {
                bail!("card details mismatch: {ack}");
            }
            crate::log(&format!(
                "DEVICE CHECK count={count} elapsed_ms={} {ack}",
                began.elapsed().as_millis()
            ));
            let repeat = sender.send(&mut device, &tx)?;
            if !repeat.contains("unread=0 ") {
                bail!("diagnostic unexpectedly found unread alerts: {repeat}");
            }
        }
        Ok(())
    })();
    device.close();
    drop(state);
    let _ = std::fs::remove_file(dbpath);
    // No production state writes; synthetic fixtures are removed.
    outcome
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn retrying_during_cooldown_does_not_postpone_reconnection_forever() {
        let mut d = Device::new(None, Mode::Auto, None);
        d.recover();
        let until = d.fallback_until;
        d.recover();
        assert_eq!(until, d.fallback_until);
        assert!(until > Instant::now());
    }
}
