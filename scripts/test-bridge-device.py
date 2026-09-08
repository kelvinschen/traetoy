#!/usr/bin/env python3
"""Two clearly labeled synthetic completions through the new durable-state/USB path."""
import argparse
import secrets
import tempfile
import time
from pathlib import Path

import companion as c
from passport.runtime import transaction, transmit
from passport.state import Batch, Completion, State, Task


def fields(line):
    return {k: int(v) for part in line.split() if '=' in part for k, v in [part.split('=', 1)]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=90)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='passport-device-test-') as directory:
        state = State(Path(directory)/'state.db')
        state.register('test', now=0)
        state.windows = [(27, 10080, 'TEST DATA'), (-1, 0, 'TEST DATA')]
        state.quota_fetched = state.usage_fetched = time.monotonic()
        state.usage = ('--', '--', 'TEST')
        base = 2_000_000_000 + secrets.randbelow(10_000_000)
        device = c.Device()
        try:
            heartbeat = transaction(c, state, base)
            ack = transmit(device, heartbeat)
            print('BASELINE', ack, flush=True)
            if fields(ack)['unread']:
                print('SKIP: existing real unread notifications preserved', flush=True)
                return
            packets = []
            for i, name, project, seconds in [(1, 'TEST A 较早完成', 'traetoy', 60),
                                              (2, 'TEST B 最新完成', 'acpus · devbox', 120)]:
                task = Task('test', 'test-'+str(i), name, project, 'turn-'+str(i))
                completed = Completion(task, 'completed', time.time()+i, seconds)
                state.apply(Batch('test', (), (completed,), time.time()))
                seq, alert = state.next_alert(lambda: base+i)
                tx = transaction(c, state, seq, alert)
                ack = transmit(device, tx)
                assert fields(ack)['unread'] == i and fields(ack)['alert'] == seq, ack
                state.delivered(seq)
                packets.append(tx)
                print('DELIVERED', ack, flush=True)
            # Simulate delayed replay of an older USB transaction.
            ack = transmit(device, packets[0])
            assert fields(ack)['unread'] == 2 and fields(ack)['alert'] == base+2, ack
            assert fields(ack)['elapsed'] == 120, ack
            print('PASS: durable deliveries, newest-on-top, delayed replay, immutable duration', flush=True)
            print('READY: OK -> A, hold OK -> home, OK -> A, OK -> home', flush=True)
            expected = [(2, 1, base+1), (0, 1, base+1), (2, 1, base+1), (0, 0, 0)]
            step = 0
            end = time.monotonic()+args.seconds
            next_heartbeat = 0
            packet = c.frame(base+3, state.windows, 0, 2, 0, True, 'TEST')
            while time.monotonic() < end and step < len(expected):
                if time.monotonic() >= next_heartbeat:
                    device.serial.write(packet); device.serial.flush()
                    next_heartbeat = time.monotonic()+3
                line = device.serial.readline().decode('utf-8', 'replace').strip()
                if line.startswith('CDX_VIEW '):
                    print(line, flush=True)
                    value = fields(line)
                    if (value['page'], value['unread'], value['alert']) == expected[step]:
                        step += 1
            print('Physical navigation: '+('PASS' if step == 4 else f'not confirmed ({step}/4)'), flush=True)
        finally:
            device.close()
            state.close()


if __name__ == '__main__':
    main()
