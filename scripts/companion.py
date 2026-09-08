#!/usr/bin/env python3
"""Codex account and multi-host tasks -> AI Passport over USB."""
import argparse
import hashlib
import platform
import shutil
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFont
import fcntl
import datetime as dt
import json
import logging
import os
from pathlib import Path
import signal
import secrets
import subprocess
import time
from collections import deque
import serial
from serial.tools import list_ports

LOG = logging.getLogger('passport')
ROOT = Path(__file__).resolve().parents[1]

def codex_command():
    # npm's launcher only spawns this same native binary; avoid its idle Node process.
    entry = Path(shutil.which('codex') or 'codex').resolve()
    if platform.system() == 'Darwin' and platform.machine() in ('arm64', 'x86_64'):
        arch = 'arm64' if platform.machine() == 'arm64' else 'x64'
        triple = 'aarch64' if arch == 'arm64' else 'x86_64'
        native = entry.parent.parent / f'node_modules/@openai/codex-darwin-{arch}/vendor/{triple}-apple-darwin/bin/codex'
        if native.is_file() and os.access(native, os.X_OK):
            return str(native)
    return str(entry)



def quotas(response, bucket='codex'):
    buckets = response.get('rateLimitsByLimitId')
    selected = buckets.get(bucket) if isinstance(buckets, dict) else None
    if not buckets:
        legacy = response.get('rateLimits')
        if legacy and legacy.get('limitId', 'codex') == bucket:
            selected = legacy
    result = []
    for key in ('primary', 'secondary'):
        w = (selected or {}).get(key)
        if not w or w.get('usedPercent') is None or not w.get('windowDurationMins'):
            continue
        remaining = max(0, min(100, round(100 - float(w['usedPercent']))))
        reset = w.get('resetsAt')
        text = dt.datetime.fromtimestamp(reset).strftime('%m/%d %H:%M') if reset else 'Reset unknown'
        result.append((remaining, int(w['windowDurationMins']), text))
    return (result + [(-1, 0, 'Not available')] * 2)[:2]


def display_title(title, tid):
    # The stock font has Latin glyphs; avoid unreadable boxes for CJK titles.
    clean = ''.join(c if 32 <= ord(c) <= 126 and c != '|' else ' ' for c in title).strip()
    if not title.isascii() or not clean:
        clean = 'Task ' + tid[-8:]
    return clean[:48]


def frame(seq, windows, running, completed, alert, fresh, title):
    a, b = windows
    fields = ['CDX1', seq, a[0], a[1], b[0], b[1], min(999, running), min(999999, completed),
              alert, int(fresh), display_title(title, title), a[2][:16], b[2][:16], 'END']
    return ('|'.join(map(str, fields)) + '\n').encode('ascii')


def compact_tokens(value):
    if value is None:
        return '--'
    for scale, suffix in ((1_000_000_000, 'B'), (1_000_000, 'M'), (1_000, 'K')):
        if value >= scale:
            return f'{value / scale:.2f}'.rstrip('0').rstrip('.') + suffix
    return str(value)


def token_activity(response):
    # Buckets follow the service's dates; do not assume their timezone or invent today's zero.
    buckets = response.get('dailyUsageBuckets')
    if not buckets:
        return ('--', '--', 'No data')
    days = {}
    for bucket in buckets:
        try:
            date = dt.date.fromisoformat(bucket['startDate'])
            tokens = bucket['tokens']
            if isinstance(tokens, int) and not isinstance(tokens, bool) and tokens >= 0:
                days[date] = tokens
        except (KeyError, TypeError, ValueError):
            continue
    if not days:
        return ('--', '--', 'No data')
    latest = max(days)
    start = latest - dt.timedelta(days=6)
    # A short response cannot establish a complete seven-day range.
    week = sum(v for day, v in days.items() if start <= day <= latest) if min(days) <= start else None
    return compact_tokens(days[latest]), compact_tokens(week), latest.strftime('%m/%d')


def metadata_frame(seq, usage, durations, alert_seconds=-1, alert_host=None):
    if len(durations) > TASK_LIMIT:
        raise ValueError('Too many task durations')
    rows = ','.join(f'{title_identity(tid)}:{max(-1, min(2147483647, seconds))}' for tid, seconds in durations) or '-'
    fields = ['CDXM', seq, *usage, alert_seconds, len(durations), rows]
    if alert_host is not None:
        host = ''.join(c if 32 <= ord(c) <= 126 and c != '|' else ' ' for c in alert_host)[:48]
        fields += [0, ','.join(['-1']*7), '--', ','.join(['--']*7), ','.join(['--']*7), -1, host]
    return ('|'.join(map(str, [*fields, 'END'])) + '\n').encode('ascii')


TITLE_WIDTH, TITLE_HEIGHT, TASK_LIMIT = 200, 64, 16

@lru_cache(maxsize=2)
def title_font(size=20):
    font_path = os.environ.get('PASSPORT_TITLE_FONT', '/System/Library/Fonts/Supplemental/Arial Unicode.ttf')
    return ImageFont.truetype(font_path, size)

@lru_cache(maxsize=128)
def title_bitmap(title, project=""):
    font = title_font()
    title = ' '.join(str(title).split())
    lines, line = [], ''
    for char in title:
        if line and font.getlength(line + char) > TITLE_WIDTH:
            split = line.rfind(' ')
            if split > 0:
                lines.append(line[:split]); line = line[split+1:] + char
            else:
                lines.append(line); line = char
            if len(lines) == 2:
                while lines[-1] and font.getlength(lines[-1] + '…') > TITLE_WIDTH:
                    lines[-1] = lines[-1][:-1]
                lines[-1] += '…'; line = ''; break
        else:
            line += char
    if line:
        lines.append(line)
    # FreeType renders grayscale edges; pack four alpha levels, four pixels per byte.
    image = Image.new('L', (TITLE_WIDTH, TITLE_HEIGHT), 0)
    draw = ImageDraw.Draw(image)
    if project:
        project_font = title_font(16)
        project = ' '.join(str(project).split())
        if project_font.getlength(project) > TITLE_WIDTH:
            while project and project_font.getlength(project + '…') > TITLE_WIDTH:
                project = project[:-1]
            project += '…'
        draw.text((0, 0), project, font=project_font, fill=255, anchor='lt')
    for row, text in enumerate(lines):
        draw.text((0, (20 if project else 0) + row * 22), text, font=font, fill=255, anchor='lt')
    pixels = image.tobytes()
    packed = bytearray(len(pixels) // 4)
    for i, alpha in enumerate(pixels):
        packed[i // 4] |= ((alpha * 3 + 127) // 255) << (6 - 2 * (i % 4))
    return bytes(packed)


@lru_cache(maxsize=64)
def completion_bitmap(title, project=''):
    # Reuse the 12,800-pixel slot: 168x60 title + 170x16 workspace; host travels as metadata.
    width = 168
    font = title_font()
    lines, line = [], ''
    for char in ' '.join(str(title or 'Task').split()):
        if line and font.getlength(line + char) > width:
            split = line.rfind(' ')
            if split > 0:
                lines.append(line[:split]); line = line[split+1:] + char
            else:
                lines.append(line); line = char
            if len(lines) == 3:
                while lines[-1] and font.getlength(lines[-1] + '…') > width:
                    lines[-1] = lines[-1][:-1]
                lines[-1] += '…'; line = ''; break
        else:
            line += char
    if line:
        lines.append(line)
    title_area = Image.new('L', (width, 60), 0)
    title_draw = ImageDraw.Draw(title_area)
    for row, text in enumerate(lines):
        title_draw.text((0, row*20), text, font=font, fill=255, anchor='lt')
    metadata = Image.new('L', (170, 16), 0)
    draw = ImageDraw.Draw(metadata)
    project_font = title_font(16)
    project = ' '.join(str(project or 'No workspace').split())
    name, separator, host = project.rpartition(' · ')
    if not separator:
        name, host = project, ''
    for row, text in enumerate((name,)):
        if project_font.getlength(text) > 170:
            while text and project_font.getlength(text + '…') > 170:
                text = text[:-1]
            text += '…'
        draw.text((0, row*16), text, font=project_font, fill=255, anchor='lt')
    pixels = title_area.tobytes() + metadata.tobytes()
    packed = bytearray(len(pixels)//4)
    for i, alpha in enumerate(pixels):
        packed[i//4] |= ((alpha*3+127)//255) << (6-2*(i%4))
    return bytes(packed)


@lru_cache(maxsize=64)
def project_name(cwd):
    if not cwd:
        return 'No workspace'
    path = Path(cwd)
    try:
        # Git common-dir maps subdirectories and linked worktrees to the original project.
        common = subprocess.check_output(['git', '-C', str(path), 'rev-parse', '--path-format=absolute', '--git-common-dir'],
                                         stderr=subprocess.DEVNULL, text=True, timeout=2).strip()
        if common and Path(common).name == '.git':
            return Path(common).parent.name
    except (OSError, subprocess.SubprocessError):
        pass
    return path.name or str(path)


def title_identity(tid):
    return (int.from_bytes(hashlib.sha256(tid.encode()).digest()[:4], 'big') & 0x7fffffff) or 1


def title_packets(seq, task_titles, alert_title, alert_project=""):
    if len(task_titles) > TASK_LIMIT:
        raise ValueError('At most 16 title slots per device snapshot')
    rows = [(i, record[0], record[1], record[2] if len(record) > 2 else '') for i, record in enumerate(task_titles)]
    rows.append((TASK_LIMIT, 'notification', alert_title, alert_project))
    packets = []
    for index, tid, title, project in rows:
        bitmap = completion_bitmap(title, project) if index == TASK_LIMIT else title_bitmap(title, project)
        assert len(bitmap) == TITLE_WIDTH * TITLE_HEIGHT // 4
        packet = f'CDXP|{seq}|{index}|{title_identity(tid)}|{bitmap.hex()}|END\n'.encode('ascii')
        packets.append((packet, f'CDX_TILE_ACK {seq} {index}'))
    packets.append((f'CDXL|{seq}|{len(task_titles)}|END\n'.encode(), f'CDX_LIST_ACK {seq} count={len(task_titles)}'))
    return packets


class Events:
    """Only lifecycle metadata is retained; prompt and assistant text are discarded."""
    def __init__(self, directory, thread_id=None, since=None):
        self.directory = Path(directory)
        self.thread_id = thread_id
        self.started = time.time() if since is None else since
        self.offsets = {}
        self.ids = {}
        self.workspaces = {}
        self.active = {}
        self.start_times = {}
        self.signatures = {}
        self.files_read = self.bytes_read = 0
        self.seen = set()
        self.seen_order = deque()
        self.done = 0
        self.pending = deque()
        self.completions = deque()
        self.last_scan = 0
        self.paths = set()
        self.poll(baseline=since is None)
    def apply(self, record, tid, baseline=False):
        if self.thread_id and tid != self.thread_id:
            return
        if record.get('type') != 'event_msg':
            return
        event = record.get('payload', {})
        kind = event.get('type')
        turn = event.get('turn_id')
        if kind not in ('task_started', 'task_complete', 'turn_aborted') or not turn:
            return
        key = (tid, turn)
        if kind == 'task_started':
            self.active[tid] = turn
            started = event.get('started_at')
            try:
                self.start_times[key] = float(started) if isinstance(started, (int, float)) else dt.datetime.fromisoformat(record['timestamp'].replace('Z', '+00:00')).timestamp()
            except (KeyError, TypeError, ValueError):
                pass
            return
        if self.active.get(tid) == turn:
            self.active.pop(tid, None)
        if key in self.seen:
            return
        self.seen.add(key)
        self.seen_order.append(key)
        if len(self.seen_order) > 8192:
            self.seen.discard(self.seen_order.popleft())
        try:
            when = dt.datetime.fromisoformat(record['timestamp'].replace('Z', '+00:00')).timestamp()
        except (KeyError, ValueError):
            return  # Never alert on an event with unknown age.
        started = self.start_times.pop(key, None)
        elapsed = event.get('duration_ms')
        seconds = int(elapsed / 1000) if isinstance(elapsed, (int, float)) and elapsed >= 0 else max(0, int(when-started)) if started is not None else -1
        if baseline or when < self.started:
            return
        alert = 1 if kind == 'task_complete' else 2
        if alert == 1:
            self.done += 1
        self.pending.append((tid, alert, seconds))
        self.completions.append((tid, turn, alert, seconds, when))
    def elapsed(self, tid):
        start = self.start_times.get((tid, self.active.get(tid)))
        return max(0, int(time.time() - start)) if start is not None else -1

    def poll(self, baseline=False):
        if baseline or time.monotonic() - self.last_scan >= 10:
            cutoff = self.started-86400 if not self.last_scan else time.time()-86400
            self.last_scan = time.monotonic()
            for p in self.directory.rglob('*.jsonl'):
                try:
                    if p.stat().st_mtime >= cutoff:
                        self.paths.add(p)
                except OSError:
                    continue
            # Keep active rollouts, but retire unchanged inactive files after a
            # day. A future append will rediscover them through their new mtime.
            for p in tuple(self.paths):
                if self.ids.get(p) in self.active:
                    continue
                try:
                    old = p.stat().st_mtime < time.time()-86400
                except OSError:
                    old = True
                if old and p in self.offsets:
                    self.paths.discard(p)
                    for mapping in (self.ids, self.offsets, self.signatures):
                        mapping.pop(p, None)
        for p in sorted(self.paths):
            try:
                stat = p.stat()
                signature = (stat.st_ino, stat.st_size, stat.st_mtime_ns)
                if self.signatures.get(p) == signature:
                    continue
                self.signatures[p] = signature
                with p.open('rb') as f:
                    self.files_read += 1
                    size = os.fstat(f.fileno()).st_size
                    offset = self.offsets.get(p, 0)
                    if size < offset:
                        offset = 0
                    f.seek(offset)
                    while True:
                        position = f.tell()
                        line = f.readline()
                        if not line or not line.endswith(b'\n'):
                            self.offsets[p] = position
                            break
                        self.bytes_read += len(line)
                        if not any(marker in line for marker in (b'"session_meta"', b'"task_started"', b'"task_complete"', b'"turn_aborted"')):
                            continue
                        try:
                            r = json.loads(line)
                        except (ValueError, UnicodeDecodeError):
                            continue
                        if r.get('type') == 'session_meta':
                            meta = r.get('payload', {})
                            source = meta.get('source')
                            # Exclude internal subagents; root user sessions are strings.
                            self.ids[p] = meta.get('id') if isinstance(source, str) else None
                            if self.ids[p]:
                                self.workspaces[self.ids[p]] = meta.get('cwd') or ''
                        tid = self.ids.get(p)
                        if tid:
                            self.apply(r, tid, baseline)
            except OSError:
                continue


class Device:
    def __init__(self, port=None):
        self.port = port
        self.serial = None
        self.refresh = False
        self.title_signature = None
    def close(self):
        self.title_signature = None
        if self.serial:
            self.serial.close()
            self.serial = None
    def connect(self):
        ports = [p.device for p in list_ports.comports() if p.vid == 0x303A]
        port = self.port
        if not port:
            if len(ports) != 1:
                raise OSError('Connect one Espressif board, or supply --port')
            port = ports[0]
        s = serial.Serial()
        s.port, s.baudrate, s.timeout, s.write_timeout = port, 115200, .15, 2
        s.dtr = s.rts = False
        s.open()
        self.serial = s
        LOG.info('USB connected: %s', port)
    def send(self, packet, seq):
        if not self.serial:
            self.connect()
        # Retry the identical sequence; firmware deduplicates notification sound.
        for attempt in range(2):
            self.serial.write(packet)
            self.serial.flush()
            end = time.monotonic() + 3
            while time.monotonic() < end:
                line = self.serial.readline().decode('utf-8', 'replace').strip()
                if line.startswith(('CDX_VIEW ', 'CDX_AUDIO_DONE')):
                    LOG.info('Device: %s', line)
                if line.startswith(f'CDX_ACK {seq} '):
                    return line
                if line == 'CDX_REFRESH':
                    self.refresh = True
        raise OSError('No CDX_ACK: companion firmware is required, or device is unavailable')

    def send_metadata(self, seq, usage, durations, alert_seconds, alert_host=None):
        packet = metadata_frame(seq, usage, durations, alert_seconds, alert_host)
        if not self.serial:
            self.connect()
        for attempt in range(2):
            self.serial.write(packet); self.serial.flush()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                line = self.serial.readline().decode('utf-8', 'replace').strip()
                if line.startswith(('CDX_VIEW ', 'CDX_AUDIO_DONE')):
                    LOG.info('Device: %s', line)
                if line == f'CDX_META_ACK {seq}':
                    return
        raise OSError('No metadata acknowledgment')

    def send_titles(self, seq, task_titles, alert_title, alert_project=""):
        signature = (tuple(task_titles), alert_title, alert_project)
        if signature == self.title_signature and self.serial:
            return
        if not self.serial:
            self.connect()
        for packet, expected in title_packets(seq, task_titles, alert_title, alert_project):
            matched = False
            for attempt in range(2):
                self.serial.write(packet)
                self.serial.flush()
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    line = self.serial.readline().decode('utf-8', 'replace').strip()
                    if line == expected:
                        matched = True
                        break
                if matched:
                    break
            if not matched:
                raise OSError('Title transaction not acknowledged')
        self.title_signature = signature
        LOG.info('Task titles synced: %d', len(task_titles))


def run(args):
    from passport.runtime import run as run_bridge
    import sys
    return run_bridge(sys.modules[__name__], args)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port')
    p.add_argument('--thread', help='Only monitor this root task UUID across configured hosts')
    p.add_argument('--config', help='Bridge JSON config; default config/bridge.json')
    p.add_argument('--remote', action='append', help='SSH alias; repeat for multiple hosts, overrides config')
    p.add_argument('--local-only', action='store_true', help='Use only local compatibility source')
    p.add_argument('--state-db', help='Override durable state path; dry-run defaults to temporary state')
    p.add_argument('--log-file', action='store_true', help='Write rotated workspace bridge.log')
    p.add_argument('--bucket', default='codex')
    p.add_argument('--interval', type=float, default=3)
    p.add_argument('--quota-interval', type=float, default=60)
    p.add_argument('--seconds', type=float, default=0, help='Stop after this duration; 0 runs until Ctrl-C')
    p.add_argument('--once', action='store_true')
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args()
    if args.interval < 1 or args.quota_interval < 10 or args.seconds < 0:
        p.error('interval >= 1, quota-interval >= 10, seconds >= 0 required')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    if args.log_file:
        from passport.runtime import configure_logging
        configure_logging(ROOT/'reports')
    lock = None
    if not args.dry_run:
        (ROOT / 'reports').mkdir(exist_ok=True)
        lock = (ROOT / 'reports/bridge.lock').open('a')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            p.error('Another bridge is running; stop it before opening USB again')
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        run(args)
    except KeyboardInterrupt:
        pass

if __name__ == '__main__':
    main()
