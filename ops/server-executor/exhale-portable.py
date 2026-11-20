"""Rebuild a 30-second Exhale preview from preserved approved timelines.

No model calls, long finals, publication, or replacement of approved versions.
Run in the existing factory image with Pillow in the persistent runtime.
"""
import argparse,hashlib,json,math,os,subprocess,wave
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw,ImageFont


def run(args):
    return subprocess.run(args,check=True,capture_output=True,text=True)


def preview_pcm(source,start=0):
    # Decode thirty seconds only, matching the original NumPy mixer precisely.
    r=subprocess.run(['ffmpeg','-v','error','-nostdin','-ss',str(start),'-i',str(source),
        '-t','30','-ac','2','-ar','48000','-f','f32le','-'],check=True,capture_output=True)
    return np.frombuffer(r.stdout,np.float32).reshape(-1,2).copy()


def safe_asset(root,name):
    path=(root/name).resolve()
    if root.resolve() not in path.parents or not path.is_file():raise ValueError('Missing preserved asset: '+name)
    return path


def render_circle(mode,font_path,target):
    if target.exists():return
    width,height,diameter=1920,1080,486
    yy,xx=np.mgrid[:diameter,:diameter]
    radius=np.hypot(xx-diameter/2,yy-diameter/2)/(diameter/2)
    alpha=np.clip((1-radius)*6,0,1)*(.55+.45*(1-radius));alpha=np.clip(alpha,0,1)
    disc=Image.fromarray(np.stack([alpha*c for c in (200,205,255)],axis=2).astype(np.uint8))
    font=ImageFont.truetype(str(font_path),round(height*.035));cache={}
    temp=target.with_name(target.stem+'.partial.mp4')
    p=subprocess.Popen(['ffmpeg','-v','error','-nostdin','-y','-f','rawvideo','-pixel_format','rgb24',
        '-video_size',f'{width}x{height}','-framerate','30','-i','-','-an','-c:v','libx264',
        '-threads','2','-preset','veryfast','-crf','19','-pix_fmt','yuv420p','-movflags','+faststart',str(temp)],
        stdin=subprocess.PIPE)
    try:
        for i in range(900):
            t=i/30;size=0;caption=''
            for a,b,s0,s1,c in mode['phases']:
                if a<=t<b:size=s0+(s1-s0)*(1-math.cos(math.pi*(t-a)/(b-a)))/2;caption=c;break
            dia=int(diameter*(.35+.65*size)/2)*2
            if dia not in cache:cache[dia]=disc.resize((dia,dia),Image.Resampling.LANCZOS)
            im=Image.new('RGB',(width,height));im.paste(cache[dia],((width-dia)//2,(height-dia)//2))
            if caption:
                draw=ImageDraw.Draw(im);box=draw.textbbox((0,0),caption,font=font)
                draw.text(((width-(box[2]-box[0]))/2,height*.5+diameter*.6),caption,font=font,fill='#C7C2DD')
            if t<3:im=Image.blend(Image.new('RGB',(width,height)),im,t/3)
            p.stdin.write(im.tobytes())
        p.stdin.close()
        if p.wait()!=0:raise RuntimeError('Circle encoding failed')
    finally:
        if p.poll() is None:p.kill();p.wait()
    temp.replace(target)


def main(asset_root,output_root,number,background_db=0):
    if not -24<=background_db<=0:raise ValueError('Only bounded background reduction is supported')
    base=asset_root/'Исходники/Exhale to Sleep/Новые 20 проб'
    rows=json.loads((base/'Журнал производства.json').read_text())
    row=next(r for r in rows if r['number']==number)
    mode=json.loads((base/(row['mode']+' — синхронизация.json')).read_text())
    voice=safe_asset(asset_root,mode['voice_arranged']);background=safe_asset(asset_root,row['bank_file'])
    if not row.get('qc',{}).get('passed'):raise ValueError('Preserved preview recipe must already be checked')
    output_root.mkdir(parents=True,exist_ok=True)
    visual=output_root/(row['mode']+'-circle-30s.mp4')
    render_circle(mode,base/'DM Sans Medium.ttf',visual)
    target=output_root/(row['label']+'.mp4');temp=target.with_name(target.stem+'.partial.mp4')
    gain=float(row['background_gain'])*10**(background_db/20)
    # Stream just the required background interval; never decode all six banks into RAM.
    bg=preview_pcm(background,row['background_offset']);spoken=preview_pcm(voice)
    if len(bg)!=1440000 or len(spoken)!=1440000:raise ValueError('Incomplete thirty-second audio')
    bg*=gain;mix=spoken+bg
    if not np.isfinite(mix).all() or float(np.abs(mix).max())>=.93:
        raise ValueError('Audio mix exceeds the checked peak limit')
    mix[:480]*=np.linspace(0,1,480)[:,None];mix[-480:]*=np.linspace(1,0,480)[:,None]
    sound=output_root/(row['label']+' — source PCM.wav')
    with wave.open(str(sound),'wb') as f:
        f.setnchannels(2);f.setsampwidth(2);f.setframerate(48000)
        f.writeframes((np.clip(mix,-1,1)*32767).astype('<i2').tobytes())
    run(['ffmpeg','-v','error','-nostdin','-y','-threads','1','-i',str(visual),
         '-i',str(sound),'-map','0:v','-map','1:a',
         '-t','30','-c:v','copy','-c:a','aac','-b:a','192k','-ar','48000','-ac','2',
         '-movflags','+faststart',str(temp)])
    probe=json.loads(run(['ffprobe','-v','error','-show_streams','-of','json',str(temp)]).stdout)
    video=next(s for s in probe['streams'] if s['codec_type']=='video')
    audio=next(s for s in probe['streams'] if s['codec_type']=='audio')
    assert (video['width'],video['height'],video['r_frame_rate'])==(1920,1080,'30/1')
    assert int(video['nb_frames'])==900 and abs(float(audio['duration'])-30)<.05
    run(['ffmpeg','-v','error','-nostdin','-threads','1','-i',str(temp),'-f','null','-'])
    temp.replace(target)
    result=dict(preview=str(target),number=number,seconds=30,frames=900,mode=row['mode'],
        sha256=hashlib.sha256(target.read_bytes()).hexdigest(),rendered_on_server=True,
        voice_source=str(voice),background_source=str(background),background_gain=gain,
        source_pcm=str(sound),
        background_adjustment_db=background_db,
        owner_approval_unchanged=True,long_final_started=False)
    target.with_suffix('.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--assets',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--number',type=int,required=True)
    p.add_argument('--background-db',type=float,default=0)
    args=p.parse_args();main(args.assets,args.output,args.number,args.background_db)
