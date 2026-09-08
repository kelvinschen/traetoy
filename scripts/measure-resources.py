#!/usr/bin/env python3
"""Measure only Passport roots and their descendants; never collect command arguments."""
import argparse, ctypes, json, os, re, subprocess, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--seconds',type=int,default=40);p.add_argument('--output',required=True);p.add_argument('--pid',type=int,action='append');a=p.parse_args()
roots=set(a.pid or [])
if not roots:
    job=subprocess.run(['launchctl','print',f'gui/{os.getuid()}/cn.folotoy.codex-passport.bridge'],text=True,capture_output=True)
    match=re.search(r'\bpid = (\d+)',job.stdout)
    if match:roots.add(int(match[1]))
    for line in subprocess.check_output(['ps','-axo','pid=,comm='],text=True).splitlines():
        fields=line.strip().split(None,1)
        if len(fields)==2 and fields[1]==str(ROOT/'macos-app/build/Passport.app/Contents/MacOS/Passport'):roots.add(int(fields[0]))
if not roots:raise SystemExit('Passport is not running')
fields='user_time system_time pkg_idle_wkups interrupt_wkups pageins wired_size resident_size phys_footprint proc_start_abstime proc_exit_abstime child_user_time child_system_time child_pkg_idle_wkups child_interrupt_wkups child_pageins child_elapsed_abstime diskio_bytesread diskio_byteswritten'.split()
class Usage(ctypes.Structure):_fields_=[('uuid',ctypes.c_ubyte*16)]+[(n,ctypes.c_uint64) for n in fields]
class Timebase(ctypes.Structure):_fields_=[('numer',ctypes.c_uint32),('denom',ctypes.c_uint32)]
timebase=Timebase();ctypes.CDLL('/usr/lib/libSystem.B.dylib').mach_timebase_info(ctypes.byref(timebase))
# rusage CPU values use Mach absolute ticks on this host, verified against process_time().
ns_per_tick=timebase.numer/timebase.denom
lib=ctypes.CDLL('/usr/lib/libproc.dylib');lib.proc_pid_rusage.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.c_void_p]
def snapshot():
    parents={int(p):int(pp) for p,pp in (line.split() for line in subprocess.check_output(['ps','-axo','pid=,ppid='],text=True).splitlines())}
    selected=roots.copy()
    while True:
        more={p for p,pp in parents.items() if pp in selected}
        if more<=selected:break
        selected|=more
    result={}
    for pid in selected:
        u=Usage()
        if lib.proc_pid_rusage(pid,2,ctypes.byref(u))==0:result[pid]={n:getattr(u,n) for n in fields[:10]}
    return result
start=time.monotonic();before=snapshot();after=before;peak=0
while time.monotonic()-start<a.seconds:
    time.sleep(min(5,max(0,a.seconds-(time.monotonic()-start))));after=snapshot();peak=max(peak,sum(r['resident_size'] for r in after.values()))
elapsed=time.monotonic()-start
common=[pid for pid in before if pid in after and before[pid]['proc_start_abstime']==after[pid]['proc_start_abstime']]
def delta(field):return sum(after[p][field]-before[p][field] for p in common)
r={'duration_seconds':round(elapsed,2),'process_count':len(after),'cpu_percent_one_core':round((delta('user_time')+delta('system_time'))*ns_per_tick/1e9/elapsed*100,3),'rss_total_mib':round(sum(r['resident_size'] for r in after.values())/1048576,2),'footprint_total_mib':round(sum(r['phys_footprint'] for r in after.values())/1048576,2),'rss_peak_mib':round(peak/1048576,2),'package_idle_wakeups_per_second':round(delta('pkg_idle_wkups')/elapsed,3),'interrupt_wakeups_per_second':round(delta('interrupt_wkups')/elapsed,3),'mach_timebase_numer':timebase.numer,'mach_timebase_denom':timebase.denom,'processes':after,'before_processes':before}
Path(a.output).write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r))
