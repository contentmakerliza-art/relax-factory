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
    recipe=base/'recipe-and-checks.json'
    if recipe.exists():
        value=json.loads(recipe.read_text())
        if value.get('publication_loop_mode')=='repeat':
            from cabin_loop_recipe import VERSION
            master=base/'loop-master.mp4'
            if value.get('builder_version')!=VERSION or hashlib.sha256(master.read_bytes()).hexdigest()!=value['loop_master_sha256']:
                raise ValueError('Cyclic recipe does not match master')
            out=base/'publication-loop.mp4';tmp=base/'publication-check';tmp.mkdir(exist_ok=True)
            settings=engine.RenderSettings(width=1920,height=1080,fps=24,loop_mode='repeat',loop_crossfade=0,
                stabilize=False,smooth=False,find_loop_point=False,video_bitrate='8M')
            original=engine._run
            def bounded(cmd):
                if cmd[0]=='ffmpeg':cmd=cmd[:1]+['-nostdin','-threads','1','-filter_complex_threads','1']+cmd[1:-1]+['-threads','2']+cmd[-1:]
                return original(cmd)
            engine._run=bounded
            seconds=engine.build_loop_segment([master],out,settings,tmp)
            if abs(seconds-value['loop_seconds'])>1/24:raise ValueError('Publication changed cycle duration')
            report=dict(validated_with_factory_engine=True,loop_seconds=seconds,crossfade_seconds=0,
                loop_builder_version=VERSION,publication_loop_mode='repeat',long_render_started=False,
                loop_master_sha256=value['loop_master_sha256'])
            result.write_text(json.dumps(report,indent=2));return report
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
