//! Built-in Codex module: collection, durable alerts and presentation are owned here.
use crate::{display, info, local, log, now, remote, state};
use anyhow::Result;
use serde_json::{json, Value};
use std::{
    path::{Path, PathBuf},
    sync::{
        atomic::AtomicBool,
        mpsc::{self, Receiver},
        Arc,
    },
    thread::JoinHandle,
    time::Duration,
};
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
    input: Option<Receiver<state::Update>>,
    workers: Vec<JoinHandle<()>>,
    stop: Arc<AtomicBool>,
    filter: Option<String>,
    pending: Option<display::Transaction>,
    temporary: Option<PathBuf>,
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
        let home = std::env::var_os("CODEX_HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from(std::env::var_os("HOME").unwrap()).join(".codex"));
        // Register before spawning so a startup DB error cannot leave detached workers.
        let initial = state.register("local", now())?;
        let mut remotes = vec![];
        for alias in aliases {
            let initial = state.register(&format!("ssh:{alias}"), now())?;
            let id = if alias == account_host {
                identity.clone()
            } else {
                None
            };
            remotes.push((remote::Remote::new(alias, initial), id));
        }
        let (out, input) = mpsc::sync_channel(64);
        let mut workers = vec![];
        let s = stop.clone();
        let o = out.clone();
        workers.push(std::thread::spawn(move || {
            local::worker(local::Local::new(home, initial), o, s)
        }));
        for (remote, id) in remotes {
            let s = stop.clone();
            let o = out.clone();
            workers.push(std::thread::spawn(move || remote::worker(remote, o, s, id)));
        }
        drop(out);
        Ok(Self {
            state,
            account: display::Account::default(),
            input: Some(input),
            workers,
            stop,
            filter,
            pending: None,
            temporary: temporary.then_some(path),
        })
    }
    pub fn poll(&mut self) -> Result<()> {
        if let Ok(update) = self
            .input
            .as_ref()
            .unwrap()
            .recv_timeout(Duration::from_millis(100))
        {
            match update {
                state::Update::Batch(b) => self.state.apply(b)?,
                state::Update::Health(id, h) => {
                    if let Some(s) = self.state.sources.get_mut(&id) {
                        s.healthy = h;
                    }
                }
                state::Update::Quota(v) => {
                    self.account.windows = display::quota(&v);
                    self.account.reset_cards = display::reset_cards(&v);
                    self.account.cards = info::cards(&v);
                    self.account.quota_at = now();
                }
                state::Update::Usage(v) => {
                    self.account.usage = display::usage(&v);
                    self.account.usage_at = now();
                }
            }
        }
        Ok(())
    }
    pub fn summary(&self) -> Value {
        json!({"id":"codex","sources":self.state.sources.iter().map(|(name,s)|json!({"name":name,"healthy":s.healthy&&now()-s.observed<30.,"active":s.active.len()})).collect::<Vec<_>>()})
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
