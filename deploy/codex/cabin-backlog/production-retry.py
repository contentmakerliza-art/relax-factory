import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import cabin_backlog_registry as backlog
"""Bounded server production: three Runway attempts per source, then a new image.

Runs only explicitly staged configurations. Good previews remain held for final
review; this worker neither approves nor starts a three-hour render.
"""
import argparse
from motion_policy import VERSION
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import time

ROOT = Path('/opt/relax-codex')
DOWNLOADS = Path('/opt/marketplace-analytics/studio-downloads')
STATE = Path('/opt/marketplace-analytics/studio-state')
MAX_ATTEMPTS = 3

@contextmanager
def media_slot():
    with (ROOT/'cabin-backlog/media-check.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        yield

def pipeline_is_running(path):
    if not path.exists():return False
    with path.open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return True
    return False
DEFAULT_MODEL = 'Gen-4 Turbo'


def model_failures(model):
    """Count confirmed technical failures since this model's last real result."""
    known = []
    for path in STATE.glob('runway-*.json'):
        try:
            value = read(path)
            if value.get('model') == model:
                known.append(value)
        except (OSError, ValueError):
            continue
    success = max((v.get('created', 0) for v in known if v.get('state') in
                   ('downloaded_needs_qc', 'generated_needs_download')), default=0)
    return sum(v.get('state') == 'generation_failed' and v.get('created', 0) > success
               for v in known)


def run(args, timeout=3600):
    return subprocess.run(args, check=True, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=timeout)


def read(path):
    return json.loads(path.read_text()) if path.exists() else None


def main(config_path):
    config = read(config_path)
    if config['channel'] != 'Quiet Pines Cabin' or not 1 <= len(config['sources']) <= 3:
        raise ValueError('Unsupported staged configuration')
    job = config['request_group']
    if not backlog.group(job):
        raise ValueError('Unsupported production group')
    if sum(bool(s.get('new_image_request')) for s in config['sources'])>2:
        raise ValueError('At most two paid new images per staged run')
    for source in config['sources']:
        ids = source['attempts']
        if not 3 <= len(ids) <= 6 or len(set(ids)) != len(ids):
            raise ValueError('Stage 3–6 unique submission IDs; at most three completed videos per image')
        if any(not backlog.attempt(x, job) for x in ids):
            raise ValueError('Unsupported staged attempt')
    all_ids = [i for s in config['sources'] for i in s['attempts']]
    if len(all_ids) != len(set(all_ids)):
        raise ValueError('Attempt IDs cannot be reused across images')
    folder = ROOT / 'production-runs' / job
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / 'worker.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return work(config, folder)


def work(config, folder):
    job = config['request_group']
    def save(stage, **details):
        tmp = folder / 'state.tmp'
        tmp.write_text(json.dumps(dict(stage=stage, updated=time.time(), **details),
                                  ensure_ascii=False, indent=2))
        tmp.replace(folder / 'state.json')
    def salvage(request_id):
        save('looking_for_long_clean_segment', request_id=request_id)
        cached = read(ROOT / 'assets' / request_id / 'long-segment.json')
        if cached and not cached.get('recheck_requested') and cached.get('state') != 'preview_ready':
            return False
        with media_slot():
            result = json.loads(run(['/usr/bin/python3', str(ROOT / 'cabin-backlog' / 'try-long-segment.py'),
                                 request_id], timeout=900).stdout)
        if result['state'] == 'preview_ready':
            save('preview_ready_for_final_checks', request_id=result['request_id'],
                 preview=result['preview'], parent_request_id=request_id,
                 owner_approval=False)
            return True
        return False
    image_budget=3*sum(bool(s.get('new_image_request')) for s in config['sources'])
    hashes = set()
    for index, source in enumerate(config['sources']):
        image_number=source.get('image_number',index+1)
        if source.get('new_image_request'):
            edit = read(Path(source['new_image_request']))
            ledger = STATE / (edit['request_id'] + '.json')
            if not ledger.exists():
                known = []
                for item in STATE.glob('runway-*.json'):
                    try:
                        value = read(item)
                        if value.get('state') in ('generation_failed', 'downloaded_needs_qc'):
                            known.append(value)
                    except (OSError, ValueError):
                        pass
                last_success = max((x.get('created', 0) for x in known
                                    if x['state'] == 'downloaded_needs_qc'), default=0)
                outages = [x for x in known if x['state'] == 'generation_failed'
                           and x.get('created', 0) > last_success]
                if len(outages) >= 2:
                    save('provider_unavailable_no_image_purchase',
                         reason='Two technical failures since last successful video; source quality is not the cause')
                    return
                save('generating_new_source', image_number=image_number,
                     maximum_image_cost_tokens=3)
                run(['/usr/bin/python3',str(ROOT/'cabin-backlog/await-syntx.py'),'image',source['new_image_request']])
            result = read(ledger)
            if result and result.get('async_submission') and result.get('state') in ('submitted','generated_needs_download'):
                run(['/usr/bin/python3',str(ROOT/'cabin-backlog/await-syntx.py'),'image',source['new_image_request']])
                result=read(ledger)
            if not result or result.get('state') != 'downloaded_needs_qc':
                save('recover_existing_image', image_number=image_number)
                return
            local = Path(result['file'])
        else:
            local = Path(source['file'])
        if local.parent != Path('/downloads') or not (DOWNLOADS / local.name).is_file():
            raise ValueError('Expected a staged source image')
        try:
            with media_slot():
                backlog.prepare_geometry(job, index, DOWNLOADS / local.name)
        except backlog.SourceRejected as error:
            save('source_rejected_changing_image', defects=[str(error)])
            continue
        digest = hashlib.sha256((DOWNLOADS / local.name).read_bytes()).hexdigest()
        if digest in hashes:
            raise ValueError('Identical image cannot reset the three-attempt counter')
        hashes.add(digest)
        completed = 0
        model = source.get('model', DEFAULT_MODEL)
        for slot, request_id in enumerate(source['attempts'], 1):
            if completed >= MAX_ATTEMPTS:
                break
            attempt = completed + 1
            ledger = STATE / ('runway-' + request_id + '.json')
            generation = read(ledger)
            pipeline = ROOT / 'assets' / request_id / 'pipeline.json'
            prior = read(pipeline)
            # A code/policy version change must never erase a durable rejection.
            # Reconsider this exact media only on an explicit, one-use request.
            if prior and prior.get('stage') in ('rejected','rejected_motion','rejected_preview') and prior.get('recheck_requested') is True:
                history=pipeline.parent/'qa-history';history.mkdir(exist_ok=True)
                (history/('pipeline-before-owner-policy-'+str(time.time_ns())+'.json')).write_text(json.dumps(prior,ensure_ascii=False,indent=2))
                receipt_path=folder/'delivery.json'
                receipt=read(receipt_path)
                if receipt and request_id in receipt.get('rejected_requests',[]):
                    (history/('delivery-before-explicit-recheck-'+str(time.time_ns())+'.json')).write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
                    receipt['rejected_requests'].remove(request_id)
                    receipt_path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
                for name in ('visual-qc.json','final-preview-qc.json','long-segment.json'):
                    cached=pipeline.parent/name
                    if cached.exists():cached.rename(history/(str(time.time_ns())+'-'+name))
                prior.pop('recheck_requested',None)
                prior.update(stage='needs_recheck_under_owner_policy',updated=time.time())
                pipeline.write_text(json.dumps(prior,ensure_ascii=False,indent=2))
            if generation and generation.get('async_submission') and generation['state'] in ('submitted','generated_needs_download'):
                save('resuming_existing_server_generation',request_id=request_id)
                run(['/usr/bin/python3',str(ROOT/'cabin-backlog/await-syntx.py'),'video',str(DOWNLOADS/(request_id+'-request.json'))])
                generation=read(ledger)
            if generation and generation['state'] == 'submitted':
                save('waiting_for_already_submitted_video', request_id=request_id)
                remaining = max(0, 900 - (time.time() - generation.get('created', 0)))
                deadline = time.monotonic() + remaining
                while generation['state'] == 'submitted' and time.monotonic() < deadline:
                    time.sleep(5)
                    generation = read(ledger)
            # An independent server follower may already be checking this exact
            # result. Wait for its durable outcome instead of racing its lock.
            prior = read(pipeline)
            if prior and prior['stage'] in ('checking_frames','checking_cat_motion','building_preview') and pipeline_is_running(pipeline.parent/'pipeline.lock'):
                deadline = time.monotonic() + 900
                while prior['stage'] in ('checking_frames','checking_cat_motion','building_preview') and time.monotonic() < deadline:
                    time.sleep(5)
                    prior = read(pipeline)
            if prior and prior['stage'] == 'held_for_motion_and_audio_review':
                save('preview_ready_for_final_checks', request_id=request_id,
                     preview=prior['preview'], owner_approval=False)
                return
            if prior and prior['stage'] in ('rejected', 'rejected_motion', 'rejected_preview'):
                completed += 1
                if salvage(request_id):return
                continue
            if generation and generation['state'] in ('generation_failed','client_result_lost_no_download'):
                continue
            if not generation:
                failures = model_failures(model)
                if failures >= 2:
                    save('model_unavailable_no_retry', model=model, technical_failures=failures,
                         completed_video_attempts=completed, source_sha256=digest,
                         reason='Two consecutive confirmed technical failures; keep image and switch work')
                    return
                request = dict(request_id=request_id, source=str(local), prompt=source['runway_prompt'], model=model)
                request_path = DOWNLOADS / (request_id + '-request.json')
                if request_path.exists() and read(request_path) != request:
                    raise ValueError('Existing staged request differs')
                request_path.write_text(json.dumps(request))
                save('generating_video', request_id=request_id, image_number=image_number,
                     attempt=attempt, submission_slot=slot, source_sha256=digest,
                     maximum_attempts=3, model=model)
                try:
                    run(['/usr/bin/python3',str(ROOT/'cabin-backlog/await-syntx.py'),'video',str(request_path)])
                except (subprocess.SubprocessError, OSError) as error:
                    generation = read(ledger)
                    if generation and generation['state'] in ('generation_failed','client_result_lost_no_download'):
                        continue
                    if generation and generation['state'] == 'generated_needs_download':
                        # The generation succeeded: resume below, never buy another.
                        pass
                    else:
                        (folder / (request_id + '-preparation-error.txt')).write_text(
                            (getattr(error, 'stderr', '') or str(type(error).__name__))[-4000:])
                        save('recover_existing_video' if generation else 'preparation_failed_no_submission',
                             request_id=request_id)
                        return
                generation = read(ledger)
            if generation and generation['state'] in ('generation_failed','client_result_lost_no_download'):
                continue
            if generation['state'] == 'generated_needs_download':
                spec = importlib.util.spec_from_file_location('follow', ROOT / 'follow-generation.py')
                follow = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(follow)
                follow.recover_download(request_id, ledger, generation)
                generation = read(ledger)
                if generation['state'] == 'generated_needs_download':
                    try:
                        run(['docker', 'exec', 'marketplace-syntx-studio', 'python',
                             '/app/cabin-backlog-download.py', request_id], timeout=240)
                    except subprocess.SubprocessError:
                        # The UI may have saved the real file despite a client error.
                        follow.recover_download(request_id, ledger, read(ledger))
                    generation = read(ledger)
            if generation['state'] != 'downloaded_needs_qc':
                save('recover_existing_video', request_id=request_id)
                return
            # Preserve source provenance independently of factory cleanup.
            assets = ROOT / 'assets' / request_id
            assets.mkdir(parents=True, exist_ok=True)
            (assets / 'production-source.json').write_text(json.dumps(dict(
                source_image=str(local), source_sha256=digest, attempt=attempt,
                image_number=image_number, group=job), indent=2))
            save('checking_video', request_id=request_id)
            try:
                with media_slot():
                    run(['/usr/bin/python3', str(ROOT / 'cabin-backlog' / 'pipeline-one.py'), request_id], timeout=900)
            except subprocess.SubprocessError as error:
                (folder / (request_id+'-pipeline-error.txt')).write_text(
                    (getattr(error,'stderr','') or type(error).__name__)[-4000:])
                save('technical_attention_required', request_id=request_id, pipeline=read(pipeline))
                return
            checked = read(pipeline)
            if checked['stage'] in ('rejected', 'rejected_motion', 'rejected_preview'):
                completed += 1
                if salvage(request_id):return
                save('deferred_after_video_rejection',request_id=request_id,completed_video_attempts=completed)
                return
            if checked['stage'] == 'held_for_motion_and_audio_review':
                save('preview_ready_for_final_checks', request_id=request_id,
                     preview=checked['preview'], owner_approval=False)
                return
            save('technical_attention_required', request_id=request_id, pipeline=checked)
            return
        if completed < MAX_ATTEMPTS:
            save('submission_slots_exhausted_no_image_purchase', image_number=image_number,
                 completed_video_attempts=completed,
                 reason='Technical failures do not consume the three-video image budget')
            return
        save('three_attempts_exhausted_changing_image', image_number=image_number)
    save('prepared_source_pool_exhausted', maximum_new_image_cost_tokens=image_budget,
         action='Continue with a freshly prepared source pool; never publish rejected media')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('config', type=Path)
    main(parser.parse_args().config)
