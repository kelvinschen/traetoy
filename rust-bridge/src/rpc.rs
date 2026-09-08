use anyhow::{bail, Context, Result};
use serde_json::{json, Value};
use std::{
    io::{self, Read, Write},
    os::fd::AsRawFd,
    process::{Child, ChildStdin, ChildStdout, Command, Stdio},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    time::{Duration, Instant},
};
use tungstenite::{protocol::WebSocketConfig, Message, WebSocket};

#[derive(Debug)]
pub struct Pipe {
    child: Child,
    input: ChildStdin,
    output: ChildStdout,
    deadline: Instant,
    stop: Arc<AtomicBool>,
    pub rx: u64,
    pub tx: u64,
}
impl Pipe {
    fn wait(&self, fd: i32, event: i16) -> io::Result<()> {
        loop {
            if self.stop.load(Ordering::Relaxed) {
                return Err(io::Error::new(io::ErrorKind::Interrupted, "stopping"));
            }
            if Instant::now() >= self.deadline {
                return Err(io::Error::new(io::ErrorKind::TimedOut, "RPC deadline"));
            }
            let mut p = libc::pollfd {
                fd,
                events: event,
                revents: 0,
            };
            let n = unsafe { libc::poll(&mut p, 1, 200) };
            if n > 0 {
                return Ok(());
            }
            if n < 0 && io::Error::last_os_error().kind() != io::ErrorKind::Interrupted {
                return Err(io::Error::last_os_error());
            }
        }
    }
}
impl Read for Pipe {
    fn read(&mut self, b: &mut [u8]) -> io::Result<usize> {
        self.wait(self.output.as_raw_fd(), libc::POLLIN)?;
        let n = self.output.read(b)?;
        self.rx += n as u64;
        Ok(n)
    }
}
impl Write for Pipe {
    fn write(&mut self, b: &[u8]) -> io::Result<usize> {
        self.wait(self.input.as_raw_fd(), libc::POLLOUT)?;
        let n = self.input.write(b)?;
        self.tx += n as u64;
        Ok(n)
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}
impl Drop for Pipe {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

pub struct Rpc {
    socket: WebSocket<Pipe>,
    pub offset: f64,
    pub calls: u64,
}
impl Rpc {
    pub fn remote(alias: &str, stop: Arc<AtomicBool>) -> Result<Self> {
        if alias.starts_with('-')
            || alias.is_empty()
            || !alias
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || b"_.-".contains(&c))
        {
            bail!("invalid SSH alias");
        }
        let command="\"$SHELL\" -lic 'PATH=\"${CODEX_INSTALL_DIR:-$HOME/.local/bin}:$PATH\"; export PATH; printf \"PASSPORT_CLOCK %s\\n\" \"$(date +%s)\"; exec codex app-server proxy'";
        let mut child = Command::new("ssh")
            .args([
                "-T",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=8",
                "-o",
                "ServerAliveInterval=15",
                "-o",
                "ServerAliveCountMax=3",
                alias,
                command,
            ])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()?;
        let input = child.stdin.take().context("stdin")?;
        let output = child.stdout.take().context("stdout")?;
        let mut pipe = Pipe {
            child,
            input,
            output,
            deadline: Instant::now() + Duration::from_secs(12),
            stop,
            rx: 0,
            tx: 0,
        };
        // Nonblocking writes keep cancellation/deadlines effective under a stalled proxy.
        unsafe {
            let fd = pipe.input.as_raw_fd();
            let flags = libc::fcntl(fd, libc::F_GETFL);
            libc::fcntl(fd, libc::F_SETFL, flags | libc::O_NONBLOCK);
        }
        let mut banner = Vec::new();
        let mut byte = [0u8];
        let offset = loop {
            if pipe.read(&mut byte)? == 0 {
                bail!("SSH proxy closed before banner");
            }
            banner.push(byte[0]);
            if banner.len() > 65536 {
                bail!("SSH banner too long");
            }
            if byte[0] == b'\n' {
                let line = String::from_utf8_lossy(&banner);
                if let Some((_, tail)) = line.rsplit_once("PASSPORT_CLOCK ") {
                    break tail.trim().parse::<f64>()? - crate::now();
                }
                banner.clear();
            }
        };
        let mut cfg = WebSocketConfig::default();
        cfg.max_message_size = Some(8_000_000);
        cfg.max_frame_size = Some(8_000_000);
        cfg.write_buffer_size = 0;
        let (socket, _) =
            tungstenite::client::client_with_config("ws://codex-app-server/rpc", pipe, Some(cfg))
                .map_err(|e| anyhow::anyhow!("WebSocket handshake: {e}"))?;
        let mut rpc = Self {
            socket,
            offset,
            calls: 0,
        };
        rpc.call("initialize",json!({"clientInfo":{"name":"passport_rust","version":"0.3.0"},"capabilities":{"experimentalApi":true,"optOutNotificationMethods":serde_json::from_str::<Value>(include_str!("notification-opt-out.json"))?}}))?;
        rpc.socket.send(Message::Text(
            json!({"method":"initialized"}).to_string().into(),
        ))?;
        Ok(rpc)
    }
    pub fn call(&mut self, method: &str, params: Value) -> Result<Value> {
        if ![
            "initialize",
            "thread/list",
            "thread/read",
            "thread/loaded/list",
            "thread/turns/list",
            "project/list",
            "account/read",
            "account/rateLimits/read",
            "account/usage/read",
        ]
        .contains(&method)
        {
            bail!("read-only method restriction");
        }
        self.calls += 1;
        let id = self.calls;
        self.socket.get_mut().deadline = Instant::now() + Duration::from_secs(12);
        self.socket.send(Message::Text(
            json!({"id":id,"method":method,"params":params})
                .to_string()
                .into(),
        ))?;
        loop {
            let message = self.socket.read()?;
            if let Message::Text(text) = message {
                let v: Value = serde_json::from_str(&text)?;
                if v.get("method").is_some() {
                    if let Some(id) = v.get("id") {
                        self.socket.send(Message::Text(
                            json!({"id":id,"error":{"code":-32601,"message":"Read-only monitor"}})
                                .to_string()
                                .into(),
                        ))?;
                    }
                    continue;
                }
                if v["id"].as_u64() == Some(id) {
                    if let Some(e) = v.get("error") {
                        bail!("RPC {}: {}", method, e);
                    }
                    return Ok(v["result"].clone());
                }
            } else if matches!(message, Message::Close(_)) {
                bail!("App Server closed");
            }
        }
    }
    pub fn stats(&self) -> (u64, u64, u64) {
        let p = self.socket.get_ref();
        (self.calls, p.rx, p.tx)
    }
}
