"""Stage full frozen Exhale inputs without touching approvals or starting finals."""
import hashlib,json,os,shutil,wave
from pathlib import Path

DATA=Path('/var/lib/relax-factory');LIB=DATA/'sources/executor-library'
ASSETS=LIB/'assets';BASE=ASSETS/'Исходники/Exhale to Sleep/Новые 20 проб'
STAGE=LIB/'exhale-publication-staging'

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def source(name):
    p=(ASSETS/name).resolve()
    if ASSETS.resolve() not in p.parents or not p.is_file():raise ValueError('Preserved source missing')
    return p

def link(a,b):
    if b.exists():
        if sha(a)!=sha(b):raise ValueError('Existing staged input differs')
    else:os.link(a,b)

def main():
    rows=json.loads((BASE/'Журнал производства.json').read_text())
    if len(rows)!=23:raise ValueError('Expected complete 23-episode approved series')
    STAGE.mkdir(exist_ok=True);manifest=[]
    for row in rows:
        jid=row['telegram_job_id'];folder=DATA/jid;meta=json.loads((folder/'job.json').read_text())
        if meta.get('approval',{}).get('status')!='одобрено' or meta.get('status')!='готово':
            raise ValueError('Exact episode is no longer approved')
        output=folder/meta['output'];approved_hash=sha(output)
        if approved_hash!=row['qc']['sha256']:raise ValueError('Original approved preview changed')
        mode=json.loads((BASE/(row['mode']+' — синхронизация.json')).read_text())
        dst=STAGE/jid;(dst/'voice').mkdir(parents=True,exist_ok=True);(dst/'ambient').mkdir(exist_ok=True)
        voice=source(mode['voice_arranged']);background=source(row['bank_file']);font=BASE/'DM Sans Medium.ttf'
        with wave.open(str(voice)) as f:seconds=f.getnframes()/f.getframerate()
        for src,target in [(voice,dst/'voice/00-arranged-voice.wav'),(font,dst/'voice/DM Sans Medium.ttf'),
                           (background,dst/'ambient/background.flac')]:link(src,target)
        entry=lambda p:dict(name=p.name,sha256=sha(p))
        recipe=dict(schema=1,kind='exhale-preserved-v1',mode=row['mode'],source_job=jid,
            approved_preview_sha256=approved_hash,voice_seconds=seconds,phases=mode['phases'],rise=mode['rise'],
            background_offset=row['background_offset'],background_gain=row['background_gain'],after_gain=1,
            voice=entry(dst/'voice/00-arranged-voice.wav'),font=entry(dst/'voice/DM Sans Medium.ttf'),
            background=entry(dst/'ambient/background.flac'),
            after_gain_basis='Native post-intro bed from the owner original 10h episode, extracted at 600s',
            fade_seconds=20,background_rise_seconds=15)
        marker=dst/'voice/zz-preserved-exhale.json';marker.write_text(json.dumps(recipe,ensure_ascii=False,indent=2))
        breath=dict(script=mode['script'],rise=mode['rise'])
        (dst/'breath.json').write_text(json.dumps(breath,ensure_ascii=False,indent=2))
        manifest.append(dict(job_id=jid,number=row['number'],publish_at=row['date']+'T22:00',
            mode=row['mode'],background=row['background'],label=row['label'],preview_sha256=approved_hash,
            recipe_sha256=sha(marker),voice_seconds=seconds))
    (STAGE/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    print(json.dumps({'staged':len(manifest),'new_generations':0,'approvals_changed':False,'queue_changed':False}))

if __name__=='__main__':main()
