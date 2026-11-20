"""Reject visible defects using server Codex; samples alone never approve motion."""
import argparse
import json
from pathlib import Path
import pwd
import os
import re
import subprocess


def run(*args):
    return subprocess.run(list(args),capture_output=True,text=True,check=True).stdout


def main(request_id):
    if not re.fullmatch('[a-z0-9-]{16,80}',request_id):raise ValueError('Bad ID')
    root=Path('/opt/relax-codex/assets')/request_id;root.mkdir(exist_ok=True)
    source=Path('/opt/marketplace-analytics/studio-downloads')/(request_id+'.mp4')
    prefix='/tmp/'+request_id
    run('docker','exec','relax-factory','mkdir','-p',prefix)
    run('docker','cp',str(source),'relax-factory:'+prefix+'/source.mp4')
    for name,filter_string in [('contact','fps=2,scale=640:-1,tile=5x4'),
                               ('frame5','select=eq(n\\,120)')]:
        run('docker','exec','relax-factory','ffmpeg','-v','error','-y','-i',prefix+'/source.mp4',
            '-vf',filter_string,'-frames:v','1',prefix+'/'+name+'.png')
        run('docker','cp','relax-factory:'+prefix+'/'+name+'.png',str(root/(name+'.png')))
    u=pwd.getpwnam('relax-codex')
    workspace=Path('/var/lib/relax-codex/workspace')/request_id
    workspace.mkdir(mode=0o700,exist_ok=True);os.chown(workspace,u.pw_uid,u.pw_gid)
    import shutil
    for name in ('contact.png','frame5.png'):
        dst=workspace/name;shutil.copyfile(root/name,dst);os.chown(dst,u.pw_uid,u.pw_gid);dst.chmod(0o600)
    schema={'type':'object','additionalProperties':False,'properties':{
        'verdict':{'type':'string','enum':['REJECT','NEEDS_MOTION_REVIEW']},
        'defects':{'type':'array','items':{'type':'string'}},
        'limitations':{'type':'string'}},'required':['verdict','defects','limitations']}
    (workspace/'schema.json').write_text(json.dumps(schema))
    output=workspace/'qc.json'
    prompt=('Do not use tools. Review the actual full video samples: first image is chronological '
        'frames at 0.5 second intervals in 5 columns, second full frame at 5 seconds. '
        'Rules: noticeable snowfall only OUTSIDE behind window glass, no indoor specks; '
        'cat asleep, fixed head ears paws tail, barely perceptible breathing; no camera movement, '
        'rigid room and fireplace structure, no inserts or overlays, natural existing flames, '
        'few plausible reflections. REJECT any visible defect, give concrete evidence in Russian. '
        'Otherwise NEEDS_MOTION_REVIEW: samples do not prove smooth motion, transitions or audio. '
        'Do not invent defects or assume prior attempt failed.')
    cmd=['systemd-run','--unit=relax-qc-'+request_id,'--collect','--wait','--pipe',
         '-p','User=relax-codex','-p','WorkingDirectory='+str(workspace),'-p','MemoryMax=512M',
         '-p','CPUQuota=25%','-p','RuntimeMaxSec=180','--setenv=HOME=/var/lib/relax-codex',
         '--setenv=CODEX_HOME=/var/lib/relax-codex/.codex',
         '/opt/relax-codex/release-0.171.0/bin/codex','exec','--ephemeral','--skip-git-repo-check',
         '--sandbox','read-only','--image',str(workspace/'contact.png'),'--image',str(workspace/'frame5.png'),
         '--output-schema',str(workspace/'schema.json'),'-o',str(output),prompt]
    subprocess.run(cmd,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=210,check=True)
    report=json.loads(output.read_text());(root/'visual-qc.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('request_id');main(parser.parse_args().request_id)
