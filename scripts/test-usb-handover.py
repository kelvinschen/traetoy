#!/usr/bin/env python3
"""Verify exclusive BLE-to-USB takeover without physical cable manipulation.
Run with the bridge stopped, a paired device plugged in and no unread alerts.
Uses a temporary state database and shows no real tasks or test notifications.
"""
import argparse
from pathlib import Path
import signal
import subprocess
import tempfile
import time
from serial.tools import list_ports

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--port')
parser.add_argument('--log', type=Path, default=ROOT/'reports/usb-handover.log')
args = parser.parse_args()
ports = [p.device for p in list_ports.comports() if p.vid == 0x303A]
if not args.port and len(ports) != 1:
    parser.error('Connect one Passport or specify --port')
physical = Path(args.port or ports[0]).resolve(strict=True)
args.log.parent.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='passport-handover-') as directory:
    scratch = Path(directory)
    port = scratch/'usb-port'
    with args.log.open('w') as output:
        process = subprocess.Popen([
            str(ROOT/'rust-bridge/target/release/passport-bridge'),
            '--workspace', str(ROOT), '--local-only', '--thread', 'handover-no-task',
            '--state-db', str(scratch/'state.sqlite3'), '--port', str(port),
            '--transport', 'auto', '--seconds', '100',
        ], stdout=output, stderr=output)
        try:
            until = time.monotonic()+60
            while time.monotonic() < until:
                lines = args.log.read_text().splitlines()
                baseline = [s for s in lines if 'link=ble' in s]
                if baseline:
                    assert 'unread=0' in baseline[-1], 'Dismiss unread alerts before testing'
                    print('BLE baseline connected', flush=True)
                    # Only make the USB path available. The cable never moves,
                    # isolating serial open from any power or enumeration event.
                    port.symlink_to(physical)
                    break
                if process.poll() is not None:
                    raise RuntimeError(f'Bridge exited; see {args.log}')
                time.sleep(.2)
            else:
                raise AssertionError('No BLE baseline within 60 seconds')
            # Observe several heartbeats after takeover to catch an accidental
            # BLE reconnect while USB remains active.
            time.sleep(27)
            lines = args.log.read_text().splitlines()
            usb = [s for s in lines if 'link=usb' in s]
            assert len(usb) >= 5, f'USB did not provide regular acknowledgments: {usb}'
            assert all('usb=1 ble=0' in s for s in usb[1:]), f'BLE remained connected after USB takeover: {usb[-2:]}'
            assert 'BLE disconnected for USB takeover' in '\n'.join(lines), 'BLE was not explicitly released'
            transcript = '\n'.join(lines)
            assert transcript.index('BLE disconnected for USB takeover') < transcript.index('USB connected'), 'USB opened before BLE was released'
            print('PASS: USB took over; BLE disconnected and stayed disconnected', flush=True)
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
            process.wait(timeout=25)
