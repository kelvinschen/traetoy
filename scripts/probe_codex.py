import subprocess,json,selectors,time
p=subprocess.Popen(['codex','app-server'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,bufsize=1)
sel=selectors.DefaultSelector();sel.register(p.stdout,selectors.EVENT_READ)
def rpc(i,m,params=None):
 p.stdin.write(json.dumps({'id':i,'method':m,'params':params})+'\n');p.stdin.flush()
 deadline=time.monotonic()+20
 while time.monotonic()<deadline:
  if not sel.select(1):continue
  line=p.stdout.readline()
  if not line:raise RuntimeError('server closed')
  r=json.loads(line)
  if r.get('id')==i:return r
 raise TimeoutError(m)
try:
 print('initialize:', 'result' in rpc(1,'initialize',{'clientInfo':{'name':'passport_monitor','version':'0.1.0'},'capabilities':{'experimentalApi':True}}))
 p.stdin.write('{"method":"initialized"}\n');p.stdin.flush()
 r=rpc(2,'account/rateLimits/read')
 print('rate limits:', {k:v for k,v in r.get('result',{}).items() if k in ['rateLimits','rateLimitsByLimitId']} if 'result' in r else r)
 r=rpc(3,'thread/list',{'limit':3,'sortKey':'updated_at'})
 print('threads:',[{k:t.get(k) for k in ['id','name','status','updatedAt']} for t in r.get('result',{}).get('data',[])])
 r=rpc(4,'thread/turns/list',{'threadId':'01a076d5-7e39-7f21-bb23-530f70d4203a','limit':2,'itemsView':'notLoaded'})
 print('turns:', [{k:v for k,v in t.items() if k!='items'} for t in r.get('result',{}).get('data',[])], r.get('error'))
finally:
 p.terminate()
 try:p.wait(timeout=3)
 except subprocess.TimeoutExpired:p.kill();p.wait()
