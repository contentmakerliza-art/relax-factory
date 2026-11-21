"""Verify frozen recipes, approved openings and the actual full-intro export."""
import json,subprocess,sys
from pathlib import Path
from types import SimpleNamespace
import numpy as np

LIB=Path('/data/sources/executor-library');DATA=Path('/data')
sys.path.insert(0,str(LIB/'tools/exhale-render-staging'))
from render import preserved_exhale

def audio(path,start=0,seconds=30):
    r=subprocess.run(['ffmpeg','-v','error','-nostdin','-threads','1','-ss',str(start),'-i',str(path),
        '-t',str(seconds),'-vn','-ac','1','-ar','22050','-f','f32le','-'],capture_output=True,check=True)
    return np.frombuffer(r.stdout,np.float32).copy()

def correlation(a,b):
    count=min(len(a),len(b));a=a[44100:count-44100];b=b[44100:count-44100]
    return float(np.corrcoef(a,b)[0,1])

def frames(path):
    return subprocess.Popen(['ffmpeg','-v','error','-nostdin','-threads','1','-i',str(path),
        '-t','30','-vf','scale=640:360','-pix_fmt','gray','-threads','1','-f','rawvideo','-'],stdout=subprocess.PIPE)

def visual_difference(a,b):
    procs=[frames(a),frames(b)];diffs=[]
    try:
        while True:
            data=[p.stdout.read(640*360) for p in procs]
            if not any(data):break
            if any(len(x)!=640*360 for x in data):raise ValueError('Partial comparison frame')
            aa,bb=[np.frombuffer(x,np.uint8).astype(np.int16) for x in data]
            diffs.append(float(np.abs(aa-bb).mean()))
        if any(p.wait()!=0 for p in procs):raise ValueError('Decode failed')
    finally:
        for p in procs:
            p.stdout.close()
            if p.poll() is None:p.kill();p.wait()
    if len(diffs)!=900:raise ValueError('Expected all 900 approved opening frames')
    return max(diffs)

def main():
    rows=json.loads((LIB/'exhale-publication-staging/manifest.json').read_text());results=[]
    settings=SimpleNamespace(duration=36000,width=1920,height=1080,fps=30,logo='')
    for row in rows:
        root=LIB/'exhale-publication-staging'/row['job_id']
        job=SimpleNamespace(voice=root/'voice/00-arranged-voice.wav',ambient=[root/'ambient/background.flac'],tracks=[])
        recipe,*_=preserved_exhale.validate(job,settings)
        folder=DATA/row['job_id'];meta=json.loads((folder/'job.json').read_text());original=folder/meta['output']
        if meta['approval']['status']!='одобрено' or preserved_exhale.digest(original)!=recipe['approved_preview_sha256']:
            raise ValueError('Exact approval or original preview changed')
        expected=audio(job.voice)+audio(job.ambient[0],recipe['background_offset'])*recipe['background_gain']
        corr=correlation(audio(original),expected)
        if not np.isfinite(corr) or corr<.995:raise ValueError('Preserved opening sound differs from approval')
        results.append(dict(number=row['number'],job_id=row['job_id'],opening_audio_correlation=corr,
                            full_voice_seconds=recipe['voice_seconds'],date=row['publish_at']))
    rendered=LIB/'tests/preserved-exhale/1/intro-then-black.mp4';row=rows[0]
    root=DATA/row['job_id'];meta=json.loads((root/'job.json').read_text());original=root/meta['output']
    difference=visual_difference(original,rendered);actual_audio=correlation(audio(original),audio(rendered))
    full=json.loads(rendered.with_suffix('.preserved-exhale.json').read_text())
    black_at=full['intro_seconds']+2
    black=subprocess.run(['ffmpeg','-v','error','-nostdin','-ss',str(black_at),'-i',str(rendered),
        '-frames:v','1','-pix_fmt','gray','-threads','1','-f','rawvideo','-'],capture_output=True,check=True).stdout
    # Measure native pixels. Smooth gray downscaling can add one LSB to a black frame.
    if len(black)!=1920*1080:raise ValueError('Missing black tail')
    maximum=int(np.frombuffer(black,np.uint8).max())
    report=dict(passed=bool(difference<1 and actual_audio>.995 and maximum==0),
        recipes_checked=len(results),recipes=results,opening_frames_compared=900,
        max_opening_frame_mean_difference=difference,rendered_opening_audio_correlation=actual_audio,
        black_tail_max_pixel=maximum,full_intro_seconds=full['intro_seconds'],
        smoke_duration_seconds=full['full_seconds'],full_voice_hash_verified=True,
        complete_decode_performed=False,listening_performed=False,owner_approvals_changed=False)
    (LIB/'tests/preserved-exhale/quality-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='recipes'}),flush=True)
    if not report['passed']:raise ValueError('Full-intro smoke did not match approved opening')

if __name__=='__main__':main()
