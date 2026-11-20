"""Continue one already submitted generation on server, without a MacBook session."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import time


def main(request_id):
    if not re.fullmatch('cabin(?:17|18)-fullframe-v[1-3]-20261120',request_id):
        raise ValueError('Unsupported pilot')
    ledger=Path('/opt/marketplace-analytics/studio-state')/('runway-'+request_id+'.json')
    deadline=time.monotonic()+780
    while time.monotonic()<deadline:
        try:state=json.loads(ledger.read_text())['state']
        except (OSError,ValueError,KeyError):state='waiting'
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
