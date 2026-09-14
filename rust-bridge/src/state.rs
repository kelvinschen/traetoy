use anyhow::{Context, Result};
use rusqlite::{params, Connection};
use serde::{Deserialize, Serialize};
use std::{collections::BTreeMap, os::unix::fs::PermissionsExt, path::Path};

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Task {
    pub source: String,
    pub thread: String,
    pub title: String,
    pub project: String,
    #[serde(default)]
    pub turn: String,
    pub started: Option<f64>,
}
impl Task {
    pub fn key(&self) -> String {
        format!("{}/{}", self.source, self.thread)
    }
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Completion {
    pub task: Task,
    pub status: String,
    pub ended: f64,
    pub seconds: i64,
}
#[derive(Clone, Debug)]
pub struct Batch {
    pub source: String,
    pub active: Vec<Task>,
    pub completed: Vec<Completion>,
    pub checkpoint: f64,
}
#[derive(Clone, Debug)]
pub enum Update {
    Hook(String, Box<crate::hooks::Frame>, f64),
    Quota(serde_json::Value, f64),
    AccountVerified(bool, f64),
    Usage(serde_json::Value),
}
#[derive(Clone, Debug)]
pub struct SourceState {
    pub first: f64,
    pub checkpoint: f64,
    pub observed: f64,
    pub active: Vec<Task>,
    pub healthy: bool,
}
pub struct State {
    pub db: Connection,
    pub sources: BTreeMap<String, SourceState>,
    next: i64,
    end: i64,
    last_cleanup: f64,
    notification_since: Option<f64>,
    waiting: BTreeMap<String, BTreeMap<String, Task>>,
}
impl State {
    pub fn open(path: &Path) -> Result<Self> {
        if let Some(p) = path.parent() {
            std::fs::create_dir_all(p)?;
        }
        let db = Connection::open(path)?;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))?;
        db.execute_batch("PRAGMA busy_timeout=2000; PRAGMA cache_size=-256;
   CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,first_seen REAL NOT NULL,checkpoint REAL NOT NULL,active TEXT NOT NULL DEFAULT '[]');
   CREATE TABLE IF NOT EXISTS alerts(source TEXT,thread TEXT,turn TEXT,payload TEXT NOT NULL,ended REAL NOT NULL,seq INTEGER UNIQUE,delivered INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(source,thread,turn));
   CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value INTEGER NOT NULL);
   INSERT OR IGNORE INTO settings VALUES('sequence',1000000000);")?;
        Ok(Self {
            db,
            sources: BTreeMap::new(),
            next: 0,
            end: 0,
            last_cleanup: 0.,
            notification_since: None,
            waiting: BTreeMap::new(),
        })
    }
    pub fn register(&mut self, id: &str, now: f64) -> Result<SourceState> {
        self.db.execute(
            "INSERT OR IGNORE INTO sources(id,first_seen,checkpoint) VALUES(?,?,?)",
            params![id, now, now],
        )?;
        let (first, checkpoint, text): (f64, f64, String) = self.db.query_row(
            "SELECT first_seen,checkpoint,active FROM sources WHERE id=?",
            [id],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )?;
        let s = SourceState {
            first,
            checkpoint,
            observed: checkpoint,
            active: serde_json::from_str(&text)?,
            healthy: false,
        };
        self.sources.insert(id.to_owned(), s.clone());
        Ok(s)
    }
    /// Stream generations have no historical baseline or task restoration.
    pub fn reset_live_source(&mut self, source: &str, at: f64, healthy: bool) -> Result<()> {
        let s = self
            .sources
            .get_mut(source)
            .context("unregistered hook source")?;
        s.first = at;
        s.checkpoint = at;
        s.observed = at;
        s.active.clear();
        s.healthy = healthy;
        self.waiting.remove(source);
        self.db.execute(
            "UPDATE alerts SET delivered=2 WHERE source=? AND delivered=0",
            [source],
        )?;
        Ok(())
    }
    pub fn accepts_live(&self, at: f64) -> bool {
        self.notification_since.is_some_and(|since| at > since)
    }
    pub fn end_notifications(&mut self) -> Result<()> {
        self.notification_since = None;
        self.waiting.clear();
        self.db
            .execute("UPDATE alerts SET delivered=2 WHERE delivered=0", [])?;
        Ok(())
    }
    /// A hook is an edge, so its first arrival is not a polled baseline.
    pub fn live_attention(&mut self, task: Task, active: bool, at: f64) -> Result<()> {
        if !self.accepts_live(at) {
            return Ok(());
        }
        let source = task.source.clone();
        let mut next = self.waiting.entry(source.clone()).or_default().clone();
        if active {
            next.insert(task.thread.clone(), task);
        } else {
            next.remove(&task.thread);
        }
        self.waiting(source, next.into_values().collect(), at)
    }
    /// Start a live notification window; skipped deliveries are distinct from ACKs.
    pub fn begin_notifications(&mut self, at: f64) -> Result<()> {
        self.db
            .execute("UPDATE alerts SET delivered=2 WHERE delivered=0", [])?;
        self.notification_since = Some(at);
        self.waiting.clear();
        Ok(())
    }
    /// Edge-triggered attention notifications; the first snapshot after reconnect
    /// is a baseline, never a replay of questions raised while disconnected.
    pub fn waiting(&mut self, source: String, tasks: Vec<Task>, at: f64) -> Result<()> {
        if !self.sources.contains_key(&source) {
            anyhow::bail!("unregistered waiting source");
        }
        if self.notification_since.is_none_or(|since| at <= since) {
            return Ok(());
        }
        let next: BTreeMap<_, _> = tasks.into_iter().map(|t| (t.thread.clone(), t)).collect();
        let previous = self.waiting.remove(&source);
        if let Some(previous) = previous {
            for (thread, task) in &previous {
                if next.get(thread).is_none_or(|t| t.turn != task.turn) {
                    self.db.execute("UPDATE alerts SET delivered=2 WHERE source=? AND thread=? AND delivered=0 AND json_extract(payload,'$.status')='waiting'", params![source,thread])?;
                }
            }
            for (thread, task) in &next {
                if previous.get(thread).is_some_and(|t| t.turn == task.turn) {
                    continue;
                }
                if self.notification_since.is_none_or(|since| at <= since) {
                    continue;
                }
                let mut task = task.clone();
                task.source = source.clone();
                task.turn = format!("waiting:{}:{}", task.turn, self.seq()?);
                let seconds = task.started.map(|n| (at - n).max(0.) as i64).unwrap_or(-1);
                let event = Completion {
                    task,
                    status: "waiting".into(),
                    ended: at,
                    seconds,
                };
                self.db.execute("INSERT OR IGNORE INTO alerts(source,thread,turn,payload,ended) VALUES(?,?,?,?,?)", params![source,thread,event.task.turn,serde_json::to_string(&event)?,at])?;
            }
        }
        self.waiting.insert(source, next);
        Ok(())
    }
    pub fn is_pending(&self, seq: i64) -> Result<bool> {
        Ok(self.db.query_row(
            "SELECT EXISTS(SELECT 1 FROM alerts WHERE seq=? AND delivered=0)",
            [seq],
            |r| r.get(0),
        )?)
    }
    pub fn apply(&mut self, b: Batch) -> Result<()> {
        let previous = self
            .sources
            .get(&b.source)
            .context("unregistered source")?
            .clone();
        let tx = self.db.transaction()?;
        for done in &b.completed {
            if done.ended < previous.first
                || self.notification_since.is_some_and(|at| done.ended <= at)
                || done.task.turn.is_empty()
            {
                continue;
            }
            tx.execute(
                "INSERT OR IGNORE INTO alerts(source,thread,turn,payload,ended) VALUES(?,?,?,?,?)",
                params![
                    b.source,
                    done.task.thread,
                    done.task.turn,
                    serde_json::to_string(done)?,
                    done.ended
                ],
            )?;
        }
        let save = previous.active != b.active
            || !b.completed.is_empty()
            || b.checkpoint - previous.checkpoint >= 60.;
        if save {
            tx.execute(
                "UPDATE sources SET checkpoint=?,active=? WHERE id=?",
                params![b.checkpoint, serde_json::to_string(&b.active)?, b.source],
            )?;
        }
        tx.commit()?;
        self.sources.insert(
            b.source,
            SourceState {
                first: previous.first,
                checkpoint: if save {
                    b.checkpoint
                } else {
                    previous.checkpoint
                },
                observed: b.checkpoint,
                active: b.active,
                healthy: true,
            },
        );
        if crate::now() - self.last_cleanup > 3600. {
            self.db.execute(
                "DELETE FROM alerts WHERE delivered!=0 AND ended<?",
                [crate::now() - 30. * 86400.],
            )?;
            self.last_cleanup = crate::now();
        }
        Ok(())
    }
    pub fn seq(&mut self) -> Result<i64> {
        if self.next == self.end {
            let tx = self.db.transaction()?;
            self.next =
                tx.query_row("SELECT value FROM settings WHERE key='sequence'", [], |r| {
                    r.get(0)
                })?;
            if self.next > 2_147_000_000 {
                self.next = 1_000_000_000;
            }
            self.end = self.next + 10000;
            tx.execute(
                "UPDATE settings SET value=? WHERE key='sequence'",
                [self.end],
            )?;
            tx.commit()?;
        }
        let n = self.next;
        self.next += 1;
        Ok(n)
    }
    pub fn pending(&mut self, filter: Option<&str>) -> Result<Option<(i64, Completion)>> {
        let row = {
            let mut stmt=self.db.prepare("SELECT payload,seq,source FROM alerts WHERE delivered=0 AND (? IS NULL OR thread=?) ORDER BY ended,source,thread,turn")?;
            let mut rows = stmt.query(params![filter, filter])?;
            let mut selected = None;
            while let Some(row) = rows.next()? {
                let source: String = row.get(2)?;
                if self.sources.contains_key(&source) {
                    selected = Some((row.get::<_, String>(0)?, row.get::<_, Option<i64>>(1)?));
                    break;
                }
            }
            selected
        };
        if let Some((payload, seq)) = row {
            let done: Completion = serde_json::from_str(&payload)?;
            // Disabled sources do not silently consume their pending deliveries.
            if !self.sources.contains_key(&done.task.source) {
                return Ok(None);
            }
            let seq = if let Some(n) = seq {
                n
            } else {
                let n = self.seq()?;
                self.db.execute(
                    "UPDATE alerts SET seq=? WHERE source=? AND thread=? AND turn=?",
                    params![n, done.task.source, done.task.thread, done.task.turn],
                )?;
                n
            };
            Ok(Some((seq, done)))
        } else {
            Ok(None)
        }
    }
    pub fn delivered(&self, seq: i64) -> Result<()> {
        self.db
            .execute("UPDATE alerts SET delivered=1 WHERE seq=?", [seq])?;
        Ok(())
    }
    pub fn done_count(&self) -> Result<i64> {
        Ok(self.db.query_row("SELECT count(*) FROM alerts WHERE delivered=1 AND json_extract(payload,'$.status')='completed'",[],|r|r.get(0))?)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn fixture() -> (std::path::PathBuf, State) {
        let path = std::env::temp_dir().join(format!(
            "passport-state-test-{}-{}.db",
            std::process::id(),
            crate::now()
        ));
        let state = State::open(&path).unwrap();
        (path, state)
    }
    fn completion(source: &str, turn: &str, ended: f64) -> Completion {
        Completion {
            task: Task {
                source: source.into(),
                thread: "t".into(),
                title: "任务".into(),
                project: "workspace".into(),
                turn: turn.into(),
                started: Some(100.),
            },
            status: "completed".into(),
            ended,
            seconds: 10,
        }
    }
    fn apply(s: &mut State, source: &str, turn: &str, ended: f64) {
        s.apply(Batch {
            source: source.into(),
            active: vec![],
            completed: vec![completion(source, turn, ended)],
            checkpoint: ended,
        })
        .unwrap();
    }
    #[test]
    fn waiting_edges_are_deduplicated_resolved_and_not_replayed() {
        let (path, mut s) = fixture();
        s.register("local", 100.).unwrap();
        s.begin_notifications(110.).unwrap();
        s.waiting("local".into(), vec![], 109.).unwrap(); // Delayed pre-connection snapshot.
        let t = completion("local", "turn", 115.).task;
        s.waiting("local".into(), vec![t.clone()], 111.).unwrap();
        assert!(
            s.pending(None).unwrap().is_none(),
            "existing waiting state is baseline"
        );
        s.waiting("local".into(), vec![], 112.).unwrap();
        s.waiting("local".into(), vec![t.clone()], 113.).unwrap();
        let (seq, event) = s.pending(None).unwrap().unwrap();
        assert_eq!(event.status, "waiting");
        s.waiting("local".into(), vec![t.clone()], 114.).unwrap();
        assert_eq!(s.pending(None).unwrap().unwrap().0, seq);
        s.waiting("local".into(), vec![], 115.).unwrap();
        assert!(!s.is_pending(seq).unwrap());
        assert!(
            s.pending(None).unwrap().is_none(),
            "resolved request must not be sent later"
        );
        s.waiting("local".into(), vec![t.clone()], 116.).unwrap();
        let (again, _) = s.pending(None).unwrap().unwrap();
        assert_ne!(
            again, seq,
            "a new waiting episode in the same turn can notify"
        );
        s.delivered(again).unwrap();
        assert_eq!(s.done_count().unwrap(), 0);
        apply(&mut s, "local", "turn", 117.);
        assert_eq!(s.pending(None).unwrap().unwrap().1.status, "completed");
        s.begin_notifications(118.).unwrap();
        s.waiting("local".into(), vec![t], 119.).unwrap();
        assert!(s.pending(None).unwrap().is_none());
        drop(s);
        let _ = std::fs::remove_file(path);
    }
    #[test]
    fn restart_preserves_delivery_sequence_and_deduplicates() {
        let (p, mut s) = fixture();
        s.register("local", 100.).unwrap();
        apply(&mut s, "local", "old", 99.);
        assert!(s.pending(None).unwrap().is_none());
        apply(&mut s, "local", "one", 110.);
        let (seq, _) = s.pending(None).unwrap().unwrap();
        drop(s);
        let mut s = State::open(&p).unwrap();
        s.register("local", 120.).unwrap();
        assert_eq!(s.pending(None).unwrap().unwrap().0, seq);
        s.delivered(seq).unwrap();
        apply(&mut s, "local", "one", 110.);
        assert!(s.pending(None).unwrap().is_none());
        drop(s);
        std::fs::remove_file(p).unwrap();
    }
    #[test]
    fn startup_skips_persisted_backlog_and_keeps_live_state() {
        let (p, mut s) = fixture();
        s.register("local", 100.).unwrap();
        apply(&mut s, "local", "old", 110.);
        s.pending(None).unwrap().unwrap(); // Sequence already allocated before shutdown.
        drop(s);
        let mut s = State::open(&p).unwrap();
        s.register("local", 120.).unwrap();
        s.begin_notifications(130.).unwrap();
        assert!(s.pending(None).unwrap().is_none());
        apply(&mut s, "local", "late", 125.);
        assert!(s.pending(None).unwrap().is_none());
        let active = completion("local", "running", 131.).task;
        s.apply(Batch {
            source: "local".into(),
            active: vec![active.clone()],
            completed: vec![completion("local", "new", 131.)],
            checkpoint: 132.,
        })
        .unwrap();
        assert_eq!(s.sources["local"].active, vec![active]);
        assert_eq!(s.pending(None).unwrap().unwrap().1.task.turn, "new");
        assert_eq!(s.done_count().unwrap(), 0); // Skipping is not a successful delivery.
        drop(s);
        std::fs::remove_file(p).unwrap();
    }
    #[test]
    fn disabled_source_does_not_starve_enabled_source() {
        let (p, mut s) = fixture();
        s.register("off", 100.).unwrap();
        s.register("on", 100.).unwrap();
        apply(&mut s, "off", "one", 110.);
        apply(&mut s, "on", "two", 120.);
        s.sources.remove("off");
        assert_eq!(s.pending(None).unwrap().unwrap().1.task.source, "on");
        assert!(s.pending(Some("other-thread")).unwrap().is_none());
        drop(s);
        std::fs::remove_file(p).unwrap();
    }
}
