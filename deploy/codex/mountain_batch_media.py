"""Container-side media and delivery for the explicitly staged Mountain backlog.

No generation, approval changes, long render, or publication. Native full-frame
fire and snow only. Preserve a cyclic master for later exact-version rendering.
"""
import argparse, base64, hashlib, json, math, os, subprocess, urllib.parse, urllib.request
from pathlib import Path


def normalize(folder):
    """Bounded factory camera correction on the whole scene, never local fire masks."""
    import sys
    sys.path.insert(0,'/app')
    from render import engine,zoomfix
    raw=folder/'raw.mp4';output=folder/'source.mp4';marker=folder/'normalization.json'
    digest=hashlib.sha256(raw.read_bytes()).hexdigest()
    if marker.exists():
        old=json.loads(marker.read_text())
        if old['raw_sha256']==digest and output.exists() and old['normalized_sha256']==hashlib.sha256(output.read_bytes()).hexdigest():return old
    measurement=zoomfix._measure(raw,'')
    if measurement:
        indices,values=measurement
        if (max(v[0] for v in values)/min(v[0] for v in values)>1.08 or
                max(abs(v[1]) for v in values)>7.2 or max(abs(v[2]) for v in values)>12.8):
            raise ValueError('Camera movement too large for bounded correction')
        top=max(v[0] for v in values)
        zoom=zoomfix._perspective(zoomfix._ramp(indices,[top/v[0] for v in values]),
             zoomfix._ramp(indices,[v[2]/320 for v in values]),zoomfix._ramp(indices,[v[1]/180 for v in values]))
    else:zoom=''
    original=engine._run
    def limited(args):
        if args[0]=='ffmpeg':args=args[:1]+['-nostdin','-threads','1','-filter_threads','1','-filter_complex_threads','1']+args[1:-1]+['-threads','2']+args[-1:]
        return original(args)
    engine._run=limited
    tmp=folder/'normalized.partial.mp4'
    engine._normalized_clip(raw,tmp,engine.RenderSettings(width=1280,height=720,fps=24,stabilize=True,smooth=False,codec='work'),zoom=zoom)
    tmp.replace(output)
    value={'raw_sha256':digest,'normalized_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
           'camera_fit':measurement,'whole_frame_only':True,'fire_masks':False}
    marker.write_text(json.dumps(value));return value


def run(*args):
    result=subprocess.run(list(args),capture_output=True,text=True,stdin=subprocess.DEVNULL)
    if result.returncode:raise RuntimeError(result.stderr[-2500:])
    return result.stdout


def probe(path):
    return json.loads(run('ffprobe','-v','error','-show_streams','-of','json',str(path)))['streams']


def build(folder, fade_frames):
    source=folder/'source.mp4'
    stream=next(s for s in probe(source) if s['codec_type']=='video')
    n=min(240, math.floor(float(stream['duration'])*24+.01))
    if n<192: raise ValueError('Need at least eight native seconds')
    if fade_frames not in (6,3,0): raise ValueError('Unexpected seam option')
    master=folder/('master-'+str(fade_frames)+'.mp4')
    if not master.exists():
        graph=f'[0:v]fps=24,trim=end_frame={n},settb=1/24,setpts=N,setsar=1,format=yuv420p'
        if fade_frames:
            graph+=f',trim=start_frame={fade_frames},setpts=PTS-STARTPTS,fps=24[tail];[1:v]fps=24,trim=end_frame={fade_frames},settb=1/24,setpts=N,setsar=1,format=yuv420p,fps=24[head];[tail][head]xfade=duration={fade_frames/24}:offset={(n-2*fade_frames)/24}'
        graph+=',scale=1920:1080:flags=lanczos,format=yuv420p[v]'
        tmp=master.with_suffix('.partial.mp4')
        inputs=['-threads','1','-i',str(source)]
        if fade_frames:inputs+=['-threads','1','-i',str(source)]
        run('ffmpeg','-nostdin','-v','error','-y',*inputs,
            '-filter_complex_threads','1','-filter_complex',graph,'-map','[v]',
            '-an','-c:v','libx264','-threads','2','-preset','fast','-crf','17',str(tmp))
        tmp.replace(master)
    preview=folder/('preview-'+str(fade_frames)+'.mp4')
    if not preview.exists():
        tmp=preview.with_suffix('.partial.mp4')
        run('ffmpeg','-nostdin','-v','error','-y','-threads','1','-stream_loop','-1',
            '-i',str(master),'-i',str(folder/'audio.wav'),'-t','30','-map','0:v:0',
            '-map','1:a:0','-c:v','libx264','-threads','2','-preset','fast','-crf','17','-r','24','-frames:v','720',
            '-c:a','aac','-b:a','192k','-movflags','+faststart',str(tmp))
        run('ffmpeg','-nostdin','-v','error','-threads','1','-i',str(tmp),'-f','null','-')
        tmp.replace(preview)
    streams=probe(preview)
    v=next(s for s in streams if s['codec_type']=='video');a=next(s for s in streams if s['codec_type']=='audio')
    if (v['width'],v['height'],v['r_frame_rate'])!=(1920,1080,'24/1'): raise ValueError('Invalid video format')
    if any(abs(float(s['duration'])-30)>.06 for s in (a,v)): raise ValueError('Invalid preview duration')
    import numpy as np
    raw=subprocess.run(['ffmpeg','-nostdin','-v','error','-threads','1','-i',str(preview),
        '-vn','-ac','1','-ar','12000','-f','f32le','-'],check=True,capture_output=True).stdout
    samples=np.frombuffer(raw,dtype='<f4')
    ref=subprocess.run(['ffmpeg','-nostdin','-v','error','-threads','1','-i',str(folder/'audio.wav'),
        '-t','30','-vn','-ac','1','-ar','12000','-f','f32le','-'],check=True,capture_output=True).stdout
    ref=np.frombuffer(ref,dtype='<f4');length=min(len(ref),len(samples));corr=float(np.corrcoef(ref[:length],samples[:length])[0,1])
    if not corr>.98 or float(np.max(np.abs(samples)))>.999 or float(np.sqrt(np.mean(samples**2)))<.0005:
        raise ValueError('Audio identity, clipping or silence check failed')
    report={'technical_pass':True,'audio_correlation':corr,'audio_source_sha256':hashlib.sha256((folder/'audio.wav').read_bytes()).hexdigest(),
            'native_frames':n,'fade_frames':fade_frames,'master_frames':n-fade_frames,'seconds':30,
            'preview_sha256':hashlib.sha256(preview.read_bytes()).hexdigest(),'master_sha256':hashlib.sha256(master.read_bytes()).hexdigest(),
            'audio_note':'Approved fireplace reference checked by correlation, no claim of human listening'}
    (folder/('technical-'+str(fade_frames)+'.json')).write_text(json.dumps(report))
    return report


def sheets(folder, source, prefix, seam_frame=None, regions=None):
    from PIL import Image, ImageDraw
    if seam_frame is None:
        run('ffmpeg','-nostdin','-v','error','-y','-threads','1','-i',str(source),
            '-vf','fps=2,scale=640:-1,tile=5x4','-frames:v','1','-threads','1',str(folder/(prefix+'-contact.png')))
        return
    first=max(0,seam_frame-6)
    raw=subprocess.run(['ffmpeg','-nostdin','-v','error','-threads','1','-i',str(source),
        '-vf',f'select=between(n\\,{first}\\,{first+11})','-vsync','0','-frames:v','12',
        '-pix_fmt','rgb24','-f','rawvideo','-'],capture_output=True,check=True).stdout
    framebytes=1920*1080*3
    if len(raw)!=12*framebytes: raise ValueError('Incomplete seam burst')
    frames=[Image.frombytes('RGB',(1920,1080),raw[i*framebytes:(i+1)*framebytes]) for i in range(12)]
    sheet=Image.new('RGB',(6*480,2*290),'#111111');draw=ImageDraw.Draw(sheet)
    for i,f in enumerate(frames):
        x=i%6*480;y=i//6*290;sheet.paste(f.resize((480,270)),(x,y));draw.text((x,y+271),str(first+i),fill='white')
    sheet.save(folder/(prefix+'-seam.png'))
    regions=regions or [[600,400,200,180],[900,600,200,180],[1450,650,200,180]]
    crops=Image.new('RGB',(12*220,len(regions)*205),'#111111');draw=ImageDraw.Draw(crops)
    for row,(x,y,w,h) in enumerate(regions):
        if not 0<=x<x+w<=1920 or not 0<=y<y+h<=1080 or not 30<=w<=220 or not 30<=h<=180:
            raise ValueError('Invalid rigid crop')
        for i,f in enumerate(frames):
            crops.paste(f.crop((x,y,x+w,y+h)),(i*220,row*205));draw.text((i*220,row*205+181),str(first+i),fill='white')
    crops.save(folder/(prefix+'-rigid.png'))


def call(path,method='GET',data=None):
    auth=base64.b64encode(('relax:'+os.environ['APP_PASSWORD']).encode()).decode()
    req=urllib.request.Request('http://127.0.0.1:8000'+path,data=data,method=method,headers={'Authorization':'Basic '+auth})
    with urllib.request.urlopen(req,timeout=120) as response:return json.load(response)


def deliver(folder, cfg, fade):
    ledger=Path('/data')/('mountain-delivery-'+cfg['request_id']+'.json')
    ready=json.loads((folder/'ready.json').read_text());preview=folder/('preview-'+str(fade)+'.mp4')
    digest=hashlib.sha256(preview.read_bytes()).hexdigest()
    if ledger.exists():
        previous=json.loads(ledger.read_text())
        if previous.get('preview_sha256')!=digest:raise ValueError('Different version already registered; preserve existing delivery')
        return previous
    if not ready.get('pass') or ready['preview_sha256']!=digest:raise ValueError('Exact checked version required')
    def save(**row):ledger.write_text(json.dumps(row));return row
    with ledger.open('x') as f:json.dump({'stage':'creating_job_uncertain'},f)
    jid=call('/jobs/new','POST',b'')['id'];save(stage='uploading',job_id=jid)
    name=f"Mountain View Cafe — {cfg['date']} — {cfg['episode']:02d} {cfg['concept']} — 30 секунд.mp4"
    offset=0
    with preview.open('rb') as f:
        while chunk:=f.read(8*1024*1024):
            call('/jobs/'+jid+'/files/visual/'+urllib.parse.quote(name)+'?offset='+str(offset),'PUT',chunk);offset+=len(chunk)
    call('/jobs/'+jid+'/import-preview','POST',b'')
    jobfolder=Path('/data')/jid
    recipe=dict(cfg,preview_sha256=digest,loop_mode='repeat',loop_master_sha256=ready['master_sha256'],
                audio_sha256=ready['audio_source_sha256'],owner_approval_required=True,long_final_started=False,
                publication_blocker='Mountain View profile is not connected',qa=ready)
    (jobfolder/'mountain-production-recipe.json').write_text(json.dumps(recipe,ensure_ascii=False,indent=2))
    import shutil
    shutil.copy2(folder/('master-'+str(fade)+'.mp4'),jobfolder/'mountain-cyclic-master.mp4')
    shutil.copy2(folder/'audio.wav',jobfolder/'mountain-full-audio.wav')
    save(stage='telegram_submission_uncertain',job_id=jid,preview_sha256=digest)
    call('/jobs/'+jid+'/telegram','POST',b'')
    return save(stage='telegram_requested',job_id=jid,preview_sha256=digest)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['normalize','build','source-sheet','preview-sheet','deliver']);p.add_argument('folder',type=Path);p.add_argument('--fade',type=int,default=6)
    a=p.parse_args();cfg=json.loads((a.folder/'config.json').read_text())
    if a.action=='normalize':print(json.dumps(normalize(a.folder)))
    elif a.action=='build':print(json.dumps(build(a.folder,a.fade)))
    elif a.action=='source-sheet':sheets(a.folder,a.folder/'source.mp4','source')
    elif a.action=='preview-sheet':
        sheets(a.folder,a.folder/f'preview-{a.fade}.mp4',f'preview-{a.fade}')
        t=json.loads((a.folder/f'technical-{a.fade}.json').read_text())
        sheets(a.folder,a.folder/f'preview-{a.fade}.mp4',f'preview-{a.fade}',t['master_frames'],cfg.get('rigid_regions'))
    else:print(json.dumps(deliver(a.folder,cfg,a.fade)))
