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
VERSION='2026-11-22-mountain-native-batch-v1'


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
        if not (cfg.get('image_job_id') and previous.get('reason') in ('uncertain','failed')
                and image_job(cfg['image_job_id'])['state']=='completed'):
            return
    def state(stage,**kw):save(status,dict(stage=stage,updated=time.time(),episode=cfg['episode'],date=cfg['date'],**kw))
    source=folder/'source.jpg'
    if not source.exists():
        if cfg.get('image_job_id'):
            job=image_job(cfg['image_job_id'])
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
        src=DOWNLOADS/(rid+'.mp4');cp(src,'relax-factory:'+container+'/raw.mp4')
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
        q=judge(attemptdir,'stable-video-qc',[folder/'source-review.jpg',attemptdir/'stable-source-contact.png'],
            'Compare the source still and chronological20 frames from the actual10-second Mountain View animation after bounded whole-frame camera correction (5columns). A small constant framing crop versus the source is permitted. Require a locked camera and rigid room/mountains, natural existing fireplace flames, visible moving fine snowfall OUTSIDE every pane only. No indoor snow, moving furniture, invented objects, focus breathing, geometric deformation or strong new reflections. Natural tiny flame shadows and subpixel shimmer allowed. Reject residual noticeable camera zoom, unstable correction or clearly static/absent snowfall; mark UNCERTAIN if sample evidence insufficient. A PASS here only permits testing the final loop; does not approve assembly or audio. Give concrete defects in Russian, no invented history.')
        if q['verdict']!='PASS':feedback=q['defects'];continue
        shutil.copy2(ROOT/'assets/cabin-approved-fireplace-9.wav',folder/'audio.wav')
        cp(folder/'audio.wav','relax-factory:'+container+'/audio.wav')
        for fade in (6,3,0):
            # Different source attempts must never reuse an older render.
            attemptcontainer=container+'-a'+str(attempt)
            docker('mkdir','-p',attemptcontainer)
            for name in ('source.mp4','audio.wav','config.json'):docker('cp',container+'/'+name,attemptcontainer+'/'+name)
            state('assembly_qc',request_id=rid,fade_frames=fade)
            technical=json.loads(docker('python','/tmp/mountain_batch_media.py','build',attemptcontainer,'--fade',str(fade),timeout=600))
            docker('python','/tmp/mountain_batch_media.py','preview-sheet',attemptcontainer,'--fade',str(fade),timeout=180)
            names=[f'preview-{fade}-'+suffix+'.png' for suffix in ('contact','seam','rigid')]
            for name in names:cp('relax-factory:'+attemptcontainer+'/'+name,attemptdir/name)
            q=judge(attemptdir,'assembly-'+str(fade),[attemptdir/name for name in names],
                'Inspect the finished30-second Mountain View preview. Image1 chronological20 frames across30s. Image2 twelve consecutive frames centered on the actual cyclic wrap, labeledframe numbers. Image3 three rows of twelve native-scale rigid-region crops around the same seam. Require visible fine exterior snowfall only, fixed frames/furniture/mountains and native natural fire. Reject visible jump, doubled furniture, ghosting or blur at the seam, camera pullback/reset, indoor flakes or visual deformation. Tiny texture shimmer is allowed. Do not infer prior failures. PASS only when these exact assembly samples look sound; UNCERTAIN blocks delivery. Audio is separately measured against the owner-approved fireplace reference, do not claim listening. Defects in Russian.')
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
        for cfg in read(BATCH/'plan.json'):
            try:process(cfg)
            except Exception as e:
                folder=BATCH/cfg['request_id'];folder.mkdir(exist_ok=True)
                save(folder/'state.json',{'stage':'held','reason':'technical_failure_no_blind_retry','error':str(e)[-1700:],'updated':time.time()})
                print(json.dumps({'episode':cfg['episode'],'error':str(e)[-300:]}),flush=True)


if __name__=='__main__':main()
