"""Durable server-owned Cabin layout, assembly checking and preview delivery."""
import argparse,fcntl,hashlib,json,os,pwd,re,shutil,sqlite3,subprocess,time
from pathlib import Path
from window_snow_contract import VERSION,digest,job_id,schema,validate_plan,transform_box
ROOT=Path('/opt/relax-codex');DATA=Path('/var/lib/relax-factory');STATE=ROOT/'window-snow'
TERMINAL={'delivered','held','failed','superseded'}

def read(p):return json.loads(p.read_text()) if p.exists() else {}
def atomic(p,value):
 p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2));tmp.replace(p)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def run(args,**kwargs):return subprocess.run(args,check=True,capture_output=True,text=True,**kwargs)
def note(folder,stage,**extra):
 value=read(folder/'state.json')
 if stage not in ['held','failed']:
  for key in ['reason','error','detail']:value.pop(key,None)
 value.update(stage=stage,updated=time.time(),**extra);atomic(folder/'state.json',value)
 return value

def enqueue(parent,*,decision='',feedback='',source_job=None,kick=True):
 import cabin_backlog_registry as registry
 match=registry.entry(parent)
 if not match:raise ValueError('Source not in Cabin registry')
 row,_=match;group=row['request_group']
 normalized=ROOT/'assets'/parent/'normalized.mp4'
 source=normalized if normalized.exists() else Path('/opt/marketplace-analytics/studio-downloads')/(parent+'.mp4')
 if not source.exists():raise ValueError('Original animation is unavailable')
 raw_qc=read(ROOT/'assets'/parent/'visual-qc.json')
 if raw_qc.get('verdict')!='NEEDS_MOTION_REVIEW':raise ValueError('Raw source has not passed object/animation prescreen')
 checksum=sha(source);identifier=job_id(parent,checksum,decision);folder=STATE/'jobs'/identifier
 folder.mkdir(parents=True,exist_ok=True)
 request=folder/'request.json'
 value=dict(id=identifier,parent_request_id=parent,source=str(source),source_sha256=checksum,normalized_input=source==normalized,
  group=group,channel='Quiet Pines Cabin',decision_id=decision,feedback=feedback,source_job=source_job,created=time.time(),mask_policy=VERSION,max_layout_attempts=2)
 if request.exists():
  existing=read(request)
  if any(existing.get(k)!=value[k] for k in ['parent_request_id','source_sha256','decision_id']):raise ValueError('Job identity changed')
 else:
  with request.open('x') as f:json.dump(value,f,ensure_ascii=False,indent=2)
  note(folder,'queued')
 if kick:
  subprocess.run(['systemctl','start','--no-block','relax-window-snow.service'],capture_output=True,text=True,timeout=10)
 return identifier

def dispatch_decision(task_id,row,db):
 if row.get('archived') or row.get('status')!='правка' or 'Quiet Pines Cabin' not in row.get('label',''):return False
 comments=row.get('comments') or []
 if not comments:return False
 text=comments[-1].get('text') or comments[-1].get('transcript') or ''
 if not re.search(r'сне[гж]|склей|мутн|двоит|наезд|рам[ауы]|спинк|snow|seam',text,re.I):return False
 if re.search(r'замени.*кот|цвет.*кот|голов.*дви|звук|музык|топк|плам',text,re.I):return False
 if not re.fullmatch('[a-f0-9]{64}',task_id):raise ValueError('Invalid decision identity')
 actual=hashlib.sha256(json.dumps({k:row[k] for k in ['job_id','status','time','comments']},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
 if task_id!=actual:raise ValueError('Owner decision changed')
 queue=read(DATA/'queue/queue.json') or []
 if any(item.get('source')==row['job_id'] for item in queue):return False
 for receipt in DATA.glob('codex-delivery-cabin*.json'):
  if read(receipt).get('job_id')!=row['job_id']:continue
  rid=receipt.stem.removeprefix('codex-delivery-');meta=read(ROOT/'assets'/rid/'recipe-and-checks.json')
  parent=meta.get('parent_request_id',rid)
  # These edits change assembly only; operate on a known preserved native source.
  if read(ROOT/'assets'/parent/'visual-qc.json').get('verdict')!='NEEDS_MOTION_REVIEW':
   prior=read(ROOT/'assets'/parent/'segment-selection.json')
   if parent.startswith('cabin20-trimmed-'):parent='cabin20-fixed-v15-20261121'
  try:identifier=enqueue(parent,decision=task_id,feedback=text,source_job=row['job_id'])
  except ValueError:return False
  with db:db.execute("UPDATE tasks SET state='window_queued' WHERE id=?",(task_id,))
  return True
 return False

def current(job):
 if not job.get('decision_id'):return True
 import importlib.util
 spec=importlib.util.spec_from_file_location('window_bridge',ROOT/'approval-bridge.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 row=m.read_rows(DATA).get(job['source_job'])
 if not row or row.get('status')!='правка':return False
 actual=hashlib.sha256(json.dumps({k:row[k] for k in ['job_id','status','time','comments']},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
 return actual==job['decision_id']

def media(mode,base,folder):
 for name in ['window_snow_media.py','window_snow_contract.py','cabin_loop_recipe.py']:
  run(['docker','cp',str(ROOT/name),'relax-factory:/tmp/'+name])
 result=subprocess.run(['docker','exec','relax-factory','python','/tmp/window_snow_media.py',mode,base],capture_output=True,text=True,timeout=900)
 (folder/(mode+'-run.log')).write_text(result.stdout+result.stderr)
 result.check_returncode()
 return json.loads(result.stdout)

def codex_layout(prepared_dir,job,attempt,feedback,cache):
 user=pwd.getpwnam('relax-codex');work=Path('/var/lib/relax-codex/workspace')/(job['id']+f'-mask-{attempt}')
 work.mkdir(mode=0o700,exist_ok=True);os.chown(work,user.pw_uid,user.pw_gid)
 for i in range(4):
  p=work/f'frame{i}.png';shutil.copy2(prepared_dir/f'frame{i}.png',p);os.chown(p,user.pw_uid,user.pw_gid);p.chmod(0o600)
 (work/'schema.json').write_text(json.dumps(schema()))
 prompt=('Do not use tools. Annotate the attached four frames of ONE normalized 1280x720 Quiet Pines Cabin animation. '
  'Coordinates are native image pixels, x from left, y from top. These are frames at start, one second, middle and end. '
  'Return glass polygons ONLY INSIDE the visible inner edge of each glass pane. Every wooden mullion/transom splits panes: enumerate each pane separately; never cover a whole multi-pane window with one polygon. '
  'Use the intersection of safe glass over all four frames. Exclude frames, sill, wall, ceiling, fireplace, furnishings. '
  'Return foreground polygons covering the COMPLETE silhouettes of ALL chairs, backs, posts, rails, spindles, furniture, plants and objects crossing glass. '
  'For a chair back use its complete outer silhouette including holes: Snow must not hit any wooden upright or rail. Use the union over the four frames. '
  'The fireplace/cat is not an editing region. No fireplace replacement or fire masks. '
  'Choose inset_fullhd_px at least 4; 6-8 if boundaries have slight motion/uncertainty. Renderer erodes glass and expands foreground, then feathers only inward. '
  'Also annotate 3-6 rigid_regions [x,y,width,height], each 24-200 pixels wide and 24-160 high, distributed across textured indoor wood/stone and solid window frames. '
  'All rigid_regions must lie within the retained rectangle x=48..1232,y=27..693 after camera-border crop. These are measurement crops, never editing masks. Exclude flames, cat, reflections, outdoor Snow and moving leaves from rigid_regions. '
  'If boundaries cannot be located safely choose UNCERTAIN; do not invent coordinates. '
  'Keep notes short and in Russian. Existing owner feedback and previous FAILED layout feedback apply only to this source: '+feedback[:5000])
 cached=cache/'plan.json';cache.mkdir(parents=True,exist_ok=True)
 if cached.exists():return validate_plan(read(cached))
 output=work/'plan.json'
 started=cache/'model-started.json'
 if started.exists():
  unit='relax-auto-mask-'+job['id'][-12:]+f'-{attempt}.service'
  deadline=time.monotonic()+250
  while not output.exists() and time.monotonic()<deadline:
   active=subprocess.run(['systemctl','is-active','--quiet',unit],capture_output=True).returncode==0
   if not active:break
   time.sleep(3)
  if output.exists():
   atomic(cached,read(output));return validate_plan(read(cached))
  raise RuntimeError('Prior AI layout outcome uncertain; automatic duplicate is blocked')
 args=['systemd-run','--unit=relax-auto-mask-'+job['id'][-12:]+f'-{attempt}','--collect','--wait','--pipe','-p','User=relax-codex','-p','WorkingDirectory='+str(work),'-p','MemoryMax=512M','-p','CPUQuota=25%','-p','RuntimeMaxSec=240',
 '--setenv=HOME=/var/lib/relax-codex','--setenv=CODEX_HOME=/var/lib/relax-codex/.codex',
 '/opt/relax-codex/release-0.171.0/bin/codex','exec','--ephemeral','--skip-git-repo-check','--sandbox','read-only',
 *[a for i in range(4) for a in ['--image',str(work/f'frame{i}.png')]],'--output-schema',str(work/'schema.json'),'-o',str(output),prompt]
 atomic(started,{'stage':'model_started','unit':args[1],'created':time.time()})
 run(args,timeout=270)
 atomic(cached,read(output))
 return validate_plan(read(cached))

def copy_from(base,name,target):run(['docker','cp','relax-factory:'+base+'/'+name,str(target/name)])

def hold(folder,reason):
 note(folder,'held',reason=reason)
 marker=folder/'notification.json'
 if not marker.exists():
  atomic(marker,{'stage':'sending'})
  job=read(folder/'request.json');config=read(ROOT/'production-configs'/(job['group']+'.json'))
  text=f"Проба Cabin «{config.get('scene_title','')}» остановлена на проверке. {reason[:500]} Материалы сохранены; новая генерация и публикация не запускались."
  try:
   run(['docker','exec','relax-factory','python','-c','import sys;from render import telegram;telegram.send_text(sys.argv[1])',text],timeout=90)
   atomic(marker,{'stage':'sent'})
  except Exception:atomic(marker,{'stage':'unconfirmed_no_resend'})

def finish(job,rid,assets):
 import cabin_backlog_registry as registry
 prepared=read(assets/'recipe-and-checks.json')
 geometry=json.loads(json.dumps(registry.geometry(job['parent_request_id'])))
 geometry['regions']={k:transform_box(box) for k,box in geometry['regions'].items()}
 for name in ['detail','snow']:
  geometry[name+'_box']=transform_box(geometry[name+'_box']);x,y,w,h=geometry[name+'_box'];geometry[name+'_crop']=f'{w}:{h}:{x}:{y}'
 registry.stage_geometry(rid,geometry)
 source=Path('/opt/marketplace-analytics/studio-downloads')/(rid+'.mp4')
 if not source.exists():shutil.copy2(assets/'composed.mp4',source)
 if sha(source)!=prepared['source_sha256']:raise ValueError('Derived source checksum mismatch')
 atomic(Path('/opt/marketplace-analytics/studio-state')/('derived-'+rid+'.json'),dict(state='downloaded_needs_qc',kind='server_auto_window_snow',request_id=rid,parent_request_id=job['parent_request_id'],source_sha256=sha(source),cost_tokens=0))
 atomic(assets/'pipeline.json',dict(stage='held_for_motion_and_audio_review',request_id=rid,preview=str(assets/'preview.mp4'),source_screen_reference=job['parent_request_id'],derived_source=True,owner_approval=False))
 folder=ROOT/'production-runs'/job['group'];history=folder/'auto-snow-history';history.mkdir(exist_ok=True)
 with (folder/'finisher.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  for name in ['state.json','delivery.json']:
   p=folder/name
   if p.exists():shutil.copy2(p,history/(str(time.time_ns())+'-'+name))
  old=read(folder/'delivery.json')
  if old.get('stage')=='sent_for_owner_approval' and old.get('request_id')==rid:return old
  atomic(folder/'state.json',dict(stage='preview_ready_for_final_checks',request_id=rid,preview=str(assets/'preview.mp4'),owner_approval=False,updated=time.time()))
  atomic(folder/'delivery.json',dict(stage='waiting_for_auto_snow_preview',request_id=rid,rejected_requests=old.get('rejected_requests',[]),updated=time.time()))
 run(['python3',str(ROOT/'cabin-backlog/finish-production.py'),job['group']],timeout=1200)
 return read(folder/'delivery.json')

def process(folder):
 job=read(folder/'request.json');source=Path(job['source'])
 if not current(job):note(folder,'superseded');return
 if sha(source)!=job['source_sha256']:raise ValueError('Original changed after queueing')
 base='/data/sources/auto-window-snow/'+job['id'];prepared_dir=folder/'prepared';prepared_dir.mkdir(exist_ok=True)
 note(folder,'normalizing')
 run(['docker','exec','relax-factory','mkdir','-p',base])
 jobmedia=dict(job,snow_path='',audio_path='')
 atomic(folder/'job-media.json',jobmedia)
 with (ROOT/'cabin-backlog/media-check.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  run(['docker','cp',str(source),'relax-factory:'+base+'/input.mp4'])
  run(['docker','cp',str(folder/'job-media.json'),'relax-factory:'+base+'/job.json'])
  prepared=media('prepare',base,folder)
  for name in ['normalized.mp4','prepared.json',*[f'frame{i}.png' for i in range(4)]]:copy_from(base,name,prepared_dir)
 cache_key=digest(dict(source=prepared['normalized_sha256'],policy=VERSION,feedback=job.get('feedback','')))
 layout_cache=STATE/'layouts'/cache_key;layout_cache.mkdir(parents=True,exist_ok=True)
 feedback=job.get('feedback','');audio=ROOT/'assets/cabin-approved-fireplace-9.wav'
 snow=next((DATA/'sources/executor-library').rglob('Снег Little Paris — мелкие хлопья — альфа 30 секунд.mkv'))
 for attempt in range(1,job['max_layout_attempts']+1):
  if not current(job):note(folder,'superseded');return
  rid=job['id']+f'-a{attempt}';assets=ROOT/'assets'/rid;assets.mkdir(exist_ok=True)
  delivered=read(assets/'auto-delivery.json')
  if delivered.get('stage')=='sent_for_owner_approval':note(folder,'delivered',request_id=rid,delivery=delivered);return
  if (assets/'auto-rejected.json').exists():
   feedback=read(assets/'auto-rejected.json').get('feedback',feedback)
   prior=read(assets/'final-preview-qc.json')
   if prior.get('repair_stage')=='ASSEMBLY' and attempt<job['max_layout_attempts']:atomic(folder/'assembly-repair.json',{'reason':prior.get('defects',[]),'strategy':'native_backtrack','source_request_id':rid,'new_layout_model_call':False})
   continue
  repair=read(folder/'assembly-repair.json')
  note(folder,'ai_window_layout',attempt=attempt,request_id=rid)
  try:plan=validate_plan(read(assets.parent/(job['id']+'-a1')/'layout.json')) if repair and attempt==2 else codex_layout(prepared_dir,job,attempt,feedback,layout_cache/f'attempt{attempt}')
  except ValueError as error:
   feedback=str(error);atomic(assets/'auto-rejected.json',{'feedback':feedback});continue
  atomic(assets/'layout.json',plan)
  atomic(STATE/'requests'/(rid+'.json'),dict(request_id=rid,parent_request_id=job['parent_request_id'],group=job['group']))
  target=base+f'/a{attempt}';run(['docker','exec','relax-factory','mkdir','-p',target])
  jobmedia.update(loop_strategy='native_backtrack' if repair and attempt==2 else 'matched_crossfade',request_id=rid,snow_path='/data/'+str(snow.relative_to(DATA)),audio_path=target+'/audio.wav')
  atomic(assets/'job-media.json',jobmedia)
  note(folder,'compositing_and_seam_checks',attempt=attempt,request_id=rid)
  with (ROOT/'cabin-backlog/media-check.lock').open('a') as lock:
   fcntl.flock(lock,fcntl.LOCK_EX)
   for name in ['normalized.mp4','prepared.json',*[f'frame{i}.png' for i in range(4)]]:run(['docker','exec','relax-factory','cp',base+'/'+name,target+'/'+name])
   for src,dst in [(assets/'job-media.json','job.json'),(assets/'layout.json','layout.json'),(audio,'audio.wav')]:run(['docker','cp',str(src),'relax-factory:'+target+'/'+dst])
   try:report=media('build',target,assets)
   except subprocess.CalledProcessError as error:
    try:copy_from(target,'assembly-qc.json',assets)
    except Exception:pass
    detail=error.stderr or ''
    if 'ASSEMBLY_HOLD:' in detail:hold(folder,'Не удалось собрать достаточно резкий и плавный стык из сохранённой анимации.');return
    if not any(message in detail for message in ['ValueError: Implausible glass','ValueError: Invalid polygon','ValueError: Need at least three','ValueError: Snow overlaps']):raise
    # Layout validation errors may be repaired once using the same native clip.
    feedback=(assets/'build-run.log').read_text()[-1800:];atomic(assets/'auto-rejected.json',{'feedback':feedback});continue
   for name in ['preview.mp4','loop-master.mp4','composed.mp4','recipe-and-checks.json','window-mask.png','preview-mask.png','preview-seam.png','assembly-qc.json']:copy_from(target,name,assets)
  if not current(job):note(folder,'superseded');return
  note(folder,'ai_final_preview_review',attempt=attempt,request_id=rid)
  delivery=finish(job,rid,assets);atomic(assets/'auto-delivery.json',delivery)
  if delivery.get('stage')=='sent_for_owner_approval':
   native=read(DATA/delivery['job_id']/'job.json')
   if native.get('telegram',{}).get('status')!='отправлено':raise ValueError('Telegram delivery is not confirmed')
   atomic(layout_cache/'accepted.json',{'attempt':attempt,'layout_sha256':digest(plan),'request_id':rid})
   note(folder,'delivered',request_id=rid,delivery=delivery)
   pipeline=ROOT/'assets'/job['parent_request_id']/'pipeline.json'
   prior=read(pipeline)
   if prior.get('stage')=='window_snow_queued':
    prior.update(stage='auto_preview_delivered',auto_job=job['id'],delivered_request_id=rid,telegram_job=delivery['job_id'],updated=time.time());atomic(pipeline,prior)
   if job.get('decision_id'):
    with sqlite3.connect('/var/lib/relax-codex-bridge/tasks.sqlite') as db:db.execute("UPDATE tasks SET state='window_delivered' WHERE id=?",(job['decision_id'],))
   return
  if delivery.get('stage')=='superseded_owner_decision':note(folder,'superseded');return
  qc=read(assets/'final-preview-qc.json');feedback=json.dumps(qc,ensure_ascii=False)
  atomic(assets/'auto-rejected.json',{'feedback':feedback})
  if qc.get('repair_stage')=='ASSEMBLY' and attempt<job['max_layout_attempts']:
   atomic(folder/'assembly-repair.json',{'reason':qc.get('defects',[]),'source_request_id':rid,'strategy':'native_backtrack','new_layout_model_call':False});continue
  if qc.get('repair_stage') not in ['MASK','SNOW_DENSITY']:hold(folder,'Проверка монтажа требует другого исходника или отдельного разбора: '+str(qc.get('defects',[]))[:300]);return
 hold(folder,'Две попытки автоматической разметки не прошли проверку. Нужна проверка границ окон.')

def main():
 STATE.mkdir(exist_ok=True)
 with (STATE/'worker.lock').open('a') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return
  # Local queue inspection performs no AI calls when empty/terminal.
  for request in sorted((STATE/'jobs').glob('*/request.json')):
   folder=request.parent
   if read(folder/'state.json').get('stage') in TERMINAL:continue
   try:process(folder)
   except Exception as error:
    note(folder,'failed',error=type(error).__name__,detail=str(error)[-1000:])
    hold(folder,'Техническая ошибка '+type(error).__name__+'. Повторная платная генерация не запускалась.')

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--enqueue');p.add_argument('--feedback',default='');a=p.parse_args()
 if a.enqueue:print(enqueue(a.enqueue,feedback=a.feedback))
 else:main()
