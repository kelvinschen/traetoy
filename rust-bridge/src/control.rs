//! Same-user, bounded local control. A managed backend lives only while its UI owns it.
use anyhow::{bail, Result};
use serde_json::{json, Value};
use std::{
    io::{Read, Write},
    os::{
        fd::AsRawFd,
        unix::{
            fs::PermissionsExt,
            net::{UnixListener, UnixStream},
        },
    },
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    thread::{self, JoinHandle},
    time::{Duration, Instant},
};
const LIMIT: usize = 4096;
#[derive(Clone)]
pub struct Control {
    pub stop: Arc<AtomicBool>,
    pub reconnect: Arc<AtomicBool>,
    snapshot: Arc<Mutex<Value>>,
}
impl Control {
    pub fn new(stop: Arc<AtomicBool>) -> Self {
        Self {
            stop,
            reconnect: Arc::new(AtomicBool::new(false)),
            snapshot: Arc::new(Mutex::new(
                json!({"v":1,"service":"starting","pid":std::process::id()}),
            )),
        }
    }
    pub fn update(&self, status: Value) {
        *self.snapshot.lock().unwrap() = status;
    }
    fn status(&self) -> Value {
        self.snapshot.lock().unwrap().clone()
    }
}
struct Client {
    stream: UnixStream,
    buffer: Vec<u8>,
    subscribed: bool,
    owner: bool,
    last: Value,
}
pub struct Server {
    path: PathBuf,
    stop: Arc<AtomicBool>,
    worker: Option<JoinHandle<()>>,
}
fn same_user(s: &UnixStream) -> bool {
    let (mut uid, mut gid) = (0, 0);
    unsafe { libc::getpeereid(s.as_raw_fd(), &mut uid, &mut gid) == 0 && uid == libc::geteuid() }
}
fn reply(s: &mut UnixStream, v: &Value) -> bool {
    let mut b = serde_json::to_vec(v).unwrap();
    b.push(b'\n');
    s.write_all(&b).is_ok()
}
fn valid(v: &Value) -> bool {
    v["v"] == 1
        && matches!(
            v["op"].as_str(),
            Some("status" | "subscribe" | "stop" | "reconnect")
        )
}
impl Server {
    pub fn start(root: &Path, ctl: Control, managed: bool) -> Result<Self> {
        let dir = root.join("reports/control");
        std::fs::create_dir_all(&dir)?;
        std::fs::set_permissions(&dir, std::fs::Permissions::from_mode(0o700))?;
        let path = dir.join("bridge.sock");
        if path.as_os_str().len() >= 104 {
            bail!("workspace path is too long for local control socket");
        }
        if path.exists() {
            std::fs::remove_file(&path)?;
        }
        let listener = UnixListener::bind(&path)?;
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))?;
        listener.set_nonblocking(true)?;
        let stop = ctl.stop.clone();
        let worker = thread::spawn(move || {
            let mut clients: Vec<Client> = vec![];
            let mut owner_deadline = Instant::now() + Duration::from_secs(30);
            while !crate::stopping(&ctl.stop) {
                let mut polls = vec![libc::pollfd {
                    fd: listener.as_raw_fd(),
                    events: libc::POLLIN,
                    revents: 0,
                }];
                polls.extend(clients.iter().map(|c| libc::pollfd {
                    fd: c.stream.as_raw_fd(),
                    events: libc::POLLIN,
                    revents: 0,
                }));
                unsafe {
                    libc::poll(polls.as_mut_ptr(), polls.len() as _, 1000);
                }
                for i in (0..clients.len()).rev() {
                    let mut alive = true;
                    if polls[i + 1].revents != 0 {
                        let mut buf = [0u8; 1024];
                        match clients[i].stream.read(&mut buf) {
                            Ok(0) => alive = false,
                            Ok(n) => {
                                clients[i].buffer.extend_from_slice(&buf[..n]);
                                if clients[i].buffer.len() > LIMIT {
                                    alive = false;
                                }
                                while alive {
                                    let Some(end) =
                                        clients[i].buffer.iter().position(|&b| b == b'\n')
                                    else {
                                        break;
                                    };
                                    let line: Vec<_> = clients[i].buffer.drain(..=end).collect();
                                    let request = serde_json::from_slice::<Value>(&line);
                                    match request {
                                        Ok(v) if valid(&v) => {
                                            match v["op"].as_str().unwrap() {
                                                "subscribe" => {
                                                    if v["owner"] == true {
                                                        if clients
                                                            .iter()
                                                            .enumerate()
                                                            .any(|(j, c)| j != i && c.owner)
                                                        {
                                                            alive = reply(
                                                                &mut clients[i].stream,
                                                                &json!({"v":1,"error":"owner_exists"}),
                                                            );
                                                            continue;
                                                        }
                                                        clients[i].owner = true;
                                                    }
                                                    clients[i].subscribed = true;
                                                }
                                                "stop" => {
                                                    ctl.stop.store(true, Ordering::Relaxed);
                                                }
                                                "reconnect" => {
                                                    ctl.reconnect.store(true, Ordering::Relaxed);
                                                }
                                                _ => {}
                                            }
                                            let status = ctl.status();
                                            alive = reply(&mut clients[i].stream, &status);
                                            clients[i].last = status;
                                        }
                                        _ => {
                                            reply(
                                                &mut clients[i].stream,
                                                &json!({"v":1,"error":"invalid_request"}),
                                            );
                                            alive = false;
                                        }
                                    }
                                }
                            }
                            Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {}
                            Err(_) => alive = false,
                        }
                    }
                    if alive && clients[i].subscribed {
                        let status = ctl.status();
                        if status != clients[i].last {
                            alive = reply(&mut clients[i].stream, &status);
                            clients[i].last = status;
                        }
                    }
                    if !alive {
                        if clients[i].owner {
                            owner_deadline = Instant::now() + Duration::from_secs(10);
                        }
                        clients.remove(i);
                    }
                }
                if polls[0].revents != 0 {
                    while let Ok((s, _)) = listener.accept() {
                        if clients.len() >= 8 || !same_user(&s) {
                            continue;
                        }
                        let _ = s.set_nonblocking(true);
                        clients.push(Client {
                            stream: s,
                            buffer: vec![],
                            subscribed: false,
                            owner: false,
                            last: Value::Null,
                        });
                    }
                }
                if managed && !clients.iter().any(|c| c.owner) && Instant::now() >= owner_deadline {
                    crate::log("Menu owner disconnected; stopping backend");
                    ctl.stop.store(true, Ordering::Relaxed);
                }
            }
        });
        Ok(Self {
            path,
            stop,
            worker: Some(worker),
        })
    }
}
impl Drop for Server {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
        if let Some(w) = self.worker.take() {
            let _ = w.join();
        }
        let _ = std::fs::remove_file(&self.path);
    }
}
pub fn command(root: &Path, op: &str) -> Result<Value> {
    let mut s = UnixStream::connect(root.join("reports/control/bridge.sock"))?;
    s.set_read_timeout(Some(Duration::from_secs(3)))?;
    s.set_write_timeout(Some(Duration::from_secs(3)))?;
    let request = json!({"v":1,"op":op});
    if !valid(&request) {
        bail!("unknown control operation");
    }
    if !reply(&mut s, &request) {
        bail!("control write failed");
    }
    let mut result = vec![];
    for _ in 0..65536 {
        let mut b = [0];
        s.read_exact(&mut b)?;
        if b[0] == b'\n' {
            return Ok(serde_json::from_slice(&result)?);
        }
        result.push(b[0]);
    }
    bail!("control reply too large")
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn request_versions_and_operations() {
        assert!(valid(&json!({"v":1,"op":"stop"})));
        assert!(!valid(&json!({"v":2,"op":"stop"})));
        assert!(!valid(&json!({"v":1,"op":"shell"})));
    }
    #[test]
    fn real_socket_status_and_stop() {
        let root = std::env::temp_dir().join(format!("passport-ctl-{}", std::process::id()));
        let stop = Arc::new(AtomicBool::new(false));
        let ctl = Control::new(stop.clone());
        let server = Server::start(&root, ctl, false).unwrap();
        assert_eq!(command(&root, "status").unwrap()["service"], "starting");
        command(&root, "stop").unwrap();
        assert!(crate::stopping(&stop));
        drop(server);
        std::fs::remove_dir_all(root).unwrap();
    }
}
