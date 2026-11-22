"""Resume the 14 explicitly requested Mountain previews, Dec9 through Dec22.

Persistent inputs/decisions, no blind generation or Telegram retries. No finals.
All paid stills use the existing ordinary Banana queue, <=3 tokens per image.
All animations use the existing adapter which verifies displayed zero cost.
"""
import fcntl, hashlib, json, os, pwd, shutil, sqlite3, subprocess, time, urllib.request, urllib.parse
from pathlib import Path

ROOT=Path('/opt/relax-codex');BATCH=ROOT/'mountain-backlog-20261122'
DOWNLOADS=Path('/opt/marketplace-analytics/studio-downloads')
STATE=Path('/opt/marketplace-analytics/studio-state')
DATA=Path('/var/lib/relax-factory')
VERSION='2026-11-22-mountain-window-snow-v2'


def read(p,default=None):return json.loads(p.read_text()) if p.exists() else default
def save(p,value):
    tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2));tmp.replace(p)
def run(args,timeout=240,input=None):
    r=subprocess.run(args,input=input,capture_output=True,text=True,timeout=timeout)
    if r.returncode:raise RuntimeError(r.stderr[-1700:])
    return r.stdout
def docker(*args,timeout=240):
    with (ROOT/'cabin-backlog/media-check.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        return run(['docker','exec','relax-factory',*map(str,args)],timeout)
def cp(src,dst):run(['docker','cp',str(src),str(dst)])


def judge(folder,stage,images,prompt,extra=None):
    cached=folder/(stage+'.json')
    if cached.exists():return read(cached)
    identity=hashlib.sha256(str(folder).encode()).hexdigest()[:12]
    user=pwd.getpwnam('relax-codex');workspace=Path('/var/lib/relax-codex/workspace')/('mountain-'+identity+'-'+stage)
    workspace.mkdir(mode=0o700,parents=True,exist_ok=True);os.chown(workspace,user.pw_uid,user.pw_gid)
    args=[]
    for i,image in enumerate(images):
        dst=workspace/(str(i)+image.suffix);shutil.copy2(image,dst);os.chown(dst,user.pw_uid,user.pw_gid);dst.chmod(0o600);args+=['--image',str(dst)]
    properties={'verdict':{'type':'string','enum':['PASS','REJECT','UNCERTAIN']},
                'defects':{'type':'array','items':{'type':'string'}},'limitations':{'type':'string'}}
    properties.update(extra or {})
    schema={'type':'object','additionalProperties':False,'properties':properties,'required':list(properties)}
    save(workspace/'schema.json',schema)
    output=workspace/'verdict.json'
    if not output.exists():
        # One CLI invocation per stage; failed output is a technical hold, not a visual rejection.
        start=workspace/'started.json'
        if start.exists():raise RuntimeError('QC previously started without output; inspect existing run')
        save(start,{'started':time.time(),'version':VERSION})
        run(['systemd-run','--unit=relax-qc-mountain-'+identity+'-'+stage,'--collect','--wait','--pipe',
             '-p','User=relax-codex','-p','WorkingDirectory='+str(workspace),'-p','MemoryMax=512M','-p','CPUQuota=35%',
             '-p','RuntimeMaxSec=240','--setenv=HOME=/var/lib/relax-codex','--setenv=CODEX_HOME=/var/lib/relax-codex/.codex',
             str(ROOT/'release-0.171.0/bin/codex'),'exec','--ephemeral','--skip-git-repo-check','--sandbox','read-only',
             *args,'--output-schema',str(workspace/'schema.json'),'-o',str(output),'Do not use tools. '+prompt],timeout=270)
    result=read(output);save(cached,result);return result


def image_job(job_id):
    with sqlite3.connect('file:'+str(STATE/'jobs.sqlite')+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row;row=db.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
    if not row:raise ValueError('Unknown Banana job')
    return dict(row)


def recover_image(job_id,folder):
    row=image_job(job_id)
    retry=folder/'image-preflight-retry.json'
    if retry.exists():row=image_job(read(retry)['id'])
    elif row['state']=='failed' and row.get('error') in ('SYNTX preparation failed; inspect browser','Browser connection unavailable','Worker stopped before submission'):
        # These explicit states precede the chargeable click; retry the preparation once.
        payload=json.loads(row['payload'])
        if 'Mountain View Cafe' not in payload['prompt']:return row
        code="import json,sys;from jobs import Queue;a=json.load(sys.stdin);print(json.dumps(Queue('/state/jobs.sqlite').create(a['request_id'],a['prompt'],'16:9')))"
        result=json.loads(run(['docker','exec','-i','-e','PYTHONPATH=/app','marketplace-syntx-studio','python','-c',code],
            input=json.dumps({'request_id':'mountain-preflight-retry-'+job_id,'prompt':payload['prompt']})))
        save(retry,{'id':result['id'],'previous':job_id,'reason':'explicit_failure_before_submission'});row=image_job(result['id'])
    job_id=row['id']
    if row['state']!='uncertain':return row
    marker=folder/'image-recovery.json';record=read(marker,{'attempts':0})
    if record['attempts']>=3:return row
    save(marker,dict(attempts=record['attempts']+1,job_id=job_id,started=time.time()))
    run(['docker','exec','-e','PYTHONPATH=/app','marketplace-syntx-studio','python',
         '/downloads/recover_mountain_image30.py','--auto',job_id],timeout=600)
    return image_job(job_id)


def recover_video(rid,row):
    """Fetch only the exact already-generated CDN result recorded by the UI."""
    url=urllib.parse.urlsplit(row.get('video_url',''))
    if row.get('state')!='generated_needs_download' or url.scheme!='https' or url.netloc!='r2.syntx.ai':return row
    run(['docker','exec','-e','PYTHONPATH=/app','marketplace-syntx-studio','python','/downloads/recover_mountain_video.py',rid],timeout=300)
    return read(STATE/('runway-'+rid+'.json'))


def replace_source(cfg,folder,defects):
    generation=cfg.get('source_round',0)+1
    if generation>2:
        save(folder/'state.json',{'stage':'held','reason':'bounded_new_images_exhausted','defects':defects});return
    prompt=cfg['image_prompt']+' Keep geometry simple and realistic; matte original hearth, clear glass, minimal reflections.'
    rid=f"mountain{cfg['episode']:02d}-replacement-{generation}-20261122"
    code="import json,sys;from jobs import Queue;q=Queue('/state/jobs.sqlite');a=json.load(sys.stdin);print(json.dumps(q.create(a['request_id'],a['prompt'],'16:9')))"
    result=json.loads(run(['docker','exec','-i','-e','PYTHONPATH=/app','marketplace-syntx-studio','python','-c',code],
                          input=json.dumps({'request_id':rid,'prompt':prompt})))
    child=dict(cfg,request_id=cfg['request_id']+'-s'+str(generation),source_round=generation,image_job_id=result['id'])
    child.pop('source',None)
    save(folder/'replacement-config.json',child)
    save(folder/'state.json',{'stage':'replacing_source','reason':'visual_rejection','defects':defects,'image_job_id':result['id'],'updated':time.time()})


def window_mask(folder,container):
    from window_snow_contract import schema,validate_plan
    docker('python','/tmp/mountain_batch_media.py','window-frames',container)
    for i in range(4):cp('relax-factory:'+container+f'/frame{i}.png',folder/f'frame{i}.png')
    fields={k:v for k,v in schema()['properties'].items() if k not in ('verdict','notes')}
    result=judge(folder,'window-layout',[folder/f'frame{i}.png' for i in range(4)],
        'Annotate safe exterior window glass in these four1280x720 frames of ONE Mountain View cafe animation. Coordinates in native1280x720 pixels. Each individual glass pane needs its own polygon inside its inner edges, excluding all mullions, frame, sill and wall. Foreground polygons cover the FULL silhouettes of every chair back, posts, rails, furniture, plants or other indoor object crossing glass; cover holes in chair backs too, taking the union over frames. Glass is the intersection safe over all four frames. Snow must never cover furniture or frames. Inset_fullhd_px=8. Return3..6 textured rigid interior regions [x,y,width,height], x>=48,y>=27,x+w<=1232,y+h<=693,width24..200,height24..160, away from fire, sky, reflections and snow. No fireplace, flame or interior editing. PASS only if boundaries can be located safely, otherwise UNCERTAIN. The rendered mask is separately checked before any preview delivery.',fields)
    if result['verdict']!='PASS':raise ValueError('Window geometry uncertain; preserve source, no provider retry')
    plan={k:result[k] for k in fields};plan.update(verdict='READY',notes=result['limitations']);validate_plan(plan)
    save(folder/'window-plan.json',plan);cp(folder/'window-plan.json','relax-factory:'+container+'/window-plan.json')
    docker('python','/tmp/mountain_batch_media.py','window-mask',container)
    cp('relax-factory:'+container+'/mask-overlay.png',folder/'mask-overlay.png')
    snow=DATA/'sources/executor-library/assets/Исходники/Little Paris Jazz Cafe/Неделя 3 — 29 ноября–5 декабря/Снег Little Paris — мелкие хлопья — альфа 30 секунд.mkv'
    if not snow.is_file():raise ValueError('Existing approved Snow layer unavailable')
    cp(snow,'relax-factory:'+container+'/external-snow.mkv')


def process(cfg):
    folder=BATCH/cfg['request_id'];folder.mkdir(exist_ok=True)
    status=folder/'state.json';previous=read(status,{})
    if previous.get('stage')=='delivered':return
    if previous.get('stage')=='replacing_source':
        child=read(folder/'replacement-config.json');process(child)
        current=read(BATCH/child['request_id']/'state.json',{})
        if current.get('stage')=='delivered':save(status,dict(current,replacement_request_id=child['request_id']))
        return
    if previous.get('stage')=='held':
        if previous.get('reason') in ('source_image_qc','three_native_videos_exhausted_new_image_required'):
            replace_source(cfg,folder,previous.get('defects',[]))
            return
        if not (cfg.get('image_job_id') and previous.get('reason') in ('uncertain','failed')):return
        if recover_image(cfg['image_job_id'],folder)['state']!='completed':return
    def state(stage,**kw):save(status,dict(stage=stage,updated=time.time(),episode=cfg['episode'],date=cfg['date'],**kw))
    source=folder/'source.jpg'
    if not source.exists():
        if cfg.get('image_job_id'):
            job=recover_image(cfg['image_job_id'],folder)
            if job['state']!='completed':
                state('waiting_image' if job['state'] in ('queued','preparing','submitted') else 'held',reason=job['state']);return
            result=json.loads(job['result']);name=Path(result['file']).name
            src=Path('/opt/marketplace-analytics/assets/studio')/name
            if not src.exists():src=DOWNLOADS/name
            if float(result['cost_tokens'])>3:raise ValueError('Image cost exceeds authorized cap')
            save(folder/'image-receipt.json',result)
        else:src=Path(cfg['source'])
        shutil.copy2(src,source)
    container='/tmp/'+cfg['request_id']
    docker('mkdir','-p',container);cp(source,'relax-factory:'+container+'/source.jpg')
    if not (folder/'source-review.jpg').exists():
        docker('ffmpeg','-nostdin','-v','error','-y','-threads','1','-i',container+'/source.jpg','-vf','scale=1920:1080','-frames:v','1',container+'/source-review.jpg')
        cp('relax-factory:'+container+'/source-review.jpg',folder/'source-review.jpg')
    extra={'rigid_regions':{'type':'array','minItems':3,'maxItems':3,'items':{'type':'array','minItems':4,'maxItems':4,'items':{'type':'integer'}}}}
    state('image_qc')
    q=judge(folder,'image-qc',[folder/'source-review.jpg'],
        'Inspect the new Mountain View Cafe still at exactly1920x1080. A realistic empty mountain cafe, readable snowy mountains, original wood fireplace, plausible furniture and minimal plausible glass reflections. Reject severe malformed geometry, visible indoor particles, people, fake fire inserts or bright window-like hearth reflections. Settled outdoor snow in a still is fine; moving snowfall is checked later. Do not reject a quiet undecorated interior. Return three small rigid interior reference rectangles [x,y,width,height], width30..220,height30..180, fully inside1920x1080, on window frames, stone or furniture edges; avoid sky, snow and fire. These rectangles are measurement crops, never masks. Defects in Russian.',extra)
    if q['verdict']!='PASS':replace_source(cfg,folder,q['defects']);return
    cfg=dict(cfg,rigid_regions=q['rigid_regions']);save(folder/'config.json',cfg);cp(folder/'config.json','relax-factory:'+container+'/config.json')
    feedback=[]
    for attempt in range(1+3*cfg.get('source_round',0),4+3*cfg.get('source_round',0)):
        rid=f"mountain{cfg['episode']:02d}-native-v{attempt}-20261122"
        ledger=STATE/('runway-'+rid+'.json')
        row=read(ledger)
        if row is None:
            shutil.copy2(source,DOWNLOADS/(rid+'.jpg'))
            prompt=cfg['video_prompt']
            if feedback:prompt+=' Specifically keep architecture completely rigid, fixed camera, fine snowfall only behind glass.'
            request={'request_id':rid,'source':'/downloads/'+rid+'.jpg','prompt':prompt,'model':'Gen-4 Turbo'}
            save(DOWNLOADS/(rid+'-request.json'),request)
            state('runway_generation',request_id=rid,cost_tokens=0)
            # Adapter persists BEFORE click and verifies displayed 0 tokens +10s.
            run(['docker','exec','marketplace-syntx-studio','python','/app/runway_prepare.py','--submit','--request','/downloads/'+rid+'-request.json'],timeout=1000)
            row=read(ledger)
        row=recover_video(rid,row)
        if row['state']!='downloaded_needs_qc':
            state('waiting_runway' if row['state']=='submitted' else 'held',request_id=rid,reason=row['state']);return
        attemptdir=folder/('attempt-'+str(attempt));attemptdir.mkdir(exist_ok=True)
        src=DOWNLOADS/(rid+'.mp4');archived=attemptdir/'raw.mp4'
        if not src.exists() and archived.exists():shutil.copy2(archived,src)
        if archived.exists():
            if hashlib.sha256(archived.read_bytes()).digest()!=hashlib.sha256(src.read_bytes()).digest():
                raise ValueError('Frozen native video changed')
        else:shutil.copy2(src,archived)
        cp(src,'relax-factory:'+container+'/raw.mp4')
        try:
            normalization=json.loads(docker('python','/tmp/mountain_batch_media.py','normalize',container,timeout=300))
        except RuntimeError as e:
            if 'Camera movement too large for bounded correction' in str(e):
                save(attemptdir/'normalization-rejection.json',{'reason':str(e)});feedback=['Camera movement exceeds bounded correction'];continue
            raise
        save(attemptdir/'normalization.json',normalization)
        if not (attemptdir/'stable-source-contact.png').exists():
            docker('python','/tmp/mountain_batch_media.py','source-sheet',container)
            cp('relax-factory:'+container+'/source-contact.png',attemptdir/'stable-source-contact.png')
        state('video_qc',request_id=rid)
        q=judge(attemptdir,'stable-video-qc-v2',[folder/'source-review.jpg',attemptdir/'stable-source-contact.png'],
            'Compare the source still and chronological20 frames of the actual10-second Mountain View animation after bounded camera correction. Small CONSTANT framing crop versus still is allowed. Judge source integrity: fixed camera, rigid room/mountains, natural original flames, no indoor snow, moving furniture, focus breathing, geometric deformation or strong new reflections. Tiny flame shadows and subpixel shimmer allowed. PASS means this physical source is suitable for assembly, NOT finished preview approval. Separately report outdoor_snow=VISIBLE/ABSENT/UNCERTAIN based on falling flakes, not settled snow. ABSENT or UNCERTAIN exterior snowfall ALONE must not reject a sound physical source: the assembler can add the existing Snow layer behind separately checked glass masks. Indoor flakes remain a real source defect. Mark actual object/camera defects REJECT; unclear source integrity UNCERTAIN. Russian defects, no invented history.',
            {'outdoor_snow':{'type':'string','enum':['VISIBLE','ABSENT','UNCERTAIN']}})
        if q['verdict']!='PASS':feedback=q['defects'];continue
        snow_needed=q['outdoor_snow']!='VISIBLE'
        if snow_needed:window_mask(attemptdir,container)
        shutil.copy2(ROOT/'assets/cabin-approved-fireplace-9.wav',folder/'audio.wav')
        cp(folder/'audio.wav','relax-factory:'+container+'/audio.wav')
        for fade in (6,3,0):
            # Different source attempts must never reuse an older render.
            attemptcontainer=container+'-a'+str(attempt)+('-snow' if snow_needed else '')
            docker('mkdir','-p',attemptcontainer)
            for name in ('source.mp4','audio.wav','config.json'):docker('cp',container+'/'+name,attemptcontainer+'/'+name)
            if snow_needed:
                for name in ('mask.png','window-plan.json','external-snow.mkv'):docker('cp',container+'/'+name,attemptcontainer+'/'+name)
            state('assembly_qc',request_id=rid,fade_frames=fade)
            technical=json.loads(docker('python','/tmp/mountain_batch_media.py','build',attemptcontainer,'--fade',str(fade),timeout=600))
            docker('python','/tmp/mountain_batch_media.py','preview-sheet',attemptcontainer,'--fade',str(fade),timeout=180)
            names=[f'preview-{fade}-'+suffix+'.png' for suffix in ('contact','seam','rigid')]
            for name in names:cp('relax-factory:'+attemptcontainer+'/'+name,attemptdir/name)
            q=judge(attemptdir,'assembly-'+str(fade)+('-snow' if snow_needed else ''),[attemptdir/name for name in names]+([attemptdir/'mask-overlay.png'] if snow_needed else []),
                'Inspect the finished30-second Mountain View preview. Image1 chronological20 frames across30s. Image2 twelve consecutive frames centered on the actual cyclic wrap, labeledframe numbers. Image3 three rows of twelve native-scale rigid-region crops around the same seam. Optional image4 is the diagnostic pink window Snow mask, not actual pink content. Require Snow only behind glass, mask avoiding whole furniture silhouettes and all wooden frames. Require VISIBLE fine falling exterior snow, fixed frames/furniture/mountains and original natural fire. Reject visible jump, doubled furniture, ghosting, blur at seam, residual zoom/reset, Snow on frames/chairs or other indoor objects, deformation. Tiny texture shimmer allowed. Do not infer prior failures. PASS only for sound exact assembly samples; UNCERTAIN blocks delivery. Audio measured separately against approved fireplace reference; do not claim listening. Defects in Russian.')
            if q['verdict']!='PASS':continue
            ready=dict(technical,**{'pass':True,'visual_qc':q,'request_id':rid,'sampled_visual_review':True,'owner_approval_required':True})
            save(folder/'ready.json',ready);cp(folder/'ready.json','relax-factory:'+attemptcontainer+'/ready.json')
            for name in (f'preview-{fade}.mp4',f'master-{fade}.mp4'):
                cp('relax-factory:'+attemptcontainer+'/'+name,folder/name)
            state('sending_checked_preview',request_id=rid)
            result=json.loads(docker('python','/tmp/mountain_batch_media.py','deliver',attemptcontainer,'--fade',str(fade)))
            if result['stage']!='telegram_requested':state('held',reason='delivery_uncertain',delivery=result);return
            save(folder/'delivery.json',result);state('delivered',job_id=result['job_id'],preview_sha256=result['preview_sha256']);return
        feedback=['Final assembly did not pass; do not accept a blurred or jumping loop']
    replace_source(cfg,folder,feedback)


def main():
    BATCH.mkdir(exist_ok=True)
    with (BATCH/'worker.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        cp(ROOT/'mountain_batch_media.py','relax-factory:/tmp/mountain_batch_media.py')
        cp(ROOT/'window_snow_contract.py','relax-factory:/tmp/window_snow_contract.py')
        for cfg in read(BATCH/'plan.json'):
            try:process(cfg)
            except Exception as e:
                folder=BATCH/cfg['request_id'];folder.mkdir(exist_ok=True)
                save(folder/'state.json',{'stage':'held','reason':'technical_failure_no_blind_retry','error':str(e)[-1700:],'updated':time.time()})
                print(json.dumps({'episode':cfg['episode'],'error':str(e)[-300:]}),flush=True)


if __name__=='__main__':main()
