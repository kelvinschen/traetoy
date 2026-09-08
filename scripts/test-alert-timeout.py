#!/usr/bin/env python3
"""Verify two labeled alerts share 30-second visible budgets on the real USB device.
Run with the bridge stopped and no unread alerts. Produces two test sounds.
"""
import fcntl
from pathlib import Path
import time
from companion import Device, frame
ROOT=Path(__file__).resolve().parents[1]
lock=(ROOT/'reports/bridge.lock').open('a')
fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
def fields(line):
    return dict(part.split('=',1) for part in line.split() if '=' in part)
device=Device();base=int(time.time());windows=[(39,10080,'TEST DATA'),(-1,0,'TEST DATA')]
try:
    packets=[]
    began=time.monotonic()
    for i,title in [(0,'TEST A 自动确认计时'),(1,'TEST B 最新提醒优先')]:
        if i:time.sleep(max(0,5-(time.monotonic()-began)))
        seq=base+i
        device.send_titles(seq,[],title,'traetoy / timeout test')
        device.send_metadata(seq,('1M','7M','TEST'),[],60+i*60)
        packet=frame(seq,windows,0,i+1,1,True,'TEST '+('A' if not i else 'B'))
        packets.append(packet)
        ack=device.send(packet,seq);v=fields(ack)
        assert int(v['unread'])==i+1 and int(v['alert'])==seq,ack
        if i:b_began=time.monotonic()
        else:began=time.monotonic()
        print(ack,flush=True)
    heartbeat=frame(base+2,windows,0,2,0,True,'TEST heartbeat')
    saw_a=False;duplicate=False;end=began+75
    while time.monotonic()<end:
        if not duplicate and time.monotonic()-b_began>=12:
            device.send(packets[1],base+1);duplicate=True
        ack=device.send(heartbeat,base+2);v=fields(ack);now=time.monotonic()
        print(f't={now-began:.1f}s {ack}',flush=True)
        if int(v['unread'])==1:
            assert int(v['alert'])==base,ack
            if not saw_a:
                assert 29<=now-b_began<=35,(now-b_began,ack)
                saw_a=True
        if int(v['unread'])==0:
            assert saw_a and v['page']=='0' and 59<=now-began<=68,ack
            print('PASS: B expired, A resumed remaining time, duplicate did not reset, returned home',flush=True)
            break
        time.sleep(2)
    else:raise AssertionError('Alerts did not expire on schedule')
finally:
    device.serial.write(b'CDXB|RELEASE|END\n');device.serial.flush()
    device.close()
