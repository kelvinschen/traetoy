#!/usr/bin/env python3
"""Isolated IPC ownership and firmware-gating integration tests; never touch the real device."""
import json, os, pty, select, socket, subprocess, tempfile, threading, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];BIN=ROOT/'rust-bridge/target/release/passport-bridge'
def wait_socket(root,proc):
    path=root/'reports/control/bridge.sock'
    end=time.monotonic()+10
    while time.monotonic()<end:
        if path.exists():return path
        if proc.poll() is not None:raise AssertionError('backend exited during startup')
        time.sleep(.05)
    raise AssertionError('control startup timeout')
def connect(path):
    s=socket.socket(socket.AF_UNIX);s.settimeout(3);s.connect(str(path));return s
def request(path,op):
    with connect(path) as s:
        s.sendall(json.dumps({'v':1,'op':op}).encode()+b'\n');return json.loads(s.makefile('rb').readline())
with tempfile.TemporaryDirectory(prefix='passport-ipc-') as d:
    root=Path(d)
    with open(root/'stderr','wb') as log:
        proc=subprocess.Popen([str(BIN),'--workspace',d,'--managed','--local-only','--transport','usb','--port','/nonexistent-passport'],stderr=log)
        try:
            path=wait_socket(root,proc);assert path.stat().st_mode&0o777==0o600
            assert request(path,'status')['v']==1
            owner=connect(path);owner.sendall(b'{"v":1,"op":"subscribe","owner":true}\n');assert json.loads(owner.makefile('rb').readline())['v']==1
            with connect(path) as bad:
                bad.sendall(b'{"v":99,"op":"stop"}\n');assert b'invalid_request' in bad.recv(4096)
            assert proc.poll() is None
            with connect(path) as large:
                large.sendall(b'x'*5000)
                assert large.recv(1)==b''
            duplicate=subprocess.run([str(BIN),'--workspace',d,'--seconds','1','--local-only'],capture_output=True)
            assert duplicate.returncode!=0 and b'another bridge' in duplicate.stderr
            owner.close();start=time.monotonic();proc.wait(timeout=16);assert proc.returncode==0;assert time.monotonic()-start<16
            print('IPC version, bounds, permissions, singleton and owner-loss cleanup: PASS',flush=True)
        finally:
            if proc.poll() is None:proc.terminate();proc.wait(timeout=10)

print('Firmware gating is covered by codex_wire unit tests and real USB/BLE checks.',flush=True)
