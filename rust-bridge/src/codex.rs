//! Built-in Codex module: live hook collection, device alerts and presentation are owned here.
use crate::{account, display, hooks, info, log, now, state};
use anyhow::Result;
use serde_json::{json, Value};
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
    sync::{
        atomic::AtomicBool,
        mpsc::{self, Receiver},
        Arc,
    },
    thread::JoinHandle,
    time::Duration,
};

// Match the bounded channel created in `Session::open`. Draining a full batch
// prevents a delayed device transaction from publishing a stale source-health
// snapshot before its already-queued heartbeat is applied.
const UPDATE_DRAIN_LIMIT: usize = 64;

pub struct Options {
    pub remotes: Vec<String>,
    pub local_only: bool,
    pub db: Option<PathBuf>,
    pub dry: bool,
    pub filter: Option<String>,
}
pub struct Session {
    state: state::State,
    account: display::Account,
    snapshot_gate: account::SnapshotGate,
    input: Option<Receiver<state::Update>>,
    workers: Vec<JoinHandle<()>>,
    stop: Arc<AtomicBool>,
    filter: Option<String>,
    pending: Option<display::Transaction>,
    temporary: Option<PathBuf>,
    connection_generation: Option<u64>,
    trackers: BTreeMap<String, hooks::Tracker>,
}
impl Session {
    pub fn open(
        root: &Path,
        config: &Value,
        options: Options,
        stop: Arc<AtomicBool>,
    ) -> Result<Self> {
        let Options {
            remotes,
            local_only,
            db,
            dry,
            filter,
        } = options;
        let reports = root.join("reports");
        let temporary = dry && db.is_none();
        let path = db.unwrap_or_else(|| {
            if temporary {
                std::env::temp_dir().join(format!("passport-shadow-{}.sqlite3", std::process::id()))
            } else {
                reports.join("companion-state.sqlite3")
            }
        });
        let mut state = state::State::open(&path)?;
        let mut aliases: Vec<String> = if local_only {
            vec![]
        } else if !remotes.is_empty() {
            remotes
        } else {
            config["remotes"]
                .as_array()
                .map(|a| {
                    a.iter()
                        .filter_map(|s| s.as_str().map(String::from))
                        .collect()
                })
                .unwrap_or_default()
        };
        aliases.sort();
        aliases.dedup();
        let account_host = config["account_host"].as_str().unwrap_or("devbox");
        let identity = std::fs::read_to_string(reports.join("account-identity.sha256"))
            .ok()
            .map(|s| s.trim().to_string())
            .filter(|s| s.len() == 64 && s.chars().all(|c| c.is_ascii_hexdigit()));
        let (out, input) = mpsc::sync_channel(64);
        let mut workers = vec![];
        let mut trackers = BTreeMap::new();
        let mut sources = vec![None];
        sources.extend(aliases.into_iter().map(Some));
        // Register every source before creating receiver processes.
        for alias in &sources {
            let source = alias
                .as_ref()
                .map(|a| format!("ssh:{a}"))
                .unwrap_or_else(|| "local".into());
            state.register(&source, now())?;
            state.reset_live_source(&source, now(), false)?;
            trackers.insert(source, hooks::Tracker::default());
        }
        for alias in sources {
            let s = stop.clone();
            let o = out.clone();
            let root = root.to_path_buf();
            workers.push(std::thread::spawn(move || hooks::worker(root, alias, o, s)));
        }
        if let Some(identity) = identity {
            let s = stop.clone();
            let o = out.clone();
            let alias = account_host.to_string();
            workers.push(std::thread::spawn(move || {
                account::worker(alias, identity, o, s)
            }));
        }
        drop(out);
        Ok(Self {
            state,
            account: display::Account::default(),
            snapshot_gate: account::SnapshotGate::new(account_host),
            input: Some(input),
            workers,
            stop,
            filter,
            pending: None,
            temporary: temporary.then_some(path),
            connection_generation: None,
            trackers,
        })
    }
    pub fn poll(&mut self) -> Result<()> {
        // Live quota events must not keep stale reset-credit data fresh forever.
        if self.account.calibrated_at > 0. && now() - self.account.calibrated_at >= 900. {
            self.account.reset_cards = None;
            self.account.cards = info::Cards::default();
        }
        let Ok(update) = self
            .input
            .as_ref()
            .unwrap()
            .recv_timeout(Duration::from_millis(100))
        else {
            return Ok(());
        };
        self.apply_update(update)?;
        for _ in 1..UPDATE_DRAIN_LIMIT {
            let Ok(update) = self.input.as_ref().unwrap().try_recv() else {
                break;
            };
            self.apply_update(update)?;
        }
        Ok(())
    }

    fn apply_update(&mut self, update: state::Update) -> Result<()> {
        match update {
            state::Update::Hook(source, frame, observed) => {
                if frame.kind == hooks::Kind::Quota {
                    if self.snapshot_gate.apply(
                        &source,
                        &frame.quota,
                        frame.quota_at,
                        observed,
                        &mut self.account,
                    ) {
                        log(&format!("quota snapshot accepted source={source}"));
                    }
                    return Ok(());
                }
                if let Some(tracker) = self.trackers.get_mut(&source) {
                    tracker.apply(&source, *frame, observed, &mut self.state)?;
                }
                if self.pending.as_ref().is_some_and(|t| t.is_alert)
                    && !self.state.is_pending(self.pending.as_ref().unwrap().seq)?
                {
                    self.pending = None;
                }
            }
            state::Update::AccountVerified(valid, at) => {
                self.snapshot_gate.verify(valid, at);
                if !valid {
                    self.account = display::Account::default();
                }
            }
            state::Update::Quota(v, at) => {
                if at >= self.account.quota_at {
                    self.account.windows = display::quota(&v);
                    self.account.quota_at = at;
                }
                self.account.reset_cards = display::reset_cards(&v);
                self.account.cards = info::cards(&v);
                self.account.calibrated_at = at;
            }
            state::Update::Usage(v) => {
                self.account.usage = display::usage(&v);
                self.account.usage_at = now();
            }
        }
        Ok(())
    }
    pub fn summary(&self) -> Value {
        json!({"id":"codex","account":{"source":self.snapshot_gate.source,"quotaUpdatedAt":self.account.quota_at,"calibratedAt":self.account.calibrated_at,"calibrationIntervalSeconds":account::QUOTA_INTERVAL},"sources":self.state.sources.iter().map(|(name,s)|json!({"name":name,"healthy":s.healthy&&now()-s.observed<30.,"active":s.active.len()})).collect::<Vec<_>>()})
    }
    pub fn connected(&mut self, generation: u64, at: f64) -> Result<()> {
        if self.connection_generation != Some(generation) {
            self.state.begin_notifications(at)?;
            self.pending = None;
            self.connection_generation = Some(generation);
            log("Codex notification window opened; offline backlog skipped");
        }
        Ok(())
    }
    pub fn disconnected(&mut self) -> Result<()> {
        if self.connection_generation.take().is_some() {
            self.state.end_notifications()?;
            self.pending = None;
        }
        Ok(())
    }
    pub fn next(&mut self) -> Result<&display::Transaction> {
        if self.pending.is_none() {
            let alert = self.state.pending(self.filter.as_deref())?;
            let seq = if let Some((n, _)) = &alert {
                *n
            } else {
                self.state.seq()?
            };
            self.pending = Some(display::snapshot(
                &self.state,
                &self.account,
                seq,
                alert.as_ref().map(|(_, a)| a),
                self.filter.as_deref(),
            )?);
        }
        Ok(self.pending.as_ref().unwrap())
    }
    pub fn delivered(&mut self) -> Result<()> {
        if let Some(t) = &self.pending {
            if t.is_alert {
                self.state.delivered(t.seq)?;
            }
        }
        self.pending = None;
        Ok(())
    }
    pub fn shadow(&mut self) -> Result<()> {
        let seq = self.state.seq()?;
        let tx = display::snapshot(
            &self.state,
            &self.account,
            seq,
            None,
            self.filter.as_deref(),
        )?;
        log(&format!(
            "SHADOW {} {}",
            tx.packet.trim(),
            tx.metadata.trim()
        ));
        Ok(())
    }
}
impl Drop for Session {
    fn drop(&mut self) {
        self.stop.store(true, std::sync::atomic::Ordering::Relaxed);
        self.input.take();
        for w in self.workers.drain(..) {
            if w.join().is_err() {
                log("worker panicked");
            }
        }
        if let Some(path) = &self.temporary {
            let _ = std::fs::remove_file(path);
        }
    }
}

pub fn supports(f: &crate::firmware::Firmware) -> bool {
    f.protocol == 1
        && ["codex-v1", "completion-wide-v1", "info-v1"]
            .iter()
            .all(|s| f.capabilities.iter().any(|c| c == s))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn quota_events_preserve_tasks_cards_and_newer_snapshots() {
        let path = std::env::temp_dir().join(format!(
            "passport-quota-{}-{}.db",
            std::process::id(),
            now()
        ));
        let mut state = state::State::open(&path).unwrap();
        state.register("local", now()).unwrap();
        let (out, input) = mpsc::sync_channel(8);
        let mut session = Session {
            state,
            account: display::Account::default(),
            snapshot_gate: account::SnapshotGate::new("local"),
            input: Some(input),
            workers: vec![],
            stop: Arc::new(AtomicBool::new(false)),
            filter: None,
            pending: None,
            temporary: Some(path),
            connection_generation: None,
            trackers: BTreeMap::new(),
        };
        let at = now() - 1.;
        out.send(state::Update::AccountVerified(true, at - 1.))
            .unwrap();
        session.poll().unwrap();
        let snapshot = json!({"limitId":"codex","primary":{"usedPercent":42,"windowDurationMins":300,"resetsAt":1800000000},"secondary":null});
        let frame: hooks::Frame = serde_json::from_value(
            json!({"v":1,"kind":"quota","thread":"t","turn":"r","quota":snapshot,"quota_at":at}),
        )
        .unwrap();
        out.send(state::Update::Hook("local".into(), Box::new(frame), now()))
            .unwrap();
        session.poll().unwrap();
        assert_eq!(session.account.windows[0].left, 58);
        assert!(session.state.sources["local"].active.is_empty());
        assert_eq!(session.state.done_count().unwrap(), 0);
        // An RPC begun before the snapshot may finish later. Its older windows
        // must not win, but its reset-credit fields remain authoritative.
        out.send(state::Update::Quota(json!({"rateLimits":{"primary":{"usedPercent":10,"windowDurationMins":300}},"rateLimitResetCredits":{"availableCount":2,"credits":[]}}), at - 0.5)).unwrap();
        session.poll().unwrap();
        assert_eq!(session.account.windows[0].left, 58);
        assert_eq!(session.account.reset_cards, Some(2));
        assert!(session.account.cards.known);
        for (age, expected) in [(299., "1"), (301., "1"), (599., "1"), (601., "0")] {
            session.account.quota_at = now() - age;
            let tx = display::snapshot(&session.state, &session.account, 7, None, None).unwrap();
            assert_eq!(tx.packet.split('|').nth(9), Some(expected));
            assert!(!tx.is_alert);
        }
        session.account.quota_at = at;
        session.account.calibrated_at = now() - 901.;
        session.poll().unwrap();
        assert_eq!(session.account.reset_cards, None);
        assert!(!session.account.cards.known);
        assert_eq!(session.account.windows[0].left, 58);
    }
    #[test]
    fn poll_drains_queued_heartbeats_before_reporting_source_health() {
        let path = std::env::temp_dir().join(format!(
            "passport-heartbeat-drain-{}-{}.db",
            std::process::id(),
            now()
        ));
        let mut state = state::State::open(&path).unwrap();
        state.register("local", now()).unwrap();
        let (out, input) = mpsc::sync_channel(8);
        let mut trackers = BTreeMap::new();
        trackers.insert("local".into(), hooks::Tracker::default());
        let mut session = Session {
            state,
            account: display::Account::default(),
            snapshot_gate: account::SnapshotGate::new("local"),
            input: Some(input),
            workers: vec![],
            stop: Arc::new(AtomicBool::new(false)),
            filter: None,
            pending: None,
            temporary: Some(path),
            connection_generation: None,
            trackers,
        };
        let ready: hooks::Frame = serde_json::from_value(json!({"v":1,"kind":"ready"})).unwrap();
        let pulse: hooks::Frame = serde_json::from_value(json!({"v":1,"kind":"pulse"})).unwrap();
        out.send(state::Update::Hook(
            "local".into(),
            Box::new(ready),
            now() - 31.,
        ))
        .unwrap();
        out.send(state::Update::Hook("local".into(), Box::new(pulse), now()))
            .unwrap();

        session.poll().unwrap();

        assert_eq!(session.summary()["sources"][0]["healthy"], true);
    }
    #[test]
    fn reconnect_discards_cached_and_late_offline_alerts_but_delivers_new() {
        let path =
            std::env::temp_dir().join(format!("passport-reconnect-{}.db", std::process::id()));
        let _ = std::fs::remove_file(&path);
        let mut state = state::State::open(&path).unwrap();
        state.register("local", 100.).unwrap();
        let mut session = Session {
            state,
            account: display::Account::default(),
            snapshot_gate: account::SnapshotGate::new("local"),
            input: None,
            workers: vec![],
            stop: Arc::new(AtomicBool::new(false)),
            filter: None,
            pending: None,
            temporary: Some(path),
            connection_generation: None,
            trackers: BTreeMap::new(),
        };
        fn complete(s: &mut Session, turn: &str, ended: f64) {
            s.state
                .apply(state::Batch {
                    source: "local".into(),
                    active: vec![],
                    checkpoint: ended,
                    completed: vec![state::Completion {
                        task: state::Task {
                            source: "local".into(),
                            thread: "t".into(),
                            title: "task".into(),
                            project: "project".into(),
                            turn: turn.into(),
                            started: None,
                        },
                        status: "completed".into(),
                        ended,
                        seconds: 1,
                    }],
                })
                .unwrap();
        }
        session.connected(1, 110.).unwrap();
        complete(&mut session, "failed-send", 120.);
        assert!(session.next().unwrap().is_alert); // Cached transaction when the cable drops.
        complete(&mut session, "offline", 130.);
        session.connected(2, 140.).unwrap();
        assert!(
            !session.next().unwrap().is_alert,
            "reconnect must not replay cached offline notifications"
        );
        session.delivered().unwrap();
        complete(&mut session, "late-offline", 135.); // Worker reports old completion after reconnect.
        assert!(!session.next().unwrap().is_alert);
        session.delivered().unwrap();
        complete(&mut session, "new", 141.);
        session.connected(2, 142.).unwrap(); // Ordinary heartbeat must not discard new messages.
        assert!(session.next().unwrap().is_alert);
        session.delivered().unwrap();
        assert_eq!(session.state.done_count().unwrap(), 1);
    }
}
