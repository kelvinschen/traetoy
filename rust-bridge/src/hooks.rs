//! Live Codex hook streams. A receiver heartbeat measures transport liveness;
//! task silence is idle. No source discovery, history scan, or reconnect replay.
use crate::{
    now,
    state::{Batch, Completion, State, Task, Update},
};
use anyhow::{bail, Context, Result};
use serde::Deserialize;
use std::{
    collections::{BTreeMap, VecDeque},
    io::Read,
    os::fd::AsRawFd,
    path::Path,
    process::{Command, Stdio},
    sync::{atomic::AtomicBool, mpsc::SyncSender, Arc},
    time::{Duration, Instant},
};

#[derive(Clone, Debug, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Kind {
    Ready,
    Pulse,
    Quota,
    Started,
    Waiting,
    ToolFinished,
    Closed,
    Interrupted,
    Completed,
    Failed,
    Unavailable,
    #[serde(skip)]
    Disconnected,
}
#[derive(Clone, Debug, Deserialize)]
pub struct Frame {
    pub v: u8,
    pub kind: Kind,
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub thread: String,
    #[serde(default)]
    pub turn: String,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub project: String,
    #[serde(default)]
    pub call: String,
    #[serde(default)]
    pub asynchronous: bool,
    #[serde(default)]
    pub seconds: Option<i64>,
    #[serde(default)]
    pub reason: String,
    #[serde(default)]
    pub quota: serde_json::Value,
    #[serde(default)]
    pub quota_at: f64,
}
impl Frame {
    fn disconnected() -> Self {
        Self {
            v: 1,
            kind: Kind::Disconnected,
            id: String::new(),
            thread: String::new(),
            turn: String::new(),
            title: String::new(),
            project: String::new(),
            call: String::new(),
            asynchronous: false,
            seconds: None,
            reason: String::new(),
            quota: serde_json::Value::Null,
            quota_at: 0.,
        }
    }
    fn validate(&self) -> Result<()> {
        if self.v != 1 {
            bail!("unsupported hook stream version");
        }
        for value in [
            &self.id,
            &self.thread,
            &self.turn,
            &self.title,
            &self.project,
            &self.call,
            &self.reason,
        ] {
            if value.len() > 800 || value.chars().any(char::is_control) {
                bail!("invalid hook metadata");
            }
        }
        if !matches!(self.kind, Kind::Ready | Kind::Pulse | Kind::Disconnected)
            && self.thread.is_empty()
        {
            bail!("hook thread missing");
        }
        Ok(())
    }
}

#[derive(Default)]
pub struct Tracker {
    active: BTreeMap<String, Task>,
    // All outstanding approvals/input calls for a thread; async questions remain
    // open after their tool returns and close on user input or terminal status.
    waiting: BTreeMap<(String, String), (bool, usize)>,
    ended: VecDeque<(String, String)>,
    degraded: bool,
}
impl Tracker {
    pub fn apply(&mut self, source: &str, frame: Frame, at: f64, state: &mut State) -> Result<()> {
        frame.validate()?;
        match frame.kind {
            Kind::Ready | Kind::Disconnected => {
                *self = Self::default();
                state.reset_live_source(source, at, frame.kind == Kind::Ready)?;
                return Ok(());
            }
            Kind::Quota => return Ok(()),
            Kind::Pulse => {
                if let Some(s) = state.sources.get_mut(source) {
                    s.observed = at;
                    s.healthy = !self.degraded;
                }
                return Ok(());
            }
            Kind::Unavailable => {
                self.degraded = true;
                if let Some(s) = state.sources.get_mut(source) {
                    s.healthy = false;
                }
                crate::log(&format!(
                    "hook source {source} unavailable: {}",
                    frame.reason
                ));
                return Ok(());
            }
            _ => {}
        }
        if frame.turn.is_empty() && frame.kind != Kind::Closed {
            return Ok(());
        }
        if self
            .ended
            .contains(&(frame.thread.clone(), frame.turn.clone()))
        {
            return Ok(());
        }
        let mut completed = vec![];
        let project = format!(
            "{} · {}",
            frame.project,
            source.strip_prefix("ssh:").unwrap_or(source)
        );
        let task = self
            .active
            .get(&frame.thread)
            .filter(|t| t.turn == frame.turn)
            .cloned()
            .map(|mut t| {
                if !frame.title.is_empty() {
                    t.title = frame.title.clone();
                }
                if !frame.project.is_empty() {
                    t.project = project.clone();
                }
                t
            })
            .unwrap_or(Task {
                source: source.into(),
                thread: frame.thread.clone(),
                turn: frame.turn.clone(),
                title: if frame.title.is_empty() {
                    "Codex task".into()
                } else {
                    frame.title.clone()
                },
                project,
                started: Some(at),
            });
        match frame.kind {
            Kind::Started => {
                self.clear_waiting(source, &frame.thread, at, state)?;
                self.active.insert(frame.thread.clone(), task);
                self.degraded = false;
            }
            Kind::Waiting => {
                let was_waiting = self
                    .waiting
                    .keys()
                    .any(|(thread, _)| thread == &frame.thread);
                let pending = self
                    .waiting
                    .entry((frame.thread.clone(), frame.call.clone()))
                    .or_insert((frame.asynchronous, 0));
                if frame.call.starts_with("approval:") {
                    pending.1 += 1;
                } else {
                    pending.1 = 1;
                }
                self.active
                    .entry(frame.thread.clone())
                    .or_insert_with(|| task.clone());
                if !was_waiting {
                    state.live_attention(task, true, at)?;
                }
            }
            Kind::ToolFinished => {
                let key = (frame.thread.clone(), frame.call.clone());
                if let Some((asynchronous, count)) = self.waiting.get_mut(&key) {
                    if !*asynchronous {
                        *count = count.saturating_sub(1);
                    }
                    if *count == 0 {
                        self.waiting.remove(&key);
                    }
                }
                if !self
                    .waiting
                    .keys()
                    .any(|(thread, _)| thread == &frame.thread)
                {
                    state.live_attention(task, false, at)?;
                }
            }
            Kind::Completed | Kind::Failed | Kind::Interrupted => {
                let status = match frame.kind {
                    Kind::Completed => "completed",
                    Kind::Failed => "failed",
                    _ => "interrupted",
                };
                if self
                    .active
                    .get(&frame.thread)
                    .is_some_and(|t| t.turn == frame.turn)
                {
                    self.active.remove(&frame.thread);
                    self.clear_waiting(source, &frame.thread, at, state)?;
                }
                let seconds = frame.seconds.unwrap_or_else(|| {
                    task.started
                        .map(|start| (at - start).max(0.) as i64)
                        .unwrap_or(-1)
                });
                if state.accepts_live(at) {
                    completed.push(Completion {
                        task,
                        status: status.into(),
                        ended: at,
                        seconds,
                    });
                }
                self.ended.push_back((frame.thread.clone(), frame.turn));
                if self.ended.len() > 256 {
                    self.ended.pop_front();
                }
            }
            Kind::Closed => {
                self.active.remove(&frame.thread);
                self.clear_waiting(source, &frame.thread, at, state)?;
            }
            _ => unreachable!(),
        }
        state.apply(Batch {
            source: source.into(),
            active: self.active.values().cloned().collect(),
            completed,
            checkpoint: at,
        })?;
        if self.degraded {
            state.sources.get_mut(source).unwrap().healthy = false;
        }
        Ok(())
    }
    fn clear_waiting(
        &mut self,
        source: &str,
        thread: &str,
        at: f64,
        state: &mut State,
    ) -> Result<()> {
        self.waiting.retain(|(t, _), _| t != thread);
        let task = Task {
            source: source.into(),
            thread: thread.into(),
            turn: String::new(),
            title: String::new(),
            project: String::new(),
            started: None,
        };
        state.live_attention(task, false, at)
    }
}

fn command(root: &Path, remote: Option<&str>) -> Result<Command> {
    if let Some(alias) = remote {
        if alias.is_empty()
            || alias.starts_with('-')
            || !alias
                .chars()
                .all(|c| c.is_ascii_alphanumeric() || "._-".contains(c))
        {
            bail!("invalid hook SSH alias");
        }
        let mut cmd = Command::new("ssh");
        cmd.args([
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=8",
            "-o",
            "ServerAliveInterval=10",
            "-o",
            "ServerAliveCountMax=2",
            alias,
            "exec python3 \"$HOME/.codex/passport/hook.py\" --listen",
        ]);
        Ok(cmd)
    } else {
        let mut cmd = Command::new("/usr/bin/python3");
        cmd.arg(root.join("scripts/codex-hooks/hook.py"))
            .arg("--listen");
        Ok(cmd)
    }
}

fn stream(
    mut cmd: Command,
    source: &str,
    out: &SyncSender<Update>,
    stop: &AtomicBool,
) -> Result<()> {
    let mut child = cmd
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .context("start hook receiver")?;
    let result = (|| -> Result<()> {
        let mut stdout = child.stdout.take().context("hook stdout")?;
        let fd = stdout.as_raw_fd();
        let mut pending = Vec::new();
        let mut deadline = Instant::now() + Duration::from_secs(20);
        while !crate::stopping(stop) {
            if Instant::now() > deadline {
                bail!("hook receiver heartbeat expired");
            }
            let mut poll = libc::pollfd {
                fd,
                events: libc::POLLIN,
                revents: 0,
            };
            let rc = unsafe { libc::poll(&mut poll, 1, 100) };
            if rc < 0 {
                let e = std::io::Error::last_os_error();
                if e.kind() == std::io::ErrorKind::Interrupted {
                    continue;
                }
                return Err(e.into());
            }
            if rc == 0 {
                continue;
            }
            let mut buffer = [0; 4096];
            let size = stdout.read(&mut buffer)?;
            if size == 0 {
                bail!("hook receiver disconnected");
            }
            pending.extend_from_slice(&buffer[..size]);
            while let Some(end) = pending.iter().position(|b| *b == b'\n') {
                if end > 4000 {
                    bail!("hook frame too large");
                }
                let frame: Frame =
                    serde_json::from_slice(&pending[..end]).context("decode hook frame")?;
                frame.validate()?;
                if frame.kind == Kind::Ready {
                    crate::log(&format!("hook source {source} connected"));
                }
                pending.drain(..=end);
                deadline = Instant::now() + Duration::from_secs(20);
                if !crate::publish(
                    out,
                    stop,
                    Update::Hook(source.into(), Box::new(frame), now()),
                ) {
                    return Ok(());
                }
            }
            if pending.len() > 4000 {
                bail!("unterminated hook frame");
            }
        }
        Ok(())
    })();
    // Closing stdin lets the remote helper remove its socket before SSH exits.
    child.stdin.take();
    let until = Instant::now() + Duration::from_secs(1);
    while Instant::now() < until {
        if child.try_wait()?.is_some() {
            return result;
        }
        std::thread::sleep(Duration::from_millis(10));
    }
    let _ = child.kill();
    let _ = child.wait();
    result
}

pub fn worker(
    root: std::path::PathBuf,
    remote: Option<String>,
    out: SyncSender<Update>,
    stop: Arc<AtomicBool>,
) {
    let source = remote
        .as_ref()
        .map(|a| format!("ssh:{a}"))
        .unwrap_or_else(|| "local".into());
    let mut retry = 1;
    while !crate::stopping(&stop) {
        let result =
            command(&root, remote.as_deref()).and_then(|cmd| stream(cmd, &source, &out, &stop));
        if crate::stopping(&stop) {
            break;
        }
        if let Err(e) = result {
            crate::log(&format!(
                "hook source {source} unavailable: {e:#}; retry_s={retry}"
            ));
        }
        crate::publish(
            &out,
            &stop,
            Update::Hook(source.clone(), Box::new(Frame::disconnected()), now()),
        );
        crate::pause(&stop, Duration::from_secs(retry));
        retry = (retry * 2).min(30);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{display::Account, info};
    use serde_json::json;
    struct Fixture {
        path: std::path::PathBuf,
        state: State,
        tracker: Tracker,
    }
    impl Fixture {
        fn new() -> Self {
            let path = std::env::temp_dir().join(format!(
                "passport-hook-state-{}-{}",
                std::process::id(),
                now()
            ));
            let mut state = State::open(&path).unwrap();
            state.register("local", 100.).unwrap();
            state.begin_notifications(100.).unwrap();
            Self {
                path,
                state,
                tracker: Tracker::default(),
            }
        }
        fn event(&mut self, kind: &str, turn: &str, call: &str, asynchronous: bool, at: f64) {
            let frame: Frame = serde_json::from_value(json!({"v":1,"kind":kind,"id":format!("{kind}:{call}:{at}"),
                "thread":"task","turn":turn,"title":"test","project":"repo","call":call,"asynchronous":asynchronous})).unwrap();
            self.tracker
                .apply("local", frame, at, &mut self.state)
                .unwrap();
        }
        fn disconnect(&mut self, at: f64) {
            self.tracker
                .apply("local", Frame::disconnected(), at, &mut self.state)
                .unwrap();
        }
    }
    impl Drop for Fixture {
        fn drop(&mut self) {
            let _ = std::fs::remove_file(&self.path);
        }
    }
    #[test]
    fn idle_heartbeat_is_healthy_without_task_events_and_outage_clears_state() {
        let mut f = Fixture::new();
        f.event("ready", "", "", false, 101.);
        f.event("pulse", "", "", false, 7200.);
        assert!(info::packet(&f.state, &Account::default(), 7229.).ends_with("|local|1"));
        assert!(info::packet(&f.state, &Account::default(), 7230.).ends_with("|local|0"));
        f.event("started", "a", "", false, 7201.);
        assert_eq!(f.state.sources["local"].active.len(), 1);
        f.disconnect(7202.);
        assert!(!f.state.sources["local"].healthy);
        assert!(f.state.sources["local"].active.is_empty());
        f.event("ready", "", "", false, 7203.);
        assert!(f.state.sources["local"].active.is_empty());
        assert!(f.state.pending(None).unwrap().is_none());
    }
    #[test]
    fn first_waiting_hook_notifies_and_overlapping_approvals_wait_for_all_calls() {
        let mut f = Fixture::new();
        f.event("started", "a", "", false, 101.);
        f.event("waiting", "a", "one", false, 102.);
        let (seq, completion) = f.state.pending(None).unwrap().unwrap();
        assert_eq!(completion.status, "waiting");
        f.event("waiting", "a", "two", false, 103.);
        assert_eq!(f.state.pending(None).unwrap().unwrap().0, seq);
        f.event("tool_finished", "a", "one", false, 104.);
        assert!(f.state.is_pending(seq).unwrap());
        f.event("tool_finished", "a", "two", false, 105.);
        assert!(!f.state.is_pending(seq).unwrap());
        f.event("waiting", "a", "three", false, 106.);
        assert_ne!(f.state.pending(None).unwrap().unwrap().0, seq);
    }
    #[test]
    fn identical_parallel_permission_requests_are_counted_until_both_finish() {
        let mut f = Fixture::new();
        f.event("started", "a", "", false, 101.);
        f.event("waiting", "a", "approval:same", false, 102.);
        f.event("waiting", "a", "approval:same", false, 103.);
        let seq = f.state.pending(None).unwrap().unwrap().0;
        f.event("tool_finished", "a", "approval:same", false, 104.);
        assert!(f.state.is_pending(seq).unwrap());
        f.event("tool_finished", "a", "approval:same", false, 105.);
        assert!(!f.state.is_pending(seq).unwrap());
    }
    #[test]
    fn async_question_stays_waiting_until_input_or_final_event() {
        let mut f = Fixture::new();
        f.event("started", "a", "", false, 101.);
        f.event("waiting", "a", "question", true, 102.);
        let seq = f.state.pending(None).unwrap().unwrap().0;
        f.event("tool_finished", "a", "question", false, 103.);
        assert!(f.state.is_pending(seq).unwrap());
        f.event("started", "a", "", false, 104.);
        assert!(!f.state.is_pending(seq).unwrap());
        f.event("waiting", "a", "question2", true, 105.);
        f.event("completed", "a", "", false, 106.);
        assert_eq!(
            f.state.pending(None).unwrap().unwrap().1.status,
            "completed"
        );
    }
    #[test]
    fn failure_and_interrupt_notify_once_and_old_terminal_does_not_stop_new_turn() {
        let mut f = Fixture::new();
        f.event("started", "a", "", false, 101.);
        f.event("started", "b", "", false, 102.);
        f.event("failed", "a", "", false, 103.);
        assert_eq!(f.state.sources["local"].active[0].turn, "b");
        let (seq, event) = f.state.pending(None).unwrap().unwrap();
        assert_eq!(event.status, "failed");
        f.state.delivered(seq).unwrap();
        f.event("failed", "a", "", false, 104.);
        assert!(f.state.pending(None).unwrap().is_none());
        f.event("interrupted", "b", "", false, 105.);
        let (seq, event) = f.state.pending(None).unwrap().unwrap();
        assert_eq!(event.status, "interrupted");
        f.state.delivered(seq).unwrap();
        f.event("interrupted", "b", "", false, 106.);
        f.event("tool_finished", "b", "old-tool", false, 107.);
        assert!(f.state.sources["local"].active.is_empty());
        assert!(f.state.pending(None).unwrap().is_none());
    }
    #[test]
    fn disconnected_device_does_not_persist_hook_alerts() {
        let mut f = Fixture::new();
        f.state.end_notifications().unwrap();
        f.event("started", "a", "", false, 101.);
        f.event("waiting", "a", "q", false, 102.);
        f.event("completed", "a", "", false, 103.);
        let count: i64 = f
            .state
            .db
            .query_row("SELECT count(*) FROM alerts", [], |r| r.get(0))
            .unwrap();
        assert_eq!(count, 0);
        f.state.begin_notifications(104.).unwrap();
        f.event("started", "b", "", false, 105.);
        f.event("completed", "b", "", false, 106.);
        assert_eq!(f.state.pending(None).unwrap().unwrap().1.task.turn, "b");
    }
    #[test]
    fn source_disconnect_drops_pending_notification_and_active_tasks() {
        let mut f = Fixture::new();
        f.event("started", "a", "", false, 101.);
        f.event("completed", "a", "", false, 102.);
        assert!(f.state.pending(None).unwrap().is_some());
        f.disconnect(103.);
        assert!(f.state.pending(None).unwrap().is_none());
        f.event("ready", "", "", false, 104.);
        assert!(f.state.sources["local"].active.is_empty());
    }
    #[test]
    fn file_loss_is_not_hidden_by_transport_heartbeat() {
        let mut f = Fixture::new();
        f.event("started", "a", "", false, 101.);
        f.event("unavailable", "a", "", false, 102.);
        f.event("pulse", "", "", false, 103.);
        assert!(!f.state.sources["local"].healthy);
        assert!(f.state.pending(None).unwrap().is_none());
    }
    #[test]
    fn local_and_remote_use_same_reducer_without_cross_source_collisions() {
        let mut f = Fixture::new();
        f.state.register("ssh:devbox", 100.).unwrap();
        let mut remote = Tracker::default();
        for kind in ["started", "waiting", "failed"] {
            let at = 101.
                + match kind {
                    "started" => 0.,
                    "waiting" => 1.,
                    _ => 2.,
                };
            f.event(kind, "a", "tool", false, at);
            let frame = serde_json::from_value(json!({"v":1,"kind":kind,"thread":"task","turn":"a","title":"remote","project":"repo","call":"tool"})).unwrap();
            remote.apply("ssh:devbox", frame, at, &mut f.state).unwrap();
        }
        let (local_seq, local) = f.state.pending(None).unwrap().unwrap();
        assert_eq!(local.task.source, "local");
        f.state.delivered(local_seq).unwrap();
        let (_, remote) = f.state.pending(None).unwrap().unwrap();
        assert_eq!(remote.task.source, "ssh:devbox");
        assert_eq!(remote.status, "failed");
    }
}
