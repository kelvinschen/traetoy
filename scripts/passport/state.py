"""Immutable observations and durable delivery state; no Codex or USB I/O."""
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import sqlite3
import time


@dataclass(frozen=True)
class Task:
    source: str
    thread: str
    title: str
    project: str
    turn: str = ''
    started: float | None = None

    @property
    def key(self):
        return self.source + '/' + self.thread


@dataclass(frozen=True)
class Completion:
    task: Task
    status: str
    ended: float
    seconds: int = -1


@dataclass(frozen=True)
class Batch:
    source: str
    active: tuple[Task, ...]
    completed: tuple[Completion, ...]
    checkpoint: float


@dataclass(frozen=True)
class Health:
    source: str
    error: str


@dataclass(frozen=True)
class Account:
    kind: str
    value: object
    fetched: float


class State:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        os.chmod(path, 0o600)
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS sources (
                id TEXT PRIMARY KEY, first_seen REAL NOT NULL, checkpoint REAL NOT NULL,
                active TEXT NOT NULL DEFAULT '[]');
            CREATE TABLE IF NOT EXISTS alerts (
                source TEXT, thread TEXT, turn TEXT, payload TEXT NOT NULL,
                ended REAL NOT NULL, seq INTEGER UNIQUE, delivered INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(source, thread, turn));
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value INTEGER NOT NULL);
            INSERT OR IGNORE INTO settings VALUES ('sequence', 1000000000);
        ''')
        self.sources = {}
        self.health = {}
        self.fetched = {}
        self.last_write = {}
        self.enabled = set()
        self.windows = ((-1, 0, 'Not available'),) * 2
        self.quota_fetched = self.usage_fetched = 0
        self.usage = ('--', '--', 'No data')
        self.last_cleanup = 0
        self.thread_filter = None

    def register(self, source, now=None):
        now = time.time() if now is None else now
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO sources(id,first_seen,checkpoint) VALUES (?,?,?)',
                            (source, now, now))
        first, checkpoint, active = self.db.execute(
            'SELECT first_seen,checkpoint,active FROM sources WHERE id=?', (source,)).fetchone()
        self.enabled.add(source)
        self.sources[source] = tuple(Task(**t) for t in json.loads(active))
        self.health[source] = 'Connecting'
        self.fetched[source] = checkpoint
        self.last_write[source] = checkpoint
        return first, checkpoint

    def apply(self, update):
        if isinstance(update, Health):
            self.health[update.source] = update.error
            return
        if isinstance(update, Account):
            if update.kind == 'quota':
                self.windows, self.quota_fetched = update.value, update.fetched
            else:
                self.usage, self.usage_fetched = update.value, update.fetched
            return
        source = update.source
        old = self.sources.get(source, ())
        first = self.db.execute('SELECT first_seen FROM sources WHERE id=?', (source,)).fetchone()[0]
        # A batch is committed atomically: never advance a cursor past an unsaved alert.
        with self.db:
            for done in update.completed:
                if done.ended < first or not done.task.turn:
                    continue
                self.db.execute('INSERT OR IGNORE INTO alerts(source,thread,turn,payload,ended) VALUES (?,?,?,?,?)',
                    (source, done.task.thread, done.task.turn,
                     json.dumps(asdict(done), ensure_ascii=False), done.ended))
            if old != update.active or update.completed or update.checkpoint-self.last_write[source] >= 60:
                self.db.execute('UPDATE sources SET checkpoint=?,active=? WHERE id=?', (
                    update.checkpoint, json.dumps([asdict(t) for t in update.active], ensure_ascii=False), source))
                self.last_write[source] = update.checkpoint
        self.sources[source] = update.active
        self.health[source] = ''
        self.fetched[source] = update.checkpoint
        if time.time() - self.last_cleanup >= 3600:
            with self.db:
                self.db.execute('DELETE FROM alerts WHERE delivered=1 AND ended<?', (time.time()-30*86400,))
            self.last_cleanup = time.time()

    def allocate_sequence(self):
        # Reserve a range so ordinary 3s heartbeats do not require disk writes.
        with self.db:
            start = self.db.execute("SELECT value FROM settings WHERE key='sequence'").fetchone()[0]
            if start >= 2_147_000_000:
                start = 1000000000
            self.db.execute("UPDATE settings SET value=? WHERE key='sequence'", (start+10000,))
        return iter(range(start, start+10000))

    def next_alert(self, next_seq):
        if not self.enabled:
            return None
        placeholders = ','.join('?' for _ in self.enabled)
        row = self.db.execute(f'''SELECT source,thread,turn,payload,seq FROM alerts
            WHERE delivered=0 AND source IN ({placeholders}) AND (? IS NULL OR thread=?)
            ORDER BY ended,source,thread,turn LIMIT 1''',
            (*self.enabled, self.thread_filter, self.thread_filter)).fetchone()
        if not row:
            return None
        source, thread, turn, payload, seq = row
        if seq is None:
            seq = next_seq()
            with self.db:
                self.db.execute('UPDATE alerts SET seq=? WHERE source=? AND thread=? AND turn=?',
                                (seq, source, thread, turn))
        data = json.loads(payload)
        data['task'] = Task(**data['task'])
        return seq, Completion(**data)

    def delivered(self, seq):
        with self.db:
            self.db.execute('UPDATE alerts SET delivered=1 WHERE seq=?', (seq,))

    def active_tasks(self, now=None):
        now = time.time() if now is None else now
        result = []
        for source in sorted(self.enabled):
            stale = bool(self.health.get(source)) or now-self.fetched.get(source, 0) > 30
            observed = min(now, self.fetched.get(source, now)) if stale else now
            for task in self.sources.get(source, ()):
                if self.thread_filter and task.thread != self.thread_filter:
                    continue
                seconds = max(0, int(observed-task.started)) if task.started is not None else -1
                result.append((task, seconds, stale))
        return sorted(result, key=lambda item: item[0].key)

    def done_count(self):
        # Session-independent count of retained successful delivered turns.
        return self.db.execute("SELECT count(*) FROM alerts WHERE delivered=1 AND json_extract(payload,'$.status')='completed'").fetchone()[0]

    def close(self):
        self.db.close()
