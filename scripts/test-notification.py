#!/usr/bin/env python3
"""Send a clearly labeled synthetic completion to the real board; bridge must be stopped."""
import argparse
import datetime as dt
import tempfile
import time
import subprocess
from pathlib import Path
from PIL import Image
import companion
from companion import Events,Device,frame
parser=argparse.ArgumentParser()
parser.add_argument('--hold-seconds',type=float,default=0)
args=parser.parse_args()
with tempfile.TemporaryDirectory() as directory:
    # Use production Rust rasterization, not the legacy Python font path.
    fixture = Path(directory)/'raster'
    root = Path(__file__).resolve().parents[1]
    subprocess.run([str(root/'rust-bridge/target/release/passport-bridge'),
                    '--render-fixture',str(fixture)],check=True)
    pixels = b''.join(Image.open(fixture/f'{name}.pgm').tobytes()
                      for name in ('alert','project'))
    assert len(pixels)==12800
    packed = bytearray(3200)
    for i, alpha in enumerate(pixels):
        packed[i//4] |= ((alpha*3+127)//255) << (6-2*(i%4))
    legacy_bitmap = companion.completion_bitmap
    companion.completion_bitmap = lambda title, project='': (
        bytes(packed) if str(title).startswith('TEST') else legacy_bitmap(title, project))
    events=Events(directory)
    record={'timestamp':dt.datetime.now(dt.timezone.utc).isoformat(),'type':'event_msg','payload':{'type':'task_complete','turn_id':'test-turn','duration_ms':125000}}
    events.apply(record,'test-thread')
    assert events.done==1 and len(events.pending)==1
    seq=int(time.time())
    packet=frame(seq,[(39,10080,'TEST DATA'),(-1,0,'TEST DATA')],0,events.done,1,True,'TEST notification')
    device=Device()
    try:
        device.send_titles(seq,[],"TEST 完成页：突出任务标题与工作区","ToutiaoKMP · devbox")
        device.send_metadata(seq,('1M','7M','TEST'),[],125,'devbox')
        print(device.send(packet,seq),flush=True)
        sounds=0
        end=time.monotonic()+1.5
        while time.monotonic()<end:
            if device.serial.readline().strip()==b'CDX_AUDIO_DONE':sounds+=1
        print('Audio completion acknowledgments:',sounds,flush=True)
        assert sounds==1,'Expected one audio completion'
        print('Duplicate frame:',device.send(packet,seq),flush=True)
        end=time.monotonic()+1.5
        duplicates=0
        while time.monotonic()<end:
            if device.serial.readline().strip()==b'CDX_AUDIO_DONE':duplicates+=1
        assert duplicates==0,'Duplicate frame replayed notification sound'
        device.send_titles(seq+1,[],"IGNORE background sync","different workspace")
        device.send_metadata(seq+1,('2M','8M','TEST'),[],999)
        heartbeat=frame(seq+1,[(39,10080,'TEST DATA'),(-1,0,'TEST DATA')],0,events.done,0,True,'TEST notification')
        preserved=device.send(heartbeat,seq+1)
        assert 'page=2' in preserved and 'elapsed=125' in preserved,'Background sync changed completed duration'
        print('Completed duration survives background sync: PASS',flush=True)
        print('Synthetic event -> real device ACK -> audio done: PASS; duplicate suppression: PASS',flush=True)
        end=time.monotonic()+max(0,args.hold_seconds)
        while time.monotonic()<end:
            time.sleep(min(3,max(0,end-time.monotonic())))
            device.send(heartbeat,seq+1)
    finally:device.close()
