"""Read-only JSON-RPC over native stdio or SSH WebSocket proxy.

One owner per connection. wsproto handles framing, masking and fragmentation;
deadlines cover both reads and writes. Only metadata methods are allowed.
"""
from collections import Counter, deque
import json
import os
import re
import select
import shlex
import subprocess
import time

from wsproto import ConnectionType, WSConnection
from wsproto.events import AcceptConnection, CloseConnection, Ping, Request, TextMessage

READ_METHODS = {'initialize', 'thread/list', 'thread/read', 'thread/loaded/list',
                'thread/turns/list', 'project/list', 'account/rateLimits/read', 'account/usage/read'}


class RpcError(RuntimeError):
    def __init__(self, error):
        self.code = error.get('code')
        super().__init__(error.get('message', 'RPC failed'))


class RPC:
    def __init__(self, command, websocket=False, clock_banner=False, timeout=12, stop=None):
        self.timeout = timeout
        self.stop = stop
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, bufsize=0)
        self.ws = WSConnection(ConnectionType.CLIENT) if websocket else None
        self.buffer = b''
        self.parts = []
        self.part_size = 0
        self.messages = deque()
        self.notifications = Counter()
        self.counter = self.bytes_read = self.bytes_written = 0
        self.clock_offset = 0.0
        os.set_blocking(self.process.stdin.fileno(), False)
        try:
            deadline = time.monotonic() + timeout
            if clock_banner:
                banner = b''
                while b'\n' not in banner or not re.search(rb'PASSPORT_CLOCK [0-9]+\r?\n', banner):
                    banner += self._read(deadline)
                    if len(banner) > 65536:
                        raise OSError('Remote login banner too large')
                match = re.search(rb'PASSPORT_CLOCK ([0-9]+)\r?\n', banner)
                self.clock_offset = int(match[1]) - time.time()
                # The proxy cannot send WebSocket frames until our handshake.
            if self.ws:
                self._write(self.ws.send(Request(host='codex-app-server', target='/rpc')), deadline)
                accepted = False
                while not accepted:
                    self.ws.receive_data(self._read(deadline))
                    for event in self.ws.events():
                        if isinstance(event, AcceptConnection):
                            accepted = True
                        else:
                            raise OSError('WebSocket handshake rejected')
            self.info = self.call('initialize', {
                'clientInfo': {'name': 'passport_monitor', 'version': '0.2.0'},
                'capabilities': {'experimentalApi': True}})
            self._send({'method': 'initialized'}, time.monotonic() + timeout)
        except BaseException:
            self.close()
            raise

    @classmethod
    def remote(cls, alias, **kwargs):
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', alias):
            raise ValueError('Use an explicit SSH config alias')
        payload = ('PATH="${CODEX_INSTALL_DIR:-$HOME/.local/bin}:$PATH"; export PATH; '
                   'printf "PASSPORT_CLOCK %s\\n" "$(date +%s)"; exec codex app-server proxy')
        return cls(['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8',
                    '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
                    alias, '"$SHELL" -lic ' + shlex.quote(payload)],
                   websocket=True, clock_banner=True, **kwargs)

    def _read(self, deadline):
        while True:
            if self.stop is not None and self.stop.is_set():
                raise InterruptedError('Monitor shutting down')
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise TimeoutError('RPC read timed out')
            if select.select([self.process.stdout], [], [], min(.25, remaining))[0]:
                break
        data = os.read(self.process.stdout.fileno(), 65536)
        if not data:
            raise EOFError('App Server disconnected')
        self.bytes_read += len(data)
        return data

    def _write(self, data, deadline):
        while data:
            if self.stop is not None and self.stop.is_set():
                raise InterruptedError('Monitor shutting down')
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise TimeoutError('RPC write timed out')
            if not select.select([], [self.process.stdin], [], min(.25, remaining))[1]:
                continue
            count = os.write(self.process.stdin.fileno(), data)
            self.bytes_written += count
            data = data[count:]

    def _send(self, message, deadline):
        text = json.dumps(message, separators=(',', ':'))
        data = self.ws.send(TextMessage(data=text)) if self.ws else (text+'\n').encode()
        self._write(data, deadline)

    def _receive(self, deadline):
        while not self.messages:
            data = self._read(deadline)
            if self.ws:
                self.ws.receive_data(data)
                for event in self.ws.events():
                    if isinstance(event, Ping):
                        self._write(self.ws.send(event.response()), deadline)
                    elif isinstance(event, CloseConnection):
                        raise EOFError('WebSocket closed')
                    elif isinstance(event, TextMessage):
                        self.parts.append(event.data)
                        self.part_size += len(event.data)
                        if self.part_size > 8_000_000:
                            raise OSError('RPC message exceeds metadata limit')
                        if event.message_finished:
                            self.messages.append(json.loads(''.join(self.parts)))
                            self.parts, self.part_size = [], 0
            else:
                self.buffer += data
                if len(self.buffer) > 8_000_000:
                    raise OSError('RPC message exceeds metadata limit')
                while b'\n' in self.buffer:
                    line, self.buffer = self.buffer.split(b'\n', 1)
                    if line.strip():
                        self.messages.append(json.loads(line))
        return self.messages.popleft()

    def call(self, method, params=None):
        if method not in READ_METHODS:
            raise ValueError('Monitor only allows read-only methods')
        self.counter += 1
        rid = self.counter
        deadline = time.monotonic() + self.timeout
        self._send({'id': rid, 'method': method, 'params': params or {}}, deadline)
        while True:
            message = self._receive(deadline)
            if 'method' in message:
                self.notifications[message['method']] += 1
                if 'id' in message:
                    # Never approve commands or claim ownership of another client's work.
                    self._send({'id': message['id'], 'error': {
                        'code': -32601, 'message': 'Read-only monitor'}}, deadline)
                continue
            if message.get('id') == rid:
                if 'error' in message:
                    raise RpcError(message['error'])
                return message['result']

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        for stream in (self.process.stdin, self.process.stdout):
            stream.close()
