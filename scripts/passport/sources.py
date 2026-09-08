"""Native remote metadata and local compatibility observations.

Sources own blocking I/O. They publish atomic batches into a bounded queue;
network failures never interrupt the device scheduler.
"""
import logging
from pathlib import Path, PurePosixPath
import queue
import threading
import time

from .rpc import RPC, RpcError
from .state import Account, Batch, Completion, Health, Task

LOG = logging.getLogger('passport')


def root_thread(thread):
    return not thread.get('ephemeral') and isinstance(thread.get('source'), str)


def elapsed(turn):
    duration = turn.get('durationMs')
    if isinstance(duration, (int, float)) and duration >= 0:
        return int(duration/1000)
    start, end = turn.get('startedAt'), turn.get('completedAt')
    return max(0, int(end-start)) if isinstance(start, (int, float)) and isinstance(end, (int, float)) else -1


class RemoteSource:
    def __init__(self, alias, first_seen, checkpoint, active=(), thread_id=None):
        self.alias = alias
        self.source = 'ssh:' + alias
        self.first_seen, self.checkpoint = first_seen, checkpoint
        self.active = {t.thread: t for t in active}
        self.thread_id = thread_id
        self.projects = {}
        self.next_projects = 0
        self.db_only = True
        self.first_poll = True
        self.next_discovery = 0

    def turns_since(self, rpc, tid, cutoff):
        cursor = None
        seen_cursors = set()
        for _ in range(500):
            params = {'threadId': tid, 'limit': 10, 'itemsView': 'notLoaded', 'sortDirection': 'desc'}
            if cursor:
                params['cursor'] = cursor
            page = rpc.call('thread/turns/list', params)
            rows = page.get('data', [])
            for turn in rows:
                yield turn
            # Fetch all intervening turns, not just the most recent completion.
            if any(isinstance(t.get('completedAt'), (int, float)) and
                   t['completedAt']-rpc.clock_offset < cutoff for t in rows):
                return
            cursor = page.get('nextCursor')
            if not cursor:
                return
            if cursor in seen_cursors:
                raise OSError('Repeated turn cursor')
            seen_cursors.add(cursor)
        raise OSError('Turn backfill exceeds 500 pages; checkpoint unchanged')

    def discover(self, rpc, cutoff):
        candidates = {}
        # A task may finish and be archived while disconnected. Scan both lists
        # with independent cursors so that this lifecycle is not silently lost.
        for archived in (False, True):
            cursor = None
            cursors = set()
            for _ in range(500):
                limit = 1 if (not self.active or archived) and cursor is None else 25
                params = {'limit': limit, 'sortKey': 'updated_at', 'sortDirection': 'desc',
                          'archived': archived}
                if self.db_only:
                    params['useStateDbOnly'] = True
                if cursor:
                    params['cursor'] = cursor
                try:
                    page = rpc.call('thread/list', params)
                except RpcError as exc:
                    if self.db_only and exc.code == -32602:
                        self.db_only = False
                        return self.discover(rpc, cutoff)
                    raise
                rows = page.get('data', [])
                for thread in rows:
                    if root_thread(thread):
                        candidates[thread['id']] = thread
                if not page.get('nextCursor') or any(
                        t.get('updatedAt', time.time()+rpc.clock_offset)-rpc.clock_offset < cutoff
                        for t in rows):
                    break
                cursor = page['nextCursor']
                if cursor in cursors:
                    raise OSError('Repeated thread cursor')
                cursors.add(cursor)
            else:
                raise OSError('Thread backfill exceeds 500 pages; checkpoint unchanged')
        return candidates

    def poll(self, rpc):
        observed = time.time()
        discover = self.first_poll or observed >= self.next_discovery
        # Active-task reads must not advance past short tasks between discoveries.
        discovery_cutoff = max(self.first_seen, getattr(self, 'discovery_checkpoint', self.checkpoint)-3)
        candidates = self.discover(rpc, discovery_cutoff) if discover else {}
        # Long-running threads may be older than the recent metadata page.
        ids = set(self.active)
        if self.first_poll:
            cursor = None
            while True:
                loaded = rpc.call('thread/loaded/list', {'cursor': cursor, 'limit': 100})
                ids.update(loaded.get('data', []))
                new_cursor = loaded.get('nextCursor')
                if not new_cursor:
                    break
                if new_cursor == cursor:
                    raise OSError('Repeated loaded-thread cursor')
                cursor = new_cursor
        for tid in ids-candidates.keys():
            try:
                thread = rpc.call('thread/read', {'threadId': tid, 'includeTurns': False})['thread']
            except RpcError:
                # An unreadable active task remains unknown; don't invent a completion.
                raise OSError('Previously observed task is unreadable')
            if root_thread(thread):
                candidates[tid] = thread
        if observed >= self.next_projects:
            try:
                page = rpc.call('project/list', {'limit': 100})
                self.projects = {p['id']: p.get('name') for p in page.get('data', [])}
            except RpcError as exc:
                if exc.code not in (-32601, -32600):
                    raise
            self.next_projects = observed+600
        active = dict(self.active)
        completions = []
        for tid, thread in candidates.items():
            if self.thread_id and tid != self.thread_id:
                continue
            running = thread.get('status', {}).get('type') == 'active'
            recent = thread.get('updatedAt', 0)-rpc.clock_offset >= discovery_cutoff
            if not running and not recent and tid not in active:
                continue
            cwd = thread.get('cwd') or ''
            project = self.projects.get(thread.get('projectId')) or PurePosixPath(cwd).name or 'No workspace'
            project = f'{project} · {self.alias}'
            title = thread.get('name') or ('Task ' + tid[-8:])
            current = None
            for turn in self.turns_since(rpc, tid, discovery_cutoff):
                started = turn.get('startedAt')
                started = started-rpc.clock_offset if isinstance(started, (int, float)) else None
                task = Task(self.source, tid, title, project, turn['id'], started)
                status = turn.get('status')
                if status == 'inProgress' and current is None:
                    current = task
                ended = turn.get('completedAt')
                if status in ('completed', 'interrupted', 'failed') and isinstance(ended, (int, float)):
                    ended -= rpc.clock_offset
                    if ended >= discovery_cutoff:
                        completions.append(Completion(task, status, ended, elapsed(turn)))
            if running:
                active[tid] = current or Task(self.source, tid, title, project)
            else:
                active.pop(tid, None)
        if discover:
            self.discovery_checkpoint = observed
            self.next_discovery = observed+10
        # Durable checkpoint only covers completed discovery, not just active reads.
        result = Batch(self.source, tuple(sorted(active.values(), key=lambda t: t.key)),
                       tuple(sorted(completions, key=lambda c: c.ended)), self.discovery_checkpoint)
        self.active = active
        self.checkpoint = self.discovery_checkpoint
        self.first_poll = False
        return result


class LocalSource:
    def __init__(self, companion, directory, first_seen, checkpoint, names, names_lock, thread_id=None):
        self.c = companion
        self.names, self.names_lock = names, names_lock
        self.first_seen = first_seen
        self.events = companion.Events(directory, thread_id, since=max(first_seen, checkpoint-3))

    def task(self, tid, turn='', started=None):
        with self.names_lock:
            title, cwd = self.names.get(tid, ('', ''))
        cwd = cwd or self.events.workspaces.get(tid, '')
        return Task('local', tid, title or ('Task '+tid[-8:]), self.c.project_name(cwd), turn, started)

    def poll(self):
        if not self.events.directory.is_dir():
            raise OSError('Local Codex sessions directory unavailable')
        observed = time.time()
        self.events.poll()
        completed = []
        while self.events.completions:
            tid, turn, kind, seconds, ended = self.events.completions.popleft()
            completed.append(Completion(self.task(tid, turn), 'completed' if kind == 1 else 'interrupted', ended, seconds))
        self.events.pending.clear()
        active = tuple(self.task(tid, turn, self.events.start_times.get((tid, turn)))
                       for tid, turn in sorted(self.events.active.items()))
        return Batch('local', active, tuple(completed), observed)


def publish(out, stop, item):
    while not stop.is_set():
        try:
            out.put(item, timeout=.25)
            return True
        except queue.Full:
            pass
    return False


class Workers:
    def __init__(self, out, stop):
        self.out, self.stop = out, stop
        self.threads = []

    def start(self, target, *args):
        thread = threading.Thread(target=target, args=args, daemon=True)
        self.threads.append(thread)
        thread.start()

    def remote(self, source):
        rpc = None
        delay = 1
        next_stats = 0
        try:
            while not self.stop.is_set():
                try:
                    if rpc is None:
                        rpc = RPC.remote(source.alias, stop=self.stop)
                        source.first_poll = True
                        LOG.info('Source %s connected to existing App Server; read-only polling, clock offset %.1fs', source.source, rpc.clock_offset)
                    batch = source.poll(rpc)
                    publish(self.out, self.stop, batch)
                    if time.monotonic() >= next_stats:
                        LOG.info('Source %s active=%d rpc=%d rx=%d tx=%d notifications=%s',
                                 source.source, len(batch.active), rpc.counter, rpc.bytes_read, rpc.bytes_written, dict(rpc.notifications))
                        next_stats = time.monotonic()+60
                    delay = 1
                    self.stop.wait(3 if batch.active else 10)
                except Exception as exc:
                    LOG.warning('Source %s unavailable: %s', source.source, type(exc).__name__)
                    publish(self.out, self.stop, Health(source.source, 'Offline'))
                    if rpc:
                        rpc.close()
                        rpc = None
                    self.stop.wait(delay)
                    delay = min(60, delay*2)
        finally:
            if rpc:
                rpc.close()

    def local(self, factory):
        source = None
        while not self.stop.is_set():
            try:
                if source is None:
                    source = factory()
                publish(self.out, self.stop, source.poll())
                self.stop.wait(3)
            except Exception as exc:
                LOG.warning('Local lifecycle source unavailable: %s', type(exc).__name__)
                publish(self.out, self.stop, Health('local', 'Unavailable'))
                self.stop.wait(5)

    def account(self, c, bucket, quota_interval, names, names_lock):
        rpc = None
        next_due = {'quota': 0, 'usage': 0, 'names': 0}
        intervals = {'quota': quota_interval, 'usage': 300, 'names': 60}
        try:
            while not self.stop.is_set():
                for kind in next_due:
                    if self.stop.is_set() or time.monotonic() < next_due[kind]:
                        continue
                    next_due[kind] = time.monotonic()+intervals[kind]
                    try:
                        if rpc is None:
                            rpc = RPC([c.codex_command(), 'app-server'], stop=self.stop)
                        if kind == 'names':
                            result = rpc.call('thread/list', {'limit': 100, 'sortKey': 'updated_at', 'useStateDbOnly': True})
                            with names_lock:
                                names.clear()
                                names.update({t['id']: (t.get('name') or '', t.get('cwd') or '') for t in result.get('data', [])})
                        else:
                            method = 'account/rateLimits/read' if kind == 'quota' else 'account/usage/read'
                            data = rpc.call(method)
                            value = c.quotas(data, bucket) if kind == 'quota' else c.token_activity(data)
                            publish(self.out, self.stop, Account(kind, value, time.monotonic()))
                            LOG.info('Account %s updated: %s', kind, value)
                    except Exception as exc:
                        LOG.warning('Account %s unavailable: %s', kind, type(exc).__name__)
                        if rpc:
                            rpc.close()
                            rpc = None
                self.stop.wait(.5)
        finally:
            if rpc:
                rpc.close()

    def join(self):
        # RPC deadlines are <=12s; shutdown does not leave proxy processes behind.
        for thread in self.threads:
            thread.join(timeout=16)
