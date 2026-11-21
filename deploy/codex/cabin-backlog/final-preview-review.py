import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import cabin_backlog_registry as backlog
"""Automated visual prescreen of a complete 30-second owner preview, not approval."""
import argparse,json,os,pwd,shutil,subprocess,re,time
from pathlib import Path
import project_memory


def run(args,**kw):
    return subprocess.run(args,check=True,capture_output=True,text=True,
                          stdin=subprocess.DEVNULL,**kw)


def main(rid,recheck=False):
    if not backlog.attempt(rid):raise ValueError('Unsupported preview')
    root=Path('/opt/relax-codex/assets')/rid
    memory=project_memory.context('Quiet Pines Cabin',stage='preview_qc',request_id=rid,
                                  request='снег окна кот голова камин склейка')
    result=root/'final-preview-qc.json'
    if result.exists():
        cached=json.loads(result.read_text())
        if not recheck and cached.get('memory_policy_fingerprint')==memory['policy_fingerprint']:return cached
        history=root/'qa-history';history.mkdir(exist_ok=True)
        shutil.copy2(result,history/f'final-preview-before-native-snow-{time.time_ns()}.json')
    prefix='/tmp/'+rid
    # Factory updates clear /tmp; the durable preview is the source of truth.
    run(['docker','exec','relax-factory','mkdir','-p',prefix])
    run(['docker','cp',str(root/'preview.mp4'),'relax-factory:'+prefix+'/preview.mp4'])
    crop=backlog.geometry(rid)['detail_crop']
    snow_crop=backlog.geometry(rid)['snow_crop']
    filters={'preview-contact':'fps=2/3,scale=640:-1,tile=5x4',
             'preview-detail':'fps=2,scale=1280:720,crop='+crop+',scale=300:-1,tile=6x10',
             'preview-snow':'fps=1/5,scale=1280:720,crop='+snow_crop+',tile=2x3'}
    for name,f in filters.items():
        run(['docker','exec','relax-factory','ffmpeg','-nostdin','-v','error','-y','-threads','1',
             '-i',prefix+'/preview.mp4','-vf',f,'-frames:v','1','-threads','1',prefix+'/'+name+'.jpg'])
        run(['docker','cp','relax-factory:'+prefix+'/'+name+'.jpg',str(root/(name+'.jpg'))])
    user=pwd.getpwnam('relax-codex');w=Path('/var/lib/relax-codex/workspace')/(rid+'-final')
    w.mkdir(mode=0o700,exist_ok=True);os.chown(w,user.pw_uid,user.pw_gid)
    for name in filters:
        p=w/(name+'.jpg');shutil.copyfile(root/p.name,p);os.chown(p,user.pw_uid,user.pw_gid);p.chmod(0o600)
    schema={'type':'object','additionalProperties':False,'properties':{
        'verdict':{'type':'string','enum':['REJECT','READY_FOR_OWNER_PREVIEW']},
        'defects':{'type':'array','items':{'type':'string'}},
        'limitations':{'type':'string'}},'required':['verdict','defects','limitations']}
    (w/'schema.json').write_text(json.dumps(schema))
    (w/'context-snapshot.json').write_text(json.dumps(memory,ensure_ascii=False,indent=2))
    references=project_memory.reference_images(memory,w,user)
    prompt=('Do not use tools. These are chronological samples of the actual 30-second preview. '
        'First image: 20 whole-frame samples, five columns. Second: 60 fireplace/cat closeups, six columns. '
        'Third: six window crops at native pixel scale in two columns, at 0, 5, 10, 15, 20, 25 seconds. '
        'Use the native window crops to judge fine snow, not only the reduced whole-frame sheet. '
        'Do not call snow absent merely because tiny flakes disappear after downscaling; '
        'reject if the detailed samples show no visible falling snow. '
        'Reject obvious snow indoors, window-shaped reflections in the firebox, double/inserted hearth, '
        'moving fireplace structure, distorted furniture, waking/moving cat, moving head ears paws tail, '
        'camera movement, ghosted shapes or rhythmic seam jumps. Fine snow must visibly fall outside '
        'all windows. Natural fixed stone/wood texture is not floating snow. The cat may breathe barely. '
        'Numerical full-sequence checks run separately. This is an automated prescreen for a human test '
        'approval, never owner approval or evidence of listening or real-time playback. Give concrete '
        'defects in Russian; if sampled visuals are suitable for owner inspection choose '
        'READY_FOR_OWNER_PREVIEW. State sampling limitations honestly. '
        'Additional images, if present, are historical references from the same channel, '
        'not extra frames of this clip. Different rooms are allowed. Historical verdicts '
        'are not proof of a defect in current frames. Active scoped project memory:\n'
        +json.dumps(memory,ensure_ascii=False))
    run(['systemd-run','--unit=relax-final-qc-'+rid,'--collect','--wait','--pipe',
        '-p','User=relax-codex','-p','WorkingDirectory='+str(w),'-p','MemoryMax=512M',
        '-p','CPUQuota=25%','-p','RuntimeMaxSec=180','--setenv=HOME=/var/lib/relax-codex',
        '--setenv=CODEX_HOME=/var/lib/relax-codex/.codex',
        '/opt/relax-codex/release-0.171.0/bin/codex','exec','--ephemeral','--skip-git-repo-check',
        '--sandbox','read-only','--image',str(w/'preview-contact.jpg'),'--image',str(w/'preview-detail.jpg'),
        '--image',str(w/'preview-snow.jpg'),
        *[arg for ref in references for arg in ['--image',ref]],
        '--output-schema',str(w/'schema.json'),'-o',str(w/'qc.json'),prompt],timeout=210)
    value=json.loads((w/'qc.json').read_text());value['memory_policy_fingerprint']=memory['policy_fingerprint']
    result.write_text(json.dumps(value,ensure_ascii=False,indent=2))
    return value


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('request_id');p.add_argument('--recheck',action='store_true')
    a=p.parse_args();print(json.dumps(main(a.request_id,a.recheck),ensure_ascii=False))
