"""Resolve uncertain fine snowfall from small, lossless native-scale bursts once."""
import argparse,hashlib,json,os,pwd,shutil,subprocess
from pathlib import Path
import cabin_backlog_registry as registry
ROOT=Path('/opt/relax-codex')


def run(args,**kw):return subprocess.run(args,check=True,capture_output=True,text=True,**kw)


def main(rid,kind):
    if kind not in ('source','preview') or not registry.attempt(rid):raise ValueError('Unsupported Snow evidence')
    folder=ROOT/'assets'/rid
    media=folder/'preview.mp4' if kind=='preview' else Path('/opt/marketplace-analytics/studio-downloads')/(rid+'.mp4')
    digest=hashlib.sha256(media.read_bytes()).hexdigest();cached=folder/('snow-detail-'+kind+'.json')
    if cached.exists():
        value=json.loads(cached.read_text())
        if value['media_sha256']!=digest:raise ValueError('Media changed under a frozen Snow review')
        print(json.dumps(value,ensure_ascii=False));return
    prefix='/data/sources/cabin-qa/'+rid;run(['docker','exec','relax-factory','mkdir','-p',prefix])
    run(['docker','cp',str(media),'relax-factory:'+prefix+'/'+kind+'.mp4'])
    crop=registry.geometry(rid)['snow_crop'];user=pwd.getpwnam('relax-codex')
    w=Path('/var/lib/relax-codex/workspace')/(rid+'-snow-detail-'+kind);w.mkdir(exist_ok=True,mode=0o700);os.chown(w,user.pw_uid,user.pw_gid)
    images=[]
    for i,start in enumerate([48,96,144],1):
        name=f'{kind}-snow-native-{i}.png'
        flt=f'fps=24,select=between(n\\,{start}\\,{start+11}),scale=1280:720,crop={crop},tile=4x3'
        run(['docker','exec','relax-factory','ffmpeg','-nostdin','-v','error','-y','-threads','1','-filter_threads','1',
             '-i',prefix+'/'+kind+'.mp4','-vf',flt,'-frames:v','1','-threads','1',prefix+'/'+name])
        run(['docker','cp','relax-factory:'+prefix+'/'+name,str(w/name)])
        os.chown(w/name,user.pw_uid,user.pw_gid);(w/name).chmod(0o600);images.append(str(w/name))
    schema={'type':'object','additionalProperties':False,'properties':{
        'outdoor_snow':{'type':'string','enum':['VISIBLE','ABSENT','UNCERTAIN']},
        'evidence':{'type':'string'}},'required':['outdoor_snow','evidence']}
    (w/'schema.json').write_text(json.dumps(schema))
    prompt=('Do not use tools. Assess only falling exterior snow in these lossless native-scale window crops. '
        'There are three separate sheets, each four columns by three rows, ordered left to right then down. '
        'Sheet one shows consecutive frames 48-59 (2 seconds); sheet two frames 96-107 (4 seconds); '
        'sheet three frames 144-155 (6 seconds), at 24 fps. The sheets are deliberately small enough to preserve '
        'fine low-contrast flakes; do not treat a static snowy landscape as falling snow. '
        'VISIBLE requires identifiable flakes changing position between adjacent frames within at least one burst. '
        'ABSENT requires a clearly static snowy view without falling flakes. Choose UNCERTAIN if not established. '
        'Fine small flakes and natural perspective-related intensity differences are permitted. '
        'Do not reject solely because flakes are small or pale, but do not infer falling snow from texture shimmer. '
        'Give concise evidence in Russian, citing the sheet/row and visible motion if VISIBLE. Do not discuss cat, '
        'camera, sound or approval: those have separate checks.')
    with cached.open('x') as reserved:json.dump({'media_sha256':digest,'outdoor_snow':'UNCERTAIN','state':'review_started','evidence':'Reserved, no automatic duplicate model call'},reserved)
    run(['systemd-run','--unit=relax-snow-detail-'+kind+'-'+rid,'--collect','--wait','--pipe',
         '-p','User=relax-codex','-p','WorkingDirectory='+str(w),'-p','MemoryMax=512M','-p','CPUQuota=25%','-p','RuntimeMaxSec=180',
         '--setenv=HOME=/var/lib/relax-codex','--setenv=CODEX_HOME=/var/lib/relax-codex/.codex',
         '/opt/relax-codex/release-0.171.0/bin/codex','exec','--ephemeral','--skip-git-repo-check','--sandbox','read-only',
         *[arg for image in images for arg in ['--image',image]],'--output-schema',str(w/'schema.json'),'-o',str(w/'result.json'),prompt],timeout=210)
    value=json.loads((w/'result.json').read_text());value.update(media_sha256=digest,state='completed',review='native-lossless-bursts-v1',kind=kind)
    temp=cached.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2));temp.replace(cached)
    print(json.dumps(value,ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('request_id');p.add_argument('--kind',choices=['source','preview'],required=True)
    a=p.parse_args();main(a.request_id,a.kind)
