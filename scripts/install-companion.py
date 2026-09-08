#!/usr/bin/env python3
"""Install only the verified companion app on the backed-up Passport."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import sys
from serial.tools import list_ports
from firmware import verified_image
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--install',action='store_true')
p.add_argument('--workspace',default='codex',help='Firmware workspace name (default: codex)')
a=p.parse_args()
try:
    full=verified_image(a.workspace)
except (ValueError,OSError) as error:
    p.error(f'{error}; run scripts/firmware.py build {a.workspace} first')
image=full.read_bytes()
if len(image)<=0x10000 or len(image)>0x310000 or image[0x10000]!=0xe9:
    p.error('Merged image has an unexpected application offset or size')
backup=(ROOT/'backups/original-flash.bin').read_bytes()
expected=(ROOT/'backups/original-flash.sha256').read_text().split()[0]
if len(backup)!=0x800000 or hashlib.sha256(backup).hexdigest()!=expected:
    p.error('Original backup integrity failed')
identity=(ROOT/'backups/device-serial.txt').read_text().strip()
ports=[x for x in list_ports.comports() if x.vid==0x303A and x.serial_number==identity]
if len(ports)!=1:p.error('Wake and connect the original backed-up Passport')
app=full.parent/'passport-app.bin'
app.write_bytes(image[0x10000:])
print(f'App: {len(image)-0x10000} bytes at 0x10000; original bootloader/table/identity/resources preserved',flush=True)
if not a.install:
    print('Preview only. Add --install to write the app.');sys.exit(0)
# Verify protected bytes still match the saved device before and after app-only flashing.
regions=[]
for name,start,length in [('boot-and-table',0,0x9000),('cardid',0x356000,0x4000)]:
    part=ROOT/f'backups/{name}.bin';part.write_bytes(backup[start:start+length]);part.chmod(0o600)
    regions += [hex(start),str(part)]
base=[sys.executable,'-m','esptool','--chip','esp32c3','--port',ports[0].device,'--baud','460800']
subprocess.run(base+['verify-flash']+regions,check=True)
subprocess.run(base+['write-flash','0x10000',str(app)],check=True)
subprocess.run(base+['verify-flash']+regions,check=True)
print('Installation and protected-region verification passed.',flush=True)
