"""Outdoor Paris preview from a clean plate/checked loop and EXISTING snow.
No snowfall generation, model calls, publication or final render.
"""
import argparse,json,shutil,subprocess
from pathlib import Path


def render(plate,snow,music,output,outdoor_view):
    if not outdoor_view:raise ValueError('Whole-frame snow layer requires an outdoor viewpoint')
    for source in (plate,snow,music):
        if not source.is_file():raise ValueError('Missing preserved input: '+str(source))
    ff=shutil.which('ffmpeg');probe=shutil.which('ffprobe')
    if not ff or not probe:raise RuntimeError('Server FFmpeg is required')
    image=plate.suffix.lower() in ('.jpg','.jpeg','.png','.webp')
    if not image:
        result=subprocess.run([probe,'-v','error','-show_entries','format=duration','-of',
            'default=nw=1:nk=1',str(plate)],check=True,capture_output=True,text=True)
        if not 29.95<=float(result.stdout)<=30.05:
            raise ValueError('Use a checked 30-second motion loop; do not silently repeat a short clip')
    graph=('[0:v]scale=1920:1080:flags=lanczos,fps=24,format=yuv420p[bg];'
        '[1:v]format=gray[alpha];color=c=0xf5f8fa:s=1920x1080:r=24:d=30[white];'
        '[white][alpha]alphamerge[snow];[bg][snow]overlay=shortest=1:format=auto,format=yuv420p[v];'
        '[2:a]atrim=0:30,asetpts=PTS-STARTPTS,loudnorm=I=-19:TP=-2:LRA=5,'
        'afade=t=in:d=0.5,afade=t=out:st=28.5:d=1.5[a]')
    output.parent.mkdir(parents=True,exist_ok=True)
    temp=output.with_name(output.stem+'.partial.mp4')
    args=[ff,'-v','error','-nostdin','-y','-threads','1']
    if image:args+=['-loop','1','-framerate','24']
    args+=['-i',str(plate),'-i',str(snow),'-i',str(music),'-filter_complex_threads','1',
           '-filter_complex',graph,'-map','[v]','-map','[a]','-t','30','-r','24',
           '-c:v','libx264','-threads','2','-preset','fast','-crf','17','-pix_fmt','yuv420p',
           '-c:a','aac','-b:a','192k','-ar','48000','-ac','2','-movflags','+faststart',str(temp)]
    subprocess.run(args,check=True,capture_output=True,text=True)
    subprocess.run([ff,'-v','error','-nostdin','-threads','1','-i',str(temp),'-f','null','-'],check=True,capture_output=True)
    temp.replace(output)
    return dict(preview=str(output),seconds=30,snow_source=str(snow),snow_generation=False,
                long_final_started=False,owner_approval_unchanged=True)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ['plate','snow','music','output']:p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--outdoor-view',action='store_true');a=p.parse_args()
    print(json.dumps(render(a.plate,a.snow,a.music,a.output,a.outdoor_view),ensure_ascii=False))
