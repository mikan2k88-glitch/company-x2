"""Subprocess bridge for the synthetic browser test; disposable loopback DB only."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

dsn=os.environ.get('CX2_TEST_DSN','')
if urlparse(dsn).hostname not in ('localhost','127.0.0.1','::1'):
    raise ValueError('Disposable loopback database required')
schema,action,key=sys.argv[1:]
if not re.fullmatch('browser_delivery_[a-f0-9]{32}',schema):raise ValueError('Invalid test schema')

def sql(query):
    result=subprocess.run(['psql',dsn,'-X','-A','-t','-v','ON_ERROR_STOP=1','-c',query],capture_output=True,text=True)
    if result.returncode:raise RuntimeError('Disposable database command failed')
    return result.stdout.strip()

if action=='init':
    sql((Path(__file__).parent/'fixtures'/'delivery_rpc.sql').read_text().replace('__SCHEMA__',schema))
elif action=='drop':
    sql(f'DROP SCHEMA {schema} CASCADE')
elif action=='claim':
    if not re.fullmatch('[a-f0-9]{64}',key):raise ValueError('Invalid test identity')
    raw=sql(f"SELECT {schema}.journal('claim','{{\"identity\":\"{key}\"}}'::jsonb)")
    result=json.loads(raw) if raw else None
    print(json.dumps(result['lease'] if result else None))
else:raise ValueError('Unsupported bridge action')
