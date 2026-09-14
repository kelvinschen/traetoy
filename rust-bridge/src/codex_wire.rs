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
    fn waiting_alerts(&self) -> bool {
        false
    }
    fn exchange(&mut self, packet: &str, expected: &str, prefix: bool) -> Result<String>;
}
impl Channel for Device {
    fn ready(&mut self) -> Result<bool> {
        Device::ready(self, crate::codex::supports)
    }
    fn generation(&self) -> u64 {
        self.generation
    }
    fn waiting_alerts(&self) -> bool {
        self.firmware
            .as_ref()
            .is_some_and(|f| f.capabilities.iter().any(|c| c == "waiting-alert-v1"))
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
        let packet = compatible_packet(&t.packet, device.waiting_alerts());
        device.exchange(&packet, &format!("CDX_ACK {} ", t.seq), true)
    }
}

fn compatible_packet(packet: &str, waiting: bool) -> String {
    let mut fields: Vec<_> = packet.split('|').collect();
    if !waiting && fields.get(8) == Some(&"3") {
        fields[8] = "0";
    }
    fields.join("|")
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn waiting_alert_requires_advertised_capability() {
        let p = "CDX1|7|50|300|50|10080|1|0|3|1|Waiting|--|--|END\n";
        assert_eq!(compatible_packet(p, true), p);
        assert_eq!(compatible_packet(p, false).split('|').nth(8), Some("0"));
        assert_eq!(
            compatible_packet(&p.replace("|3|1|", "|2|1|"), false),
            p.replace("|3|1|", "|2|1|")
        );
    }
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
