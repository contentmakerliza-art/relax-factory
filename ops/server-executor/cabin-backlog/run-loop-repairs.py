import pathlib,json,time,subprocess,fcntl
ROOT=pathlib.Path('/opt/relax-codex');BASE=ROOT/'cabin-backlog'
PARENTS=['cabin03-fullframe-v13-20261121','cabin05-fullframe-v14-20261121','cabin10-fullframe-v15-20261121','cabin11-fullframe-v1-20261121','cabin12-fullframe-v2-20261121','cabin15-fullframe-v14-20261121','cabin20-fullframe-v15-20261121','cabin21-fullframe-v2-20261121']
lock=(BASE/'loop-repair-batch.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
status_path=BASE/'loop-repair-status.json'
status=json.loads(status_path.read_text()) if status_path.exists() else {'scenes':{}}
def save():
 status['updated']=time.time();p=status_path.with_suffix('.tmp');p.write_text(json.dumps(status,ensure_ascii=False,indent=2));p.replace(status_path)
status.update(state='running',paid_generations=False);save()
for parent in PARENTS:
 group=parent[:7]+'-backlog-20261121';folder=ROOT/'production-runs'/group
 receipt=folder/'delivery.json';previous=json.loads(receipt.read_text()) if receipt.exists() else {}
 if previous.get('stage')=='sent_for_owner_approval':
  status['scenes'][group]=previous;save();continue
 if group in status['scenes']:continue
 status['current']=group;save();print('REPAIR',parent,flush=True)
 try:
  p=subprocess.run(['python3',str(ROOT/'repair-saved-cabin.py'),parent],capture_output=True,text=True,timeout=1800)
  (folder/'loop-repair-output.log').write_text((p.stdout+p.stderr)[-9000:])
  result=json.loads(receipt.read_text()) if receipt.exists() else {}
  if p.returncode:result={'stage':'repair_needs_attention','error':(p.stderr+p.stdout)[-1500:],'previous_delivery':result}
 except Exception as e:result={'stage':'repair_needs_attention','error':str(e)}
 status['scenes'][group]=result;save();print('RESULT',group,result.get('stage'),flush=True)
status.update(state='completed',current=None);save()
