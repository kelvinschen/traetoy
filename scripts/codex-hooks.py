#!/usr/bin/env python3
"""Install/remove Passport's independent hooks.json entries locally and over SSH.

Examples:
  python3 scripts/codex-hooks.py install --remote devbox
  python3 scripts/codex-hooks.py status --remote devbox
  python3 scripts/codex-hooks.py uninstall --remote devbox

Only Passport entries are replaced. Existing hooks are preserved.
--trust uses Codex's normal review RPC to save its hooks.state trust metadata;
script definitions stay in hooks.json. Configuration is backed up before trust.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import os
import queue
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import threading

EVENTS = ['UserPromptSubmit', 'Stop', 'Interrupt', 'SessionEnd',
          'PermissionRequest', 'PreToolUse', 'PostToolUse']


def atomic_write(path, content, mode):
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '.', dir=str(path.parent))
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'wb') as target:
            target.write(content)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def build_sender(folder, source):
    compiler = shutil.which('cc')
    if not compiler:
        raise RuntimeError('Installing Passport hooks requires a C compiler (cc) on this host.')
    with tempfile.TemporaryDirectory(prefix='.build-', dir=str(folder)) as build:
        source_path = Path(build)/'send.c'
        executable = Path(build)/'hook'
        source_path.write_bytes(source)
        subprocess.run([compiler, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
            str(source_path), '-o', str(executable)], capture_output=True, text=True, check=True, timeout=60)
        atomic_write(folder/'hook', executable.read_bytes(), 0o700)


def apply(action, helper=None, home=None, sender=None):
    home = Path(home or os.environ.get('CODEX_HOME', str(Path.home()/'.codex')))
    path = home / 'hooks.json'
    folder = home / 'passport'
    callback = folder / 'hook'
    receiver = folder / 'hook.py'
    original = path.read_bytes() if path.exists() else None
    config = json.loads(original) if original is not None else {}
    if not isinstance(config, dict) or not isinstance(config.get('hooks', {}), dict):
        raise ValueError('existing hooks.json is not a hooks object')
    hooks = config.setdefault('hooks', {})
    def ours(handler):
        if not isinstance(handler, dict) or handler.get('type') != 'command':
            return False
        try:
            parts = shlex.split(handler.get('command', ''))
            return str(callback) in parts or str(receiver) in parts
        except ValueError:
            return False
    present = sum(ours(handler) for groups in hooks.values() for group in groups for handler in group.get('hooks', []))
    if action == 'status':
        return {'home':str(home), 'hooks_file':str(path), 'passport_handlers':present,
                'sender_sha256':hashlib.sha256(callback.read_bytes()).hexdigest() if callback.exists() else None,
                'receiver_sha256':hashlib.sha256(receiver.read_bytes()).hexdigest() if receiver.exists() else None,
                'config_toml_changed':False}
    if action not in ('install', 'uninstall'):
        raise ValueError('unknown action')
    for event, groups in list(hooks.items()):
        remaining = []
        for group in groups:
            entries = group.get('hooks', [])
            selected = [entry for entry in entries if not ours(entry)]
            if len(selected) == len(entries):
                remaining.append(group)
            elif selected:
                remaining.append(dict(group, hooks=selected))
        if remaining:
            hooks[event] = remaining
        else:
            hooks.pop(event, None)
    if action == 'install':
        if not helper:
            raise ValueError('missing helper')
        home.mkdir(parents=True, exist_ok=True)
        folder.mkdir(mode=0o700, exist_ok=True)
        os.chmod(folder, 0o700)
        if sender is None:
            sender = (Path(__file__).parent/'codex-hooks/send.c').read_bytes()
        build_sender(folder, sender)
        command = shlex.quote(str(callback))
        for event in EVENTS:
            group = {'hooks':[{'type':'command','command':command,'timeout':2}]}
            if event == 'PreToolUse':
                group['matcher'] = r'(^|[._])request_user_input(_async)?$'
            hooks.setdefault(event, []).append(group)
        atomic_write(receiver, helper, 0o700)
    encoded = (json.dumps(config, ensure_ascii=False, indent=2)+'\n').encode()
    changed = original != encoded
    backup = None
    if changed and original is not None:
        folder.mkdir(mode=0o700, exist_ok=True)
        backup = folder / ('hooks-before-' + time.strftime('%Y%m%d-%H%M%S') + '-' + str(time.time_ns()) + '.json')
        atomic_write(backup, original, 0o600)
    if changed and (original is not None or action == 'install'):
        atomic_write(path, encoded, 0o600)
    if action == 'uninstall' and callback.exists():
        # Retain helpers and backups for rollback; removing definitions and
        # refreshing Codex sessions stops new callbacks.
        pass
    return {'home':str(home), 'hooks_file':str(path), 'changed':changed,
            'backup':str(backup) if backup else None, 'passport_handlers':len(EVENTS) if action=='install' else 0,
            'config_toml_changed':False, 'review_required':action=='install'}


def review(home, trust=False):
    """Use Codex's /hooks RPC workflow, limited to our installed definitions."""
    home = Path(home)
    callback = home/'passport/hook'
    program = os.environ.get('CODEX_BIN') or shutil.which('codex')
    if program:
        command = [program, 'app-server', '--listen', 'stdio://']
    else:
        command = [os.environ.get('SHELL', '/bin/sh'), '-lic', 'exec codex app-server --listen stdio://']
    env = dict(os.environ, CODEX_HOME=str(home))
    process = subprocess.Popen(command, cwd=str(home), env=env, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
    messages = queue.Queue()
    def read():
        for line in process.stdout:
            try: messages.put(json.loads(line))
            except ValueError: continue
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    serial = 0
    def send(value):
        process.stdin.write(json.dumps(value)+'\n');process.stdin.flush()
    def call(method, params):
        nonlocal serial
        serial += 1
        send({'id':serial, 'method':method, 'params':params})
        due = time.monotonic()+20
        while time.monotonic()<due:
            try: result = messages.get(timeout=max(.01, due-time.monotonic()))
            except queue.Empty: break
            if result.get('id') == serial:
                if 'error' in result: raise RuntimeError(str(result['error']))
                return result.get('result', {})
        raise RuntimeError('Codex '+method+' timed out')
    def owned():
        entries = call('hooks/list', {'cwds':[str(home)]})['data']
        selected = []
        for entry in entries:
            if entry.get('errors'): raise RuntimeError('Codex rejected hooks.json')
            for handler in entry.get('hooks', []):
                if handler.get('handlerType') != 'command': continue
                if str(callback) in shlex.split(handler.get('command','')):
                    selected.append(handler)
        expected = {event[0].lower()+event[1:] for event in EVENTS}
        if len(selected) != len(EVENTS) or {h['eventName'] for h in selected} != expected:
            raise RuntimeError('Passport hook definitions do not match the installer')
        return selected
    try:
        call('initialize', {'clientInfo':{'name':'passport_hook_setup','version':'1'},'capabilities':{'experimentalApi':True}})
        send({'method':'initialized'})
        selected = owned()
        config_backup = None
        if trust:
            updates = {h['key']:{'trusted_hash':h['currentHash']} for h in selected if h['trustStatus']!='trusted'}
            if updates:
                config_path = home/'config.toml'
                if config_path.exists():
                    config_backup = home/'passport'/('config-before-trust-'+str(time.time_ns())+'.toml')
                    atomic_write(config_backup, config_path.read_bytes(), 0o600)
                call('config/batchWrite', {'edits':[{'keyPath':'hooks.state','value':updates,'mergeStrategy':'upsert'}], 'reloadUserConfig':True})
            selected = owned()
        return {'trusted':all(h['trustStatus']=='trusted' for h in selected),
                'config_backup':str(config_backup) if config_backup else None,
                'definitions':[{'event':h['eventName'],'command':h['command'],'trust':h['trustStatus']} for h in selected]}
    finally:
        process.terminate()
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired: process.kill();process.wait()
        reader.join(timeout=2)
        process.stdin.close();process.stdout.close()


def reload_connection(rpc):
    """One setup operation: reload existing sessions without editing configuration.

    The collection RPC allowlist stays read-only. Setup owns this connection and
    sends this fixed administrative request; it never starts/answers a task.
    """
    rpc.counter += 1
    request_id = rpc.counter
    deadline = time.monotonic() + rpc.timeout
    rpc._send({'id':request_id, 'method':'config/batchWrite',
               'params':{'edits':[], 'reloadUserConfig':True}}, deadline)
    while True:
        value = rpc._receive(deadline)
        if value.get('id') == request_id and 'method' not in value:
            if 'error' in value:
                raise RuntimeError(str(value['error']))
            if value.get('result', {}).get('status') != 'ok':
                raise RuntimeError('Codex did not acknowledge runtime reload')
            return {'state':'reloaded', 'message':'Existing Codex sessions refreshed; no restart needed.'}
        if 'method' in value and 'id' in value:
            rpc._send({'id':value['id'],'error':{'code':-32601,'message':'Hook setup does not handle task requests'}}, deadline)


def refresh_remote(alias):
    # wsproto already belongs to the workspace tool environment; remote hosts
    # still need only standard-library Python for installation and delivery.
    runtime = Path(__file__).resolve().parent.parent/'.venv/bin/python'
    if not runtime.exists():
        return {'state':'restart_required','message':'Restart remote Codex; workspace Python environment unavailable for online refresh.'}
    try:
        result = subprocess.run([str(runtime),str(Path(__file__).resolve()),'--refresh-remote-worker',alias],
            capture_output=True,text=True,timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return {'state':'restart_required','message':'Online refresh unavailable; restart remote Codex.'}
    if result.returncode:
        return {'state':'restart_required','message':'Could not refresh the existing remote Codex. Restart remote Codex.',
                'detail':result.stderr.strip()[-400:]}
    return json.loads(result.stdout)


def main():
    if '--refresh-remote-worker' in sys.argv:
        from passport.rpc import RPC
        rpc = RPC.remote(sys.argv[-1])
        try:
            print(json.dumps(reload_connection(rpc)))
        finally:
            rpc.close()
        return
    if '--worker' in sys.argv:
        value = json.load(sys.stdin)
        helper = base64.b64decode(value['helper']) if value.get('helper') else None
        sender = base64.b64decode(value['sender']) if value.get('sender') else None
        result = apply(value['action'], helper, sender=sender)
        if value.get('trust'):
            result['review'] = review(result['home'], True)
            result['review_required'] = not result['review']['trusted']
            result['config_toml_changed'] = 'Codex-managed hooks.state only'
        print(json.dumps(result))
        return
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('action', choices=['install','status','uninstall'])
    parser.add_argument('--remote', action='append', default=[], help='Also apply on this SSH alias; repeatable')
    parser.add_argument('--trust', action='store_true', help='Trust only the installed Passport definitions through Codex /hooks RPC (install only)')
    args = parser.parse_args()
    if args.trust and args.action!='install': parser.error('--trust is only valid with install')
    helper = (Path(__file__).parent/'codex-hooks/hook.py').read_bytes() if args.action=='install' else None
    sender = (Path(__file__).parent/'codex-hooks/send.c').read_bytes() if args.action=='install' else None
    results = {'local':apply(args.action, helper, sender=sender)}
    if args.trust:
        results['local']['review'] = review(results['local']['home'], True)
        results['local']['review_required'] = not results['local']['review']['trusted']
        results['local']['config_toml_changed'] = 'Codex-managed hooks.state only'
    if args.action != 'status':
        results['local']['activation'] = {'state':'restart_required',
            'message':'Restart desktop Codex to refresh existing sessions. Restarting Passport is insufficient.'}
    source = Path(__file__).read_text()
    payload = json.dumps({'action':args.action, 'helper':base64.b64encode(helper).decode() if helper else None,
                          'sender':base64.b64encode(sender).decode() if sender else None,'trust':args.trust})
    for alias in args.remote:
        if not alias or alias.startswith('-') or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-' for c in alias):
            raise ValueError('invalid SSH alias')
        command = 'python3 -c ' + shlex.quote(source) + ' --worker'
        result = subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=8',alias,command],
            input=payload, text=True, capture_output=True, timeout=120, check=True)
        results[alias] = json.loads(result.stdout)
        if args.action == 'uninstall' or (args.action == 'install' and args.trust):
            results[alias]['activation'] = refresh_remote(alias)
        elif args.action == 'install':
            results[alias]['activation'] = {'state':'review_required','message':'Review hooks in the running Codex, or trust and restart it.'}
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
