"""Render a frozen, approved Exhale timeline once, followed by black video.

Only prepared inputs with matching hashes activate this path. No speech
recognition, alignment, new voice generation or loudness normalization.
"""
import fcntl,hashlib,json,math,os,re,subprocess,sys,wave
from pathlib import Path
from dataclasses import replace

MARKER='zz-preserved-exhale.json'
VERSION=1

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def checked_file(folder,entry):
    name=entry['name']
    if not isinstance(name,str) or name in ('.','..') or Path(name).name!=name:
        raise ValueError('Preserved Exhale: invalid input name')
    path=folder/name
    if not path.is_file() or digest(path)!=entry['sha256']:
        raise ValueError('Preserved Exhale: source missing or changed')
    return path

def validate(job,s):
    voice_dir=job.voice.parent
    recipe=json.loads((voice_dir/MARKER).read_text())
    if recipe.get('schema')!=VERSION or recipe.get('kind')!='exhale-preserved-v1':
        raise ValueError('Unknown preserved Exhale recipe')
    voice=checked_file(voice_dir,recipe['voice'])
    font=checked_file(voice_dir,recipe['font'])
    backgrounds=job.ambient if isinstance(job.ambient,list) else [job.ambient]
    if len(backgrounds)!=1 or backgrounds[0] is None:raise ValueError('One preserved background required')
    background=checked_file(backgrounds[0].parent,recipe['background'])
    if voice!=job.voice or background!=backgrounds[0]:raise ValueError('Renderer inputs differ from recipe')
    with wave.open(str(voice)) as f:
        if (f.getnchannels(),f.getsampwidth(),f.getframerate())!=(2,2,48000):
            raise ValueError('Expected preserved stereo PCM voice')
        length=f.getnframes()/f.getframerate()
    if not 60<length<210 or abs(recipe['voice_seconds']-length)>.001:
        raise ValueError('Complete intro voice required')
    intro_length=math.ceil(length+21)
    if not intro_length<=s.duration<=36000 or (s.width,s.height,s.fps)!=(1920,1080,30):
        raise ValueError('Unexpected Exhale render dimensions or duration')
    if s.logo or job.tracks:raise ValueError('No music or logo on preserved black-screen episode')
    for key,low,high in [('background_gain',.00001,1),('after_gain',.00001,1),
                         ('background_offset',0,147),('rise',30,length)]:
        value=recipe[key]
        if not isinstance(value,(int,float)) or not math.isfinite(value) or not low<=value<=high:
            raise ValueError('Invalid preserved audio parameter: '+key)
    previous=0
    for a,b,x,y,caption in recipe['phases']:
        if not (math.isfinite(a+b+x+y) and a>=previous and b>a and 0<=x<=1 and 0<=y<=1
                and caption in ('','inhale','hold','exhale')):raise ValueError('Invalid breathing timeline')
        previous=b
    if not recipe['phases'] or recipe['phases'][-1][1]<intro_length:
        raise ValueError('Timeline does not cover the complete fade')
    return recipe,voice,font,background,intro_length

def draw_circle(recipe,font_path,target,length,fade_start):
    # The same Pillow geometry, easing, font and colour as the approved previews.
    try:from PIL import Image,ImageDraw,ImageFont
    except ImportError:
        runtime=Path(os.environ.get('APP_DATA','/data'))/'sources/executor-library/runtime/python3.12'
        sys.path.insert(0,str(runtime));from PIL import Image,ImageDraw,ImageFont
    import numpy as np
    width,height,diameter=1920,1080,486
    yy,xx=np.mgrid[:diameter,:diameter]
    radius=np.hypot(xx-diameter/2,yy-diameter/2)/(diameter/2)
    alpha=np.clip((1-radius)*6,0,1)*(.55+.45*(1-radius));alpha=np.clip(alpha,0,1)
    disc=Image.fromarray(np.stack([alpha*c for c in (200,205,255)],axis=2).astype(np.uint8))
    font=ImageFont.truetype(str(font_path),round(height*.035));cache={}
    partial=target.with_suffix('.partial.mp4')
    proc=subprocess.Popen(['ffmpeg','-v','error','-nostdin','-y','-f','rawvideo','-pixel_format','rgb24',
        '-video_size',f'{width}x{height}','-framerate','30','-i','-','-an','-c:v','libx264',
        '-threads','2','-preset','veryfast','-crf','19','-pix_fmt','yuv420p','-movflags','+faststart',str(partial)],
        stdin=subprocess.PIPE)
    try:
        for i in range(length*30):
            t=i/30;size=0;caption=''
            for a,b,s0,s1,c in recipe['phases']:
                if a<=t<b:size=s0+(s1-s0)*(1-math.cos(math.pi*(t-a)/(b-a)))/2;caption=c;break
            dia=int(diameter*(.35+.65*size)/2)*2
            if dia not in cache:cache[dia]=disc.resize((dia,dia),Image.Resampling.LANCZOS)
            im=Image.new('RGB',(width,height));im.paste(cache[dia],((width-dia)//2,(height-dia)//2))
            if caption:
                draw=ImageDraw.Draw(im);box=draw.textbbox((0,0),caption,font=font)
                draw.text(((width-(box[2]-box[0]))/2,height*.5+diameter*.6),caption,font=font,fill='#C7C2DD')
            if t<3:im=Image.blend(Image.new('RGB',(width,height)),im,t/3)
            if t>fade_start:im=Image.blend(Image.new('RGB',(width,height)),im,max(0,1-(t-fade_start)/20))
            proc.stdin.write(im.tobytes())
        proc.stdin.close()
        if proc.wait()!=0:raise RuntimeError('Full Exhale intro encoding failed')
    finally:
        if proc.poll() is None:proc.kill();proc.wait()
    partial.replace(target)

def cached_intro(recipe,font,length,voice_length):
    cache=Path(os.environ.get('APP_DATA','/data'))/'sources/executor-library/final-intros'
    cache.mkdir(parents=True,exist_ok=True)
    identity=dict(version=VERSION,phases=recipe['phases'],voice_length=voice_length,font=recipe['font']['sha256'])
    key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    target=cache/(key+'.mp4');receipt=cache/(key+'.json')
    with (cache/(key+'.lock')).open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if target.exists() and receipt.exists() and json.loads(receipt.read_text()).get('sha256')==digest(target):return target
        draw_circle(recipe,font,target,length,voice_length)
        receipt.write_text(json.dumps(dict(sha256=digest(target),identity=identity,seconds=length)))
    return target

def build_audio(recipe,voice,background,dst,s,tmp,engine,encode=True):
    n=600*48000  # Whole AAC frames; voice and its 20-second fade fit entirely in the head.
    native_level=engine.measure_loudness(background)
    cycle=tmp/'preserved-cycle.wav'
    settings=replace(s,loudness=native_level,ambient_level=0)
    engine._ambient_cycle(background,cycle,n,settings,tmp,level=0)
    if recipe['after_gain']!=1:
        quiet=tmp/'preserved-cycle-quiet.wav'
        engine._run(['ffmpeg','-y','-i',str(cycle),'-af',f"volume={recipe['after_gain']:.12f}",'-c:a','pcm_s16le',str(quiet)])
        cycle=quiet
    # Preserve the approved opening sample exactly. Blend onto the seamless bank
    # at 30..33 seconds; the rest of the head matches the cycle's sample positions.
    ratio=recipe['background_gain']/recipe['after_gain'];r=recipe['rise']
    volume=f'if(lt(t,{r}),{ratio:.12f},if(lt(t,{r}+15),{ratio:.12f}+(1-{ratio:.12f})*(t-{r})/15,1))'
    head=tmp/'preserved-head.wav'
    filters=(f"[0:a]atrim=duration=33,asetpts=PTS-STARTPTS,volume={recipe['after_gain']:.12f}[start];"
        '[1:a]atrim=start=30,asetpts=PTS-STARTPTS[tail];'
        '[start][tail]acrossfade=d=3:c1=tri:c2=tri[bed];'
        f"[bed]volume='{volume}':eval=frame[bg];"
        '[2:a]apad[voice];[bg][voice]amix=inputs=2:normalize=0:duration=first,'
        'afade=t=in:st=0:d=0.01,atrim=end_sample=28800000[a]')
    engine._run(['ffmpeg','-y','-ss',str(recipe['background_offset']),'-i',str(background),
        '-i',str(cycle),'-i',str(voice),'-filter_complex',filters,'-map','[a]',
        '-ar','48000','-ac','2','-c:a','pcm_s16le',str(head)])
    meter=engine._run(['ffmpeg','-nostats','-i',str(head),'-af','volumedetect','-f','null','-'])
    peak=re.search(r'max_volume: (-?[\d.]+) dB',meter)
    if not peak or float(peak.group(1))>-.6:raise ValueError('Preserved audio mix exceeds checked peak limit')
    if not encode:return cycle,head
    # The shared encoder plays `head` once, then only the background cycle.
    engine.encode_seamless_aac(cycle,dst,s.duration,s.audio_bitrate,tmp,head)

def render(job,s,say,tmp,engine):
    recipe,voice,font,background,intro_length=validate(job,s)
    say('Собираю сохранённое вступление Exhale',.05)
    intro=cached_intro(recipe,font,intro_length,recipe['voice_seconds'])
    black=tmp/'black.mp4'
    engine.breathing.black_video(black,s.width,s.height,s.fps,engine._video_codec_args(s),engine._run)
    say('Собираю полный звук без повторения голоса',.4)
    audio=tmp/'audio.m4a';build_audio(recipe,voice,background,audio,s,tmp,engine)
    listing=tmp/'preserved-repeat.txt'
    listing.write_text(f"file '{intro}'\n"+f"file '{black}'\n"*(math.ceil(s.duration/10)+1))
    say('Соединяю вступление и чёрный экран',.8)
    engine._run(['ffmpeg','-y','-f','concat','-safe','0','-i',str(listing),'-i',str(audio),
        '-map','0:v','-map','1:a','-c','copy','-t',str(s.duration),str(job.output)])
    job.previews=engine.make_previews(intro,intro_length,job.output)
    job.timecodes='';job.warning=''
    # Copy the shared cached intro before the kit moves its own files.
    import shutil
    intro_copy=tmp/'intro.mp4';shutil.copy2(intro,intro_copy)
    engine._kit(job,[intro_copy],black,audio)
    job.output.with_suffix('.preserved-exhale.json').write_text(json.dumps(dict(
        recipe=recipe,voice_plays_once=True,intro_seconds=intro_length,black_after_intro=True,
        full_seconds=s.duration,renderer_version=VERSION),ensure_ascii=False,indent=2))
    engine.make_check_clips(job);say('Готово',1)
    return job.output
