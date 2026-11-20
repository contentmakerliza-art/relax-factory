"""Continue one already submitted generation on server, without a MacBook session."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import time
import shutil
from urllib.parse import urlsplit


def recover_download(request_id, ledger, record):
    url=urlsplit(record.get('video_url',''))
    name=Path(url.path).name
    if url.scheme!='https' or url.netloc!='r2.syntx.ai' or not re.fullmatch(r'[A-Za-z0-9_-]+\.mp4',name):
        raise ValueError('Unexpected generated video URL')
    candidates=[Path('/opt/marketplace-analytics/studio-downloads')/name,
                Path('/opt/marketplace-analytics/browser/Downloads')/name]
    found=[p for p in candidates if p.is_file() and not p.is_symlink() and p.stat().st_size>10000]
    if len(found)!=1:return False
    target=Path('/opt/marketplace-analytics/studio-downloads')/(request_id+'.mp4')
    if target.exists():raise ValueError('Inspect existing recovered result; do not overwrite')
    temporary=target.with_suffix('.recovered.tmp')
    shutil.copyfile(found[0],temporary);temporary.chmod(0o644);temporary.replace(target)
    record.update(state='downloaded_needs_qc',file='/downloads/'+target.name,
                  download_recovery='Exact generated video filename recovered after UI download')
    temporary=ledger.with_suffix('.recovered.tmp');temporary.write_text(json.dumps(record));temporary.replace(ledger)
    return True


def main(request_id):
    if not re.fullmatch('cabin(?:08|17|18|22)-fullframe-v[1-3]-20261120',request_id):
        raise ValueError('Unsupported pilot')
    ledger=Path('/opt/marketplace-analytics/studio-state')/('runway-'+request_id+'.json')
    deadline=time.monotonic()+780
    while time.monotonic()<deadline:
        try:
            record=json.loads(ledger.read_text());state=record['state']
        except (OSError,ValueError,KeyError):state='waiting'
        if state=='generated_needs_download':
            # Give the original downloader time to finish before attempting recovery.
            if time.time()-record.get('created',time.time())>600:
                recover_download(request_id,ledger,record)
            time.sleep(5);continue
        if state=='downloaded_needs_qc':
            subprocess.run(['/usr/bin/python3','/opt/relax-codex/pipeline-one.py',request_id],
                           check=True,timeout=600)
            return
        if state in ('qc_rejected','submission_uncertain'):
            raise RuntimeError('Inspection required; never retry generation')
        time.sleep(5)
    raise TimeoutError('Generation wait expired; no retry or new generation submitted')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('request_id');main(p.parse_args().request_id)
