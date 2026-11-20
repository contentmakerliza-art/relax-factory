"""Resume staged series once a newer successful Runway result proves recovery.

Called by the existing minute dispatcher. No model or browser calls on idle.
"""
import fcntl,json,subprocess,time
from pathlib import Path

ROOT=Path('/opt/relax-codex')
STATE=Path('/opt/marketplace-analytics/studio-state')
BLOCKED={'provider_unavailable_no_image_purchase','waiting_for_provider_health_check'}


def read(p):
    try:return json.loads(p.read_text())
    except (OSError,ValueError):return None


def launch(args):
    subprocess.run(args,check=True,capture_output=True,text=True,timeout=20)


def main():
    directory=ROOT/'production-runs'
    if not directory.is_dir():return
    with (directory/'health-recovery.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        known=[(p.name,read(p)) for p in STATE.glob('runway-*.json')]
        successes=[(p,d) for p,d in known if d and d.get('state')=='downloaded_needs_qc']
        if not successes:return
        latest_name,latest=max(successes,key=lambda x:x[1].get('created',0))
        last_failure=max((d.get('created',0) for _,d in known if d and d.get('state')=='generation_failed'),default=0)
        if latest.get('created',0)<=last_failure:return
        for day in ('08','22'):
            group='cabin'+day+'-retry-20261120';folder=directory/group
            state=read(folder/'state.json') or {}
            config_path=ROOT/'production-configs'/(group+'.json')
            config=read(config_path)
            if state.get('stage') not in BLOCKED or not config or config.get('paused_by_owner'):continue
            delivery=read(folder/'delivery.json') or {}
            if delivery.get('stage')=='sent_for_owner_approval':continue
            marker=folder/'health-recovery.json';previous=read(marker) or {}
            if previous.get('success_ledger')==latest_name:continue
            record={'state':'dispatching','success_ledger':latest_name,'created':time.time()}
            marker.write_text(json.dumps(record))
            stamp=str(time.time_ns())
            try:
                launch(['systemd-run','--unit=relax-recover-'+day+'-'+stamp,'--collect',
                    '-p','MemoryMax=128M','-p','CPUQuota=10%','-p','RuntimeMaxSec=10800',
                    '/usr/bin/python3',str(ROOT/'production-retry.py'),str(config_path)])
                if delivery:
                    launch(['systemd-run','--unit=relax-recover-finish-'+day+'-'+stamp,'--collect',
                        '-p','MemoryMax=128M','-p','CPUQuota=10%','-p','RuntimeMaxSec=14400',
                        '/usr/bin/python3',str(ROOT/'finish-production.py'),group])
                record['state']='started'
            except subprocess.SubprocessError:
                record['state']='dispatch_uncertain_no_duplicate'
            marker.write_text(json.dumps(record))


if __name__=='__main__':main()
