"""Keep reusable sources when a finished phone preview is imported.

The approved MP4 remains unchanged. Music channels use full tracks, never a
repeated 30-second music excerpt. No long render or upload is started here.
"""
from pathlib import Path
import hashlib,json,os,random,shutil,subprocess
from render.engine import measure_loudness

MUSIC_FIRST={
 '20261117-200404-dda4':'01 First Snow in Montmartre.mp3',
 '20261117-200439-c7e9':'02 First Snow in Montmartre II.mp3',
 '20261117-200506-bf86':'04 Candlelight on Rue Lepic II.mp3',
 '20261117-200537-017c':'06 Snowflakes on the Awning II.mp3',
 '20261117-200634-8fa5':'08 Hot Cocoa Waltz II.mp3',
 '20261117-200803-12be':'09 Garland Lights.mp3',
 '20261117-200839-e62b':'15 Snow on the Cobblestones.mp3',
}
MUSIC_NAMES=["38 Frosted Glass II.mp3","39 Midnight Snow Waltz.mp3","40 Midnight Snow Waltz II.mp3","27 Winter Window Glow.mp3","28 Winter Window Glow II.mp3","29 Snowy Cafe Duet.mp3","30 Snowy Cafe Duet II.mp3","31 Twinkling Lights.mp3","32 Twinkling Lights II.mp3","33 Christmas Eve on the Terrace.mp3","34 Christmas Eve on the Terrace II.mp3","35 Gingerbread and Books.mp3","36 Gingerbread and Books II.mp3","37 Frosted Glass.mp3","18 Little Paris Noel II.mp3","19 Fireside Bookshop.mp3","20 Fireside Bookshop II.mp3","21 Silent Snowfall.mp3","22 Silent Snowfall II.mp3","23 Cafe de Noel.mp3","24 Cafe de Noel II.mp3","25 Mistletoe Corner.mp3","26 Mistletoe Corner II.mp3","09 Garland Lights.mp3","10 Garland Lights II.mp3","11 Wreath on the Door.mp3","12 Wreath on the Door II.mp3","13 December Evening Stroll.mp3","14 December Evening Stroll II.mp3","15 Snow on the Cobblestones.mp3","16 Snow on the Cobblestones II.mp3","17 Little Paris Noel.mp3","04 Candlelight on Rue Lepic II.mp3","05 Snowflakes on the Awning.mp3","06 Snowflakes on the Awning II.mp3","07 Hot Cocoa Waltz.mp3","08 Hot Cocoa Waltz II.mp3","01 First Snow in Montmartre.mp3","02 First Snow in Montmartre II.mp3","03 Candlelight on Rue Lepic.mp3"]

def link(source,target):
    if target.exists():return
    try:os.link(source,target)
    except OSError:shutil.copy2(source,target)

def prepare(job_id,jobs,data,label,save):
    info=jobs[job_id];job=info['job'];name=label(info)
    if not any(channel in name for channel in ('Little Paris Jazz Cafe','Quiet Pines Cabin','Mountain View Cafe')):return False
    folder=Path(data)/job_id;visual=folder/'visual'
    if visual.is_dir() and any(visual.iterdir()):return False
    if not job.output.is_file():return False
    probe=subprocess.run(['ffprobe','-v','error','-show_entries','stream=codec_type,duration','-of','json',str(job.output)],capture_output=True,text=True,check=True)
    lengths={s['codec_type']:float(s.get('duration',0)) for s in json.loads(probe.stdout)['streams']}
    if any(not 29.95<=lengths.get(k,0)<=30.05 for k in ('video','audio')):return False
    # Prepare sound first: an interrupted music import must not look renderable.
    audio=folder/'ambient';tracks=folder/'tracks';audio.mkdir(exist_ok=True);tracks.mkdir(exist_ok=True)
    recipe={'approved_master':job.output.name,'video_seconds':30,'music_from_full_tracks':False}
    if 'Little Paris Jazz Cafe' in name:
        first=MUSIC_FIRST.get(job_id)
        if not first:return False
        pool={}
        for parent in (Path(data),Path(data)/'sources'):
            for candidate in sorted(parent.glob('*/tracks/*.mp3')):
                if candidate.name in MUSIC_NAMES and candidate.stat().st_size>500000:pool.setdefault(candidate.name,candidate)
        if first not in pool or len(pool)<6:return False
        others=sorted(set(pool)-{first});random.Random(int(hashlib.sha256(job_id.encode()).hexdigest(),16)).shuffle(others)
        selected=[first]+others
        paths=[]
        for i,track in enumerate(selected):
            target=tracks/(f'{i+1:03d} — '+track);link(pool[track],target);paths.append(target)
        job.tracks=paths;job.ambient=[]
        recipe.update(music_from_full_tracks=True,track_count=len(paths),track_order=selected)
        loudness=measure_loudness(job.output)
    else:
        sound=audio/'approved-ambience.wav';temporary=audio/'approved-ambience.tmp.wav'
        if not sound.exists():
            subprocess.run(['ffmpeg','-v','error','-y','-i',str(job.output),'-vn','-ar','48000','-ac','2','-c:a','pcm_s16le',str(temporary)],check=True,capture_output=True)
            temporary.replace(sound)
        job.ambient=[sound];job.tracks=[];loudness=measure_loudness(sound)
    visual.mkdir(exist_ok=True);source=visual/'approved-master.mp4';link(job.output,source);job.visuals=[source]
    s=job.settings;s.width=1920;s.height=1080;s.fps=24;s.duration=30;s.stabilize=False;s.smooth=False;s.loop_mode='chain';s.loop_crossfade=0;s.find_loop_point=False;s.speed=1;s.loudness=loudness;s.ambient_level=0
    recipe.update(loudness_lufs=loudness,whole_frame_stabilization=False,loop_mode='chain',loop_crossfade=0)
    (folder/'imported-recipe.json').write_text(json.dumps(recipe,ensure_ascii=False,indent=2),encoding='utf-8')
    save(job_id,info);return True
