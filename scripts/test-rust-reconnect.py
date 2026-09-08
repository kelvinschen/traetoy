#!/usr/bin/env python3
"""Pause only the bridge-owned SSH process; verify independent USB and reconnection."""
import datetime as dt
import json
import os
from pathlib import Path
import signal
import subprocess
import time
ROOT=Path(__file__).resolve().parents[1]
pid=int((ROOT/'reports/bridge.pid').read_text())
def children():
    rows=subprocess.check_output(['ps','-axo','pid=,ppid=,comm='],text=True)
    return [int(parts[0]) for line in rows.splitlines() if len(parts:=line.split(maxsplit=2))==3 and int(parts[1])==pid and Path(parts[2]).name=='ssh']
assert 'rust-bridge/target/release/passport-bridge' in subprocess.check_output(['ps','-p',str(pid),'-o','comm='],text=True)
owned=children();assert len(owned)==1,owned
log=ROOT/'reports/bridge.log';offset=log.stat().st_size
try:
    os.kill(owned[0],signal.SIGSTOP)
    time.sleep(31)
finally:
    if owned[0] in children():os.kill(owned[0],signal.SIGCONT)
time.sleep(8)
with log.open() as f:f.seek(offset);text=f.read()
acks=[dt.datetime.strptime(line[:19],'%Y-%m-%d %H:%M:%S') for line in text.splitlines() if 'CDX_ACK ' in line]
gaps=[(b-a).total_seconds() for a,b in zip(acks,acks[1:])]
result={'paused_owned_ssh':owned[0],'children_after':children(),'usb_ack_count':len(acks),'maximum_ack_gap_seconds':max(gaps,default=0),'source_failure_seen':'source devbox unavailable' in text,'source_reconnected':'native source devbox connected' in text}
(ROOT/'reports/rust-reconnect.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
assert len(acks)>=10 and max(gaps,default=100)<=5,result
assert result['source_failure_seen'] and result['source_reconnected'],result
