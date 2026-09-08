//! Codex-specific framing and bitmap cache; transport stays reusable.
use crate::{
    device::Device,
    display::{identity, Transaction},
    render::raster,
};
use anyhow::Result;
pub trait Channel {
    fn ready(&mut self) -> Result<bool>;
    fn generation(&self) -> u64;
    fn exchange(&mut self, packet: &str, expected: &str, prefix: bool) -> Result<String>;
}
impl Channel for Device {
    fn ready(&mut self) -> Result<bool> {
        Device::ready(self, crate::codex::supports)
    }
    fn generation(&self) -> u64 {
        self.generation
    }
    fn exchange(&mut self, p: &str, e: &str, prefix: bool) -> Result<String> {
        Device::exchange(self, p, e, prefix)
    }
}
#[derive(PartialEq)]
struct ContentSignature {
    tasks: Vec<(String, String, String)>,
    alert_title: String,
    alert_project: String,
}
#[derive(Default)]
pub struct Sender {
    signature: Option<ContentSignature>,
    info_sent: Option<String>,
    generation: u64,
}
impl Sender {
    pub fn send(&mut self, device: &mut impl Channel, t: &Transaction) -> Result<String> {
        if !device.ready()? {
            anyhow::bail!("incompatible firmware");
        }
        if self.generation != device.generation() {
            self.signature = None;
            self.info_sent = None;
            self.generation = device.generation();
        }
        let signature = ContentSignature {
            tasks: t.titles.clone(),
            alert_title: t.alert_title.clone(),
            alert_project: t.alert_project.clone(),
        };
        if self.signature.as_ref() != Some(&signature) {
            let mut rows = t
                .titles
                .iter()
                .enumerate()
                .map(|(i, (id, title, project))| (i, id.clone(), title.clone(), project.clone()))
                .collect::<Vec<_>>();
            rows.push((
                16,
                "notification".into(),
                t.alert_title.clone(),
                t.alert_project.clone(),
            ));
            for (index, id, title, project) in rows {
                let bytes = raster(&title, &project, index == 16);
                let packet = format!(
                    "CDXP|{}|{index}|{}|{}|END\n",
                    t.seq,
                    identity(&id),
                    hex::encode(bytes)
                );
                device.exchange(&packet, &format!("CDX_TILE_ACK {} {index}", t.seq), false)?;
            }
            device.exchange(
                &format!("CDXL|{}|{}|END\n", t.seq, t.titles.len()),
                &format!("CDX_LIST_ACK {} count={}", t.seq, t.titles.len()),
                false,
            )?;
            self.signature = Some(signature);
        }
        if self.info_sent.as_ref() != Some(&t.info) {
            device.exchange(
                &format!("CDXI|{}|{}|END\n", t.seq, t.info),
                &format!("CDX_INFO_ACK {}", t.seq),
                false,
            )?;
            self.info_sent = Some(t.info.clone());
        }
        device.exchange(&t.metadata, &format!("CDX_META_ACK {}", t.seq), false)?;
        device.exchange(&t.packet, &format!("CDX_ACK {} ", t.seq), true)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    struct Fake {
        compatible: bool,
        writes: usize,
    }
    impl Channel for Fake {
        fn ready(&mut self) -> Result<bool> {
            Ok(self.compatible)
        }
        fn generation(&self) -> u64 {
            1
        }
        fn exchange(&mut self, _: &str, e: &str, _: bool) -> Result<String> {
            self.writes += 1;
            Ok(e.into())
        }
    }
    #[test]
    fn incompatible_firmware_receives_no_business_frames() {
        let t = Transaction {
            seq: 1,
            titles: vec![],
            alert_title: "".into(),
            alert_project: "".into(),
            packet: "CDX1".into(),
            metadata: "CDXM".into(),
            info: "info".into(),
            is_alert: false,
        };
        for compatible in [false, true] {
            let mut fake = Fake {
                compatible,
                writes: 0,
            };
            let result = Sender::default().send(&mut fake, &t);
            assert_eq!(result.is_ok(), compatible);
            assert_eq!(fake.writes > 0, compatible);
        }
    }
}
