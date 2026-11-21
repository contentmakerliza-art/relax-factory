"""Bounded full-intro test of the real render path, without a 10h final."""
import argparse,json,math,sys
from pathlib import Path
from dataclasses import replace
from types import SimpleNamespace

LIB=Path('/data/sources/executor-library')
sys.path.insert(0,str(LIB/'tools/exhale-render-staging'))
from render import engine,preserved_exhale

def main(number,cycle_handoff=False):
    rows=json.loads((LIB/'exhale-publication-staging/manifest.json').read_text())
    row=next(r for r in rows if r['number']==number);source=LIB/'exhale-publication-staging'/row['job_id']
    out=LIB/'tests/preserved-exhale'/(str(number)+('-handoff' if cycle_handoff else ''));out.mkdir(parents=True,exist_ok=True)
    voice=source/'voice/00-arranged-voice.wav'
    # Full voice, full twenty-second fade, and five seconds of proven black screen.
    duration=605 if cycle_handoff else math.ceil(row['voice_seconds']+21)+5
    settings=engine.RenderSettings(width=1920,height=1080,fps=30,duration=duration,
        stabilize=False,loop_mode='none',loop_crossfade=0,video_bitrate='4M',audio_bitrate='320k')
    job=engine.Job([],[],out/'intro-then-black.mp4',settings,ambient=[source/'ambient/background.flac'],voice=voice)
    original=engine._run
    def bounded(cmd):
        if cmd[0]=='ffmpeg':
            cmd=cmd[:1]+['-nostdin','-threads','1','-filter_complex_threads','1']+cmd[1:-1]+['-threads','2']+cmd[-1:]
        return original(cmd)
    engine._run=bounded
    engine.render(job,lambda text,progress:print(json.dumps({'step':text,'progress':progress}),flush=True))
    print(json.dumps({'output':str(job.output),'seconds':duration,'number':number,'long_final_started':False}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--number',type=int,default=1)
    p.add_argument('--cycle-handoff',action='store_true');a=p.parse_args();main(a.number,a.cycle_handoff)
