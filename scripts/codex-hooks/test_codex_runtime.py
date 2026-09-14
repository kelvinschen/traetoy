#!/usr/bin/env python3
"""Exercise installed Codex against a loopback mock model in an isolated home.

No real account, model API or user task is used. The test configures and trusts
only its own temporary hook definitions through Codex's config RPC, then drives
real turn lifecycle events and compares the Passport stream.
PASSPORT_TEST_LIVE_SOCKET explicitly mirrors fixtures to a running bridge/device;
that opt-in produces real device notifications and sounds.
"""
import importlib.util
import json
import os
from pathlib import Path
import queue
import shlex
import signal
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location('transport_tests', HERE/'test_hooks.py')
transport = importlib.util.module_from_spec(spec); spec.loader.exec_module(transport)
spec = importlib.util.spec_from_file_location('hook_installer', HERE.parent/'codex-hooks.py')
installer = importlib.util.module_from_spec(spec); spec.loader.exec_module(installer)
LIVE_SOCKET = os.environ.get('PASSPORT_TEST_LIVE_SOCKET')
CODEX = os.environ.get('CODEX_BIN', '/Applications/ChatGPT.app/Contents/Resources/codex')


class MockModel(BaseHTTPRequestHandler):
    scenario = 'success'
    requests = 0
    def log_message(self, *args):
        pass
    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length', 0)))
        type(self).requests += 1
        if LIVE_SOCKET:
            time.sleep(4)  # Let the hardware display the actual running/waiting state.
        if self.scenario == 'failure':
            self.send_response(400); self.send_header('Content-Type','application/json'); self.end_headers()
            self.wfile.write(json.dumps({'error':{'message':'synthetic test failure','type':'invalid_request_error','code':'test_failure'}}).encode())
            return
        if self.scenario == 'interrupt':
            time.sleep(2)
        self.send_response(200)
        self.send_header('Content-Type','text/event-stream')
        if self.scenario == 'quota':
            for name, value in {'used-percent':'42','window-minutes':'300','reset-at':str(int(time.time())+18000)}.items():
                self.send_header('x-codex-primary-'+name, value)
        self.end_headers()
        response = {'id':'response-test','object':'response','status':'completed','output':[],
                    'usage':{'input_tokens':1,'output_tokens':1,'total_tokens':2}}
        item = {'id':'message-test','type':'message','role':'assistant','status':'completed',
                'content':[{'type':'output_text','text':'ready','annotations':[]}]}
        events = [
            {'type':'response.created','response':dict(response,status='in_progress')},
            {'type':'response.output_item.added','output_index':0,'item':dict(item,status='in_progress',content=[])},
            {'type':'response.content_part.added','item_id':item['id'],'output_index':0,'content_index':0,'part':{'type':'output_text','text':'','annotations':[]}},
            {'type':'response.output_text.delta','item_id':item['id'],'output_index':0,'content_index':0,'delta':'ready'},
            {'type':'response.output_text.done','item_id':item['id'],'output_index':0,'content_index':0,'text':'ready'},
            {'type':'response.output_item.done','output_index':0,'item':item},
            {'type':'response.completed','response':dict(response,output=[item])},
        ]
        if self.scenario in ('user_input', 'permission', 'async_input') and self.requests == 1:
            if self.scenario == 'user_input':
                name='request_user_input'
                arguments={'questions':[{'id':'choice','header':'Choice','question':'Choose a fixture value.',
                    'options':[{'label':'A','description':'First'},{'label':'B','description':'Second'}]}]}
            elif self.scenario == 'async_input':
                name='request_user_input_async'
                arguments={'questions':[{'title':'Fixture question','options':['A','B']}]}
            else:
                name='exec_command'
                arguments={'cmd':'printf passport-fixture','sandbox_permissions':'require_escalated','justification':'Run the isolated fixture printf command.'}
            item={'id':'call-item','type':'function_call','call_id':'call-fixture','name':name,'arguments':json.dumps(arguments)}
            events=[{'type':'response.created','response':dict(response,status='in_progress')},
                {'type':'response.output_item.added','output_index':0,'item':dict(item,arguments='')},
                {'type':'response.function_call_arguments.delta','item_id':item['id'],'output_index':0,'delta':item['arguments']},
                {'type':'response.output_item.done','output_index':0,'item':item},
                {'type':'response.completed','response':dict(response,output=[item])}]
        try:
            for event in events:
                self.wfile.write(('event: '+event['type']+'\ndata: '+json.dumps(event)+'\n\n').encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            if self.scenario != 'interrupt':
                raise


class AppServer:
    def __init__(self, home):
        self.home = Path(home)
        env = dict(os.environ, CODEX_HOME=str(home), PASSPORT_TEST_TOKEN='loopback-only-dummy-token')
        self.process = subprocess.Popen([CODEX,'app-server','--listen','stdio://'],cwd=home,env=env,
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1,start_new_session=True)
        self.output = queue.Queue();self.errors=[]
        self.reader = threading.Thread(target=self.read,daemon=True);self.reader.start()
        self.err_reader = threading.Thread(target=self.read_errors,daemon=True);self.err_reader.start()
        self.identifier=0;self.events=[]
        self.call('initialize',{'clientInfo':{'name':'passport_runtime_test','version':'1'},'capabilities':{'experimentalApi':True}})
        self.send({'method':'initialized'})
    def read(self):
        for line in self.process.stdout:
            try:self.output.put(json.loads(line))
            except ValueError:pass
    def read_errors(self):
        for line in self.process.stderr:self.errors.append(line)
    def send(self,value):
        self.process.stdin.write(json.dumps(value)+'\n');self.process.stdin.flush()
    def take(self, predicate, timeout=20):
        for index,value in enumerate(self.events):
            if predicate(value):return self.events.pop(index)
        until=time.monotonic()+timeout
        while time.monotonic()<until:
            try:value=self.output.get(timeout=max(.01,until-time.monotonic()))
            except queue.Empty:break
            if predicate(value):return value
            self.events.append(value)
        raise AssertionError('Codex response timeout; '+''.join(self.errors)[-2000:])
    def call(self,method,params):
        self.identifier+=1;identifier=self.identifier
        self.send({'id':identifier,'method':method,'params':params})
        response=self.take(lambda value:value.get('id')==identifier)
        if 'error' in response:raise AssertionError(response['error'])
        return response.get('result',{})
    def close(self):
        # Close the isolated Codex process group, including plugin setup children.
        os.killpg(self.process.pid, signal.SIGTERM)
        try:self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
        self.reader.join(timeout=2);self.err_reader.join(timeout=2)
        self.process.stdin.close();self.process.stdout.close();self.process.stderr.close()


def run_case(scenario):
    MockModel.scenario=scenario;MockModel.requests=0
    http=ThreadingHTTPServer(('127.0.0.1',0),MockModel)
    thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
    with tempfile.TemporaryDirectory(prefix='passport-runtime-test-') as folder:
        home=Path(folder)
        model='gpt-6-astra' if scenario=='async_input' else 'gpt-5.5'
        (home/'config.toml').write_text(f'''model = "{model}"
model_provider = "passport_test"
approval_policy = "never"
sandbox_mode = "danger-full-access"
[model_providers.passport_test]
name = "Passport loopback fixture"
base_url = "http://127.0.0.1:{http.server_port}/v1"
wire_api = "responses"
env_key = "PASSPORT_TEST_TOKEN"
request_max_retries = 0
stream_max_retries = 0
''')
        installer.apply('install',(HERE/'hook.py').read_bytes(),home)
        if scenario == 'continuation':
            block=home/'continue_once.py'
            block.write_text("import pathlib, json\np=pathlib.Path(__file__).with_suffix('.ran')\nfirst=not p.exists()\np.touch()\nprint(json.dumps({'decision':'block','reason':'One more fixture pass.'} if first else {}))\n")
            hook_path=home/'hooks.json';value=json.loads(hook_path.read_text())
            value['hooks']['Stop'].append({'hooks':[{'type':'command','command':shlex.join([sys.executable,str(block)]),'timeout':2}]})
            hook_path.write_text(json.dumps(value))
        if LIVE_SOCKET:
            live = Path(LIVE_SOCKET)
            if not live.is_socket():
                raise RuntimeError('requested live Passport socket is unavailable')
            hook_path=home/'hooks.json';value=json.loads(hook_path.read_text())
            for groups in value['hooks'].values():
                for group in groups:
                    group['hooks'].append({'type':'command','command':shlex.join([str(Path.home()/'.codex/passport/hook'),'--socket',str(live)]),'timeout':2})
            hook_path.write_text(json.dumps(value))
        receiver=transport.LiveReceiver(home)
        app=AppServer(home)
        try:
            hooks=app.call('hooks/list',{'cwds':[folder]})['data'][0]
            assert not hooks['errors'],hooks
            # Same API used by Codex's /hooks review UI, scoped to this disposable
            # test home and scripts created above; never modifies live trust.
            app.call('config/batchWrite',{'edits':[{'keyPath':'hooks.state','value':{h['key']:{'trusted_hash':h['currentHash']} for h in hooks['hooks']},'mergeStrategy':'upsert'}], 'reloadUserConfig':True})
            checked=app.call('hooks/list',{'cwds':[folder]})['data'][0]
            assert all(h['trustStatus']=='trusted' for h in checked['hooks']),checked
            start=app.call('thread/start',{'cwd':folder,'modelProvider':'passport_test','model':model,'experimentalRawEvents':False,'ephemeral':scenario=='ephemeral'})
            identifier=start['thread']['id']
            prefetched=[]
            params={'threadId':identifier,'input':[{'type':'text','text':'Run the isolated fixture.'}]}
            if scenario=='user_input':
                params['collaborationMode']={'mode':'plan','settings':{'model':'gpt-5.5','reasoning_effort':'low','developer_instructions':None}}
            if scenario=='permission':
                params['approvalPolicy']='on-request'
                params['sandboxPolicy']={'type':'readOnly'}
            begun=app.call('turn/start',params)
            if scenario in ('user_input','permission'):
                expected_method='item/tool/requestUserInput' if scenario=='user_input' else 'item/commandExecution/requestApproval'
                request=app.take(lambda value:value.get('method')==expected_method and 'id' in value,timeout=20)
                result={'answers':{'choice':{'answers':['A']}}} if scenario=='user_input' else {'decision':'accept'}
                if LIVE_SOCKET: time.sleep(4)
                app.send({'id':request['id'],'result':result})
            if scenario=='interrupt':
                prefetched.append(receiver.next('started',timeout=10))
                if LIVE_SOCKET: time.sleep(4)
                app.call('turn/interrupt',{'threadId':identifier,'turnId':begun['turn']['id']})
            terminal=app.take(lambda value:value.get('method')=='turn/completed',timeout=30)
            frames=list(prefetched)
            until=time.monotonic()+5
            while time.monotonic()<until:
                try:frame=receiver.frames.get(timeout=.3)
                except queue.Empty:continue
                if frame['kind']=='pulse':continue
                frames.append(frame)
                if frame['kind'] in ('completed','failed','interrupted'):break
            expected='failed' if scenario=='failure' else 'interrupted' if scenario=='interrupt' else 'completed'
            if scenario == 'ephemeral':
                assert not frames, ('ephemeral task must not affect device state', frames)
            else:
                assert any(f['kind']=='started' for f in frames),frames
                assert frames[-1]['kind']==expected,(terminal,frames,app.errors[-8:])
            if scenario!='interrupt':assert MockModel.requests>0
            if scenario=='quota':
                quota = [f for f in frames if f['kind']=='quota']
                assert quota and quota[-1]['quota']['primary']['usedPercent']==42, frames
            if scenario=='continuation':assert MockModel.requests==2
            if scenario in ('user_input','permission','async_input'):
                assert 'waiting' in [f['kind'] for f in frames], frames
                assert 'tool_finished' in [f['kind'] for f in frames], frames
            if scenario=='permission':
                wait=next(f for f in frames if f['kind']=='waiting')
                finish=next(f for f in frames if f['kind']=='tool_finished')
                assert wait['call']==finish['call'],(wait,finish)
            if scenario=='async_input':assert next(f for f in frames if f['kind']=='waiting')['asynchronous']
            print(json.dumps({'scenario':scenario,'model_requests':'loopback only','request_count':MockModel.requests,
                              'codex_status':terminal['params']['turn']['status'], 'passport_kinds':[f['kind'] for f in frames]}))
            if LIVE_SOCKET: time.sleep(4)  # Allow receipt before removing the active transcript.
        finally:
            app.close();receiver.close()
    http.shutdown();http.server_close();thread.join(timeout=2)



def run_reload_case():
    """Installing on disk is insufficient for a previously loaded task."""
    if LIVE_SOCKET:
        raise ValueError('reload regression is isolated only')
    os.environ['CODEX_BIN'] = CODEX
    MockModel.scenario = 'success'
    MockModel.requests = 0
    http = ThreadingHTTPServer(('127.0.0.1', 0), MockModel)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix='passport-reload-test-') as folder:
            home = Path(folder)
            (home/'config.toml').write_text(f'''model = "gpt-5.5"
model_provider = "passport_test"
approval_policy = "never"
sandbox_mode = "danger-full-access"
[model_providers.passport_test]
name = "Passport loopback fixture"
base_url = "http://127.0.0.1:{http.server_port}/v1"
wire_api = "responses"
env_key = "PASSPORT_TEST_TOKEN"
request_max_retries = 0
stream_max_retries = 0
''')
            receiver = transport.LiveReceiver(home)
            app = AppServer(home)
            try:
                identifier = app.call('thread/start', {
                    'cwd':folder, 'modelProvider':'passport_test', 'model':'gpt-5.5'})['thread']['id']
                installer.apply('install', (HERE/'hook.py').read_bytes(), home)
                assert installer.review(home, True)['trusted']

                def turn():
                    app.call('turn/start', {'threadId':identifier,
                        'input':[{'type':'text', 'text':'Reply ready.'}]})
                    app.take(lambda value:value.get('method')=='turn/completed')
                    result = []
                    due = time.monotonic()+1
                    while time.monotonic() < due:
                        try:
                            value = receiver.frames.get(timeout=.1)
                        except queue.Empty:
                            continue
                        if value['kind'] != 'pulse':
                            result.append(value['kind'])
                    return result

                def reload_existing():
                    class WireAdapter:
                        counter = app.identifier
                        timeout = 20
                        def _send(self, value, deadline):
                            app.send(value)
                        def _receive(self, deadline):
                            return app.take(lambda value:True,
                                timeout=max(.01, deadline-time.monotonic()))
                    wire = WireAdapter()
                    result = installer.reload_connection(wire)
                    app.identifier = wire.counter
                    assert result['state'] == 'reloaded'

                before = turn()
                assert before == [], before
                reload_existing()
                after = turn()
                assert after == ['started', 'completed'], after
                installer.apply('uninstall', home=home)
                still_loaded = turn()
                assert still_loaded == ['started', 'completed'], still_loaded
                reload_existing()
                removed = turn()
                assert removed == [], removed
                print(json.dumps({'scenario':'reload', 'model_requests':'loopback only',
                    'before_reload':before, 'after_reload':after,
                    'uninstalled_before_reload':still_loaded, 'uninstalled_after_reload':removed}))
            finally:
                app.close()
                receiver.close()
    finally:
        http.shutdown()
        http.server_close()
        thread.join(timeout=2)


if __name__=='__main__':
    for scenario in sys.argv[1:] or ['quota','ephemeral','success','failure','continuation','user_input','async_input','permission','interrupt','reload']:
        if scenario=='reload': run_reload_case()
        else: run_case(scenario)
