use crate::state::{Batch, Completion, SourceState, Task, Update};
use anyhow::{bail, Context, Result};
use rusqlite::{params_from_iter, types::Value as SqlValue, Connection, OpenFlags};
use serde_json::Value;
use std::{
    collections::{BTreeMap, HashMap},
    fs::File,
    io::{BufRead, BufReader, Seek, SeekFrom},
    path::{Path, PathBuf},
    process::{Command, Stdio},
    sync::{atomic::AtomicBool, mpsc::SyncSender, Arc},
    time::{Duration, Instant},
};
struct Watched {
    offset: u64,
    len: u64,
    modified: std::time::SystemTime,
    root: bool,
    partial: bool,
}
pub struct Local {
    home: PathBuf,
    first: f64,
    checkpoint: f64,
    active: BTreeMap<String, Task>,
    files: HashMap<PathBuf, Watched>,
    projects: HashMap<String, String>,
}
impl Local {
    pub fn new(home: PathBuf, s: SourceState) -> Self {
        Self {
            home,
            first: s.first,
            checkpoint: s.checkpoint,
            active: s
                .active
                .into_iter()
                .map(|t| (t.thread.clone(), t))
                .collect(),
            files: HashMap::new(),
            projects: HashMap::new(),
        }
    }
    fn project(&mut self, cwd: &str) -> String {
        if let Some(p) = self.projects.get(cwd) {
            return p.clone();
        }
        let fallback = Path::new(cwd)
            .file_name()
            .unwrap_or_default()
            .to_string_lossy()
            .to_string();
        let mut result = if fallback.is_empty() {
            "No workspace".into()
        } else {
            fallback
        };
        if let Ok(mut child) = Command::new("git")
            .args([
                "-C",
                cwd,
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            ])
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
        {
            let until = Instant::now() + Duration::from_secs(2);
            loop {
                match child.try_wait() {
                    Ok(Some(status)) => {
                        if status.success() {
                            use std::io::Read;
                            let mut text = String::new();
                            if let Some(mut out) = child.stdout.take() {
                                let _ = out.read_to_string(&mut text);
                            }
                            let p = Path::new(text.trim());
                            if p.file_name().is_some_and(|s| s == ".git") {
                                if let Some(name) = p.parent().and_then(|p| p.file_name()) {
                                    result = name.to_string_lossy().into();
                                }
                            }
                        }
                        break;
                    }
                    _ if Instant::now() >= until => {
                        let _ = child.kill();
                        let _ = child.wait();
                        break;
                    }
                    _ => std::thread::sleep(Duration::from_millis(10)),
                }
            }
        }
        if self.projects.len() >= 128 {
            self.projects.clear();
        }
        self.projects.insert(cwd.to_owned(), result.clone());
        result
    }
    pub fn poll(&mut self) -> Result<Batch> {
        let observed = crate::now();
        let cutoff = self.first.max(self.checkpoint - 3.);
        let dbpath = std::fs::read_dir(&self.home)?
            .filter_map(|e| e.ok().map(|e| e.path()))
            .filter(|p| {
                p.file_name().is_some_and(|n| {
                    n.to_string_lossy().starts_with("state_")
                        && n.to_string_lossy().ends_with(".sqlite")
                })
            })
            .max()
            .context("Codex state database absent")?;
        let db = Connection::open_with_flags(dbpath, OpenFlags::SQLITE_OPEN_READ_ONLY)?;
        db.busy_timeout(Duration::from_millis(500))?;
        db.execute_batch("PRAGMA cache_size=-128;")?;
        let mut values = vec![SqlValue::Real(cutoff - 86400.)];
        values.extend(self.active.keys().cloned().map(SqlValue::Text));
        let extra = if self.active.is_empty() {
            String::new()
        } else {
            format!(" OR id IN ({})", vec!["?"; self.active.len()].join(","))
        };
        let sql=format!("SELECT id,COALESCE(NULLIF(name,''),title),cwd,rollout_path FROM threads WHERE updated_at>=?{extra}");
        let mut stmt = db.prepare(&sql)?;
        let rows = stmt
            .query_map(params_from_iter(values), |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                    r.get::<_, String>(3)?,
                ))
            })?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        let mut completed = Vec::new();
        let mut touched = std::collections::HashSet::new();
        for (id, title, cwd, path) in rows {
            let path = PathBuf::from(path);
            touched.insert(path.clone());
            let meta = match std::fs::metadata(&path) {
                Ok(m) => m,
                Err(e) => {
                    if self.active.contains_key(&id) {
                        return Err(e.into());
                    }
                    continue;
                }
            };
            let modified = meta.modified()?;
            let len = meta.len();
            let project = self.project(&cwd);
            if let Some(t) = self.active.get_mut(&id) {
                t.title = title.clone();
                t.project = project.clone();
            }
            if self
                .files
                .get(&path)
                .is_some_and(|f| f.len == len && f.modified == modified)
            {
                continue;
            }
            let mut tracked = self.files.remove(&path).unwrap_or(Watched {
                offset: 0,
                len: 0,
                modified,
                root: false,
                partial: false,
            });
            if len < tracked.offset {
                tracked.offset = 0;
                tracked.root = false;
            }
            let mut reader = BufReader::new(File::open(&path)?);
            reader.seek(SeekFrom::Start(tracked.offset))?;
            loop {
                let start = reader.stream_position()?;
                let mut bytes = Vec::new();
                use std::io::Read;
                let n = Read::by_ref(&mut reader)
                    .take(8_000_001)
                    .read_until(b'\n', &mut bytes)?;
                if n == 0 || bytes.last() != Some(&b'\n') {
                    if n > 8_000_000 {
                        bail!("lifecycle line too large");
                    }
                    tracked.offset = start;
                    tracked.partial = n > 0;
                    break;
                }
                tracked.offset = reader.stream_position()?;
                let text = String::from_utf8_lossy(&bytes);
                if ![
                    "\"session_meta\"",
                    "\"task_started\"",
                    "\"task_complete\"",
                    "\"turn_aborted\"",
                ]
                .iter()
                .any(|m| text.contains(m))
                {
                    continue;
                }
                let v: Value = match serde_json::from_slice(&bytes) {
                    Ok(v) => v,
                    Err(_) => continue,
                };
                let p = &v["payload"];
                if v["type"] == "session_meta" {
                    tracked.root = p["source"].is_string();
                    continue;
                }
                if !tracked.root || v["type"] != "event_msg" {
                    continue;
                }
                let kind = p["type"].as_str().unwrap_or("");
                let turn = match p["turn_id"].as_str() {
                    Some(t) => t,
                    None => continue,
                };
                let when = v["timestamp"]
                    .as_str()
                    .and_then(|s| chrono::DateTime::parse_from_rfc3339(s).ok())
                    .map(|t| t.timestamp_millis() as f64 / 1000.);
                if kind == "task_started" {
                    let started = p["started_at"].as_f64().or(when);
                    self.active.insert(
                        id.clone(),
                        Task {
                            source: "local".into(),
                            thread: id.clone(),
                            title: title.clone(),
                            project: project.clone(),
                            turn: turn.into(),
                            started,
                        },
                    );
                } else if kind == "task_complete" || kind == "turn_aborted" {
                    let old = self.active.get(&id).filter(|t| t.turn == turn).cloned();
                    if old.is_some() {
                        self.active.remove(&id);
                    }
                    if let Some(ended) = when.filter(|w| *w >= cutoff) {
                        let seconds = p["duration_ms"]
                            .as_f64()
                            .filter(|n| *n >= 0.)
                            .map(|n| (n / 1000.) as i64)
                            .or_else(|| {
                                old.as_ref()
                                    .and_then(|t| t.started)
                                    .map(|s| (ended - s).max(0.) as i64)
                            })
                            .unwrap_or(-1);
                        let task = Task {
                            source: "local".into(),
                            thread: id.clone(),
                            title: title.clone(),
                            project: project.clone(),
                            turn: turn.into(),
                            started: old.and_then(|t| t.started),
                        };
                        completed.push(Completion {
                            task,
                            status: if kind == "task_complete" {
                                "completed"
                            } else {
                                "interrupted"
                            }
                            .into(),
                            ended,
                            seconds,
                        });
                    }
                }
            }
            tracked.len = len;
            tracked.modified = modified;
            self.files.insert(path, tracked);
        }
        self.files.retain(|p, _| touched.contains(p));
        if !self.files.values().any(|f| f.partial) {
            self.checkpoint = observed;
        }
        Ok(Batch {
            source: "local".into(),
            active: self.active.values().cloned().collect(),
            completed,
            checkpoint: self.checkpoint,
        })
    }
}
pub fn worker(mut local: Local, out: SyncSender<Update>, stop: Arc<AtomicBool>) {
    while !crate::stopping(&stop) {
        match local.poll() {
            Ok(b) => {
                if !crate::publish(&out, &stop, Update::Batch(b)) {
                    break;
                }
            }
            Err(e) => {
                crate::log(&format!("local unavailable: {e}"));
                crate::publish(&out, &stop, Update::Health("local".into(), false));
            }
        }
        crate::pause(&stop, Duration::from_secs(3));
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::io::Write;
    #[test]
    fn partial_record_survives_checkpoint_and_old_turn_does_not_stop_new_turn() {
        let dir = std::env::temp_dir().join(format!(
            "passport-local-test-{}-{}",
            std::process::id(),
            crate::now()
        ));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("session.jsonl");
        let mut file = File::create(&path).unwrap();
        let db = Connection::open(dir.join("state_5.sqlite")).unwrap();
        db.execute_batch("CREATE TABLE threads(id TEXT,name TEXT,title TEXT,cwd TEXT,rollout_path TEXT,updated_at REAL);").unwrap();
        db.execute(
            "INSERT INTO threads VALUES('t','中文标题','fallback',?,?,?)",
            rusqlite::params![dir.to_str(), path.to_str(), crate::now()],
        )
        .unwrap();
        writeln!(
            file,
            "{}",
            json!({"type":"session_meta","payload":{"source":"cli"}})
        )
        .unwrap();
        let event = |kind: &str, turn: &str| {
            json!({"timestamp":"2026-09-07T00:00:00Z","type":"event_msg","payload":{"type":kind,"turn_id":turn,"started_at":100}}).to_string()
        };
        writeln!(file, "{}", event("task_started", "a")).unwrap();
        let mut local = Local::new(
            dir.clone(),
            SourceState {
                first: 1.,
                checkpoint: 1.,
                observed: 1.,
                active: vec![],
                healthy: false,
            },
        );
        assert_eq!(local.poll().unwrap().active.len(), 1);
        // A record may remain unterminated across multiple scans. Its timestamp must not be skipped.
        local.checkpoint = 1.;
        write!(file, "{}", event("task_complete", "a")).unwrap();
        assert_eq!(local.poll().unwrap().checkpoint, 1.);
        assert_eq!(local.poll().unwrap().checkpoint, 1.);
        writeln!(file).unwrap();
        let b = local.poll().unwrap();
        assert_eq!(b.completed.len(), 1);
        assert!(b.active.is_empty());
        assert_eq!(b.completed[0].task.title, "中文标题");
        writeln!(file, "{}", event("task_started", "b")).unwrap();
        writeln!(file, "{}", event("turn_aborted", "a")).unwrap();
        let b = local.poll().unwrap();
        assert_eq!(b.active[0].turn, "b");
        drop(db);
        drop(file);
        std::fs::remove_dir_all(dir).unwrap();
    }
}
