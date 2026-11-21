"""Compare raw and assembled evidence once per immutable failed version."""
import argparse,hashlib,json,os,pwd,shutil,subprocess
from pathlib import Path
import cabin_backlog_registry as registry
from cabin_failure_routing import evidence_key
ROOT=Path('/opt/relax-codex')


def run(args,**kw):return subprocess.run(args,check=True,capture_output=True,text=True,**kw)


def main(rid):
    if not registry.attempt(rid):raise ValueError('Exact Cabin attempt required')
    folder=ROOT/'assets'/rid;source=Path('/opt/marketplace-analytics/studio-downloads')/(rid+'.mp4')
    pipeline=json.loads((folder/'pipeline.json').read_text())
    key=evidence_key(hashlib.sha256(source.read_bytes()).hexdigest(),
        hashlib.sha256((folder/'preview.mp4').read_bytes()).hexdigest(),pipeline.get('defects',[]))
    cached=folder/'failure-stage-comparison.json'
    if cached.exists():
        value=json.loads(cached.read_text())
        if value['evidence_key']!=key:raise ValueError('Evidence changed under frozen comparison')
        print(json.dumps(value,ensure_ascii=False));return
    prefix='/tmp/'+rid;run(['docker','exec','relax-factory','mkdir','-p',prefix])
    for src,name in [(source,'source.mp4'),(folder/'preview.mp4','preview.mp4')]:
        run(['docker','cp',str(src),'relax-factory:'+prefix+'/'+name])
    geo=registry.geometry(rid);detail=geo['detail_crop'];snow=geo['snow_crop']
    names=[]
    for kind,seconds in [('source',10),('preview',30)]:
        filters={kind+'-whole':f'fps={20/seconds},scale=640:-1,tile=5x4',
                 kind+'-detail':f'fps={60/seconds},scale=1280:720,crop={detail},scale=300:-1,tile=6x10',
                 kind+'-snow':'select=between(n\\,48\\,59)+between(n\\,120\\,131)+between(n\\,192\\,203),scale=1280:720,crop='+snow+',tile=6x6'}
        for name,flt in filters.items():
            run(['docker','exec','relax-factory','ffmpeg','-nostdin','-v','error','-y','-threads','1','-i',prefix+'/'+kind+'.mp4',
                 '-vf',flt,'-frames:v','1','-threads','1',prefix+'/'+name+'.jpg'])
            run(['docker','cp','relax-factory:'+prefix+'/'+name+'.jpg',str(folder/(name+'.jpg'))]);names.append(name)
    user=pwd.getpwnam('relax-codex');w=Path('/var/lib/relax-codex/workspace')/(rid+'-stage-comparison')
    w.mkdir(exist_ok=True,mode=0o700);os.chown(w,user.pw_uid,user.pw_gid)
    for name in names:
        target=w/(name+'.jpg');shutil.copy2(folder/target.name,target);os.chown(target,user.pw_uid,user.pw_gid);target.chmod(0o600)
    schema={'type':'object','additionalProperties':False,'properties':{
        'route':{'type':'string','enum':['SOURCE_REGENERATE','ASSEMBLY_REPAIR','UNCERTAIN']},
        'evidence':{'type':'string'},'source_defects':{'type':'array','items':{'type':'string'}}},
        'required':['route','evidence','source_defects']}
    (w/'schema.json').write_text(json.dumps(schema))
    prompt=('Do not use tools. Diagnose where the SAME defect was introduced; do not approve a video. '
        'The first three images show the raw source: 20 whole frames, 60 hearth/cat details, then 36 native window crops. '
        'The last three show the assembled 30-second preview in the same order. Window sheets contain three half-second bursts '
        'of consecutive frames 48-59, 120-131,192-203 at 24 fps, six columns. Compare falling flakes against static snow texture. '
        'Route SOURCE_REGENERATE only with concrete visible evidence of the reported defect in the raw source, '
        'and list only those proven raw defects in source_defects. A bad assembled preview alone never justifies a generation. '
        'Route ASSEMBLY_REPAIR when raw framing/objects are suitable but the assembled preview introduces double edges, '
        'loop ghosts, jumps or new distortions. Mild raw camera drift that can be stabilized is ASSEMBLY_REPAIR, not a reason '
        'to regenerate. Route UNCERTAIN when samples do not establish the cause; do not guess. Tiny texture shimmer and '
        'natural flame light are allowed. Give evidence in Russian. Known final defects: '+json.dumps(pipeline.get('defects',[]),ensure_ascii=False))
    with cached.open('x') as reserved:
        json.dump({'evidence_key':key,'route':'UNCERTAIN','state':'comparison_started',
            'source_defects':[],'evidence':'Comparison reserved; an interrupted run is not repeated automatically'},reserved)
    run(['systemd-run','--unit=relax-stage-compare-'+rid,'--collect','--wait','--pipe','-p','User=relax-codex',
         '-p','WorkingDirectory='+str(w),'-p','MemoryMax=512M','-p','CPUQuota=25%','-p','RuntimeMaxSec=180',
         '--setenv=HOME=/var/lib/relax-codex','--setenv=CODEX_HOME=/var/lib/relax-codex/.codex',
         '/opt/relax-codex/release-0.171.0/bin/codex','exec','--ephemeral','--skip-git-repo-check','--sandbox','read-only',
         *[arg for name in names for arg in ['--image',str(w/(name+'.jpg'))]],
         '--output-schema',str(w/'schema.json'),'-o',str(w/'result.json'),prompt],timeout=210)
    value=json.loads((w/'result.json').read_text());value['evidence_key']=key;value['state']='completed'
    if value['route']=='SOURCE_REGENERATE' and not value['source_defects']:value['route']='UNCERTAIN'
    temp=cached.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2));temp.replace(cached);print(json.dumps(value,ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('request_id');main(p.parse_args().request_id)
