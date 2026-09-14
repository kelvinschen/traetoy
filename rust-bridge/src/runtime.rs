use crate::{ble, codex, control, device, log, render, stopping, LOGGER};
use anyhow::{bail, Context, Result};
use std::{
    os::fd::AsRawFd,
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    time::{Duration, Instant},
};
pub fn run() -> Result<()> {
    let mut root = std::env::current_dir()?;
    let mut dry = false;
    let mut seconds = None;
    let mut port = None;
    let mut transport = None;
    let mut filter = None;
    let mut db_path = None;
    let mut local_only = false;
    let mut remotes_override = Vec::new();
    let mut logging = false;
    let mut fixture = None;
    let mut ble_check = false;
    let mut device_check = false;
    let mut managed = false;
    let mut command = None;
    let mut args = std::env::args().skip(1);
    while let Some(a) = args.next() {
        match a.as_str() {
            "--managed" => managed = true,
            "--control" => command = Some(args.next().context("control operation missing")?),
            "--workspace" => root = PathBuf::from(args.next().context("workspace missing")?),
            "--dry-run" => dry = true,
            "--once" => {
                dry = true;
                seconds = Some(20.);
            }
            "--seconds" => seconds = Some(args.next().context("seconds missing")?.parse::<f64>()?),
            "--port" => port = Some(args.next().context("port missing")?),
            "--transport" => transport = Some(args.next().context("transport missing")?),
            "--thread" => filter = args.next(),
            "--state-db" => db_path = args.next().map(PathBuf::from),
            "--local-only" => local_only = true,
            "--remote" => remotes_override.push(args.next().context("remote missing")?),
            "--log-file" => logging = true,
            "--ble-check" => ble_check = true,
            "--device-check" => device_check = true,
            "--render-fixture" => fixture = args.next().map(PathBuf::from),
            "--help" => {
                println!("passport-bridge [--workspace DIR] [--dry-run] [--seconds N] [--port PATH] [--transport auto|ble|usb] [--thread ID] [--local-only] [--remote ALIAS] [--state-db PATH] [--log-file] [--render-fixture DIR] [--ble-check] [--device-check] [--managed] [--control status|subscribe|reconnect|stop]");
                return Ok(());
            }
            _ => bail!("unknown argument {a}"),
        }
    }
    if dry && (ble_check || device_check) {
        bail!("device diagnostics cannot run in dry-run mode");
    }
    if let Some(dir) = fixture {
        std::fs::create_dir_all(&dir)?;
        for alert in [false, true] {
            let packed = render::raster(
                "TEST 优化任务完成提醒的展示布局",
                "ToutiaoKMP · devbox",
                alert,
            );
            let regions: &[(usize, usize, usize, &str)] = if alert {
                &[(168, 60, 0, "alert"), (170, 16, 10080, "project")]
            } else {
                &[(200, 64, 0, "task")]
            };
            for &(w, h, offset, name) in regions {
                let mut pgm = format!("P5\n{w} {h}\n255\n").into_bytes();
                for i in offset..offset + w * h {
                    pgm.push(((packed[i / 4] >> (6 - 2 * (i % 4))) & 3) * 85);
                }
                std::fs::write(dir.join(format!("{name}.pgm")), pgm)?;
            }
        }
        return Ok(());
    }
    if let Some(op) = command {
        println!("{}", control::command(&root, &op)?);
        return Ok(());
    }
    let reports = root.join("reports");
    std::fs::create_dir_all(&reports)?;
    if logging {
        *LOGGER.get_or_init(|| Mutex::new(None)).lock().unwrap() = Some(reports.join("bridge.log"));
    }
    let _lock = if !dry {
        let f = std::fs::OpenOptions::new()
            .create(true)
            .write(true)
            .truncate(false)
            .open(reports.join("bridge.lock"))?;
        if unsafe { libc::flock(f.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } != 0 {
            bail!("another bridge owns USB");
        }
        Some(f)
    } else {
        None
    };
    if ble_check {
        return ble::self_test(&ble::Pairing::load(&root.join("config/ble-device.json"))?);
    }
    let config_path = root.join("config/bridge.json");
    let config: serde_json::Value = if config_path.exists() {
        serde_json::from_slice(&std::fs::read(config_path)?)?
    } else {
        serde_json::json!({})
    };
    let mode: device::Mode = transport
        .as_deref()
        .or(config["transport"].as_str())
        .unwrap_or("auto")
        .parse()?;
    let pairing_path = root.join("config/ble-device.json");
    let pairing = if mode == device::Mode::Usb {
        None
    } else {
        match ble::Pairing::load(&pairing_path) {
            Ok(p) => Some(p),
            Err(e) => {
                if mode == device::Mode::Ble {
                    return Err(e.context("BLE pairing unavailable"));
                }
                log("BLE pairing unavailable; USB remains available");
                None
            }
        }
    };
    if device_check {
        return device::self_test(port, mode, pairing);
    }
    let stop = Arc::new(AtomicBool::new(false));
    let signal = stop.clone();
    ctrlc::set_handler(move || signal.store(true, Ordering::Relaxed))?;
    let ctl = control::Control::new(stop.clone());
    let _server = if !dry {
        Some(control::Server::start(&root, ctl.clone(), managed)?)
    } else {
        None
    };
    let mut session = codex::Session::open(
        &root,
        &config,
        codex::Options {
            remotes: remotes_override,
            local_only,
            db: db_path,
            dry,
            filter,
        },
        stop.clone(),
    )?;
    let mut device = device::Device::new(port, mode, pairing);
    device.cancel = Some(stop.clone());
    let mut sender = crate::codex_wire::Sender::default();
    let began = Instant::now();
    let mut due = Instant::now();
    let mut error = String::new();
    let outcome = (|| -> Result<()> {
        while !stopping(&stop) && seconds.is_none_or(|n| began.elapsed().as_secs_f64() < n) {
            session.poll()?;
            if ctl.reconnect.swap(false, Ordering::Relaxed) {
                device.close();
                session.disconnected()?;
                due = Instant::now();
            }
            if Instant::now() < due {
                continue;
            }
            due = Instant::now() + Duration::from_secs(3);
            if dry {
                session.shadow()?;
                continue;
            }
            match device.ready(codex::supports) {
                Ok(true) => {
                    // Identity handshake defines a new live window before selecting any alert.
                    session.connected(device.generation, crate::now())?;
                    match sender.send(&mut device, session.next()?) {
                        Ok(ack) => {
                            log(&ack);
                            session.delivered()?;
                            error.clear();
                        }
                        Err(e) => {
                            error = e.to_string();
                            device.recover();
                            session.disconnected()?;
                        }
                    }
                }
                Ok(false) => {
                    session.disconnected()?;
                    error.clear();
                }
                Err(e) => {
                    error = e.to_string();
                    device.recover();
                    session.disconnected()?;
                }
            }
            ctl.update(serde_json::json!({"v":1,"pid":std::process::id(),"service":"running","device":{"transport":device.transport(),"compatibility":device.compatibility,"firmware":device.firmware},"module":session.summary(),"error":error}));
        }
        Ok(())
    })();
    ctl.update(serde_json::json!({"v":1,"service":"stopping","pid":std::process::id()}));
    stop.store(true, Ordering::Relaxed);
    device.close();
    drop(session);
    outcome
}
