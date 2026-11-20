"""Test the real factory loop recipe on a short approved-preview candidate.
Run inside the factory. Does not approve, queue or produce a long final.
"""
import argparse,hashlib,json,sys
from pathlib import Path
sys.path.insert(0,'/app')
from render import engine


def main(rid):
    base=Path('/tmp')/rid;result=base/'publication-loop-check.json'
    if result.exists():return json.loads(result.read_text())
    source=base/'preview.mp4';output=base/'publication-loop.mp4'
    original=engine._run
    def limited(cmd):
        if cmd[0]=='ffmpeg':
            cmd=cmd[:1]+['-nostdin','-threads','1','-filter_complex_threads','1']+cmd[1:-1]+['-threads','2']+cmd[-1:]
        return original(cmd)
    engine._run=limited
    settings=engine.RenderSettings(width=1920,height=1080,fps=24,loop_crossfade=.75,
        stabilize=False,smooth=False,video_bitrate='4M')
    engine._crossfade_loop(source,output,30,settings)
    duration=engine.probe_duration(output)
    if abs(duration-29.25)>.06:raise ValueError('Publication loop duration mismatch')
    limited(['ffmpeg','-v','error','-i',str(output),'-an','-f','null','-'])
    value=dict(validated_with_factory_engine=True,loop_seconds=duration,
        crossfade_seconds=.75,engine_sha256=hashlib.sha256(Path(engine.__file__).read_bytes()).hexdigest(),
        long_render_started=False)
    result.write_text(json.dumps(value,indent=2));return value


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('request_id');print(json.dumps(main(p.parse_args().request_id)))
