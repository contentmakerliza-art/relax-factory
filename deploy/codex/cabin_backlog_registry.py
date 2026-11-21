"""Exact allowlist and scene-specific measurement geometry for the Nov 21 Cabin backlog.

Editing masks are forbidden. Rectangles below only select pixels for QA.
"""
import hashlib,json,os,pwd,shutil,subprocess
from pathlib import Path

ROOT=Path('/opt/relax-codex')
REGISTRY=ROOT/'cabin-backlog/registry.json'

class SourceRejected(ValueError):pass

def records():
    path=REGISTRY if REGISTRY.exists() else Path('/tmp/cabin-backlog/registry.json')
    return json.loads(path.read_text())

def group(value):
    return any(r['request_group']==value for r in records())

def entry(rid,job=None):
    parent=rid.replace('-clean-','-fullframe-').replace('-fixed-','-fullframe-')
    for row in records():
        if job is not None and row['request_group']!=job:continue
        for index,source in enumerate(row['sources']):
            if parent in source['attempts']:return row,index
    return None

def attempt(rid,job=None):
    return entry(rid,job) is not None

def validate_box(box):
    if not isinstance(box,list) or len(box)!=4 or any(type(v) is not int for v in box):
        raise ValueError('Invalid measurement rectangle')
    x,y,w,h=box
    if not (3<=x and 3<=y and w>=12 and h>=12 and x+w<=1277 and y+h<=717):
        raise ValueError('Measurement rectangle outside frame')
    return box

def geometry(rid):
    if not attempt(rid):raise ValueError('Request not in frozen backlog')
    path=ROOT/'assets'/rid/'geometry.json'
    if not path.exists():path=Path('/tmp')/rid/'geometry.json'
    value=json.loads(path.read_text())
    if value['verdict']!='NEEDS_VIDEO_TEST':raise ValueError('Source QC rejected')
    for box in value['regions'].values():validate_box(box)
    return value

def run(args,timeout=900):
    return subprocess.run(args,check=True,capture_output=True,text=True,stdin=subprocess.DEVNULL,timeout=timeout)

def stage_geometry(rid,value):
    target=ROOT/'assets'/rid;target.mkdir(exist_ok=True)
    (target/'geometry.json').write_text(json.dumps(value,ensure_ascii=False,indent=2))
    run(['docker','exec','relax-factory','mkdir','-p','/tmp/'+rid,'/tmp/cabin-backlog'])
    for src,dst in [(target/'geometry.json','/tmp/'+rid+'/geometry.json'),
        (Path(__file__),'/tmp/cabin_backlog_registry.py'),(REGISTRY,'/tmp/cabin-backlog/registry.json')]:
        run(['docker','cp',str(src),'relax-factory:'+dst])

def prepare_geometry(job,index,source):
    row=next(r for r in records() if r['request_group']==job)
    expected=row['sources'][index]
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    if expected.get('source_sha256') and digest!=expected['source_sha256']:
        raise ValueError('Staged image changed')
    folder=ROOT/'cabin-backlog/geometry';folder.mkdir(exist_ok=True)
    cache=folder/(digest+'.json')
    if cache.exists():value=json.loads(cache.read_text())
    else:
        user=pwd.getpwnam('relax-codex')
        w=Path('/var/lib/relax-codex/workspace')/(job+'-source-'+str(index));w.mkdir(mode=0o700,exist_ok=True)
        os.chown(w,user.pw_uid,user.pw_gid)
        run(['docker','cp',str(source),'relax-factory:/tmp/'+job+'-plate.jpg'])
        run(['docker','exec','relax-factory','ffmpeg','-nostdin','-v','error','-y','-i','/tmp/'+job+'-plate.jpg',
            '-vf','scale=1280:720','-frames:v','1','-threads','1','/tmp/'+job+'-plate.png'])
        run(['docker','cp','relax-factory:/tmp/'+job+'-plate.png',str(w/'source.png')])
        os.chown(w/'source.png',user.pw_uid,user.pw_gid)
        box={'type':'array','items':{'type':'integer'},'minItems':4,'maxItems':4}
        schema={'type':'object','additionalProperties':False,'properties':{
          'verdict':{'type':'string','enum':['REJECT','NEEDS_VIDEO_TEST']},
          'defects':{'type':'array','items':{'type':'string'}},
          'regions':{'type':'object','additionalProperties':False,'properties':{k:box for k in ['head','paws','wall','flank']},'required':['head','paws','wall','flank']},
          'detail_box':box,'snow_box':box,'limitations':{'type':'string'}},
          'required':['verdict','defects','regions','detail_box','snow_box','limitations']}
        (w/'schema.json').write_text(json.dumps(schema))
        prompt=('Do not use tools. Inspect the attached exact 1280x720 source photo for Quiet Pines Cabin. '
          'Reject malformed cat/furniture, awake cat, unsupported floating head, inserted/double fireplace, '
          'a window reflected inside the firebox, indoor snow particles, or unreadable winter view. '
          'Absence of falling snow in a still plate is allowed; Runway will animate outdoor snow. '
          'If source is usable choose NEEDS_VIDEO_TEST, not owner approval. '
          'Annotate precise QA rectangles in this 1280x720 image: [x,y,width,height]. '
          'head encloses visible face/ears (exclude moving flame); paws visible paws or supported chin region; '
          'flank cat torso where barely perceptible breathing is allowed; wall textured solid indoor wall excluding flames, windows, cat. '
          'Do not put head or paws boxes on empty furniture. Boxes must be at least 12x12 pixels and 3 pixels inside frame. '
          'detail_box includes fireplace AND cat for closeup motion sampling. snow_box encloses a large clear visible window view '
          '(coordinates also in 1280x720). These are QA crops ONLY, never editing masks. '
          'Give concrete defects in Russian, and honestly describe uncertainty.')
        run(['systemd-run','--unit=relax-layout-'+job+'-'+str(index),'--collect','--wait','--pipe',
          '-p','User=relax-codex','-p','WorkingDirectory='+str(w),'-p','MemoryMax=512M','-p','CPUQuota=25%',
          '-p','RuntimeMaxSec=240','--setenv=HOME=/var/lib/relax-codex','--setenv=CODEX_HOME=/var/lib/relax-codex/.codex',
          '/opt/relax-codex/release-0.171.0/bin/codex','exec','--ephemeral','--skip-git-repo-check','--sandbox','read-only',
          '--image',str(w/'source.png'),'--output-schema',str(w/'schema.json'),'-o',str(w/'qc.json'),prompt],timeout=270)
        value=json.loads((w/'qc.json').read_text())
        for boxvalue in [*value['regions'].values(),value['detail_box'],value['snow_box']]:validate_box(boxvalue)
        for key,boxkey in [('detail_crop','detail_box'),('snow_crop','snow_box')]:
            x,y,width,height=value[boxkey];value[key]=f'{width}:{height}:{x}:{y}'
        value.update(source_sha256=digest,coordinate_size=[1280,720],editing_masks=False)
        cache.write_text(json.dumps(value,ensure_ascii=False,indent=2))
    if value['verdict']=='REJECT':raise SourceRejected('Source rejected: '+str(value['defects']))
    for rid in expected['attempts']:
        stage_geometry(rid,value);stage_geometry(rid.replace('-fullframe-','-clean-'),value)
    return value
