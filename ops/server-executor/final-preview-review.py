"""Automated visual prescreen of a complete 30-second owner preview, not approval."""
import argparse,json,os,pwd,shutil,subprocess,re
from pathlib import Path


def run(args,**kw):
    return subprocess.run(args,check=True,capture_output=True,text=True,
                          stdin=subprocess.DEVNULL,**kw)


def main(rid):
    if not re.fullmatch(r'cabin(?:08|22)-(?:fullframe|clean)-v(?:[1-9]|1[0-2])-20261120',rid):raise ValueError('Unsupported preview')
    root=Path('/opt/relax-codex/assets')/rid
    result=root/'final-preview-qc.json'
    if result.exists():return json.loads(result.read_text())
    prefix='/tmp/'+rid
    crop='700:380:50:340' if rid.startswith('cabin08-') else '650:360:90:350'
    filters={'preview-contact':'fps=2/3,scale=640:-1,tile=5x4',
             'preview-detail':'fps=2,scale=1280:720,crop='+crop+',scale=300:-1,tile=6x10'}
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
    prompt=('Do not use tools. These are chronological samples of the actual 30-second preview. '
        'First image: 20 whole-frame samples, five columns. Second: 60 fireplace/cat closeups, six columns. '
        'Reject obvious snow indoors, window-shaped reflections in the firebox, double/inserted hearth, '
        'moving fireplace structure, distorted furniture, waking/moving cat, moving head ears paws tail, '
        'camera movement, ghosted shapes or rhythmic seam jumps. Fine snow must visibly fall outside '
        'all windows. Natural fixed stone/wood texture is not floating snow. The cat may breathe barely. '
        'Numerical full-sequence checks run separately. This is an automated prescreen for a human test '
        'approval, never owner approval or evidence of listening or real-time playback. Give concrete '
        'defects in Russian; if sampled visuals are suitable for owner inspection choose '
        'READY_FOR_OWNER_PREVIEW. State sampling limitations honestly.')
    run(['systemd-run','--unit=relax-final-qc-'+rid,'--collect','--wait','--pipe',
        '-p','User=relax-codex','-p','WorkingDirectory='+str(w),'-p','MemoryMax=512M',
        '-p','CPUQuota=25%','-p','RuntimeMaxSec=180','--setenv=HOME=/var/lib/relax-codex',
        '--setenv=CODEX_HOME=/var/lib/relax-codex/.codex',
        '/opt/relax-codex/release-0.171.0/bin/codex','exec','--ephemeral','--skip-git-repo-check',
        '--sandbox','read-only','--image',str(w/'preview-contact.jpg'),'--image',str(w/'preview-detail.jpg'),
        '--output-schema',str(w/'schema.json'),'-o',str(w/'qc.json'),prompt],timeout=210)
    value=json.loads((w/'qc.json').read_text());result.write_text(json.dumps(value,ensure_ascii=False,indent=2))
    return value


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('request_id');print(json.dumps(main(p.parse_args().request_id),ensure_ascii=False))
