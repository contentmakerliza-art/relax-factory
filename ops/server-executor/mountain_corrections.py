"""Durable Mountain snow corrections. Reuse source; never call a generator.

One revision per owner decision; only actual Telegram delivery closes the task.
The existing intake remains the sole Telegram consumer.
"""
import fcntl
import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path

import mountain_batch as b
from window_snow_contract import schema, validate_plan

DB='/var/lib/relax-codex-bridge/tasks.sqlite'
BASE=b.DATA/'sources/mountain-corrections'
CODE=b.ROOT/'mountain_correction_media.py'
VERSION='2026-11-22-snow-corrections-v1'
PENDING=('pending_executor','planned_needs_video_adapter','mountain_correction_running','mountain_correction_attention_required')


def supported(row):
    comments=row.get('comments') or []
    text=(comments[-1].get('text') or comments[-1].get('transcript') or '') if comments else ''
    return (row.get('status')=='правка' and not row.get('archived')
            and str(row.get('label','')).startswith('Mountain View Cafe')
            and bool(re.search(r'снег|snow',text,re.I)))


def fingerprint(row):
    fields={k:row[k] for k in ('job_id','status','time','comments')}
    return hashlib.sha256(json.dumps(fields,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def current(task_id,jid):
    d=b.read(b.DATA/jid/'job.json',{});ap=d.get('approval') or {}
    row={'job_id':jid,'status':ap.get('status'),'time':ap.get('time'),
         'comments':[{k:c[k] for k in ('time','text','transcript','voice') if k in c} for c in ap.get('comments',[]) if isinstance(c,dict)]}
    return row['status']=='правка' and fingerprint(row)==task_id


def state(folder,stage,**fields):
    old=b.read(folder/'state.json',{})
    old.update(stage=stage,updated=time.time(),**fields);b.save(folder/'state.json',old)


def update_task(task_id,value):
    with sqlite3.connect(DB,timeout=15) as db:
        db.execute('UPDATE tasks SET state=? WHERE id=?',(value,task_id))


def notice(folder,name,text):
    # Persist before network call: uncertain response is never sent repeatedly.
    p=folder/('notice-'+name+'.json')
    if p.exists():return
    b.save(p,{'state':'sending','text':text,'created':time.time()})
    script="import json,sys;from render import telegram;t=json.load(sys.stdin);s=telegram.state();r=telegram.call('sendMessage',{'chat_id':s['chat_id'],'text':t});print(json.dumps({'message_id':r['message_id']}))"
    r=b.run(['docker','exec','-i','relax-factory','python','-c',script],input=json.dumps(text),timeout=60)
    b.save(p,dict(state='sent',**json.loads(r)))


def reconcile_delivery(folder,task_id):
    delivery=b.read(b.DATA/('mountain-delivery-'+b.read(folder/'config.json')['request_id']+'.json'),{})
    jid=delivery.get('job_id')
    if not jid:raise RuntimeError('Existing partial delivery requires inspection; no duplicate submission')
    job=b.read(b.DATA/jid/'job.json',{});tg=job.get('telegram') or {}
    if tg.get('status')=='отправлено':
        state(folder,'delivered',job_id=jid,telegram=tg)
        update_task(task_id,'mountain_correction_delivered')
        return True
    if delivery.get('stage') in ('telegram_requested','telegram_submission_uncertain'):
        state(folder,'awaiting_telegram',job_id=jid)
        if tg.get('status')=='ошибка':raise RuntimeError('Telegram delivery requires inspection: '+str(tg))
        return True
    raise RuntimeError('Existing partial delivery requires inspection; no duplicate submission')


def prepare(folder,task_id,row):
    jid=row['job_id'];recipe=b.read(b.DATA/jid/'mountain-production-recipe.json')
    if not recipe:raise ValueError('Missing preserved Mountain recipe')
    rid=recipe.get('source_request_id',recipe['request_id'])
    if not re.fullmatch(r'mountain\d{2}-[a-z0-9-]+',rid):raise ValueError('Invalid source identity')
    # Only reuse the exact original animation belonging to this approved card.
    original=b.BATCH/rid;cfg=dict(recipe)
    cfg.update(request_id='mountain-fix-'+task_id[:20],correction_of=jid,
               correction_task_id=task_id,owner_request=row['comments'][-1],
               snow_density=1.8,correction_version=VERSION,source_request_id=rid,
               source_native_request_id=recipe.get('source_native_request_id',(recipe.get('qa') or {}).get('request_id','')))
    b.save(folder/'config.json',cfg)
    container='/data/sources/mountain-corrections/'+task_id
    if not (folder/'source.mp4').exists():
        native=cfg['source_native_request_id']
        match=re.fullmatch(r'mountain\d{2}-native-v(\d+)-20261122',native)
        if not match:raise ValueError('Missing original native attempt identity')
        raw=original/('attempt-'+match[1])/'raw.mp4'
        if not raw.is_file():raise ValueError('Original source missing; do not regenerate blindly')
        shutil.copy2(raw,folder/'raw.mp4')
        b.docker('python','/tmp/mountain_correction_media.py','normalize',container,timeout=400)
    if not (folder/'audio.wav').exists():
        audio=b.DATA/jid/'mountain-full-audio.wav'
        if hashlib.sha256(audio.read_bytes()).hexdigest()!=recipe['audio_sha256']:raise ValueError('Audio identity changed')
        shutil.copy2(audio,folder/'audio.wav')
    snow=b.DATA/'sources/executor-library/assets/Исходники/Little Paris Jazz Cafe/Неделя 3 — 29 ноября–5 декабря/Снег Little Paris — мелкие хлопья — альфа 30 секунд.mkv'
    if not (folder/'external-snow.mkv').exists():shutil.copy2(snow,folder/'external-snow.mkv')
    return cfg,container


def process(task_id,row):
    folder=BASE/task_id;folder.mkdir(parents=True,exist_ok=True)
    if not current(task_id,row['job_id']):update_task(task_id,'superseded');return
    old=b.read(folder/'state.json',{})
    if old.get('stage')=='held':return
    if (folder/'config.json').exists() and reconcile_if_present(folder,task_id):return
    notice(folder,'accepted',f"Приняла правку: {row['label']}. Исправляю снег на сохранённой анимации. Новая проба придёт после проверки.")
    cfg,container=prepare(folder,task_id,row)
    state(folder,'window_layout')
    b.docker('python','/tmp/mountain_correction_media.py','window-frames',container)
    fields={k:v for k,v in schema()['properties'].items() if k not in ('verdict','notes')}
    for revision in (1,2):
        qcfolder=folder/('review-'+str(revision));qcfolder.mkdir(exist_ok=True)
        images=[folder/f'frame{i}.png' for i in range(4)]
        previous=b.read(folder/'last-rejection.json',{})
        layout=b.judge(qcfolder,'window-layout-v2',images,
            'GEOMETRY ANNOTATION ONLY, not source or snowfall quality control. Mark safe glass panes in these four frames of ONE Mountain View scene at1280x720. '
            'PASS means glass/indoor boundaries can be traced safely. The EXISTING snowfall is known defective and will be fixed by the next assembly step. '
            'Absent, faint, uneven or intermittent existing snowfall MUST NOT affect this layout verdict. Do not reject for correctable camera-border texture outside the glass. '
            'IMPORTANT distinguish INDOOR from OUTDOOR objects: foreground polygons exclude ONLY indoor furniture, frames, mullions, walls, sills and indoor plants. '
            'OUTDOOR balcony railing, balusters, trees and mountains MUST remain under falling snow, including gaps between balusters: do NOT exclude outdoor railing or whole exterior lower window. '
            'Each glass pane is a separate polygon inside inner frame edges; exclude full moving indoor furniture silhouettes across all frames. '
            'Inset_fullhd_px=8. Return3..6 rigid rectangles [x,y,w,h] on interior structure x>=48,y>=27,x+w<=1232,y+h<=693,w30..140,h30..110. '
            'No flame masks. Only ambiguous geometry or occlusion boundaries require UNCERTAIN. '
            'The final assembly has a separate strict snowfall/continuity/seam review. Previous assembly feedback for mask revision only: '+json.dumps(previous,ensure_ascii=False),fields)
        if layout['verdict']!='PASS':raise ValueError('Window layout uncertain: '+str(layout['defects']))
        plan={k:layout[k] for k in fields};plan.update(verdict='READY',notes=layout['limitations']);validate_plan(plan)
        b.save(folder/'window-plan.json',plan)
        b.docker('python','/tmp/mountain_correction_media.py','window-mask',container)
        cfg['snow_density']=1.8 if revision==1 else 2.4;b.save(folder/'config.json',cfg)
        # Revisions use independent folders so render/QC caches cannot hide changes.
        renderfolder=folder/('render-'+str(revision));renderfolder.mkdir(exist_ok=True)
        for name in ('source.mp4','audio.wav','config.json','mask.png','window-plan.json','external-snow.mkv'):
            dst=renderfolder/name
            if not dst.exists():shutil.copy2(folder/name,dst)
        rendercontainer=container+'/render-'+str(revision)
        for fade in (6,3,0):
            if not current(task_id,row['job_id']):update_task(task_id,'superseded');return
            state(folder,'assembly_qc',revision=revision,fade=fade)
            technical=json.loads(b.docker('python','/tmp/mountain_correction_media.py','build',rendercontainer,'--fade',str(fade),timeout=700))
            b.docker('python','/tmp/mountain_correction_media.py','preview-sheet',rendercontainer,'--fade',str(fade),timeout=240)
            review=b.judge(qcfolder,'assembly-'+str(fade),
                [renderfolder/f'preview-{fade}-{suffix}.png' for suffix in ('contact','seam','rigid')]+[folder/'mask-overlay.png'],
                'Judge this corrected Mountain View30s preview. Image1 is ALL30seconds at one frame per second, left-to-right then top-to-bottom. '
                'Image2 twelve consecutive frames at native loop seam, image3 rigid crops, image4 diagnostic pink window mask (not video content). '
                'Owner correction: '+json.dumps(row['comments'][-1],ensure_ascii=False)+'. '
                'Require readily visible fine snowfall throughout ALL30seconds and across whole outdoor view INCLUDING in FRONT of OUTDOOR balcony railing. '
                'Indoor furniture silhouettes, wooden frames and walls must remain free of added flakes. No snowfall gaps or abrupt resets, no blur/doubled furniture/zoom/jump at seam; native fire remains natural. '
                'Tiny shimmer allowed. Compare ALL rows; never infer PASS from first10seconds. If snow visibility unclear mark UNCERTAIN. '
                'Audio measured by correlation separately, do not claim listening. Russian defects.')
            if review['verdict']!='PASS':b.save(folder/'last-rejection.json',review);continue
            if not current(task_id,row['job_id']):update_task(task_id,'superseded');return
            ready=dict(technical,**{'pass':True,'visual_qc':review,'request_id':cfg['request_id'],
                'owner_approval_required':True,'sampled_visual_review':True,'coverage_seconds':30,
                'correction_of':row['job_id'],'correction_task_id':task_id})
            b.save(renderfolder/'ready.json',ready)
            state(folder,'delivery_started',revision=revision,fade=fade)
            delivery=json.loads(b.docker('python','/tmp/mountain_correction_media.py','deliver',rendercontainer,'--fade',str(fade),timeout=240))
            b.save(folder/'delivery.json',delivery)
            state(folder,'awaiting_telegram',job_id=delivery.get('job_id'))
            reconcile_delivery(folder,task_id);return
    raise ValueError('Bounded assembly corrections exhausted: '+json.dumps(b.read(folder/'last-rejection.json'),ensure_ascii=False))


def reconcile_if_present(folder,task_id):
    cfg=b.read(folder/'config.json')
    if (b.DATA/('mountain-delivery-'+cfg['request_id']+'.json')).exists():return reconcile_delivery(folder,task_id)
    return False


def main():
    BASE.mkdir(parents=True,exist_ok=True)
    with (BASE/'worker.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        b.cp(CODE,'relax-factory:/tmp/mountain_correction_media.py')
        b.cp(b.ROOT/'window_snow_contract.py','relax-factory:/tmp/window_snow_contract.py')
        with sqlite3.connect(DB,timeout=15) as db:
            marks=','.join('?' for _ in PENDING)
            rows=db.execute('SELECT id,payload FROM tasks WHERE state IN ('+marks+') ORDER BY created',PENDING).fetchall()
        for task_id,payload in rows:
            row=json.loads(payload)
            if not supported(row):continue
            folder=BASE/task_id
            old=b.read(folder/'state.json',{})
            if old.get('stage')=='held':
                # One bounded migration for the diagnosed v1 geometry prompt:
                # it incorrectly rejected the known snowfall defect BEFORE repair.
                marker=folder/'layout-policy-recovery.json'
                if not str(old.get('reason','')).startswith('Window layout uncertain:') or marker.exists():continue
                legacy=folder/'review-1/window-layout.json'
                if not legacy.exists() or (folder/'review-1/window-layout-v2.json').exists():continue
                b.save(marker,dict(reason='separate_geometry_from_known_snow_defect',previous=old,created=time.time()))
                state(folder,'recovering_layout_policy')
            update_task(task_id,'mountain_correction_running')
            try:process(task_id,row)
            except Exception as e:
                folder=BASE/task_id;folder.mkdir(exist_ok=True)
                state(folder,'held',reason=str(e)[-2000:]);update_task(task_id,'mountain_correction_attention_required')
                try:notice(folder,'blocked',f"Правка {row['label']} сохранена, но автоматическое исправление остановлено на проверке. Новая версия ещё не готова; исходник сохранён.")
                except Exception:pass
                print(json.dumps({'task':task_id,'error':str(e)[-2000:]},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
