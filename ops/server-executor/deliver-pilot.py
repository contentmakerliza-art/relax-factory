"""Register/send the reviewed Cabin pilot via factory endpoints. Run in factory container.

Any uncertain write is held for inspection. No automatic send retry.
"""
import base64
import json
import os
from pathlib import Path
import urllib.parse
import urllib.request

SOURCE=Path('/tmp/cabin17-fullframe-v2-20261120/preview.mp4')
LABEL='Quiet Pines Cabin — 17 декабря — Библиотека у пруда — полный кадр Runway без масок — 30 секунд'
ROOT=Path(os.environ.get('APP_DATA','/app/data'))
LEDGER=ROOT/'codex-pilot-delivery.json'


def call(path,method='GET',data=None):
    password=os.environ['APP_PASSWORD']
    auth=base64.b64encode(('relax:'+password).encode()).decode()
    req=urllib.request.Request('http://127.0.0.1:8000'+path,data=data,method=method,
                               headers={'Authorization':'Basic '+auth})
    with urllib.request.urlopen(req,timeout=120) as response:
        return json.load(response)


def main():
    if LEDGER.exists():
        previous=json.loads(LEDGER.read_text())
        print(json.dumps({'held_existing_delivery':previous},ensure_ascii=False));return
    if SOURCE.stat().st_size<10000:raise ValueError('Incomplete preview')
    # Reserve before any write. Unknown responses always require inspection.
    with LEDGER.open('x') as handle:json.dump({'stage':'creating_job_uncertain'},handle)
    job_id=call('/jobs/new','POST',b'')['id']
    LEDGER.write_text(json.dumps({'stage':'uploading','job_id':job_id}))
    name=LABEL+'.mp4';offset=0
    with SOURCE.open('rb') as handle:
        while chunk:=handle.read(8*1024*1024):
            call('/jobs/'+job_id+'/files/visual/'+urllib.parse.quote(name)+'?offset='+str(offset),'PUT',chunk)
            offset+=len(chunk)
    call('/jobs/'+job_id+'/import-preview','POST',b'')
    LEDGER.write_text(json.dumps({'stage':'registered','job_id':job_id}))
    # Production source remains in /opt/relax-codex/assets, independently of cleanup.
    LEDGER.write_text(json.dumps({'stage':'telegram_submission_uncertain','job_id':job_id}))
    call('/jobs/'+job_id+'/telegram','POST',b'')
    LEDGER.write_text(json.dumps({'stage':'telegram_requested','job_id':job_id}))
    print(json.dumps({'stage':'telegram_requested','job_id':job_id},ensure_ascii=False))


if __name__=='__main__':main()
