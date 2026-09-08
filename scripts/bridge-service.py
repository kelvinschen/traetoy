#!/usr/bin/env python3
"""Manage the companion; delegate to launchd when the LaunchAgent is installed."""
import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
PID=ROOT/'reports/bridge.pid'
LOG=ROOT/'reports/bridge.log'
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('action',choices=['start','stop','status'])
p.add_argument('--thread')
p.add_argument('--transport',choices=['auto','ble','usb'])
p.add_argument('--engine',choices=['rust','python'],default='rust')
a=p.parse_args()

# Preserve existing tooling while launchd owns the service lifecycle.
agent=Path.home()/'Library/LaunchAgents/cn.folotoy.codex-passport.bridge.plist'
if agent.exists():
    if a.thread or a.transport or a.engine!='rust':
        raise SystemExit('launchd uses Rust with automatic transport. Uninstall the LaunchAgent before using legacy overrides.')
    raise SystemExit(subprocess.call([str(ROOT/'scripts/bridge-service.sh'),a.action]))

def running():
    try:
        pid=int(PID.read_text())
        cmd=subprocess.check_output(['ps','-p',str(pid),'-o','command='],text=True).strip()
        return pid if any(str(path) in cmd for path in (ROOT/'scripts/companion.py', ROOT/'rust-bridge/target/release/passport-bridge')) else None
    except (OSError,ValueError,subprocess.CalledProcessError):return None

pid=running()
if a.action=='status':print(f'Running: PID {pid}' if pid else 'Stopped')
elif a.action=='stop':
    if pid:
        os.kill(pid,signal.SIGTERM)
        for _ in range(250):
            if not running():break
            time.sleep(.1)
        print('Stop requested' if running() else 'Stopped')
    else:print('Already stopped')
else:
    if pid:
        print(f'Already running: PID {pid}');sys.exit(0)
    if a.engine=='rust':
        binary=ROOT/'rust-bridge/target/release/passport-bridge'
        if not binary.is_file():raise SystemExit('Build first: cargo build --release --manifest-path rust-bridge/Cargo.toml')
        args=[str(binary),'--workspace',str(ROOT),'--log-file']
    else:
        args=[str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/companion.py'),'--log-file']
    if a.thread:args+=['--thread',a.thread]
    if a.transport:
        if a.engine!='rust':raise SystemExit('--transport requires the Rust engine')
        args+=['--transport',a.transport]
    LOG.parent.mkdir(exist_ok=True)
    with (ROOT/'reports/bridge-startup.log').open('wb') as out:
        proc=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=out,stderr=out,start_new_session=True,cwd=ROOT)
    PID.write_text(str(proc.pid)+'\n')
    time.sleep(.5)
    if proc.poll() is not None:raise SystemExit('Bridge did not start; inspect reports/bridge.log')
    print(f'Started: PID {proc.pid}; log: {LOG}')
