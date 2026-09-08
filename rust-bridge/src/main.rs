mod ble;
mod codex;
mod codex_wire;
mod control;
mod device;
mod display;
mod firmware;
mod info;
mod local;
mod remote;
mod render;
mod rpc;
mod runtime;
mod state;
use std::{
    io::Write,
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, Ordering},
        mpsc::{SyncSender, TrySendError},
        Mutex, OnceLock,
    },
    time::{Duration, Instant},
};
static LOGGER: OnceLock<Mutex<Option<PathBuf>>> = OnceLock::new();
pub fn now() -> f64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs_f64()
}
pub fn log(s: &str) {
    let line = format!("{} {s}\n", chrono::Local::now().format("%Y-%m-%d %H:%M:%S"));
    let guard = LOGGER.get_or_init(|| Mutex::new(None)).lock().unwrap();
    if let Some(path) = &*guard {
        if std::fs::metadata(path).is_ok_and(|m| m.len() > 2_000_000) {
            for n in (1..3).rev() {
                let _ = std::fs::rename(
                    format!("{}.{}", path.display(), n),
                    format!("{}.{}", path.display(), n + 1),
                );
            }
            let _ = std::fs::rename(path, format!("{}.1", path.display()));
        }
        if let Ok(mut f) = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(path)
        {
            let _ = f.write_all(line.as_bytes());
        }
    } else {
        eprint!("{line}");
    }
}
pub fn stopping(s: &AtomicBool) -> bool {
    s.load(Ordering::Relaxed)
}
pub fn pause(s: &AtomicBool, d: Duration) {
    let end = Instant::now() + d;
    while !stopping(s) && Instant::now() < end {
        std::thread::sleep((end - Instant::now()).min(Duration::from_millis(100)));
    }
}
pub fn publish(out: &SyncSender<state::Update>, stop: &AtomicBool, mut u: state::Update) -> bool {
    while !stopping(stop) {
        match out.try_send(u) {
            Ok(()) => return true,
            Err(TrySendError::Full(v)) => {
                u = v;
                pause(stop, Duration::from_millis(100));
            }
            Err(_) => return false,
        }
    }
    false
}

fn main() {
    if let Err(e) = runtime::run() {
        log(&format!("fatal: {e:#}"));
        std::process::exit(1);
    }
}
