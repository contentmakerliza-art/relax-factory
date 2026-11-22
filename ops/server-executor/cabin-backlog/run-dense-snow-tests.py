"""Three explicitly staged, zero-token tests of the owner's dense-snow prompt."""
import concurrent.futures,fcntl,json,pathlib,subprocess,time,threading,sys,hashlib
ROOT=pathlib.Path('/opt/relax-codex');BASE=ROOT/'cabin-backlog';DL=pathlib.Path('/opt/marketplace-analytics/studio-downloads');LEDGERS=pathlib.Path('/opt/marketplace-analytics/studio-state')
sys.path.insert(0,str(ROOT));import cabin_corrections as corrections;import cabin_backlog_registry as registry
ROWS=[(3,2,'cabin03-fullframe-v15-20261121'),(11,0,'cabin11-fullframe-v2-20261121'),(21,0,'cabin21-fullframe-v3-20261121')]
status_path=BASE/'dense-snow-test-status.json';mutex=threading.Lock()
status=json.loads(status_path.read_text()) if status_path.exists() else {'scenes':{}}
def update(group,value):
 with mutex:
  status['scenes'][group]=value;status['updated']=time.time();p=status_path.with_suffix('.tmp');p.write_text(json.dumps(status,ensure_ascii=False,indent=2));p.replace(status_path)
def read(p):return json.loads(p.read_text()) if p.exists() else {}
def run(args,timeout=1200):return subprocess.run(args,check=True,capture_output=True,text=True,timeout=timeout)
def one(row):
 n,index,rid=row;group=f'cabin{n:02d}-backlog-20261121';folder=ROOT/'production-runs'/group
 with (folder/'worker.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  receipt=read(folder/'delivery.json')
  if receipt.get('stage')=='sent_for_owner_approval':update(group,receipt);return
  if group in status['scenes'] and status['scenes'][group].get('stage') in ('sent_for_owner_approval','raw_source_rejected','quality_evidence_requires_review'):return
  config=read(ROOT/'production-configs'/(group+'.json'));source=config['sources'][index]
  if rid not in source['attempts'] or not registry.attempt(rid,group):raise ValueError('Unstaged test ID')
  ledger=LEDGERS/('runway-'+rid+'.json')
  reservations=[read(LEDGERS/('runway-'+old+'.json')) for old in source['attempts'] if old!=rid]
  used=sum(x.get('state') in ('submitted','submission_uncertain','generated_needs_download','downloaded_needs_qc') for x in reservations)
  if not ledger.exists() and used>=3:raise ValueError('Three-attempt image budget exhausted')
  if source.get('new_image_request'):
   image_request=read(pathlib.Path(source['new_image_request']));image=read(LEDGERS/(image_request['request_id']+'.json'))
   if image.get('state')!='downloaded_needs_qc':raise ValueError('Only existing downloaded images; never buy another')
   file=pathlib.Path(image['file'])
  else:file=pathlib.Path(source['file'])
  if file.parent!=pathlib.Path('/downloads') or not (DL/file.name).is_file():raise ValueError('Existing image unavailable')
  with (BASE/'media-check.lock').open('a') as media:
   fcntl.flock(media,fcntl.LOCK_EX);registry.prepare_geometry(group,index,DL/file.name)
  request=DL/(rid+'-request.json')
  if not ledger.exists():
   proposed={'request_id':rid,'source':str(file),'prompt':source['runway_prompt'],'model':source.get('model','Gen-4 Turbo')}
   correction=corrections.prepare(request,proposed,[],'video',folder/'corrections')
   if correction['requires_review']:raise ValueError('Unexpected hold on owner dense-snow test')
   audit=folder/(rid+'-dense-snow-test.json')
   if not audit.exists():audit.write_text(json.dumps(dict(kind='owner_requested_dense_snow_test',request_id=rid,existing_image=str(file),max_runway_cost_tokens=0,new_paid_images=0,prompt_sha256=correction['actual_prompt_sha256'],prior_reserved_attempts=used),indent=2))
  update(group,dict(stage='generating_zero_token_snow_test',request_id=rid,new_paid_images=0))
  run(['python3',str(BASE/'await-syntx.py'),'video',str(request)])
  update(group,dict(stage='checking_raw_source',request_id=rid,new_paid_images=0))
  with (BASE/'media-check.lock').open('a') as media:
   fcntl.flock(media,fcntl.LOCK_EX)
   registry.stage_geometry(rid,registry.prepare_geometry(group,index,DL/file.name))
   result=run(['python3',str(BASE/'pipeline-one.py'),rid])
   (folder/(rid+'-snow-test-pipeline.log')).write_text(result.stdout+result.stderr)
  pipeline=read(ROOT/'assets'/rid/'pipeline.json');stage=pipeline.get('stage')
  if stage!='held_for_motion_and_audio_review':
   value=dict(stage='quality_evidence_requires_review' if stage=='held_for_snow_evidence' else 'raw_source_rejected',request_id=rid,pipeline=pipeline)
   update(group,value);return
  (folder/'state.json').write_text(json.dumps(dict(stage='preview_ready_for_final_checks',updated=time.time(),request_id=rid,preview=pipeline['preview'],owner_approval=False)))
  result=run(['python3',str(BASE/'finish-production.py'),group]);(folder/(rid+'-snow-test-finisher.log')).write_text(result.stdout+result.stderr)
  update(group,read(folder/'delivery.json'))
def guarded(row):
 group=f'cabin{row[0]:02d}-backlog-20261121'
 try:one(row)
 except Exception as e:
  detail=(getattr(e,'stderr','') or str(e))[-3500:];update(group,dict(stage='snow_test_needs_attention',request_id=row[2],error=detail))
lock=(BASE/'dense-snow-test.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
# Finish the current last reconstruction first, so versions of the same scene never race.
deadline=time.monotonic()+900
while subprocess.run(['systemctl','is-active','--quiet','relax-cabin-loop-repair.service']).returncode==0:
 if time.monotonic()>deadline:raise TimeoutError('Existing reconstruction still running; no duplicate work')
 time.sleep(2)
status.update(state='running',new_paid_images=0,max_parallel_generations=2)
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(guarded,ROWS))
status.update(state='completed',updated=time.time())
temp=status_path.with_suffix('.tmp');temp.write_text(json.dumps(status,ensure_ascii=False,indent=2));temp.replace(status_path)
