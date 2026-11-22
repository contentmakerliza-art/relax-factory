"""Server-only full-frame preview builder. Never publishes or approves results."""
import argparse
import json
import math
from pathlib import Path
import re
import subprocess


def run(*args):
    r = subprocess.run(list(args), capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if r.returncode:
        raise RuntimeError('Server media command failed: '+r.stderr[-1500:])
    return r.stdout


def main(request_id):
    if not re.fullmatch('[a-z0-9-]{16,80}', request_id):
        raise ValueError('Invalid request ID')
    import cabin_backlog_registry as backlog
    if backlog.attempt(request_id):
        import runpy
        return runpy.run_path('/opt/relax-codex/build-cabin-loop.py')['main'](request_id)
    folder = Path('/opt/relax-codex/assets') / request_id
    folder.mkdir(exist_ok=True)
    if (folder/'recipe-and-checks.json').exists() and (folder/'preview.mp4').is_file():
        old=json.loads((folder/'recipe-and-checks.json').read_text())
        if old.get('technical_check')=='passed' and (folder/'preview.mp4').stat().st_size>10000:
            print(json.dumps({'existing_checked_preview':str(folder/'preview.mp4')}));return
    source = Path('/opt/marketplace-analytics/studio-downloads') / (request_id+'.mp4')
    if not source.is_file():
        raise ValueError('No downloaded video')
    audio = Path('/opt/relax-codex/assets/cabin-approved-fireplace-9.wav')
    prefix = '/tmp/'+request_id
    run('docker', 'exec', 'relax-factory', 'mkdir', '-p', prefix)
    run('docker', 'cp', str(source), 'relax-factory:'+prefix+'/source.mp4')
    run('docker', 'cp', str(audio), 'relax-factory:'+prefix+'/audio.wav')
    probe = json.loads(run('docker','exec','relax-factory','ffprobe','-v','error',
                          '-show_streams','-of','json',prefix+'/source.mp4'))
    stream = next(s for s in probe['streams'] if s['codec_type']=='video')
    duration = float(stream['duration'])
    if duration < 7.99 or duration > 10.2:
        raise ValueError('Need a clean eight-to-ten-second source, never a three-second loop')
    frames = min(240, math.floor(duration * 24 + .01))
    seconds = frames / 24
    step = seconds - .75
    count = math.ceil((30 - seconds) / step) + 1
    filters = [f'[{i}:v]fps=24,trim=end_frame={frames},settb=1/24,setpts=N,setsar=1,format=yuv420p,fps=24[v{i}]' for i in range(count)]
    previous = 'v0'
    for i in range(1, count):
        filters.append(f'[{previous}][v{i}]xfade=transition=fade:duration=0.75:offset={i * step:.6f},settb=1/24,fps=24[x{i}]')
        previous = f'x{i}'
    # Blend at source resolution; upscale once to keep memory bounded.
    filters.append(f'[{previous}]scale=1920:1080:flags=lanczos,format=yuv420p,fps=24[full]')
    command = ['docker','exec','relax-factory','ffmpeg','-nostdin','-v','error','-n',
               '-filter_complex_threads','1']
    for _ in range(count): command += ['-threads','1','-i',prefix+'/source.mp4']
    command += ['-i',prefix+'/audio.wav','-filter_complex',';'.join(filters),
                '-map','[full]','-map',f'{count}:a:0','-t','30','-r','24','-c:v','libx264',
                '-threads','2','-preset','fast','-crf','19','-pix_fmt','yuv420p',
                '-c:a','aac','-b:a','192k','-movflags','+faststart',prefix+'/preview.mp4']
    run(*command)
    run('docker','cp','relax-factory:'+prefix+'/preview.mp4',str(folder/'preview.mp4'))
    check = json.loads(run('docker','exec','relax-factory','ffprobe','-v','error',
                          '-show_streams','-of','json',prefix+'/preview.mp4'))
    for kind in ('audio','video'):
        s = next(s for s in check['streams'] if s['codec_type']==kind)
        if abs(float(s['duration'])-30)>0.06: raise ValueError('Duration mismatch')
    volume = subprocess.run(['docker','exec','relax-factory','ffmpeg','-v','info',
        '-i',prefix+'/preview.mp4','-af','volumedetect','-vn','-f','null','-'],
        capture_output=True,text=True,check=True).stderr
    report = {'request_id':request_id,'preview':str(folder/'preview.mp4'),
              'full_frame_only':True,'local_masks':False,'audio_source':str(audio),
              'source_seconds':seconds,'source_frames':frames,'repeat_inputs':count,
              'technical_check':'passed','visual_motion_review':'PENDING',
              'listening_review':'PENDING','delivery':'HELD_UNTIL_QA',
              'audio_measurement':volume[-2000:],'command':command}
    (folder/'recipe-and-checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k not in ('command','audio_measurement')}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('request_id')
    main(parser.parse_args().request_id)
