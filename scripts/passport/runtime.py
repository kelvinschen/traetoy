"""One USB owner consumes observations independently of source I/O."""
from dataclasses import dataclass
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import queue
import tempfile
import threading
import time

from .sources import LocalSource, RemoteSource, Workers
from .state import Account, Batch, State

LOG = logging.getLogger('passport')


@dataclass(frozen=True)
class DisplayTransaction:
    seq: int
    packet: bytes
    titles: tuple
    usage: tuple
    durations: tuple
    alert_title: str
    alert_project: str
    alert_seconds: int
    is_alert: bool


def transaction(c, state, seq, alert=None):
    now = time.monotonic()
    tasks = state.active_tasks()
    titles = tuple((t.key, t.title, t.project + (' · ?' if stale else ''))
                   for t, _, stale in tasks[:c.TASK_LIMIT])
    durations = tuple((t.key, seconds) for t, seconds, _ in tasks[:c.TASK_LIMIT])
    title = project = ''
    seconds, kind = -1, 0
    if alert:
        title, project, seconds = alert.task.title, alert.task.project, alert.seconds
        if alert.status == 'failed':
            title = 'Failed: ' + title
        kind = 1 if alert.status == 'completed' else 2
    fresh = bool(state.quota_fetched and now-state.quota_fetched < 180)
    usage = state.usage if state.usage_fetched and now-state.usage_fetched < 900 else ('--', '--', 'Delayed')
    packet = c.frame(seq, state.windows, len(tasks), state.done_count(), kind, fresh,
                     c.display_title(title, alert.task.thread) if alert else 'Watching tasks')
    return DisplayTransaction(seq, packet, titles, tuple(usage), durations, title, project, seconds, bool(alert))


def transmit(device, tx):
    device.send_titles(tx.seq, tx.titles, tx.alert_title, tx.alert_project)
    device.send_metadata(tx.seq, tx.usage, tx.durations, tx.alert_seconds)
    return device.send(tx.packet, tx.seq)


def configuration(args, root):
    path = Path(args.config) if args.config else root/'config/bridge.json'
    config = json.loads(path.read_text()) if path.exists() else {'remotes': []}
    remotes = args.remote if args.remote is not None else config.get('remotes', [])
    if args.local_only:
        remotes = []
    if not isinstance(remotes, list) or any(not isinstance(r, str) for r in remotes):
        raise ValueError('remotes must be a list of SSH aliases')
    return list(dict.fromkeys(remotes))


def run(c, args):
    remotes = configuration(args, c.ROOT)
    # Dry-run is a true shadow: no USB and no production notification/cursor writes.
    temporary = tempfile.TemporaryDirectory(prefix='passport-shadow-') if args.dry_run and not args.state_db else None
    state_path = Path(args.state_db) if args.state_db else (
        Path(temporary.name)/'state.sqlite3' if temporary else c.ROOT/'reports/companion-state.sqlite3')
    state = State(state_path)
    state.thread_filter = args.thread
    out, stop = queue.Queue(maxsize=64), threading.Event()
    workers = Workers(out, stop)
    names, names_lock = {}, threading.Lock()
    local_first, local_checkpoint = state.register('local')
    directory = Path(os.environ.get('CODEX_HOME', str(Path.home()/'.codex')))/'sessions'
    workers.start(workers.account, c, args.bucket, args.quota_interval, names, names_lock)
    workers.start(workers.local, lambda: LocalSource(c, directory, local_first, local_checkpoint,
                                                   names, names_lock))
    for alias in remotes:
        first, checkpoint = state.register('ssh:'+alias)
        source = RemoteSource(alias, first, checkpoint, state.sources['ssh:'+alias])
        workers.start(workers.remote, source)
    LOG.info('Bridge v2: local lifecycle compatibility; remotes=%s; USB interval=%.1fs; state=%s',
             remotes, args.interval, state_path)
    device = c.Device(args.port)
    sequences = state.allocate_sequence()

    def next_seq():
        nonlocal sequences
        try:
            return next(sequences)
        except StopIteration:
            sequences = state.allocate_sequence()
            return next(sequences)

    started = time.monotonic()
    end = started+args.seconds if args.seconds else float('inf')
    next_send = started
    next_metrics = started+60
    retry = None
    ready = set()
    required = {'local', *('ssh:'+r for r in remotes), 'quota', 'usage'}
    metrics = {'usb_acks': 0, 'usb_failures': 0, 'max_ack_gap_seconds': 0, 'max_loop_seconds': 0}
    last_ack = None
    try:
        while time.monotonic() < end:
            loop_start = time.monotonic()
            for _ in range(64):
                try:
                    item = out.get_nowait()
                except queue.Empty:
                    break
                state.apply(item)
                if isinstance(item, Batch):
                    ready.add(item.source)
                elif isinstance(item, Account):
                    ready.add(item.kind)
            now = time.monotonic()
            # --once waits for initial data, but the normal USB heartbeat never waits for RPC.
            once_ready = not args.once or required <= ready or now-started >= 20
            if now >= next_send and once_ready:
                next_send = now+args.interval
                if retry is None:
                    pending = state.next_alert(next_seq)
                    seq, alert = pending if pending else (next_seq(), None)
                    retry = transaction(c, state, seq, alert)
                if args.dry_run:
                    LOG.info('Preview: %s tasks=%s health=%s', retry.packet.decode().strip(),
                             [(t[1], t[2]) for t in retry.titles], state.health)
                    if retry.is_alert:
                        state.delivered(retry.seq)
                    retry = None
                else:
                    try:
                        ack = transmit(device, retry)
                        ack_at = time.monotonic()
                        if last_ack is not None:
                            metrics['max_ack_gap_seconds'] = max(metrics['max_ack_gap_seconds'], ack_at-last_ack)
                        last_ack = ack_at
                        metrics['usb_acks'] += 1
                        if retry.is_alert:
                            state.delivered(retry.seq)
                            LOG.info('Notification delivered seq=%d title=%s project=%s',
                                     retry.seq, retry.alert_title, retry.alert_project)
                        LOG.info('USB %s', ack)
                        retry = None
                    except (OSError, c.serial.SerialException) as exc:
                        device.close()
                        metrics['usb_failures'] += 1
                        LOG.warning('USB unavailable: %s', exc)
                        # Alert retries retain the entire immutable transaction. Plain snapshots coalesce.
                        if not retry.is_alert:
                            retry = None
                        if args.once:
                            raise
                if args.once:
                    missing = required-ready
                    if missing:
                        LOG.warning('Initial data unavailable: %s', sorted(missing))
                    break
            metrics['max_loop_seconds'] = max(metrics['max_loop_seconds'], time.monotonic()-loop_start)
            if time.monotonic() >= next_metrics:
                LOG.info('Bridge metrics: %s health=%s', metrics, state.health)
                next_metrics = time.monotonic()+60
            stop.wait(.1)
    finally:
        stop.set()
        device.close()
        workers.join()
        LOG.info('Bridge stopped: %s', metrics)
        state.close()
        if temporary:
            temporary.cleanup()


def configure_logging(root):
    root.mkdir(exist_ok=True)
    handler = RotatingFileHandler(root/'bridge.log', maxBytes=2_000_000, backupCount=3)
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger = logging.getLogger()
    for old in logger.handlers[:]:
        logger.removeHandler(old)
        old.close()
    logger.addHandler(handler)
