import importlib.util
import json
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]/'scripts'))
import companion as c
from passport.rpc import RPC
from passport.runtime import transaction, transmit
from passport.sources import LocalSource, RemoteSource, Workers
from passport.state import Batch, Completion, Health, State, Task


def task(turn='one', source='ssh:devbox', title='任务'):
    return Task(source, 'thread', title, 'project · devbox', turn, 100)


class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/'state.db'
        self.s = State(self.path)
        self.s.register('ssh:devbox', now=100)

    def tearDown(self):
        self.s.close()
        self.tmp.cleanup()

    def test_baseline_duplicate_restart_and_reserved_sequence(self):
        old = Completion(task('old'), 'completed', 99, 12)
        done = Completion(task(), 'completed', 110, 10)
        self.s.apply(Batch('ssh:devbox', (), (old, done, done), 111))
        seqs = self.s.allocate_sequence()
        first = self.s.next_alert(lambda: next(seqs))
        self.assertEqual(first[1], done)
        self.s.close(); self.s = State(self.path)
        self.s.register('ssh:devbox', now=200)
        self.assertEqual(first, self.s.next_alert(lambda: self.fail('must reuse durable sequence')))
        self.s.delivered(first[0])
        self.s.apply(Batch('ssh:devbox', (), (done,), 112))
        self.assertIsNone(self.s.next_alert(lambda: 999))

    def test_host_turn_identity_order_and_failure(self):
        self.s.register('local', now=100)
        rows = (Completion(task('two'), 'failed', 140, 9),
                Completion(task('one'), 'completed', 130, 8))
        self.s.apply(Batch('ssh:devbox', (), rows, 150))
        self.s.apply(Batch('local', (), (Completion(task('one','local'), 'interrupted', 120, 2),),150))
        seqs = self.s.allocate_sequence()
        got = []
        for _ in range(3):
            seq, alert = self.s.next_alert(lambda: next(seqs))
            got.append((alert.task.source, alert.task.turn, alert.status))
            self.s.delivered(seq)
        self.assertEqual(got, [('local','one','interrupted'),('ssh:devbox','one','completed'),('ssh:devbox','two','failed')])
        self.assertEqual(self.s.done_count(), 1)

    def test_offline_preserves_unknown_task_and_freezes_time(self):
        self.s.apply(Batch('ssh:devbox', (task(),), (), 150))
        self.s.apply(Health('ssh:devbox', 'Offline'))
        current, seconds, stale = self.s.active_tasks(now=200)[0]
        self.assertEqual(seconds, 50)
        self.assertTrue(stale)
        self.assertIsNone(self.s.next_alert(lambda: 1))
        self.s.apply(Batch('ssh:devbox', (), (), 201))
        self.assertEqual(self.s.active_tasks(), [])
        self.assertIsNone(self.s.next_alert(lambda: 1))

    def test_snapshot_retry_is_immutable_while_new_task_arrives(self):
        alert = Completion(task(), 'completed', 130, 30)
        tx = transaction(c,self.s,22,alert)
        calls = []
        class Device:
            def send_titles(self,*args):calls.append(('titles',args))
            def send_metadata(self,*args):calls.append(('meta',args))
            def send(self,*args):calls.append(('state',args));raise OSError('lost ACK')
        with self.assertRaises(OSError):transmit(Device(),tx)
        self.s.apply(Batch('ssh:devbox',(task('next',title='新任务'),),(),150))
        with self.assertRaises(OSError):transmit(Device(),tx)
        self.assertEqual(calls[:3],calls[3:])
        self.assertEqual(tx.alert_seconds,30)

    def test_heartbeat_does_not_write_checkpoint_every_time(self):
        self.s.apply(Batch('ssh:devbox',(),(),110))
        self.assertEqual(self.s.db.execute('SELECT checkpoint FROM sources').fetchone()[0],100)
        self.s.apply(Batch('ssh:devbox',(),(),161))
        self.assertEqual(self.s.db.execute('SELECT checkpoint FROM sources').fetchone()[0],161)

    def test_display_filter_does_not_consume_other_task_alerts(self):
        self.s.apply(Batch('ssh:devbox', (), (Completion(task(), 'completed', 120, 20),), 121))
        self.s.thread_filter = 'different-thread'
        self.assertIsNone(self.s.next_alert(lambda: 1))
        self.s.thread_filter = None
        self.assertIsNotNone(self.s.next_alert(lambda: 1))


class FakeRPC:
    clock_offset = 50
    def __init__(self):
        self.calls = []
        self.pages = {
            None: {'data':[{'id':'new','status':'completed','startedAt':170,'completedAt':190,'durationMs':20000}], 'nextCursor':'p2'},
            'p2': {'data':[{'id':'middle','status':'interrupted','startedAt':160,'completedAt':170,'durationMs':10000}], 'nextCursor':'p3'},
            'p3': {'data':[{'id':'old','status':'completed','startedAt':130,'completedAt':140,'durationMs':10000}], 'nextCursor':None}}
    def call(self, method, params=None):
        params = params or {}
        self.calls.append((method,params))
        if method=='thread/list':
            return {'data':[{'id':'thread','name':'任务','cwd':'/remote/project','source':'vscode',
                             'status':{'type':'idle'},'updatedAt':190}], 'nextCursor':None}
        if method=='thread/loaded/list':return {'data':[]}
        if method=='project/list':return {'data':[]}
        if method=='thread/turns/list':return self.pages[params.get('cursor')]
        raise AssertionError(method)


class SourceTests(unittest.TestCase):
    def test_paginated_offline_completions_and_clock_adjustment(self):
        r=FakeRPC();s=RemoteSource('devbox',100,110)
        with patch('passport.sources.time.time',return_value=150):b=s.poll(r)
        self.assertEqual([(x.task.turn,x.ended,x.seconds) for x in b.completed], [('middle',120,10),('new',140,20)])
        self.assertEqual(b.completed[0].task.project,'project · devbox')
        self.assertEqual(b.active,())
        self.assertTrue(all('includeTurns' not in p for m,p in r.calls if m=='thread/turns/list'))
        self.assertTrue(all(p['itemsView']=='notLoaded' for m,p in r.calls if m=='thread/turns/list'))

    def test_repeat_cursor_does_not_advance_checkpoint(self):
        r=FakeRPC();r.pages['p2']['nextCursor']='p2'
        s=RemoteSource('devbox',100,110)
        with self.assertRaises(OSError):s.poll(r)
        self.assertEqual(s.checkpoint,110)

    def test_completed_then_archived_during_disconnect_is_backfilled(self):
        r=FakeRPC();original=r.call
        def call(method,params=None):
            if method=='thread/list' and not params.get('archived'):
                return {'data':[]}
            return original(method,params)
        r.call=call
        s=RemoteSource('devbox',100,110)
        with patch('passport.sources.time.time',return_value=150):batch=s.poll(r)
        self.assertEqual([x.task.turn for x in batch.completed],['middle','new'])

    def test_idle_without_terminal_is_not_completion(self):
        r=FakeRPC();r.pages={None:{'data':[{'id':'one','status':'inProgress','startedAt':160,'completedAt':None}]}}
        s=RemoteSource('devbox',100,110,active=[task()])
        b=s.poll(r)
        self.assertEqual(b.completed,())

    def test_discovery_watermark_survives_fast_active_poll(self):
        r = FakeRPC();s = RemoteSource('devbox',100,110)
        with patch('passport.sources.time.time',return_value=150):s.poll(r)
        with patch('passport.sources.time.time',return_value=153):b=s.poll(r)
        self.assertEqual(b.checkpoint,150)
        # A complete short turn occurs between two full discoveries.
        r.pages[None] = {'data':[{'id':'short','status':'completed', 'startedAt':201,
                                  'completedAt':202,'durationMs':1000}]}
        original = r.call
        def call(method,params=None):
            result = original(method,params)
            if method=='thread/list':result['data'][0]['updatedAt']=202
            return result
        r.call = call
        with patch('passport.sources.time.time',return_value=161):b=s.poll(r)
        self.assertEqual(b.completed[0].task.turn,'short')

    def test_quota_failure_does_not_gate_names_or_usage(self):
        out=queue.Queue(4);stop=threading.Event();workers=Workers(out,stop)
        names={};lock=threading.Lock()
        class Peer:
            def __init__(self,*a,**k):pass
            def close(self):pass
            def call(self,method,params=None):
                if method=='account/rateLimits/read':raise OSError('quota down')
                if method=='account/usage/read':return {'dailyUsageBuckets':[]}
                if method=='thread/list':
                    stop.set()
                    return {'data':[{'id':'x','name':'标题','cwd':'/project'}]}
                raise AssertionError(method)
        with patch('passport.sources.RPC',Peer):workers.account(c,'codex',60,names,lock)
        self.assertEqual(names['x'],('标题','/project'))
        self.assertEqual(out.get_nowait().kind,'usage')

    def test_local_restart_backfills_terminal_once(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'session.jsonl'
            now=time.time()
            records=[{'type':'session_meta','payload':{'id':'thread','source':'vscode','cwd':d}},
                {'type':'event_msg','timestamp':c.dt.datetime.fromtimestamp(now,c.dt.timezone.utc).isoformat(),
                 'payload':{'type':'task_complete','turn_id':'one','duration_ms':2500}}]
            p.write_text('\n'.join(json.dumps(r) for r in records)+'\n')
            s=LocalSource(c,d,now-100,now-10,{'thread':('标题',d)},threading.Lock())
            self.assertEqual(s.poll().completed[0].seconds,2)
            self.assertEqual(s.poll().completed,())

    def test_remote_timeout_does_not_block_usb_scheduler(self):
        out=queue.Queue(4);stop=threading.Event();workers=Workers(out,stop)
        entered=threading.Event();release=threading.Event()
        class Slow:
            alias='devbox';source='ssh:devbox'
            def poll(self,rpc):entered.set();release.wait(2);raise TimeoutError()
        class RPCFake:
            clock_offset=0
            def close(self):pass
        with patch('passport.sources.RPC.remote',return_value=RPCFake()):
            workers.start(workers.remote,Slow())
            self.assertTrue(entered.wait(1))
            # While the source is genuinely blocked, device transactions still complete.
            count=[]
            class Device:
                def send_titles(self,*a):pass
                def send_metadata(self,*a):pass
                def send(self,*a):count.append(1);return 'ACK'
            with tempfile.TemporaryDirectory() as d:
                s=State(Path(d)/'db')
                for seq in range(3):transmit(Device(),transaction(c,s,seq+1))
                s.close()
            self.assertEqual(len(count),3)
            stop.set();release.set();workers.join()


class RPCTests(unittest.TestCase):
    def test_framing_fragmentation_ping_and_request_correlation(self):
        # Real pipe transport with a minimal peer, not a mock of wsproto.
        program = '''
import os,json
from wsproto import WSConnection,ConnectionType
from wsproto.events import Request,AcceptConnection,TextMessage,Ping
ws=WSConnection(ConnectionType.SERVER)
while True:
 data=os.read(0,65536)
 if not data:break
 ws.receive_data(data)
 for e in ws.events():
  if isinstance(e,Request):os.write(1,ws.send(AcceptConnection()))
  elif isinstance(e,TextMessage):
   m=json.loads(e.data)
   if 'id' not in m:continue
   os.write(1,ws.send(Ping(payload=b'test')))
   os.write(1,ws.send(TextMessage(data=json.dumps({'method':'thread/status/changed','params':{}}))))
   result=json.dumps({'id':m['id'],'result':{'ok':True}})
   os.write(1,ws.send(TextMessage(data=result[:10],message_finished=False)))
   os.write(1,ws.send(TextMessage(data=result[10:])))
'''
        rpc=RPC([sys.executable,'-u','-c',program],websocket=True,timeout=2)
        try:
            self.assertEqual(rpc.call('thread/list'),{'ok':True})
            self.assertEqual(rpc.notifications['thread/status/changed'],2)
            with self.assertRaises(ValueError):rpc.call('turn/start',{})
        finally:rpc.close()
        self.assertIsNotNone(rpc.process.poll())

    def test_deadline_and_child_cleanup(self):
        before=time.monotonic()
        with self.assertRaises(TimeoutError):
            RPC([sys.executable,'-c','import time;time.sleep(10)'],timeout=.1)
        self.assertLess(time.monotonic()-before,2)

    def test_alias_is_not_a_command(self):
        for alias in ['-oProxyCommand=evil','devbox; touch /tmp/x','a b']:
            with self.assertRaises(ValueError):RPC.remote(alias)


if __name__=='__main__':unittest.main()
