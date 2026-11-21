"""Reject visible defects using server Codex; samples alone never approve motion."""
import argparse
import json
from pathlib import Path
import pwd
import os
import re
import subprocess
import project_memory


def run(*args):
    return subprocess.run(list(args),capture_output=True,text=True,check=True).stdout


def main(request_id):
    if not re.fullmatch('[a-z0-9-]{16,80}',request_id):raise ValueError('Bad ID')
    root=Path('/opt/relax-codex/assets')/request_id;root.mkdir(exist_ok=True)
    source=Path('/opt/marketplace-analytics/studio-downloads')/(request_id+'.mp4')
    prefix='/tmp/'+request_id
    run('docker','exec','relax-factory','mkdir','-p',prefix)
    run('docker','cp',str(source),'relax-factory:'+prefix+'/source.mp4')
    probe=json.loads(run('docker','exec','relax-factory','ffprobe','-v','error',
                         '-select_streams','v:0','-show_entries','stream=duration,r_frame_rate',
                         '-of','json',prefix+'/source.mp4'))['streams'][0]
    duration=float(probe['duration'])
    if not 7.99 <= duration <= 10.2:raise ValueError('Source must retain at least eight seconds')
    n,d=probe['r_frame_rate'].split('/');fps=float(n)/float(d)
    middle=int(duration*fps/2)
    for name,filter_string in [('contact',f'fps={20/duration:.8f},trim=end_frame=20,scale=640:-1,tile=5x4'),
                               ('frame5',f'select=eq(n\\,{middle})')]:
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
    memory=project_memory.context('Quiet Pines Cabin',stage='video_qc',request_id=request_id,
                                  request='снег кот голова камин движение')
    (workspace/'context-snapshot.json').write_text(json.dumps(memory,ensure_ascii=False,indent=2))
    references=project_memory.reference_images(memory,workspace,u)
    output=workspace/'qc.json'
    prompt=('Do not use tools. Review the actual full video samples: first image is chronological '
        f'20 evenly spaced frames spanning {duration:.3f} seconds in 5 columns, '
        f'second full frame near {duration/2:.3f} seconds. '
        'Rules: noticeable snowfall only OUTSIDE behind window glass, no indoor specks; '
        'cat asleep, no noticeable head/ear/paw/tail motion, barely perceptible breathing; no visible camera movement, '
        'rigid room and fireplace structure, no inserts or overlays, natural existing flames, '
        'few plausible reflections. Owner permits minor snow-size variation, perspective/occlusion-related differences between panes, natural flame shadows and subpixel texture shimmer. Reject clearly visible content defects, not these minor preferences. Give concrete evidence in Russian. '
        'Otherwise NEEDS_MOTION_REVIEW: samples do not prove smooth motion, transitions or audio. '
        'Do not invent defects or assume prior attempt failed. Extra images are historical '
        'references of other clips from this channel, not frames of the current clip. '
        'Different room layouts are allowed. Active scoped memory:\n'+json.dumps(memory,ensure_ascii=False))
    if request_id.startswith('cabin18-'):
        prompt += (' Owner specifically rejected a bright window-shaped reflection in the fireplace and repeated cat movement. '
                   'Reject any visible window-shaped rectangle/reflection inside the firebox even if it was present in the source image. '
                   'Compare head angle, ear position and chin placement across the sequence; minute breathing must not move head or paws.')
    cmd=['systemd-run','--unit=relax-qc-'+request_id,'--collect','--wait','--pipe',
         '-p','User=relax-codex','-p','WorkingDirectory='+str(workspace),'-p','MemoryMax=512M',
         '-p','CPUQuota=25%','-p','RuntimeMaxSec=180','--setenv=HOME=/var/lib/relax-codex',
         '--setenv=CODEX_HOME=/var/lib/relax-codex/.codex',
         '/opt/relax-codex/release-0.171.0/bin/codex','exec','--ephemeral','--skip-git-repo-check',
         '--sandbox','read-only','--image',str(workspace/'contact.png'),'--image',str(workspace/'frame5.png'),
         *[arg for ref in references for arg in ['--image',ref]],
         '--output-schema',str(workspace/'schema.json'),'-o',str(output),prompt]
    subprocess.run(cmd,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=210,check=True)
    report=json.loads(output.read_text());report['memory_policy_fingerprint']=memory['policy_fingerprint']
    (root/'visual-qc.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('request_id');main(parser.parse_args().request_id)
