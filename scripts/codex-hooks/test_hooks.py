#!/usr/bin/env python3
"""Offline integration tests for the real hook sender, receiver and OS file watcher."""
import importlib.util
import json
import os
from pathlib import Path
import queue
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest

SCRIPT = Path(__file__).with_name('hook.py')
spec = importlib.util.spec_from_file_location('passport_hook', SCRIPT)
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


_sender_directory = None


def sender_binary():
    global _sender_directory
    if _sender_directory is None:
        _sender_directory = tempfile.TemporaryDirectory(prefix='passport-native-test-')
        path = Path(_sender_directory.name)/'hook'
        subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror',
            str(SCRIPT.with_name('send.c')),'-o',str(path)],check=True,capture_output=True)
    return Path(_sender_directory.name)/'hook'


class LiveReceiver:
    def __init__(self, home):
        self.home = Path(home)
        self.sender = sender_binary()
        self.socket = self.home / 'passport/events.sock'
        self.env = dict(os.environ, CODEX_HOME=str(self.home))
        self.process = subprocess.Popen([sys.executable, str(SCRIPT), '--listen', '--socket', str(self.socket)],
            env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        self.frames = queue.Queue()
        self.reader = threading.Thread(target=self.read, daemon=True)
        self.reader.start()
        self.next('ready')

    def read(self):
        for line in self.process.stdout:
            self.frames.put(json.loads(line))

    def next(self, kind, timeout=2):
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            try:
                value = self.frames.get(timeout=max(.001, until-time.monotonic()))
            except queue.Empty:
                break
            if value['kind'] == 'pulse':
                continue
            if value['kind'] != kind:
                raise AssertionError(f'expected {kind}, got {value}')
            return value
        raise AssertionError(f'no {kind} frame; process={self.process.poll()}')

    def quiet(self):
        try:
            frame = self.frames.get(timeout=.12)
            assert frame['kind'] == 'pulse', frame
        except queue.Empty:
            pass

    def send(self, event, path, **extra):
        payload = dict(hook_event_name=event, session_id='root', turn_id='turn', cwd='/work/project',
                       transcript_path=str(path), **extra)
        sent = subprocess.run([str(self.sender), '--socket', str(self.socket)],
            input=json.dumps(payload), capture_output=True, text=True, env=self.env, timeout=2)
        assert sent.returncode == 0 and json.loads(sent.stdout) == {}, sent

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            self.process.wait(timeout=2)
        self.reader.join(timeout=2)
        error = self.process.stderr.read()
        self.process.stdout.close()
        self.process.stderr.close()
        assert self.process.returncode == 0, error
        assert not self.socket.exists()


class HookTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='passport-hook-test-')
        self.home = Path(self.directory.name)
        self.path = self.home / 'session.jsonl'
        self.append({'type': 'task_complete', 'turn_id': 'old'})
        self.receiver = LiveReceiver(self.home)

    def tearDown(self):
        self.receiver.close()
        self.directory.cleanup()

    def append(self, payload, newline=True):
        with self.path.open('ab') as target:
            target.write(json.dumps({'type': 'event_msg', 'payload': payload}).encode() + (b'\n' if newline else b''))

    def test_quota_watch_filters_secrets_and_does_not_complete_task(self):
        from datetime import datetime, timezone
        self.receiver.send('UserPromptSubmit', self.path)
        self.receiver.next('started')
        raw = dict(limit_id='codex', primary=dict(used_percent=42, window_minutes=300, resets_at=1800000000),
                   secondary=None, credits={'secret':'never-forward'}, arbitrary='never-forward')
        record = dict(type='event_msg', timestamp=datetime.now(timezone.utc).isoformat(),
                      payload=dict(type='token_count', rate_limits=raw, info={'secret':'never-forward'}))
        with self.path.open('a') as f: f.write(json.dumps(record)+'\n')
        frame = self.receiver.next('quota')
        self.assertEqual(frame['quota']['primary']['usedPercent'], 42)
        self.assertNotIn('never-forward', json.dumps(frame))
        self.assertEqual(set(frame['quota']), {'limitId','primary','secondary'})
        self.append({'type':'task_complete','turn_id':'turn','duration_ms':100})
        self.receiver.next('completed')

    def test_quota_rejects_invalid_stale_and_other_buckets(self):
        from datetime import datetime, timezone
        import copy
        record = dict(timestamp=datetime.now(timezone.utc).isoformat(), payload={'rate_limits':dict(
            limit_id='codex', primary=dict(used_percent=42, window_minutes=300, resets_at=1800000000))})
        self.assertIsNotNone(hook.quota_snapshot(record))
        for invalid in [None, {}, {'timestamp':'2000-01-01T00:00:00Z', 'payload':record['payload']}]:
            self.assertIsNone(hook.quota_snapshot(invalid))
        for key, value in [('used_percent',float('nan')),('used_percent',101),('window_minutes',True),('resets_at',-1)]:
            bad=copy.deepcopy(record);bad['payload']['rate_limits']['primary'][key]=value
            self.assertIsNone(hook.quota_snapshot(bad))
        record['payload']['rate_limits']['limit_id']='other'
        self.assertIsNone(hook.quota_snapshot(record))

    def test_untracked_task_never_enters_running_or_waiting(self):
        frames = []
        receiver = hook.Receiver(frames.append)
        try:
            for path in [None, str(self.home / 'missing.jsonl')]:
                for event in ['UserPromptSubmit', 'PermissionRequest', 'PreToolUse', 'Stop']:
                    receiver.receive(dict(hook_event_name=event, session_id='ephemeral',
                        turn_id='turn', cwd=str(self.home), transcript_path=path,
                        tool_name='request_user_input'), self.home)
            self.assertEqual(frames, [])
            self.assertEqual(receiver.pending, {})
        finally:
            receiver.close()

    def test_real_watch_terminal_error_without_stop_hook(self):
        self.receiver.send('UserPromptSubmit', self.path)
        self.receiver.next('started')
        self.append({'type': 'task_complete', 'turn_id': 'turn', 'error': {'message': 'synthetic failure'}, 'duration_ms': 2400})
        frame = self.receiver.next('failed')
        self.assertEqual(frame['seconds'], 2)
        self.assertNotIn('error', frame)
        self.receiver.quiet()

    def test_stop_continuation_does_not_notify_before_final_record(self):
        self.receiver.send('UserPromptSubmit', self.path)
        self.receiver.next('started')
        self.receiver.send('Stop', self.path)
        self.receiver.quiet()
        self.receiver.send('Stop', self.path, stop_hook_active=True)
        self.receiver.quiet()
        self.append({'type': 'task_complete', 'turn_id': 'turn', 'duration_ms': 9000})
        self.assertEqual(self.receiver.next('completed')['seconds'], 9)

    def test_partial_write_and_other_turn_do_not_complete_current_turn(self):
        self.receiver.send('UserPromptSubmit', self.path)
        self.receiver.next('started')
        self.append({'type': 'task_complete', 'turn_id': 'old'})
        self.receiver.quiet()
        self.append({'type': 'task_complete', 'turn_id': 'turn'}, newline=False)
        self.receiver.quiet()
        with self.path.open('ab') as target:
            target.write(b'\n')
        self.receiver.next('completed')

    def test_permission_and_both_input_tools_are_live_events(self):
        self.receiver.send('PermissionRequest', self.path, tool_name='Bash', tool_use_id='approval')
        self.assertFalse(self.receiver.next('waiting')['asynchronous'])
        self.receiver.send('PostToolUse', self.path, tool_name='Bash', tool_use_id='approval')
        self.receiver.next('tool_finished')
        for tool in ['request_user_input', 'request_user_input_async']:
            self.receiver.send('PreToolUse', self.path, tool_name=tool, tool_use_id=tool)
            self.assertEqual(self.receiver.next('waiting')['asynchronous'], tool.endswith('_async'))
            self.receiver.send('PostToolUse', self.path, tool_name=tool, tool_use_id=tool)
            self.receiver.next('tool_finished')

    def test_disconnect_drops_events_and_never_scans_old_records(self):
        self.receiver.send('UserPromptSubmit', self.path)
        self.receiver.next('started')
        self.receiver.close()
        self.receiver.send('Stop', self.path)
        self.append({'type': 'task_complete', 'turn_id': 'turn'})
        self.receiver = LiveReceiver(self.home)
        self.receiver.quiet()
        self.receiver.send('UserPromptSubmit', self.path)
        self.receiver.next('started')
        self.receiver.quiet()

    def test_permission_without_call_id_matches_post_tool_without_exposing_input(self):
        self.receiver.send('PermissionRequest', self.path, tool_name='Bash', tool_input={'command':'PRIVATE COMMAND','description':'approval description'})
        wait = self.receiver.next('waiting')
        self.receiver.send('PostToolUse', self.path, tool_name='Bash', tool_use_id='actual-call', tool_input={'command':'PRIVATE COMMAND'})
        finish = self.receiver.next('tool_finished')
        self.assertEqual(wait['call'], finish['call'])
        self.assertNotIn('PRIVATE', json.dumps([wait, finish]))

    def test_root_only_minimal_metadata_and_name_lookup(self):
        (self.home/'session_index.jsonl').write_text(json.dumps({'id': 'root', 'thread_name': '测试任务'})+'\n')
        self.receiver.send('UserPromptSubmit', self.path, prompt='PRIVATE PROMPT', tool_input={'secret': 'PRIVATE'})
        frame = self.receiver.next('started')
        self.assertEqual(frame['title'], '测试任务')
        self.assertNotIn('PRIVATE', json.dumps(frame))
        self.receiver.send('UserPromptSubmit', self.path, agent_id='child')
        self.receiver.quiet()

    def test_listener_heartbeat_without_file_or_database_activity(self):
        value = self.receiver.frames.get(timeout=6)
        self.assertEqual(value['kind'], 'pulse')
        self.assertEqual(list(self.home.glob('*.sqlite*')), [])

    def test_active_file_loss_is_explicit_not_a_success(self):
        self.receiver.send('UserPromptSubmit', self.path)
        self.receiver.next('started')
        self.path.unlink()
        frame = self.receiver.next('unavailable')
        self.assertEqual(frame['reason'], 'active transcript lost')

    def test_native_hook_exit_precedes_immediate_final_record_without_losing_it(self):
        self.receiver.send('UserPromptSubmit', self.path)
        self.append({'type':'task_complete','turn_id':'turn','duration_ms':1})
        self.receiver.next('started')
        self.receiver.next('completed')
        self.receiver.send('PostToolUse', self.path, tool_name='Bash')
        self.receiver.quiet()

    def test_ordinary_post_does_not_lookup_metadata_or_emit_a_frame(self):
        frames = []
        receiver = hook.Receiver(frames.append)
        previous = hook.normalize
        try:
            def unwanted(*args, **kwargs):
                raise AssertionError('ordinary tool call must skip normalization and title I/O')
            hook.normalize = unwanted
            receiver.receive({'hook_event_name':'PostToolUse','session_id':'root',
                'turn_id':'turn','tool_input':{'secret':'private'}}, self.home)
            self.assertEqual(frames, [])
        finally:
            hook.normalize = previous
            receiver.close()
        self.receiver.send('PostToolUse', self.path, tool_name='Bash')
        self.receiver.quiet()

    def test_parallel_matching_approvals_each_receive_a_finished_event(self):
        for _ in range(2):
            self.receiver.send('PermissionRequest', self.path, tool_name='Bash', tool_input={'command':'same'})
            self.receiver.next('waiting')
        self.receiver.send('PostToolUse', self.path, tool_name='Bash', tool_input={'command':'other'})
        self.receiver.quiet()
        for _ in range(2):
            self.receiver.send('PostToolUse', self.path, tool_name='Bash', tool_input={'command':'same'})
            self.receiver.next('tool_finished')
        self.receiver.send('PostToolUse', self.path, tool_name='Bash', tool_input={'command':'same'})
        self.receiver.quiet()

    def test_partial_client_does_not_block_other_events(self):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stalled:
            stalled.connect(str(self.receiver.socket))
            stalled.sendall(struct.pack('!I', 100) + b'{')
            self.receiver.send('UserPromptSubmit', self.path)
            self.receiver.next('started')
            stalled.settimeout(.5)
            self.assertEqual(stalled.recv(1), b'')

    def test_native_sender_is_neutral_and_bounded_when_listener_stalls(self):
        path = self.home/'stalled.sock'
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(path));server.listen(1)
            started = time.monotonic()
            result = subprocess.run([str(self.receiver.sender),'--socket',str(path)],
                input='{}',text=True,capture_output=True,timeout=1)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), '{}')
            self.assertLess(time.monotonic()-started, .5)

    def test_timed_out_sender_is_not_processed_as_a_late_task_start(self):
        path = self.home/'late.sock'
        payload = {'hook_event_name':'UserPromptSubmit','session_id':'root',
            'turn_id':'turn','transcript_path':str(self.path),'cwd':'/work/project'}
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(path));server.listen(1)
            result = subprocess.run([str(self.receiver.sender),'--socket',str(path)],
                input=json.dumps(payload),text=True,capture_output=True,timeout=1)
            self.assertEqual(result.stdout.strip(), '{}')
            client, _ = server.accept()
            with client:
                packet = bytearray()
                while True:
                    part = client.recv(4096)
                    if not part:
                        break
                    packet.extend(part)
                frames = []
                observer = hook.Receiver(frames.append)
                try:
                    observer.receive(json.loads(packet[4:]), self.home,
                        connected=lambda: hook.peer_open(client))
                    self.assertEqual(frames, [])
                    self.assertEqual(observer.transcripts, {})
                finally:
                    observer.close()

    def test_invalid_and_oversized_input_remain_neutral(self):
        for payload in ['{', 'x'*1_000_001]:
            result = subprocess.run([str(self.receiver.sender),'--socket',str(self.receiver.socket)],
                input=payload,text=True,capture_output=True,timeout=2)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), '{}')
        self.receiver.send('UserPromptSubmit', self.path)
        self.receiver.next('started')


class InstallerTests(unittest.TestCase):
    def test_install_is_idempotent_preserves_user_hooks_and_config_and_uninstalls_ours_only(self):
        spec = importlib.util.spec_from_file_location('installer', SCRIPT.parent.parent/'codex-hooks.py')
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        with tempfile.TemporaryDirectory(prefix='passport-install-test-') as folder:
            home = Path(folder)
            original = {'description':'User hooks','hooks':{'Stop':[{'hooks':[{'type':'command','command':'/usr/bin/true','timeout':1}]}]}}
            (home/'hooks.json').write_text(json.dumps(original))
            (home/'config.toml').write_text('notify = ["existing-notification"]\n')
            before = (home/'config.toml').read_bytes()
            first = installer.apply('install', SCRIPT.read_bytes(), home)
            self.assertTrue(first['changed'])
            self.assertEqual(json.loads(Path(first['backup']).read_text()), original)
            self.assertEqual((home/'config.toml').read_bytes(), before)
            second = installer.apply('install', SCRIPT.read_bytes(), home)
            self.assertFalse(second['changed'])
            self.assertEqual(installer.apply('status', home=home)['passport_handlers'], 7)
            installer.apply('uninstall', home=home)
            self.assertEqual(json.loads((home/'hooks.json').read_text()), original)
            self.assertEqual((home/'config.toml').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
