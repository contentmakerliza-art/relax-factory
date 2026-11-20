"""Reject a new Cabin source before spending free-video queue time."""
import argparse
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess


def main(source, request_id):
    if not re.fullmatch(r'cabin(?:08|22)-source-new-v[1-3]-20261120', request_id):
        raise ValueError('Unsupported source review')
    base = Path('/opt/marketplace-analytics/studio-downloads')
    if source.parent != base or source.is_symlink() or source.stat().st_size < 10000:
        raise ValueError('Expected complete staged image')
    folder = Path('/opt/relax-codex/assets') / request_id
    folder.mkdir(exist_ok=True)
    result = folder / 'source-qc.json'
    if result.exists():
        return json.loads(result.read_text())
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
    prompt = ('Do not use tools. Inspect this new source photograph for Quiet Pines Cabin. '
              'It is a new scene, not a pixel-identical restoration of an older photograph. '
              'Reject malformed cat or furniture, implausible room geometry, a second or inserted '
              'firebox, a bright window-shaped reflection inside the hearth, obvious snowflakes '
              'floating indoors or over indoor objects, or lack of noticeable snowfall outside. '
              'The cat must be naturally asleep, curled up, eyes closed, chin supported. '
              'Distinguish stationary wood knots, stone grain and natural plaster marks from snow: '
              'do not invent floating flakes from those textures. Give concrete defects in Russian. '
              'If the still scene looks sound, NEEDS_VIDEO_TEST; this is not approval of motion or sound.')
    subprocess.run(['systemd-run','--unit=relax-qc-'+request_id,'--collect','--wait','--pipe',
        '-p','User=relax-codex','-p','WorkingDirectory='+str(workspace),'-p','MemoryMax=512M',
        '-p','CPUQuota=25%','-p','RuntimeMaxSec=180','--setenv=HOME=/var/lib/relax-codex',
        '--setenv=CODEX_HOME=/var/lib/relax-codex/.codex',
        '/opt/relax-codex/release-0.171.0/bin/codex','exec','--ephemeral','--skip-git-repo-check',
        '--sandbox','read-only','--image',str(image),'--output-schema',str(workspace/'schema.json'),
        '-o',str(workspace/'qc.json'),prompt],check=True,capture_output=True,text=True,
        stdin=subprocess.DEVNULL,timeout=210)
    value=json.loads((workspace/'qc.json').read_text())
    result.write_text(json.dumps(value,ensure_ascii=False,indent=2))
    return value


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('request_id')
    a=p.parse_args();print(json.dumps(main(a.source,a.request_id),ensure_ascii=False))
