"""Fixed-destination scout client. Secrets never appear in command arguments or output."""
import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path
from .supabase_store import NoRedirect

URL='https://company-x2.onrender.com/api/company/agent-scout'
SECRET=Path(__file__).resolve().parents[1]/'work/private/agent-scout-token.txt'

def request(data=None,opener=None,token=None):
    token=token or os.environ.get('AGENT_SCOUT_TOKEN') or SECRET.read_text(encoding='utf-8').strip()
    if len(token)<32:raise ValueError('Scout authentication is not configured')
    req=urllib.request.Request(URL,data=None if data is None else json.dumps(data).encode(),
        headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},method='GET' if data is None else 'POST')
    with (opener or urllib.request.build_opener(NoRedirect()).open)(req,timeout=100) as response:
        raw=response.read(2_000_001)
    if len(raw)>2_000_000:raise ValueError('Scout response too large')
    return json.loads(raw)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--input',type=Path);args=parser.parse_args()
    try:
        data=None
        if args.input:
            if args.input.stat().st_size>20000:raise ValueError('Input too large')
            data=json.loads(args.input.read_text(encoding='utf-8'))
        print(json.dumps(request(data),ensure_ascii=True))
    except Exception:
        print('Scout request failed. Check connection, authentication and payload; retry the same run key.',file=sys.stderr)
        return 1
    return 0
if __name__=='__main__':sys.exit(main())
