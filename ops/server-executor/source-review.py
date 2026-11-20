"""Reject a new Cabin source before spending free-video queue time."""
import argparse
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import project_memory


def main(source, request_id):
    if not re.fullmatch(r'cabin(?:08|22)-source-new-v[1-3]-20261120', request_id):
        raise ValueError('Unsupported source review')
    base = Path('/opt/marketplace-analytics/studio-downloads')
    if source.parent != base or source.is_symlink() or source.stat().st_size < 10000:
        raise ValueError('Expected complete staged image')
    folder = Path('/opt/relax-codex/assets') / request_id
    folder.mkdir(exist_ok=True)
    result = folder / 'source-qc.json'
    memory=project_memory.context('Quiet Pines Cabin',stage='image_qc',request_id=request_id,
                                  request='кот анатомия камин отражение окна')
    if result.exists():
        cached=json.loads(result.read_text())
        if cached.get('memory_policy_fingerprint')==memory['policy_fingerprint']:return cached
        history=folder/'qa-history';history.mkdir(exist_ok=True)
        shutil.copy2(result,history/('source-qc-before-memory-'+str(result.stat().st_mtime_ns)+'.json'))
    user = pwd.getpwnam('relax-codex')
    workspace = Path('/var/lib/relax-codex/workspace') / request_id
    workspace.mkdir(exist_ok=True, mode=0o700)
    os.chown(workspace, user.pw_uid, user.pw_gid)
    image = workspace / ('source' + source.suffix)
    shutil.copyfile(source, image)
    os.chown(image, user.pw_uid, user.pw_gid)
    image.chmod(0o600)
    shutil.copyfile(source, folder / source.name)
    schema = {'type':'object','additionalProperties':False,'properties':{
        'verdict':{'type':'string','enum':['REJECT','NEEDS_VIDEO_TEST']},
        'defects':{'type':'array','items':{'type':'string'}},
        'limitations':{'type':'string'}},'required':['verdict','defects','limitations']}
    (workspace / 'schema.json').write_text(json.dumps(schema))
    (workspace/'context-snapshot.json').write_text(json.dumps(memory,ensure_ascii=False,indent=2))
    references=project_memory.reference_images(memory,workspace,user)
    prompt = ('Do not use tools. Inspect this new source photograph for Quiet Pines Cabin. '
              'It is a new scene, not a pixel-identical restoration of an older photograph. '
              'Reject malformed cat or furniture, implausible room geometry, a second or inserted '
              'firebox, a bright window-shaped reflection inside the hearth, obvious snowflakes '
              'floating indoors or over indoor objects, or absence of a readable winter scene outside. '
              'A still image cannot prove falling speed or continuous snow movement; those need video. '
              'The cat must be naturally asleep, curled up, eyes closed, chin supported. '
              'Distinguish stationary wood knots, stone grain and natural plaster marks from snow: '
              'do not invent floating flakes from those textures. Give concrete defects in Russian. '
              'If the still scene looks sound, NEEDS_VIDEO_TEST; this is not approval of motion or sound. '
              'Extra images are historical references from other scenes, not alternate target images. '
              'Active scoped memory:\n'+json.dumps(memory,ensure_ascii=False))
    subprocess.run(['systemd-run','--unit=relax-qc-'+request_id,'--collect','--wait','--pipe',
        '-p','User=relax-codex','-p','WorkingDirectory='+str(workspace),'-p','MemoryMax=512M',
        '-p','CPUQuota=25%','-p','RuntimeMaxSec=180','--setenv=HOME=/var/lib/relax-codex',
        '--setenv=CODEX_HOME=/var/lib/relax-codex/.codex',
        '/opt/relax-codex/release-0.171.0/bin/codex','exec','--ephemeral','--skip-git-repo-check',
        '--sandbox','read-only','--image',str(image),'--output-schema',str(workspace/'schema.json'),
        *[arg for ref in references for arg in ['--image',ref]],
        '-o',str(workspace/'qc.json'),prompt],check=True,capture_output=True,text=True,
        stdin=subprocess.DEVNULL,timeout=210)
    value=json.loads((workspace/'qc.json').read_text())
    value['memory_policy_fingerprint']=memory['policy_fingerprint']
    result.write_text(json.dumps(value,ensure_ascii=False,indent=2))
    return value


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('request_id')
    a=p.parse_args();print(json.dumps(main(a.source,a.request_id),ensure_ascii=False))
