//! Identity is descriptive; compatibility depends on protocol + capabilities.
use anyhow::{bail, Result};
use serde::Serialize;
#[derive(Clone, Debug, Serialize)]
pub struct Firmware {
    pub id: String,
    pub version: String,
    pub protocol: u32,
    pub capabilities: Vec<String>,
}
impl Firmware {
    pub fn parse(line: &str) -> Result<Self> {
        let fields: Vec<_> = line.split('|').collect();
        if fields.len() != 6 || fields[0] != "PASSPORT" || fields[5] != "END" || line.len() > 512 {
            bail!("invalid firmware identity");
        }
        if fields[1..5]
            .iter()
            .any(|f| f.is_empty() || !f.is_ascii() || f.bytes().any(|b| b < 32))
        {
            bail!("invalid firmware fields");
        }
        Ok(Self {
            id: fields[1].into(),
            version: fields[2].into(),
            protocol: fields[3].parse()?,
            capabilities: fields[4].split(',').map(String::from).collect(),
        })
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    fn supported(line: &str) -> bool {
        crate::codex::supports(&Firmware::parse(line).unwrap())
    }
    #[test]
    fn variants_share_capabilities() {
        for id in ["codex-cream", "codex-dark"] {
            assert!(supported(&format!(
                "PASSPORT|{id}|1.0|1|codex-v1,completion-wide-v1,info-v1|END"
            )));
        }
        assert!(!supported("PASSPORT|clock|1|1|clock-v1|END"));
        assert!(!supported(
            "PASSPORT|new|1|2|codex-v1,completion-wide-v1,info-v1|END"
        ));
        assert!(Firmware::parse("garbage").is_err());
    }
}
