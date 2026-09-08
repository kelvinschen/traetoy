#!/usr/bin/env python3
"""One-time identity comparison. The temporary local App Server exits afterward."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import companion
from passport.rpc import RPC, READ_METHODS

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('alias',help='Existing SSH App Server host, such as devbox')
a=p.parse_args()
READ_METHODS.add('account/read')
local=remote=None
try:
    local=RPC([companion.codex_command(),'app-server'])
    remote=RPC.remote(a.alias)
    left=local.call('account/read',{'refreshToken':False}).get('account')
    right=remote.call('account/read',{'refreshToken':False}).get('account')
    if not left or left!=right:
        raise SystemExit('Accounts differ or are unavailable; fingerprint was not changed.')
    fingerprint=hashlib.sha256(json.dumps(left,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    path=Path(__file__).resolve().parents[1]/'reports/account-identity.sha256'
    path.parent.mkdir(exist_ok=True)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as f:f.write(fingerprint+'\n')
    os.chmod(path,0o600)
    print('Same account verified; private fingerprint saved. No account details printed.')
finally:
    if remote:remote.close()
    if local:local.close()
