#!/usr/bin/env python3
"""Preview two labeled alerts and verify the user's physical LIFO/navigation actions."""
import time
import secrets
from companion import Device,frame

def fields(line):
    return {k:int(v) for part in line.split() if '=' in part for k,v in [part.split('=',1)]}

device=Device();base=secrets.randbelow(1000000000)+1
windows=[(39,10080,'TEST DATA'),(-1,0,'TEST DATA')]
try:
    packets=[]
    for i,title,project,elapsed in [(0,'TEST A 最早完成','traetoy',60),(1,'TEST B 最新完成','finance',120)]:
        seq=base+i
        device.send_titles(seq,[],title,project)
        device.send_metadata(seq,('1M','7M','TEST'),[],elapsed)
        packet=frame(seq,windows,0,i+1,1,True,'TEST '+('A' if i==0 else 'B'))
        packets.append(packet)
        ack=device.send(packet,seq);print(ack,flush=True)
        values=fields(ack)
        assert values['unread']==i+1 and values['alert']==seq
    duplicate=device.send(packets[0],base)
    assert fields(duplicate)['unread']==2 and fields(duplicate)['alert']==base+1
    print('Two snapshots + out-of-order duplicate suppression: PASS',flush=True)
    print('Press OK (A,1), hold OK (home,1), OK (A,1), OK (home,0).',flush=True)
    expected=[(2,1,base),(0,1,base),(2,1,base),(0,0,0)]
    step=0;end=time.monotonic()+120;next_send=0
    heartbeat=frame(base+2,windows,0,2,0,True,'TEST B')
    while time.monotonic()<end and step<len(expected):
        if time.monotonic()>=next_send:
            device.serial.write(heartbeat);device.serial.flush();next_send=time.monotonic()+3
        line=device.serial.readline().decode('utf-8','replace').strip()
        if line.startswith('CDX_VIEW '):
            print(line,flush=True);v=fields(line)
            if (v['page'],v['unread'],v['alert'])==expected[step]:step+=1
        if line.startswith(('CDX_ERR','Guru Meditation','assert failed')):raise RuntimeError(line)
    if step==len(expected):print('Physical LIFO pop, pause, reopen, final dismissal: PASS',flush=True)
    else:print(f'Physical checks incomplete: {step}/{len(expected)}',flush=True)
finally:device.close()
