from pathlib import Path
import sys,json,fcntl,subprocess,time,shutil,hashlib
ROOT=Path('/opt/relax-codex');sys.path.insert(0,str(ROOT));import cabin_backlog_registry as registry
from cabin_window_snow20 import PARENT,REQUEST
assets=ROOT/'assets'/REQUEST;group='cabin20-backlog-20261121';folder=ROOT/'production-runs'/group
source=Path('/opt/marketplace-analytics/studio-downloads')/(REQUEST+'.mp4');report=json.loads((assets/'recipe-and-checks.json').read_text())
if hashlib.sha256(source.read_bytes()).hexdigest()!=report['source_sha256']:raise ValueError('Composited source changed')
ledger=Path('/opt/marketplace-analytics/studio-state')/('derived-'+REQUEST+'.json')
if not ledger.exists():
 with ledger.open('x') as f:json.dump(dict(state='downloaded_needs_qc',kind='owner_requested_window_snow_prototype',request_id=REQUEST,parent_request_id=PARENT,source_sha256=report['source_sha256'],window_snow_overlay=True,mask_scope='exterior_window_glass_only',fireplace_masks=False,cost_tokens=0),f)
with (ROOT/'cabin-backlog/media-check.lock').open('a') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX)
 geometry=json.loads(json.dumps(registry.geometry(PARENT)))
 if report.get('frame_border_crop_pixels'):
  from cabin_window_snow20 import transform_box
  geometry['regions']={name:transform_box(box) for name,box in geometry['regions'].items()}
  for key in ['detail','snow']:
   geometry[key+'_box']=transform_box(geometry[key+'_box'])
   x,y,w,h=geometry[key+'_box'];geometry[key+'_crop']=f'{w}:{h}:{x}:{y}'
  geometry['qa_coordinate_transform']={'constant_border_crop':report['frame_border_crop_pixels'],'output_size':[1280,720]}
 registry.stage_geometry(REQUEST,geometry)
 result=subprocess.run(['python3',str(ROOT/'cabin-backlog/pipeline-one.py'),REQUEST],capture_output=True,text=True,timeout=900)
 (assets/'source-review-run.log').write_text(result.stdout+result.stderr)
 print(result.stdout,result.stderr[-2200:],flush=True);result.check_returncode()
 pipeline=json.loads((assets/'pipeline.json').read_text())
 if pipeline['stage']!='held_for_motion_and_audio_review':
  print(json.dumps(pipeline,ensure_ascii=False),flush=True);sys.exit(0)
 history=folder/'window-snow-prototype-history';history.mkdir(exist_ok=True)
 for name in ['state.json','delivery.json']:
  path=folder/name
  if path.exists():shutil.copy2(path,history/(str(time.time_ns())+'-'+name))
 (folder/'state.json').write_text(json.dumps(dict(stage='preview_ready_for_final_checks',updated=time.time(),request_id=REQUEST,preview=str(assets/'preview.mp4'),window_snow_overlay=True,owner_approval=False)))
# A corrected request needs a fresh receipt; keep the prior delivery in history.
with (folder/'finisher.lock').open('a') as delivery_lock:
 fcntl.flock(delivery_lock,fcntl.LOCK_EX)
 receipt=folder/'delivery.json'
 if receipt.exists():
  previous=json.loads(receipt.read_text())
  if previous.get('stage')=='sent_for_owner_approval' and previous.get('request_id')!=REQUEST:
   snapshot=folder/'window-snow-prototype-history'/(str(time.time_ns())+'-superseded-delivery.json')
   shutil.copy2(receipt,snapshot)
   temporary=folder/'delivery-corrected.tmp'
   temporary.write_text(json.dumps(dict(stage='waiting_for_corrected_preview',request_id=REQUEST,
     supersedes_request_id=previous.get('request_id'),previous_job_id=previous.get('job_id'),
     rejected_requests=previous.get('rejected_requests',[]),updated=time.time())))
   temporary.replace(receipt)
subprocess.run(['python3',str(ROOT/'check-cabin20-seam.py')],check=True,timeout=240)
print('FINAL_QA_WINDOW_SNOW',flush=True)
r=subprocess.run(['python3',str(ROOT/'cabin-backlog/finish-production.py'),group],capture_output=True,text=True,timeout=1200)
(assets/'final-review-run.log').write_text(r.stdout+r.stderr);print(r.stdout,r.stderr[-2200:],flush=True);r.check_returncode()
print((folder/'delivery.json').read_text(),flush=True)
