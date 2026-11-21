"""New version of an unsent saved clip; no provider submission or owner approval."""
import sys,fcntl,json,pathlib,subprocess,shutil,hashlib,time
sys.path.insert(0,'/opt/relax-codex')
import cabin_backlog_registry as registry
ROOT=pathlib.Path('/opt/relax-codex');DL=pathlib.Path('/opt/marketplace-analytics/studio-downloads');STATE=pathlib.Path('/opt/marketplace-analytics/studio-state')
parent=sys.argv[1];rid=parent.replace('-fullframe-','-fixed-');entry=registry.entry(parent)
if not entry or '-fullframe-' not in parent:raise ValueError('Exact original attempt required')
row,index=entry;group=row['request_group'];folder=ROOT/'production-runs'/group
receipt=folder/'delivery.json'
if receipt.exists() and json.loads(receipt.read_text()).get('stage')=='sent_for_owner_approval':raise ValueError('Preserve already-sent version')
assets=ROOT/'assets'/rid;assets.mkdir(exist_ok=True);raw=DL/(parent+'.mp4');target=DL/(rid+'.mp4')
digest=hashlib.sha256(raw.read_bytes()).hexdigest()
if target.exists():
 if hashlib.sha256(target.read_bytes()).hexdigest()!=digest:raise ValueError('Derived source changed')
else:shutil.copy2(raw,target)
ledger=STATE/('derived-'+rid+'.json')
if not ledger.exists():
 with ledger.open('x') as f:json.dump(dict(state='downloaded_needs_qc',kind='whole_frame_loop_repair',request_id=rid,parent_request_id=parent,source_sha256=digest,cost_tokens=0,local_masks=False),f)
with (ROOT/'cabin-backlog/media-check.lock').open('a') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX)
 geometry=registry.geometry(parent);registry.stage_geometry(rid,geometry)
 qc=ROOT/'assets'/parent/'visual-qc.json'
 if qc.exists() and not (assets/'visual-qc.json').exists():
  data=json.loads(qc.read_text())
  if data.get('verdict')!='NEEDS_MOTION_REVIEW':raise ValueError('Original source needs visual correction; do not bypass it')
  data.update(reused_from_exact_source=parent,source_sha256=digest)
  (assets/'visual-qc.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
 p=subprocess.run(['python3',str(ROOT/'cabin-backlog/pipeline-one.py'),rid],capture_output=True,text=True,timeout=1200)
 print(p.stdout,p.stderr[-1800:],flush=True);p.check_returncode()
 result=json.loads((assets/'pipeline.json').read_text())
 if result['stage']!='held_for_motion_and_audio_review':raise ValueError('Repaired version did not reach final checks')
 history=folder/'loop-repair-history';history.mkdir(exist_ok=True)
 for name in ('state.json','delivery.json'):
  old=folder/name
  if old.exists():shutil.copy2(old,history/(str(time.time_ns())+'-'+name))
 (folder/'state.json').write_text(json.dumps(dict(stage='preview_ready_for_final_checks',updated=time.time(),request_id=rid,parent_request_id=parent,preview=str(assets/'preview.mp4'),owner_approval=False)))
print('START_FINAL_QA',rid,flush=True)
p=subprocess.run(['python3',str(ROOT/'cabin-backlog/finish-production.py'),group],capture_output=True,text=True,timeout=1500)
print(p.stdout,p.stderr[-2000:],flush=True);p.check_returncode();print((folder/'delivery.json').read_text(),flush=True)
