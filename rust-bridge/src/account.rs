//! Account display is independent of hook task transport and never marks it unhealthy.
use crate::{rpc::Rpc, state::Update};
use anyhow::Result;
use serde_json::json;
use sha2::{Digest, Sha256};
use std::{
    sync::{atomic::AtomicBool, mpsc::SyncSender, Arc},
    time::Duration,
};

pub fn worker(alias: String, expected: String, out: SyncSender<Update>, stop: Arc<AtomicBool>) {
    let mut quota_due = 0.;
    let mut usage_due = 0.;
    while !crate::stopping(&stop) {
        let result = (|| -> Result<()> {
            let mut rpc = if alias == "local" {
                Rpc::local(stop.clone())?
            } else {
                Rpc::remote(&alias, stop.clone())?
            };
            crate::log(&format!("account source {alias} connected"));
            while !crate::stopping(&stop) {
                let account =
                    rpc.call("account/read", json!({"refreshToken":false}))?["account"].clone();
                let digest = hex::encode(Sha256::digest(serde_json::to_vec(&account)?));
                crate::publish(
                    &out,
                    &stop,
                    Update::AccountVerified(digest == expected, crate::now()),
                );
                if digest != expected {
                    crate::log("account identity mismatch: account display disabled");
                } else {
                    if crate::now() >= quota_due {
                        quota_due = crate::now() + QUOTA_INTERVAL;
                        let requested_at = crate::now();
                        match rpc.call("account/rateLimits/read", json!({})) {
                            Ok(v) => {
                                crate::publish(&out, &stop, Update::Quota(v, requested_at));
                                crate::log(&format!(
                                    "quota calibrated source={alias} interval_s={QUOTA_INTERVAL}"
                                ));
                            }
                            Err(e) => crate::log(&format!("quota unavailable: {e}")),
                        }
                    }
                    if crate::now() >= usage_due {
                        usage_due = crate::now() + 3600.;
                        match rpc.call("account/usage/read", json!({})) {
                            Ok(v) => {
                                crate::publish(&out, &stop, Update::Usage(v));
                            }
                            Err(e) => crate::log(&format!("usage unavailable: {e}")),
                        }
                    }
                }
                crate::log(&format!(
                    "account source {alias} rpc/rx/tx={:?}",
                    rpc.stats()
                ));
                crate::pause(&stop, Duration::from_secs(60));
            }
            Ok(())
        })();
        if crate::stopping(&stop) {
            break;
        }
        if let Err(e) = result {
            crate::log(&format!("account source {alias} unavailable: {e:#}"));
        }
        crate::pause(&stop, Duration::from_secs(10));
    }
}

/// Identity is checked by a local RPC every minute; only the selected host can
/// contribute live snapshots. Other hosts/accounts never overwrite this display.
pub const QUOTA_INTERVAL: f64 = 300.;
pub const QUOTA_FRESH_FOR: f64 = 600.;
pub struct SnapshotGate {
    pub source: String,
    verified_at: Option<f64>,
}
impl SnapshotGate {
    pub fn new(host: &str) -> Self {
        Self {
            source: if host == "local" {
                "local".into()
            } else {
                format!("ssh:{host}")
            },
            verified_at: None,
        }
    }
    pub fn verify(&mut self, valid: bool, at: f64) {
        self.verified_at = valid.then_some(at);
    }
    pub fn apply(
        &self,
        source: &str,
        snapshot: &serde_json::Value,
        at: f64,
        now: f64,
        account: &mut crate::display::Account,
    ) -> bool {
        // SSH hosts can be slightly ahead even with clock synchronization.
        // Never store a future freshness timestamp or accept large clock errors.
        if !at.is_finite() || at > now + 5. {
            return false;
        }
        let at = at.min(now);
        if source != self.source
            || !self.verified_at.is_some_and(|v| now >= v && now - v < 90.)
            || at <= account.quota_at
            || now - at > QUOTA_INTERVAL
            || snapshot["limitId"] != "codex"
        {
            return false;
        }
        let mut present = false;
        for key in ["primary", "secondary"] {
            let w = &snapshot[key];
            if w.is_null() {
                continue;
            }
            if !w["usedPercent"]
                .as_f64()
                .is_some_and(|v| v.is_finite() && (0. ..=100.).contains(&v))
                || !w["windowDurationMins"]
                    .as_i64()
                    .is_some_and(|v| (1..=525600).contains(&v))
                || !w["resetsAt"]
                    .as_i64()
                    .is_some_and(|v| (1..100000000000).contains(&v))
            {
                return false;
            }
            present = true;
        }
        if !present {
            return false;
        }
        account.windows = crate::display::quota(&json!({"rateLimits":snapshot}));
        account.quota_at = at;
        // Task events lack reset-credit and usage data. Preserve calibrated fields.
        true
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn snapshot() -> serde_json::Value {
        json!({"limitId":"codex", "primary":{"usedPercent":42.,"windowDurationMins":300,"resetsAt":1800000000},"secondary":null})
    }
    #[test]
    fn snapshots_require_verified_host_and_preserve_non_quota_fields() {
        let mut gate = SnapshotGate::new("devbox");
        let mut a = crate::display::Account {
            reset_cards: Some(2),
            cards: crate::info::Cards {
                known: true,
                ..Default::default()
            },
            usage_at: 800.,
            ..Default::default()
        };
        assert!(!gate.apply("ssh:devbox", &snapshot(), 999., 1000., &mut a));
        gate.verify(true, 990.);
        assert!(!gate.apply("local", &snapshot(), 999., 1000., &mut a));
        assert!(gate.apply("ssh:devbox", &snapshot(), 999., 1000., &mut a));
        assert_eq!(a.windows[0].left, 58);
        assert_eq!(a.reset_cards, Some(2));
        assert!(a.cards.known);
        assert_eq!(a.usage_at, 800.);
        assert!(!gate.apply("ssh:devbox", &snapshot(), 998., 1001., &mut a));
        gate.verify(false, 1001.);
        assert!(!gate.apply("ssh:devbox", &snapshot(), 1002., 1003., &mut a));
    }
    #[test]
    fn stale_future_malformed_and_other_buckets_do_not_replace_good_data() {
        let mut gate = SnapshotGate::new("local");
        gate.verify(true, 1000.);
        let mut a = crate::display::Account::default();
        for at in [699., 1007., f64::NAN] {
            assert!(!gate.apply("local", &snapshot(), at, 1001., &mut a));
        }
        for s in [
            json!({}),
            json!({"limitId":"codex_other"}),
            json!({"limitId":"codex","primary":{"usedPercent":150}}),
        ] {
            assert!(!gate.apply("local", &s, 1000., 1001., &mut a));
        }
        assert!(!gate.apply("local", &snapshot(), 1090., 1091., &mut a));
        assert_eq!(a.quota_at, 0.);
    }
    #[test]
    fn small_remote_clock_skew_is_clamped_without_poisoning_later_updates() {
        let mut gate = SnapshotGate::new("devbox");
        gate.verify(true, 1000.);
        let mut a = crate::display::Account::default();
        assert!(gate.apply("ssh:devbox", &snapshot(), 1001.2, 1001., &mut a));
        assert_eq!(a.quota_at, 1001.);
        assert!(gate.apply("ssh:devbox", &snapshot(), 1002.2, 1002., &mut a));
        assert_eq!(a.quota_at, 1002.);
    }
}
