"""Finish three owner-requested previews, preserving every source and receipt."""
from pathlib import Path
import subprocess,json,time,fcntl
ROOT=Path('/opt/relax-codex')
STATUS=ROOT/'cabin-backlog/three-window-snow-20261122.json'
ROWS=[(12,'cabin12-snow-v2-20261122'),(15,'cabin15-snow-v14-20261122'),(20,'cabin20-snow-v15-20261122')]

def write(value):
 p=STATUS.with_suffix('.tmp');p.write_text(json.dumps(value,ensure_ascii=False,indent=2));p.replace(STATUS)

def receipt(day,rid):
 p=ROOT/'production-runs'/f'cabin{day}-backlog-20261121'/'delivery.json'
 d=json.loads(p.read_text()) if p.exists() else {}
 if d.get('request_id')!=rid:return {'stage':'not_delivered','request_id':rid}
 job=d.get('job_id');p=Path('/var/lib/relax-factory')/str(job)/'job.json'
 if p.exists():
  j=json.loads(p.read_text());d['telegram_status']=j.get('telegram',{}).get('status')
 return d

with (ROOT/'cabin-backlog/three-window-snow.lock').open('a') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 value={'stage':'running','new_paid_generations':0,'items':{},'updated':time.time()}
 write(value)
 deadline=time.monotonic()+1500
 while subprocess.run(['systemctl','is-active','--quiet','relax-cabin12-window-snow.service']).returncode==0:
  if time.monotonic()>deadline:raise TimeoutError('First preview needs inspection')
  time.sleep(5)
 value['items']['12']=receipt(*ROWS[0]);write(value)
 for day,rid in ROWS[1:]:
  value.update(current=day,updated=time.time());write(value)
  folder=ROOT/'assets'/rid;folder.mkdir(exist_ok=True)
  try:
   for step in ['build','review']:
    result=subprocess.run(['python3',str(ROOT/f'{step}-window-snow{day}.py')],capture_output=True,text=True,timeout=1500)
    (folder/f'batch-{step}.log').write_text(result.stdout+result.stderr)
    result.check_returncode()
   value['items'][str(day)]=receipt(day,rid)
  except Exception as error:
   value['items'][str(day)]={'stage':'needs_inspection','request_id':rid,'error':type(error).__name__}
  value['updated']=time.time();write(value)
 value.update(stage='completed',current=None,updated=time.time());write(value)
 print(json.dumps(value,ensure_ascii=False),flush=True)
