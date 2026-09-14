#!/usr/bin/env python3
"""Passport live hook transport. No database, event spool, or history replay.

A native sender passes input to this bridge-owned receiver over a private local
socket. Only normalized metadata leaves the host; raw input is never retained.
The receiver watches only transcripts named by newly received hooks, from the
byte offset captured by that hook. This supplies terminal errors absent from
Codex 0.153.4's Stop hook and avoids treating Stop continuations as completion.
"""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime
import math
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import select
import signal
import socket
import stat
import struct
import sys
import time
import uuid

VERSION = 1
MAX_PAYLOAD = 1_000_000
MAX_CLIENTS = 8
MAX_PENDING = 1024
CLIENT_TIMEOUT = .1
MAX_LINE = 8_000_000
HEARTBEAT_SECONDS = 5
INPUT_TOOLS = {"request_user_input", "request_user_input_async"}
EVENTS = {"SessionEnd", "UserPromptSubmit", "Stop", "Interrupt",
          "PermissionRequest", "PreToolUse", "PostToolUse"}


def codex_home():
    return Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))


def default_socket():
    return codex_home() / "passport" / "events.sock"


def short(value, length=180):
    return " ".join(str(value or "").split())[:length]


def thread_title(home, session, fallback):
    # Event-triggered name lookup, not task discovery or database polling.
    try:
        with (home / "session_index.jsonl").open("rb") as source:
            source.seek(0, os.SEEK_END)
            source.seek(max(0, source.tell() - 262144))
            for line in reversed(source.read(262144).splitlines()):
                try:
                    entry = json.loads(line)
                    if entry.get("id") == session:
                        return short(entry.get("thread_name") or fallback)
                except (ValueError, TypeError):
                    continue
    except OSError:
        pass
    return short(fallback)


def normalize(payload, home, include_title=True):
    event = payload.get("hook_event_name")
    session = payload.get("session_id")
    if event not in EVENTS or not isinstance(session, str) or not session or len(session) > 128:
        return None
    # Only root tasks affect the pet; child hooks carry agent_id in Codex 0.153.4.
    if payload.get("agent_id"):
        return None
    tool = str(payload.get("tool_name", "")).split(".")[-1]
    if event == "PreToolUse" and tool not in INPUT_TOOLS:
        return None
    cwd = payload.get("cwd") or ""
    project = Path(cwd).name or "No workspace"
    path = payload.get("transcript_path")
    offset = None
    if isinstance(path, str) and os.path.isabs(path):
        try:
            offset = os.stat(path).st_size
        except OSError:
            pass
    # Ephemeral Codex work (including automatic thread titles) also fires hooks,
    # but has no transcript or observable final lifecycle record. Never count it.
    if offset is None and event not in {"SessionEnd", "Interrupt"}:
        return None
    call = short(payload.get("tool_use_id"), 128)
    if event in {"PermissionRequest", "PostToolUse"} and tool not in INPUT_TOOLS:
        # PermissionRequest has no tool_use_id in Codex 0.153.4. Correlate its
        # semantic input with PostToolUse without sending command/argument text.
        arguments = payload.get("tool_input", {})
        if isinstance(arguments, dict):
            arguments = {k: v for k, v in arguments.items() if k != "description"}
        digest = hashlib.sha256(json.dumps([tool, arguments], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        call = "approval:" + digest[:32]
    turn = payload.get("turn_id") or ""
    if not isinstance(turn, str) or len(turn) > 128:
        return None
    return {
        "v": VERSION, "event": event, "id": uuid.uuid4().hex,
        "thread": session, "turn": turn,
        "title": thread_title(home, session, project) if include_title else "",
        "project": short(project, 100), "tool": short(tool, 100),
        "call": call,
        "transcript": path if offset is not None else None, "offset": offset,
    }


def send_hook(destination, payload):
    """Python diagnostic entry point; installed hooks use the native sender."""
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > MAX_PAYLOAD:
        return False
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(0.05)
        try:
            client.connect(str(destination))
            client.sendall(struct.pack("!I", len(encoded)) + encoded)
            return client.recv(1) == b"1"
        except OSError:
            return False  # Drop without retry, queue or recovery.


def peer_open(client):
    try:
        return client.recv(1, socket.MSG_PEEK) != b""
    except BlockingIOError:
        return True
    except OSError:
        return False


class FileEvents:
    """kqueue on macOS and inotify on Linux; no recurring file stat/read loop."""
    def __init__(self):
        self.files = {}
        if sys.platform == "darwin":
            self.queue = select.kqueue()
            self.fd = self.queue.fileno()
            self.lib = None
        elif sys.platform.startswith("linux"):
            self.lib = ctypes.CDLL(None, use_errno=True)
            self.lib.inotify_init1.argtypes = [ctypes.c_int]
            self.lib.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
            self.lib.inotify_rm_watch.argtypes = [ctypes.c_int, ctypes.c_int]
            self.fd = self.lib.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
            if self.fd < 0:
                raise OSError(ctypes.get_errno(), "inotify_init1")
            self.queue = None
        else:
            raise RuntimeError("Passport hooks support macOS and Linux")

    def add(self, path, file):
        if self.queue is not None:
            key = file.fileno()
            event = select.kevent(key, filter=select.KQ_FILTER_VNODE,
                flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR,
                fflags=select.KQ_NOTE_WRITE | select.KQ_NOTE_EXTEND | select.KQ_NOTE_DELETE | select.KQ_NOTE_RENAME)
            self.queue.control([event], 0, 0)
        else:
            key = self.lib.inotify_add_watch(self.fd, os.fsencode(path), 0x2 | 0x4 | 0x8 | 0x400 | 0x800)
            if key < 0:
                raise OSError(ctypes.get_errno(), "inotify_add_watch")
        self.files[key] = path
        return key

    def remove(self, key):
        if key not in self.files:
            return
        del self.files[key]
        try:
            if self.queue is not None:
                self.queue.control([select.kevent(key, filter=select.KQ_FILTER_VNODE,
                    flags=select.KQ_EV_DELETE)], 0, 0)
            else:
                self.lib.inotify_rm_watch(self.fd, key)
        except OSError:
            pass

    def ready(self):
        changed = set()
        if self.queue is not None:
            for event in self.queue.control(None, 128, 0):
                path = self.files.get(event.ident)
                if path:
                    gone = bool(event.fflags & (select.KQ_NOTE_DELETE | select.KQ_NOTE_RENAME))
                    changed.add((path, gone))
        else:
            try:
                data = os.read(self.fd, 65536)
            except BlockingIOError:
                return changed
            offset = 0
            while offset + 16 <= len(data):
                key, mask, cookie, length = struct.unpack_from("iIII", data, offset)
                offset += 16 + length
                path = self.files.get(key)
                if path:
                    changed.add((path, bool(mask & (0x400 | 0x800))))
                if mask & 0x4000:  # IN_Q_OVERFLOW: report loss rather than scan history.
                    changed.update((p, True) for p in self.files.values())
        return changed

    def close(self):
        if self.queue is not None:
            self.queue.close()
        else:
            os.close(self.fd)


def quota_snapshot(value):
    """Only a small codex quota snapshot leaves the host, never token/text data."""
    try:
        raw = value["payload"]["rate_limits"]
        if not isinstance(raw, dict) or raw.get("limit_id", "codex") != "codex":
            return None
        stamp = datetime.fromisoformat(value["timestamp"].replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return None
        at = stamp.timestamp()
        if not math.isfinite(at) or not 0 <= time.time() - at <= 300:
            return None
        result = {"limitId": "codex"}
        for key in ("primary", "secondary"):
            window = raw.get(key)
            if window is None:
                result[key] = None
                continue
            used, minutes, reset = (window.get(k) for k in ("used_percent", "window_minutes", "resets_at"))
            if (type(used) not in (int, float) or not math.isfinite(used) or not 0 <= used <= 100
                    or type(minutes) is not int or not 0 < minutes <= 525600
                    or type(reset) is not int or not 0 < reset < 100000000000):
                return None
            result[key] = dict(usedPercent=used, windowDurationMins=minutes, resetsAt=reset)
        if result["primary"] is None and result["secondary"] is None:
            return None
        return dict(quota=result, quota_at=at)
    except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
        return None


class Transcript:
    def __init__(self, message, watcher):
        self.message = message
        self.path = message["transcript"]
        self.file = open(self.path, "rb", buffering=0)
        self.file.seek(message["offset"])
        self.buffer = b""
        self.key = watcher.add(self.path, self.file)

    def read(self):
        # Bound work per wakeup without interpreting assistant/tool text as events.
        data = self.file.read(MAX_LINE + 1)
        self.buffer += data
        if len(self.buffer) > MAX_LINE and b"\n" not in self.buffer:
            raise ValueError("oversized transcript record")
        lines = self.buffer.split(b"\n")
        self.buffer = lines.pop()
        for line in lines:
            try:
                value = json.loads(line)
                if value.get("type") != "event_msg":
                    continue
                event = value.get("payload", {})
                if event.get("type") == "token_count":
                    snapshot = quota_snapshot(value)
                    if snapshot:
                        yield dict(type="quota", **snapshot)
                if event.get("type") in {"task_complete", "turn_aborted"}:
                    yield event
            except (ValueError, TypeError, AttributeError):
                continue

    def close(self, watcher):
        watcher.remove(self.key)
        self.file.close()


class Receiver:
    def __init__(self, emit):
        self.emit = emit
        self.watcher = FileEvents()
        self.transcripts = {}
        self.pending = {}  # Only calls that actually emitted a waiting event.

    def clear_pending(self, thread):
        self.pending = {key: count for key, count in self.pending.items() if key[0] != thread}

    def receive(self, payload, home, connected=None):
        if not isinstance(payload, dict) or payload.get("agent_id"):
            return
        event = payload.get("hook_event_name")
        thread, turn = payload.get("session_id"), payload.get("turn_id")
        if event == "PostToolUse" and not any(
                key[:2] == (thread, turn) for key in self.pending):
            return  # Normal tool calls need no title lookup, stat, hash or Rust frame.
        message = normalize(payload, home, include_title=event != "PostToolUse")
        if message is None:
            return
        # A timed-out sender may have already let Codex finish. Do not commit a
        # late start whose transcript offset was captured after that completion.
        if connected is not None and not connected():
            return
        key = (message["thread"], message["turn"], message["call"])
        if event in {"PermissionRequest", "PreToolUse"} and key not in self.pending and len(self.pending) >= MAX_PENDING:
            self.frame(message, "unavailable", reason="pending hook limit")
            return
        if event == "PostToolUse" and key not in self.pending:
            return
        self.hook(message)

    def frame(self, message, kind, **extra):
        fields = {k: message.get(k, "") for k in ("id", "thread", "turn", "title", "project", "call", "tool")}
        self.emit(dict(v=VERSION, kind=kind, **fields, **extra))

    def hook(self, message):
        if message.get("v") != VERSION or message.get("event") not in EVENTS:
            return
        if not isinstance(message.get("thread"), str) or not message["thread"]:
            return
        event = message["event"]
        path = message.get("transcript")
        if path and isinstance(message.get("offset"), int) and message["offset"] >= 0:
            if path not in self.transcripts:
                if len(self.transcripts) >= 128:
                    self.frame(message, "unavailable", reason="active transcript limit")
                    return
                try:
                    self.transcripts[path] = Transcript(message, self.watcher)
                except (OSError, ValueError):
                    self.frame(message, "unavailable", reason="transcript unavailable")
                    return
            elif event == "UserPromptSubmit" or self.transcripts[path].message.get("turn") == message.get("turn"):
                previous = self.transcripts[path].message
                self.transcripts[path].message = dict(message,
                    title=message.get("title") or previous.get("title", ""))
        key = (message["thread"], message.get("turn", ""), message.get("call", ""))
        if event == "UserPromptSubmit":
            self.clear_pending(message["thread"])
            self.frame(message, "started")
        elif event == "PermissionRequest" or event == "PreToolUse":
            self.pending[key] = self.pending.get(key, 0) + 1 if event == "PermissionRequest" else 1
            self.frame(message, "waiting", asynchronous=message.get("tool") == "request_user_input_async")
        elif event == "PostToolUse":
            if self.pending.get(key, 0) <= 1:
                self.pending.pop(key, None)
            else:
                self.pending[key] -= 1
            self.frame(message, "tool_finished")
        elif event == "SessionEnd":
            self.clear_pending(message["thread"])
            self.frame(message, "closed")
            if path in self.transcripts:
                self.transcripts.pop(path).close(self.watcher)
        elif event == "Interrupt":
            self.clear_pending(message["thread"])
            # Explicit interruption is final even if transcript flush is delayed.
            self.frame(message, "interrupted")
            if path in self.transcripts:
                self.transcripts.pop(path).close(self.watcher)
        # Stop intentionally emits no completion: another Stop hook may continue.
        if path in self.transcripts:
            self.read(path)

    def read(self, path, gone=False):
        tracked = self.transcripts.get(path)
        if tracked is None:
            return
        terminal = False
        try:
            gone = gone or os.fstat(tracked.file.fileno()).st_nlink == 0
            for event in tracked.read():
                if event["type"] == "quota":
                    self.frame(tracked.message, "quota", quota=event["quota"], quota_at=event["quota_at"])
                    continue
                turn = event.get("turn_id")
                if not turn or turn != tracked.message.get("turn"):
                    continue
                kind = "interrupted" if event["type"] == "turn_aborted" else "failed" if event.get("error") else "completed"
                self.frame(tracked.message, kind, seconds=max(0, int(event.get("duration_ms") or 0) // 1000))
                terminal = True
        except (OSError, ValueError):
            gone = True
        if gone and not terminal:
            self.frame(tracked.message, "unavailable", reason="active transcript lost")
        if terminal or gone:
            self.clear_pending(tracked.message["thread"])
            self.transcripts.pop(path).close(self.watcher)

    def close(self):
        for tracked in self.transcripts.values():
            tracked.close(self.watcher)
        self.watcher.close()


def listen(destination):
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(destination.parent, 0o700)
    with open(destination.parent / "receiver.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if destination.exists():
            metadata = destination.lstat()
            if not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != os.getuid():
                raise RuntimeError("refusing to replace non-owned socket path")
            destination.unlink()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(destination))
            os.chmod(destination, 0o600)
            server.listen(MAX_CLIENTS)
            server.setblocking(False)
            os.set_blocking(sys.stdout.fileno(), False)
            def emit(value):
                encoded = (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
                if len(encoded) > 4000:
                    raise ValueError("oversized wire frame")
                os.write(sys.stdout.fileno(), encoded)
            receiver = Receiver(emit)
            clients = {}
            ended = False
            def stop(signum, frame):
                nonlocal ended
                ended = True
            for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
                signal.signal(sig, stop)
            try:
                emit({"v": VERSION, "kind": "ready"})
                due = time.monotonic() + HEARTBEAT_SECONDS
                while not ended:
                    deadline = min([due] + [entry[1] for entry in clients.values()])
                    ready, _, _ = select.select([server, receiver.watcher.fd, sys.stdin, *clients],
                        [], [], max(0, deadline-time.monotonic()))
                    if sys.stdin in ready and not os.read(sys.stdin.fileno(), 1024):
                        break
                    if server in ready:
                        client, _ = server.accept()
                        client.setblocking(False)
                        if len(clients) >= MAX_CLIENTS:
                            client.close()
                        else:
                            clients[client] = (bytearray(), time.monotonic()+CLIENT_TIMEOUT)
                    for client, (buffer, expires) in list(clients.items()):
                        finished = time.monotonic() >= expires
                        if client in ready and not finished:
                            try:
                                data = client.recv(65536)
                                if not data:
                                    finished = True
                                buffer.extend(data)
                                if len(buffer) >= 4:
                                    length = struct.unpack("!I", buffer[:4])[0]
                                    if not 0 < length <= MAX_PAYLOAD or len(buffer) > length+4:
                                        finished = True
                                    elif len(buffer) == length+4:
                                        receiver.receive(json.loads(buffer[4:]), codex_home(),
                                            connected=lambda: peer_open(client))
                                        # Position/watch registration precede ACK, so Codex
                                        # cannot finish the turn before we begin observing it.
                                        client.send(b"1")
                                        finished = True
                            except (OSError, ValueError, TypeError, AttributeError, RecursionError):
                                finished = True
                        if finished:
                            client.close()
                            del clients[client]
                    if receiver.watcher.fd in ready:
                        for path, gone in receiver.watcher.ready():
                            receiver.read(path, gone)
                    if time.monotonic() >= due:
                        emit({"v": VERSION, "kind": "pulse"})
                        due = time.monotonic() + HEARTBEAT_SECONDS
            finally:
                for client in clients:
                    client.close()
                receiver.close()
                destination.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen", action="store_true")
    parser.add_argument("--socket", type=Path, default=default_socket())
    args = parser.parse_args()
    if args.listen:
        listen(args.socket)
    else:
        try:
            value = json.loads(sys.stdin.buffer.read(1_000_001))
            if isinstance(value, dict):
                send_hook(args.socket, value)
        except (ValueError, OSError, TypeError):
            pass
        # Valid neutral output for every configured hook. Never affect the turn.
        print("{}")


if __name__ == "__main__":
    main()
