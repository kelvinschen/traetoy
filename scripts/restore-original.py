#!/usr/bin/env python3
"""Explicitly restore only the backed-up application, preserving other partitions."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import sys
from serial.tools import list_ports
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--port')
p.add_argument('--restore',action='store_true',help='Actually write the original application')
a=p.parse_args()
root=Path(__file__).resolve().parents[1]
b=root/'backups/original-flash.bin'
data=b.read_bytes()
expected=(root/'backups/original-flash.sha256').read_text().split()[0]
assert len(data)==8388608 and hashlib.sha256(data).hexdigest()==expected, 'Backup integrity check failed'
ports=[x.device for x in list_ports.comports() if x.vid==0x303A]
port=a.port or (ports[0] if len(ports)==1 else None)
if not port:p.error('Specify --port for the original device')
if not a.restore:
 print('Backup verified. Stop the bridge, then add --restore to write the original app at 0x10000.')
 sys.exit(0)
# Bind restore to the same physical device that was backed up.
found=next((x for x in list_ports.comports() if x.device==port),None)
identity=(root/'backups/device-serial.txt').read_text().strip()
if not found or found.serial_number!=identity:p.error('Selected USB serial does not match the backed-up device')
app=root/'backups/original-app.bin'
app.write_bytes(data[0x10000:0x310000]);app.chmod(0o600)
sys.exit(subprocess.call([sys.executable,'-m','esptool','--chip','esp32c3','--port',port,'write-flash','0x10000',str(app)]))
