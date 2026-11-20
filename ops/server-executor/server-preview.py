"""Server-only full-frame preview builder. Never publishes or approves results."""
import argparse
import json
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
    if float(stream['duration'])<9.9:
        raise ValueError('Need a complete ten-second clip')
    filters = [f'[{i}:v]fps=24,trim=end_frame=240,settb=1/24,setpts=N,scale=1920:1080:flags=lanczos,setsar=1,format=yuv420p,fps=24[v{i}]' for i in range(4)]
    filters += ['[v0][v1]xfade=transition=fade:duration=0.75:offset=9.25,settb=1/24,fps=24[x1]',
                '[x1][v2]xfade=transition=fade:duration=0.75:offset=18.5,settb=1/24,fps=24[x2]',
                '[x2][v3]xfade=transition=fade:duration=0.75:offset=27.75[full]']
    command = ['docker','exec','relax-factory','ffmpeg','-nostdin','-v','error','-n',
               '-filter_complex_threads','1']
    for _ in range(4): command += ['-i',prefix+'/source.mp4']
    command += ['-i',prefix+'/audio.wav','-filter_complex',';'.join(filters),
                '-map','[full]','-map','4:a:0','-t','30','-r','24','-c:v','libx264',
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
              'technical_check':'passed','visual_motion_review':'PENDING',
              'listening_review':'PENDING','delivery':'HELD_UNTIL_QA',
              'audio_measurement':volume[-2000:],'command':command}
    (folder/'recipe-and-checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k not in ('command','audio_measurement')}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('request_id')
    main(parser.parse_args().request_id)
