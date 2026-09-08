#!/usr/bin/env python3
"""Pair the physically connected Passport with this Mac. No secret is printed."""
import fcntl
import json
import os
from pathlib import Path
import secrets
import time
import serial
from serial.tools import list_ports
ROOT=Path(__file__).resolve().parents[1]
lock=(ROOT/'reports/bridge.lock').open('a')
try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
except BlockingIOError:raise SystemExit('Stop the bridge before USB pairing.')
ports=[p for p in list_ports.comports() if p.vid==0x303a]
identity=(ROOT/'backups/device-serial.txt').read_text().strip()
ports=[p for p in ports if p.serial_number==identity]
if len(ports)!=1:raise SystemExit('Connect the original Passport over USB.')
path=ROOT/'config/ble-device.json'
# Persist before sending, so interruption after device commit does not lose the key.
config=json.loads(path.read_text()) if path.exists() else {'key':secrets.token_hex(32)}
assert len(bytes.fromhex(config['key']))==32
fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
with os.fdopen(fd,'w') as f:json.dump(config,f);f.write('\n');f.flush();os.fsync(f.fileno())
os.chmod(path,0o600)
port=serial.Serial();port.port=ports[0].device;port.baudrate=115200;port.timeout=.2;port.dtr=False;port.rts=False;port.open()
try:
    time.sleep(1.5)
    port.reset_input_buffer()
    port.write(('CDXB|PAIR|'+config['key']+'|END\n').encode());port.flush()
    until=time.monotonic()+10
    while time.monotonic()<until:
        line=port.readline().decode(errors='replace').strip()
        if line.startswith('CDX_BLE_PAIRED '):
            config['device_id']=line.split()[1]
            if len(bytes.fromhex(config['device_id']))!=6:raise SystemExit('Invalid device identity')
            temporary=path.with_suffix('.json.tmp')
            fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
            with os.fdopen(fd,'w') as f:json.dump(config,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
            os.replace(temporary,path)
            print('USB pairing complete. Private BLE credentials saved for device '+config['device_id']);break
        if line.startswith('CDX_BLE pair_'):print(line,flush=True)
        if line.startswith('CDX_ERR'):raise SystemExit(line)
    else:raise SystemExit('Pairing acknowledgment timed out; retained key can be safely retried.')
finally:port.close()
