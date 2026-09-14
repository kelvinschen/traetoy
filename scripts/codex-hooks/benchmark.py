#!/usr/bin/env python3
"""Measure the actual native callback and shell using isolated synthetic events.

No live device, real task, model API or private conversation data is used.
CPU percentages are extrapolated for one callback per second on one CPU core.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import resource
import shlex
import statistics
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location('transport', HERE/'test_hooks.py')
transport = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transport)


def child_cpu():
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_utime + usage.ru_stime


def benchmark(count, title_hit):
    with tempfile.TemporaryDirectory(prefix='passport-hook-benchmark-') as folder:
        home = Path(folder)
        row = json.dumps({'id':'another-thread','thread_name':'fixture task'})+'\n'
        index = row*(262144//len(row))
        if title_hit:
            index += json.dumps({'id':'fixture','thread_name':'fixture task'})+'\n'
        (home/'session_index.jsonl').write_text(index)
        path = home/'fixture.jsonl'
        path.write_text('')
        receiver = transport.LiveReceiver(home)
        payload = json.dumps(dict(hook_event_name='PostToolUse',session_id='fixture',turn_id='fixture-turn',
            transcript_path=str(path),cwd='/fixture/project',tool_name='Bash',tool_use_id='call',
            tool_input={'command':'printf fixture'},tool_response={'output':'x'*1024}))
        command = [os.environ.get('SHELL','/bin/sh'),'-lc',
            shlex.join([str(receiver.sender),'--socket',str(receiver.socket)])]
        before = child_cpu()
        times = []
        started = time.monotonic()
        try:
            for _ in range(count):
                step = time.monotonic()
                sent = subprocess.run(command,input=payload,capture_output=True,text=True,
                    env=receiver.env,timeout=3,check=True)
                assert sent.stdout.strip() == '{}', sent.stdout
                times.append((time.monotonic()-step)*1000)
            elapsed = time.monotonic()-started
            sender_cpu = child_cpu()-before
            frames = list(receiver.frames.queue)
            assert all(frame['kind']=='pulse' for frame in frames), frames
        finally:
            before_close = child_cpu()
            receiver.close()
            receiver_cpu = child_cpu()-before_close
        return {'host':sys.platform,'calls':count,'title_found_at_end':title_hit,
            'payload_bytes':len(payload),'index_bytes':len(index),'shell_included':True,
            'wall_seconds':round(elapsed,3),'wall_ms_p50':round(statistics.median(times),3),
            'wall_ms_p95':round(sorted(times)[int(count*.95)-1],3),
            'sender_cpu_ms_per_call':round(sender_cpu/count*1000,3),
            'receiver_cpu_total_ms_including_startup':round(receiver_cpu*1000,3),
            'cpu_one_core_percent_at_60_calls_per_minute':round(sender_cpu/count*100,3),
            'cpu_one_core_percent_including_receiver_startup_upper_bound':round((sender_cpu+receiver_cpu)/count*100,3),
            'ordinary_tool_frames':sum(frame['kind']!='pulse' for frame in frames)}


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--count',type=int,default=60)
    parser.add_argument('--title-hit',action='store_true')
    parser.add_argument('--max-cpu-ms',type=float)
    args = parser.parse_args()
    if args.count < 10:
        parser.error('--count must be at least 10')
    result = benchmark(args.count,args.title_hit)
    print(json.dumps(result))
    if args.max_cpu_ms is not None:
        assert result['sender_cpu_ms_per_call'] <= args.max_cpu_ms, result
