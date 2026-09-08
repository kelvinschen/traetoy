#!/usr/bin/env python3
"""Exercise the installed menu controller. Briefly interrupts monitoring; ends running."""
import json,os,signal,socket,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];APP=ROOT/'macos-app/build/Passport.app';SOCK=ROOT/'reports/control/app.sock'
def cmd(op):
    s=socket.socket(socket.AF_UNIX);s.settimeout(4)
    try:
        s.connect(str(SOCK));s.sendall(json.dumps({'v':1,'op':op}).encode()+b'\n');return json.loads(s.makefile('rb').readline())
    finally:s.close()
def wait(pred,timeout=30):
    end=time.monotonic()+timeout;last=None
    while time.monotonic()<end:
        try:last=cmd('status')
        except (OSError,ValueError):last=None
        if pred(last):return last
        time.sleep(.25)
    raise AssertionError(f'timed out: {last}')
def running(s):return s and s['desired'] and not s['busy'] and s.get('backend',{}).get('service')=='running'
def alive(pid):
    try:os.kill(pid,0);return True
    except ProcessLookupError:return False
def descendants(pid):
    rows={int(a):int(b) for a,b in (l.split() for l in subprocess.check_output(['ps','-axo','pid=,ppid='],text=True).splitlines())};pids={pid}
    while True:
        more={p for p,parent in rows.items() if parent in pids}
        if more<=pids:return pids
        pids|=more
subprocess.run(['open',str(APP)],check=True);s=wait(running);print('Start: PASS',flush=True)
subprocess.run(['open','-n',str(APP)],check=True);time.sleep(1);assert cmd('status')['pid']==s['pid'];print('Duplicate launch: PASS',flush=True)
old=s['backend']['pid'];cmd('reconnect');time.sleep(4);assert cmd('status')['backend']['pid']==old;print('Reconnect preserves backend: PASS',flush=True)
owned=descendants(old);start=time.monotonic();cmd('stop');wait(lambda s:s and not s['busy'] and not s['desired']);time.sleep(1);assert all(not alive(p) for p in owned);print(f'Stop and owned-child cleanup: PASS ({time.monotonic()-start:.2f}s)',flush=True)
time.sleep(3);assert not cmd('status')['desired'];cmd('start');s=wait(running);assert s['backend']['pid']!=old
old=s['backend']['pid'];cmd('restart');s=wait(lambda s:running(s) and s['backend']['pid']!=old);print('Start after stop / restart: PASS',flush=True)
# Login preference is independent of stopping; preserve the existing setting here.
login=s['loginEnabled'];cmd('stop');wait(lambda s:s and not s['busy'] and not s['desired']);assert cmd('status')['loginEnabled']==login;cmd('start');s=wait(running)
old=s['backend']['pid'];owned=descendants(old);os.kill(old,signal.SIGKILL);s=wait(lambda s:running(s) and s['backend']['pid']!=old);assert all(not alive(p) for p in owned);print('Backend crash recovery and child cleanup: PASS',flush=True)
# Clear retry history, then exceed the configured budget.
old=s['backend']['pid'];cmd('restart');s=wait(lambda s:running(s) and s['backend']['pid']!=old)
for index in range(4):
    old=s['backend']['pid'];os.kill(old,signal.SIGKILL)
    if index<3:s=wait(lambda s:running(s) and s['backend']['pid']!=old)
    else:s=wait(lambda s:s and not s['desired'] and not s['busy'])
assert s['error'];print('Crash retry budget: PASS',flush=True)
cmd('start');s=wait(running);owned=descendants(s['backend']['pid']);app_pid=s['pid'];start=time.monotonic();os.kill(app_pid,signal.SIGKILL)
end=time.monotonic()+20
while time.monotonic()<end and any(alive(p) for p in owned):time.sleep(.25)
assert all(not alive(p) for p in owned);print(f'Menu crash / owner-loss cleanup: PASS ({time.monotonic()-start:.2f}s)',flush=True)
subprocess.run(['open',str(APP)],check=True);s=wait(running);owned=descendants(s['backend']['pid']);app_pid=s['pid'];cmd('quit');wait(lambda s:s is None);time.sleep(1);assert not alive(app_pid) and all(not alive(p) for p in owned);print('Quit stops app, backend and owned children: PASS',flush=True)
subprocess.run(['open',str(APP)],check=True);wait(lambda s:s is not None);cmd('quit');wait(lambda s:s is None);print('Quit during startup: PASS',flush=True)
subprocess.run(['open',str(APP)],check=True);wait(running);print('Restored running: PASS',flush=True)

cmd('stop');cmd('quit');wait(lambda s:s is None);print('Quit while stopping: PASS',flush=True)
subprocess.run(['open',str(APP)],check=True);wait(running);print('Final monitoring restored: PASS',flush=True)
