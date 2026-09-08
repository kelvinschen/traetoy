#!/usr/bin/env python3
"""Discover the board, query chip info, or passively read its USB console."""
import argparse
import subprocess
import sys
import time
import serial
from serial.tools import list_ports

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('action', choices=['list', 'info', 'monitor'], nargs='?', default='list')
parser.add_argument('--port')
parser.add_argument('--seconds', type=float, default=10)
args = parser.parse_args()
ports = [p for p in list_ports.comports() if p.vid == 0x303A]
if args.action == 'list':
    for p in ports:
        print(f'{p.device}: {p.description}')
    if not ports:
        print('No Espressif USB device found. Check power and USB data cable.')
        sys.exit(1)
    sys.exit(0)
port = args.port
if not port:
    if len(ports) != 1:
        parser.error('Expected one Espressif device; use --port to select explicitly.')
    port = ports[0].device
if args.action == 'info':
    sys.exit(subprocess.call([sys.executable, '-m', 'esptool', '--port', port, 'chip-id']))
if args.seconds <= 0:
    parser.error('--seconds must be positive')
s = serial.Serial()
s.port, s.baudrate, s.timeout = port, 115200, 0.2
s.dtr = s.rts = False
s.open()
try:
    deadline = time.monotonic() + args.seconds
    while time.monotonic() < deadline:
        data = s.read(4096)
        if data:
            print(data.decode('utf-8', 'replace'), end='', flush=True)
finally:
    s.close()
