import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import cabin_backlog_registry as backlog
"""Automated visual prescreen of a complete 30-second owner preview, not approval."""
import argparse,json,os,pwd,shutil,subprocess,re,time,hashlib
from pathlib import Path
import project_memory
REVIEW_VERSION='2026-11-21-native-snow-bursts-v3'


def run(args,**kw):
    return subprocess.run(args,check=True,capture_output=True,text=True,
                          stdin=subprocess.DEVNULL,**kw)


def main(rid,recheck=False):
    if not backlog.attempt(rid):raise ValueError('Unsupported preview')
    root=Path('/opt/relax-codex/assets')/rid
    memory=project_memory.context('Quiet Pines Cabin',stage='preview_qc',request_id=rid,
                                  request='снег окна кот голова камин склейка')
    result=root/'final-preview-qc.json'
    preview_sha=hashlib.sha256((root/'preview.mp4').read_bytes()).hexdigest()
    if result.exists():
        cached=json.loads(result.read_text())
        if not recheck and cached.get('preview_sha256')==preview_sha and cached.get('review_version')==REVIEW_VERSION:return cached
        history=root/'qa-history';history.mkdir(exist_ok=True)
        shutil.copy2(result,history/f'final-preview-before-native-snow-{time.time_ns()}.json')
    prefix='/data/sources/cabin-qa/'+rid
    # The mounted sources cache survives container recreation between filters.
    run(['docker','exec','relax-factory','mkdir','-p',prefix])
    run(['docker','cp',str(root/'preview.mp4'),'relax-factory:'+prefix+'/preview.mp4'])
    crop=backlog.geometry(rid)['detail_crop']
    snow_crop=backlog.geometry(rid)['snow_crop']
    filters={'preview-contact':'fps=2/3,scale=640:-1,tile=5x4',
             'preview-detail':'fps=2,scale=1280:720,crop='+crop+',scale=300:-1,tile=6x10',
             'preview-snow':'fps=2/3,scale=1280:720,crop='+snow_crop+',tile=4x5',
             'preview-snow-bursts':'select=between(n\\,48\\,59)+between(n\\,120\\,131)+between(n\\,192\\,203),scale=1280:720,crop='+snow_crop+',tile=6x6'}
    screen=root/'media-screen.json'
    if screen.exists():
        value=json.loads(screen.read_text())
        if value['max_adjacent_frame_difference']>5:
            peak=value['max_difference_frame']
            filters['preview-peak']=f'select=between(n\\,{max(0,peak-2)}\\,{peak+2}),scale=640:-1,tile=3x2'
    # Examine the exact worst numerical moments, not only evenly spaced samples.
    numeric=root/'preview-head-motion.json'
    if numeric.exists():
        from motion_policy import moving_regions
        if moving_regions(json.loads(numeric.read_text())):
            saved_traces=root/'preview-motion-traces.json'
            traces=json.loads(saved_traces.read_text()) if saved_traces.exists() else json.loads(run(['docker','exec','relax-factory','cat','/tmp/'+rid+'/preview-motion-traces.json']).stdout)
            frames={0,719};rate=traces['sample_rate']
            for region in ['head','paws','wall']:
                values=traces['positions'][region]
                for axis in [0,1]:
                    extrema=[min(range(len(values)),key=lambda i:values[i][axis]),max(range(len(values)),key=lambda i:values[i][axis])]
                    for index in extrema:
                        center=round((index+.5)*24/rate)
                        frames.update(max(0,min(719,center+delta)) for delta in [-1,0,1])
            frames=sorted(frames)[:24]
            x,y,w,h=backlog.geometry(rid)['regions']['head'];right=min(1280,x+w+20);bottom=min(720,y+h+20);x=max(0,x-20);y=max(0,y-20);w=right-x;h=bottom-y
            select='+'.join('eq(n\\,'+str(n)+')' for n in frames)
            filters['preview-motion']=f'select={select},scale=1280:720,crop={w}:{h}:{x}:{y},scale={w*3}:{h*3}:flags=neighbor,tile=6x4'
    for name,f in filters.items():
        run(['docker','exec','relax-factory','ffmpeg','-nostdin','-v','error','-y','-threads','1','-filter_threads','1',
             '-i',prefix+'/preview.mp4','-vf',f,'-frames:v','1','-threads','1',prefix+'/'+name+'.jpg'])
        run(['docker','cp','relax-factory:'+prefix+'/'+name+'.jpg',str(root/(name+'.jpg'))])
    user=pwd.getpwnam('relax-codex');w=Path('/var/lib/relax-codex/workspace')/(rid+'-final')
    w.mkdir(mode=0o700,exist_ok=True);os.chown(w,user.pw_uid,user.pw_gid)
    for name in filters:
        p=w/(name+'.jpg');shutil.copyfile(root/p.name,p);os.chown(p,user.pw_uid,user.pw_gid);p.chmod(0o600)
    schema={'type':'object','additionalProperties':False,'properties':{
        'verdict':{'type':'string','enum':['REJECT','READY_FOR_OWNER_PREVIEW']},
        'defects':{'type':'array','items':{'type':'string'}},
        'outdoor_snow':{'type':'string','enum':['VISIBLE','ABSENT','UNCERTAIN']},
        'limitations':{'type':'string'}},'required':['verdict','defects','outdoor_snow','limitations']}
    (w/'schema.json').write_text(json.dumps(schema))
    (w/'context-snapshot.json').write_text(json.dumps(memory,ensure_ascii=False,indent=2))
    references=project_memory.reference_images(memory,w,user)
    prompt=(f'The first {len(filters)} images are target sheets, in this order: {list(filters)}. Any later images are historical references. '
        'Do not use tools. These are chronological samples of the actual 30-second preview. '
        'First image: 20 whole-frame samples, five columns. Second: 60 fireplace/cat closeups, six columns. '
        'Third: twenty window crops at the scene coordinate scale in four columns, every 1.5 seconds. '
        'Fourth: 36 native-scale window crops in six columns. Rows 1-2 are consecutive video frames 48-59; rows 3-4 are frames 120-131; rows 5-6 are frames 192-203, at 24 fps. These three half-second bursts resolve small moving flakes without downscaling or 1.5-second sampling gaps. Compare adjacent frames within each burst, not only distant frames. '
        'The optional preview-peak sheet shows consecutive frames around the largest brightness difference; distinguish normal flame lighting from a geometry or camera jump. The optional preview-motion sheet shows enlarged cat-head crops at the worst numerical template-match moments. Blank cells are sheet padding, not black video frames. Judge actual visible pose changes: template displacement alone can be caused by flame shadows or compression. Accept a measurement artifact only when these closeups show the cat remains asleep with stable head/ears/paws. Reject noticeable motion or unresolved uncertainty. '
        'Use the window crops to judge fine snow, not only the reduced whole-frame sheet. '
        'Do not call snow absent merely because tiny flakes disappear after downscaling; '
        'reject if the detailed samples show no visible falling snow. '
        'Reject obvious snow indoors, window-shaped reflections in the firebox, '
        'moving fireplace structure, distorted furniture, waking cat or clearly noticeable head/ear/paw/tail movement, '
        'camera movement, ghosted shapes or rhythmic seam jumps. Fine snow must visibly fall outside '
        'the outdoor view over the sequence. Individual frames or partly occluded panes need not contain identical flakes. Natural fixed stone/wood texture is not floating snow. The cat may breathe barely. '
        'Owner allows minor flake-size differences, perspective-related uneven snow and natural flame lighting/shadows. Do not reject these preferences, tiny compression shimmer or subpixel edge changes as geometry or head motion. Noticeable outdoor snowfall, a sleeping cat, a fixed camera and a smooth loop are still required. '
        'Numerical full-sequence checks run separately. This is an automated prescreen for a human test '
        'Set outdoor_snow=VISIBLE only when moving exterior flakes are identifiable; ABSENT only when detailed bursts clearly show a static snow-covered exterior without falling flakes. If evidence is insufficient choose UNCERTAIN, not ABSENT. A static snowy landscape alone does not satisfy snowfall. '
        'approval, never owner approval or evidence of listening or real-time playback. Give concrete '
        'defects in Russian; if sampled visuals are suitable for owner inspection choose '
        'READY_FOR_OWNER_PREVIEW. State sampling limitations honestly. '
        'Additional images, if present, are historical references from the same channel, '
        'not extra frames of this clip. Different rooms are allowed. Historical verdicts '
        'are not proof of a defect in current frames. Active scoped project memory:\n'
        +json.dumps(memory,ensure_ascii=False))
    prompt += ' Keep limitations to two short sentences; list only actual defects, not every passed rule.'
    run(['systemd-run','--unit=relax-final-qc-'+rid,'--collect','--wait','--pipe',
        '-p','User=relax-codex','-p','WorkingDirectory='+str(w),'-p','MemoryMax=512M',
        '-p','CPUQuota=25%','-p','RuntimeMaxSec=180','--setenv=HOME=/var/lib/relax-codex',
        '--setenv=CODEX_HOME=/var/lib/relax-codex/.codex',
        '/opt/relax-codex/release-0.171.0/bin/codex','exec','--ephemeral','--skip-git-repo-check',
        '--sandbox','read-only','--image',str(w/'preview-contact.jpg'),'--image',str(w/'preview-detail.jpg'),
        '--image',str(w/'preview-snow.jpg'),
        '--image',str(w/'preview-snow-bursts.jpg'),
        *(['--image',str(w/'preview-peak.jpg')] if 'preview-peak' in filters else []),
        *(['--image',str(w/'preview-motion.jpg')] if 'preview-motion' in filters else []),
        *[arg for ref in references for arg in ['--image',ref]],
        '--output-schema',str(w/'schema.json'),'-o',str(w/'qc.json'),prompt],timeout=210)
    value=json.loads((w/'qc.json').read_text());value['review_version']=REVIEW_VERSION;value['memory_policy_fingerprint']=memory['policy_fingerprint'];value['preview_sha256']=preview_sha
    if value['outdoor_snow']!='VISIBLE':value['verdict']='REJECT'
    result.write_text(json.dumps(value,ensure_ascii=False,indent=2))
    return value


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('request_id');p.add_argument('--recheck',action='store_true')
    a=p.parse_args();print(json.dumps(main(a.request_id,a.recheck),ensure_ascii=False))
