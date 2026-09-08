//! Bounded, read-only auxiliary pages. No credit IDs or credentials reach the device.
use crate::{display::Account, state::State};
use chrono::{Local, TimeZone};
use serde_json::Value;

#[derive(Clone, Debug, Default)]
pub struct Cards {
    pub known: bool,
    pub rows: Vec<Card>,
}
#[derive(Clone, Debug)]
pub struct Card {
    pub title: String,
    pub status: String,
    pub granted: String,
    pub expires: String,
    pub description: String,
    pub reset_type: String,
}
fn text(s: &str, max: usize) -> String {
    // The device's dynamic text font is Latin; keep unsupported data explicit.
    let s: String = s.chars().map(|c| if c.is_ascii() && !c.is_ascii_control() && c != '|' { c } else { ' ' }).collect();
    let s = s.split_whitespace().collect::<Vec<_>>().join(" ");
    if s.len() <= max { s } else { format!("{}...", &s[..max-3]) }
}
fn date(v: &Value) -> String {
    v.as_i64().and_then(|n| Local.timestamp_opt(n, 0).single())
         .map(|d| d.format("%Y/%m/%d %H:%M").to_string()).filter(|s| s.len()==16).unwrap_or("--".into())
}
pub fn cards(v: &Value) -> Cards {
    let Some(rows) = v["rateLimitResetCredits"]["credits"].as_array() else { return Cards::default() };
    let mut rows = rows.iter().collect::<Vec<_>>();
    rows.sort_by_key(|r| r["expiresAt"].as_i64().unwrap_or(i64::MAX));
    Cards { known: true, rows: rows.into_iter().take(6).map(|r| Card {
        title: text(r["title"].as_str().unwrap_or("Rate-limit reset"), 39),
        status: text(r["status"].as_str().unwrap_or("unknown"), 15),
        granted: date(&r["grantedAt"]), expires: date(&r["expiresAt"]),
        description: text(r["description"].as_str().unwrap_or("--"), 159),
        reset_type: text(r["resetType"].as_str().unwrap_or("--"), 23),
    }).collect() }
}
pub fn packet(state: &State, account: &Account, now: f64) -> String {
    let age = if account.quota_at > 0. { ((now-account.quota_at).max(0.) as i64 / 60 * 60).min(i32::MAX as i64) } else { -1 };
    let sources = state.sources.iter().take(4).collect::<Vec<_>>();
    let mut fields = vec![account.reset_cards.unwrap_or(-1).to_string(), age.to_string(), format!("{:.0}", account.quota_at),
        (account.cards.known as u8).to_string(), account.cards.rows.len().to_string(),
        Local::now().format("UTC%:z").to_string(), sources.len().to_string()];
    for (name, s) in sources {
        fields.push(text(name.strip_prefix("ssh:").unwrap_or(name), 23));
        fields.push(if s.healthy && now-s.observed<30. { "1".into() } else { "0".into() });
    }
    for c in &account.cards.rows {
        fields.extend([c.title.clone(),c.status.clone(),c.granted.clone(),c.expires.clone(),c.description.clone(),c.reset_type.clone()]);
    }
    fields.join("|")
}
#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn null_empty_sorted_and_bounded_without_secrets() {
        assert!(!cards(&json!({})).known);
        assert!(cards(&json!({"rateLimitResetCredits":{"credits":[]}})).known);
        let parsed=cards(&json!({"rateLimitResetCredits":{"credits":[
            {"id":"SECRET", "expiresAt":null,"title":"Unknown date"},
            {"expiresAt":1800000000,"title":"Later"},
            {"expiresAt":1700000000,"title":"First", "description":"a|b\nline"}]}}));
        assert_eq!(parsed.rows[0].title,"First");
        assert_eq!(parsed.rows[0].description,"a b line");
        assert_eq!(parsed.rows[2].expires,"--");
        assert!(!format!("{parsed:?}").contains("SECRET"));
        assert_eq!(text(&"x".repeat(300),159).len(),159);
        let many=cards(&json!({"rateLimitResetCredits":{"credits":vec![json!({});20]}}));
        assert_eq!(many.rows.len(),6);
    }
}
