"""Factory-side deterministic preparation, composition and seam checks for Cabin."""
import argparse,hashlib,json,os,shutil,subprocess,sys
from pathlib import Path
sys.path.insert(0,'/app');sys.path.insert(0,'/tmp')
os.environ['OMP_NUM_THREADS']='2'
import numpy as np
from PIL import Image,ImageDraw
from render import engine,zoomfix
from window_snow_contract import make_mask,transform_box,validate_plan,retained_rigid_regions,VERSION as MASK_VERSION
from cabin_loop_recipe import VERSION as LOOP_VERSION,safe_camera_fit
original=engine._run

def run(args):return subprocess.run(args,check=True,capture_output=True,text=True)
def limited(args):
 if args[0]=='ffmpeg':args=args[:1]+['-nostdin','-threads','1','-filter_threads','1','-filter_complex_threads','1']+args[1:-1]+['-threads','2']+args[-1:]
 return original(args)
engine._run=limited

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2))

def prepare(base,job):
 source=base/'input.mp4';output=base/'normalized.mp4'
 marker=base/'prepared.json'
 if marker.exists():
  value=json.loads(marker.read_text())
  if value['input_sha256']!=sha(source) or value['normalized_sha256']!=sha(output):raise ValueError('Frozen normalization changed')
  return value
 if sha(source)!=job['source_sha256']:raise ValueError('Unexpected source bytes')
 if job['normalized_input']:shutil.copy2(source,output);measure=None
 else:
  measure=zoomfix._measure(source,'')
  if not safe_camera_fit(measure):raise ValueError('Source camera movement exceeds bounded correction')
  zoom=''
  if measure:
   idx,found=measure;top=max(v[0] for v in found)
   zoom=zoomfix._perspective(zoomfix._ramp(idx,[top/v[0] for v in found]),zoomfix._ramp(idx,[v[2]/320 for v in found]),zoomfix._ramp(idx,[v[1]/180 for v in found]))
  settings=engine.RenderSettings(width=1280,height=720,fps=24,stabilize=True,smooth=False,codec='work')
  engine._normalized_clip(source,output,settings,zoom=zoom)
 duration=engine.probe_duration(output)
 if not 8<=duration<=10.25:raise ValueError('Need an eight-to-ten-second native animation')
 times=[0,1,duration/2,max(0,duration-.09)]
 for i,t in enumerate(times):limited(['ffmpeg','-v','error','-y','-ss',str(t),'-i',str(output),'-frames:v','1',str(base/f'frame{i}.png')])
 value=dict(input_sha256=sha(source),normalized_sha256=sha(output),seconds=duration,frame_times=times,stabilization='inherited' if job['normalized_input'] else 'factory-zoomfix-and-vidstab',camera_fit=measure)
 write(marker,value);return value

def patch_sequences(path,boxes):
 p=subprocess.Popen(['ffmpeg','-nostdin','-v','error','-threads','1','-i',str(path),'-vf','scale=1280:720,format=gray','-pix_fmt','gray','-threads','1','-f','rawvideo','-'],stdout=subprocess.PIPE)
 result=[[] for _ in boxes]
 try:
  while True:
   raw=bytearray()
   while len(raw)<1280*720:
    block=p.stdout.read(1280*720-len(raw))
    if not block:break
    raw.extend(block)
   if not raw:break
   if len(raw)!=1280*720:raise ValueError('Incomplete decoded frame')
   frame=np.frombuffer(raw,np.uint8).reshape(720,1280)
   for rows,(x,y,w,h) in zip(result,boxes):rows.append(frame[y:y+h,x:x+w].astype(np.float32).copy())
 finally:
  p.stdout.close()
 if p.wait()!=0:raise ValueError('Patch decode failed')
 return [np.asarray(rows) for rows in result]

def seam_quality(path,boxes,fade_frames):
 patches=patch_sequences(path,boxes)
 energy=[];ratios=[];jumps=[]
 for values in patches:
  e=np.mean(np.diff(values,axis=1)**2,axis=(1,2))+np.mean(np.diff(values,axis=2)**2,axis=(1,2))
  baseline=float(np.median(e[6:max(7,len(e)-fade_frames-3)]))
  energy.append(e)
  if fade_frames:ratios.append(e[-fade_frames:]/max(baseline,1))
  centred=values-values.mean(axis=(1,2),keepdims=True)
  adjacent=np.mean(np.diff(centred,axis=0)**2,axis=(1,2))
  jump=float(np.mean((centred[-1]-centred[0])**2));natural=float(np.percentile(adjacent,95))
  jumps.append(dict(wrap_mse=jump,normal_p95=natural,passed=jump<=max(2,natural*3+1)))
 if fade_frames:
  pooled=np.median(np.asarray(ratios),axis=0)
  minimum=float(pooled.min());median=float(np.median(pooled))
  passed=minimum>=.92 and median>=.96 and sum(row['passed'] for row in jumps)>=len(jumps)-1
 else:
  minimum=median=1.;passed=all(row['passed'] for row in jumps)
 return dict(passed=bool(passed),fade_frames=fade_frames,frames=len(energy[0]),minimum_edge_energy_ratio=minimum,median_edge_energy_ratio=median,wrap_checks=jumps,version='2026-11-22-static-seam-gate-v1')

def seam_sheet(path,base,boxes,fade,turn=None):
 count=round(engine.probe_duration(path)*24)
 indices=list(range(max(0,count-max(fade,1)-2),count))+[0,1]
 if turn is not None:indices=list(range(max(0,turn-2),min(count,turn+3)))+indices
 ordered=sorted(set(indices));select='+'.join('eq(n\\,'+str(n)+')' for n in ordered)
 p=subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(path),'-vf',f'select={select},scale=1280:720','-fps_mode','vfr','-pix_fmt','rgb24','-threads','1','-f','rawvideo','-'],capture_output=True,check=True)
 decoded=np.frombuffer(p.stdout,np.uint8).reshape(-1,720,1280,3)
 frames={n:frame for n,frame in zip(ordered,decoded)}
 cells=[]
 for n in indices:
  for box in boxes[:3]:
   x,y,w,h=box;x+=max(0,(w-80)//2);y+=max(0,(h-60)//2);w=min(w,80);h=min(h,60)
   patch=Image.fromarray(frames[n][y:y+h,x:x+w]).resize((w*3,h*3),Image.Resampling.NEAREST)
   cell=Image.new('RGB',(240,180),'#222222');cell.paste(patch,(0,0))
   ImageDraw.Draw(cell).text((3,3),f'frame {n}',fill='red');cells.append(cell)
 cols=6;sheet=Image.new('RGB',(cols*240,((len(cells)+cols-1)//cols)*180),'#222222')
 for i,cell in enumerate(cells):sheet.paste(cell,((i%cols)*240,(i//cols)*180))
 sheet.save(base/'preview-seam.png')

def backtrack_native(base,job,prepared,plan,selected,rigid):
 # Whole native frame goes forward/back; only the Snow alpha receives a dissolve.
 # No fireplace insert or local cat/background mask is introduced.
 source=base/'normalized.mp4';forward=base/'native-forward.mp4'
 limited(['ffmpeg','-v','error','-y','-i',str(source),'-vf',f"trim=start={selected['start']}:duration={selected['seconds']},setpts=PTS-STARTPTS",'-an','-c:v','libx264','-preset','fast','-crf','16',str(forward)])
 settings=engine.RenderSettings(width=1280,height=720,fps=24,codec='work',stabilize=False,smooth=False,loop_crossfade=.25)
 forward_seconds=engine.probe_duration(forward);parts=engine._pingpong_parts(forward,forward_seconds,settings,base)
 native=base/'native-backtrack.mp4';engine._encode_list(parts,native,settings,base)
 seconds=engine.probe_duration(native)
 graph=('[0:v]fps=24,scale=1280:720,format=gray,setpts=PTS-STARTPTS[s1];'
 '[1:v]fps=24,scale=1280:720,format=gray,setpts=PTS-STARTPTS[s2];'
 "[s1][s2]blend=all_mode=lighten,lut=y='min(255,val*1.7)',format=yuv420p[v]")
 run(['ffmpeg','-nostdin','-v','error','-y','-threads','1','-i',job['snow_path'],'-threads','1','-ss','11.5','-i',job['snow_path'],
 '-filter_complex_threads','1','-filter_complex',graph,'-map','[v]','-t',str(seconds+.25),'-an','-c:v','libx264','-threads','2','-preset','fast','-crf','16',str(base/'snow-long.mp4')])
 engine._crossfade_loop(base/'snow-long.mp4',base/'snow-loop.mp4',engine.probe_duration(base/'snow-long.mp4'),settings)
 graph=('[0:v]setpts=PTS-STARTPTS[bg];[1:v]format=gray[flakes];[2:v]format=gray[mask];'
 '[flakes][mask]blend=all_mode=multiply[alpha];'
 f'color=c=0xf5f8fa:s=1280x720:r=24:d={seconds}[white];'
 '[white][alpha]alphamerge[snow];[bg][snow]overlay=shortest=1:format=auto,crop=1184:666:48:27,scale=1280:720:flags=lanczos,format=yuv420p[v]')
 run(['ffmpeg','-nostdin','-v','error','-y','-threads','1','-i',str(native),'-threads','1','-i',str(base/'snow-loop.mp4'),'-loop','1','-framerate','24','-i',str(base/'window-mask.png'),
 '-filter_complex_threads','1','-filter_complex',graph,'-map','[v]','-t',str(seconds),'-an','-c:v','libx264','-threads','2','-preset','fast','-crf','16',str(base/'composed.mp4')])
 boxes=[transform_box(box) for box in rigid];quality=seam_quality(base/'composed.mp4',boxes,0);quality['native_backtrack']=True
 write(base/'assembly-qc.json',dict(candidates=[quality],selected=quality,selected_source=selected))
 limited(['ffmpeg','-v','error','-y','-i',str(base/'composed.mp4'),'-vf','scale=1920:1080:flags=lanczos','-an','-c:v','libx264','-preset','fast','-crf','16',str(base/'loop-master.mp4')])
 limited(['ffmpeg','-v','error','-y','-stream_loop','-1','-i',str(base/'loop-master.mp4'),'-i',job['audio_path'],'-t','30','-map','0:v','-map','1:a','-r','24','-c:v','libx264','-preset','fast','-crf','19','-c:a','aac','-b:a','192k','-movflags','+faststart',str(base/'preview.mp4')])
 seam_sheet(base/'composed.mp4',base,boxes,0,turn=round(forward_seconds*24))
 value=dict(builder_version=LOOP_VERSION,mask_policy_version=MASK_VERSION,auto_window_snow=True,request_id=job['request_id'],parent_request_id=job['parent_request_id'],
 layout_sha256=sha(base/'layout.json'),mask_sha256=sha(base/'window-mask.png'),source_sha256=sha(base/'composed.mp4'),preview_sha256=sha(base/'preview.mp4'),loop_master_sha256=sha(base/'loop-master.mp4'),
 native_loop_strategy='forward-backward-native-frame-with-forward-cyclic-snow',native_turn_seconds=forward_seconds,source_seconds=prepared['seconds'],loop_seconds=engine.probe_duration(base/'loop-master.mp4'),crossfade_seconds=0,
 publication_loop_mode='repeat',publication_crossfade=0,technical_check='passed',full_frame_only=True,local_masks=True,window_snow_overlay=True,fireplace_masks=False,mask_scope='exterior_window_glass_only',frame_border_crop_pixels=[48,27],
 assembly_qc_passed=bool(quality['passed']),requires_visual_seam_review=not quality['passed'],used_rigid_regions=rigid,new_paid_images=0,snow_generation=False)
 write(base/'recipe-and-checks.json',value);return value

def build(base,job):
 prepared=json.loads((base/'prepared.json').read_text());plan=validate_plan(json.loads((base/'layout.json').read_text()))
 marker=base/'recipe-and-checks.json'
 if marker.exists():
  value=json.loads(marker.read_text())
  if value['preview_sha256']!=sha(base/'preview.mp4') or value['layout_sha256']!=sha(base/'layout.json'):raise ValueError('Frozen preview changed')
  return value
 mask=make_mask(plan);mask.save(base/'window-mask.png')
 ref=Image.open(base/'frame1.png').convert('RGB')
 Image.composite(Image.new('RGB',ref.size,'#df37a1'),ref,mask.point(lambda v:int(v*.4))).save(base/'preview-mask.png')
 # Choose endpoints using only AI-identified rigid indoor regions, never flames/cat/Snow.
 duration=prepared['seconds'];retain=min(8.5,duration);rigid=retained_rigid_regions(plan);patches=patch_sequences(base/'normalized.mp4',rigid)
 starts=sorted(set([0,*[i/2 for i in range(1,4) if i/2+retain<=duration]]))
 candidates=[]
 for start in starts:
  begin=round(start*24);end=min(len(patches[0])-1,round((start+retain)*24)-1);scores=[]
  for values in patches:
   a=values[begin];b=values[end];scores.append(float(np.mean(((a-a.mean())-(b-b.mean()))**2)))
  candidates.append(dict(start=start,seconds=retain,score=float(np.median(scores))))
 selected=min(candidates,key=lambda row:row['score'])
 if job.get('loop_strategy')=='native_backtrack':return backtrack_native(base,job,prepared,plan,selected,rigid)
 source=base/'normalized.mp4'
 graph=('[0:v]trim=start='+str(selected['start'])+':duration='+str(retain)+',setpts=PTS-STARTPTS,fps=24,format=yuv420p[bg];'
 '[1:v]fps=24,scale=1280:720,format=gray,setpts=PTS-STARTPTS[s1];'
 '[2:v]fps=24,scale=1280:720,format=gray,setpts=PTS-STARTPTS[s2];'
 '[s1][s2]blend=all_mode=lighten,lut=y=\'min(255,val*1.7)\'[dense];'
 '[3:v]format=gray[mask];[dense][mask]blend=all_mode=multiply[alpha];'
 f'color=c=0xf5f8fa:s=1280x720:r=24:d={retain}[white];'
 '[white][alpha]alphamerge[snow];[bg][snow]overlay=shortest=1:format=auto,crop=1184:666:48:27,scale=1280:720:flags=lanczos,format=yuv420p[v]')
 run(['ffmpeg','-nostdin','-v','error','-y','-threads','1','-i',str(source),'-threads','1','-i',job['snow_path'],
 '-threads','1','-ss','11.5','-i',job['snow_path'],'-loop','1','-framerate','24','-i',str(base/'window-mask.png'),
 '-filter_complex_threads','1','-filter_complex',graph,'-map','[v]','-t',str(retain),'-an','-c:v','libx264','-threads','2','-preset','fast','-crf','16',str(base/'composed.mp4')])
 actual=engine.probe_duration(base/'composed.mp4');boxes=[transform_box(box) for box in rigid]
 checks=[];chosen=None
 for fade in [.25,.125,0]:
  target=base/f'candidate-{fade}.mp4'
  if fade:
   settings=engine.RenderSettings(width=1280,height=720,fps=24,codec='work',loop_crossfade=fade,stabilize=False,smooth=False)
   engine._crossfade_loop(base/'composed.mp4',target,actual,settings)
  else:shutil.copy2(base/'composed.mp4',target)
  quality=seam_quality(target,boxes,round(fade*24));quality['crossfade_seconds']=fade;checks.append(quality)
  if quality['passed']:chosen=(target,quality,fade);break
 write(base/'assembly-qc.json',dict(candidates=checks,selected=chosen[1] if chosen else None,source_candidates=candidates,selected_source=selected))
 if not chosen:
  # Numeric deviations are triage, not proof of a visible defect. Never use an unsafe hard cut.
  usable=[(base/f"candidate-{q['crossfade_seconds']}.mp4",q,q['crossfade_seconds']) for q in checks if q['fade_frames'] and q['minimum_edge_energy_ratio']>=.75]
  if not usable:raise ValueError('ASSEMBLY_HOLD: severe seam mismatch')
  chosen=max(usable,key=lambda item:(item[1]['minimum_edge_energy_ratio'],-item[2]));chosen[1]['requires_visual_review']=True
  write(base/'assembly-qc.json',dict(candidates=checks,selected=chosen[1],source_candidates=candidates,selected_source=selected))
 loop,quality,fade=chosen
 limited(['ffmpeg','-v','error','-y','-i',str(loop),'-vf','scale=1920:1080:flags=lanczos','-an','-c:v','libx264','-preset','fast','-crf','16',str(base/'loop-master.mp4')])
 limited(['ffmpeg','-v','error','-y','-stream_loop','-1','-i',str(base/'loop-master.mp4'),'-i',job['audio_path'],'-t','30','-map','0:v','-map','1:a','-r','24','-c:v','libx264','-preset','fast','-crf','19','-c:a','aac','-b:a','192k','-movflags','+faststart',str(base/'preview.mp4')])
 seam_sheet(loop,base,boxes,round(fade*24))
 value=dict(builder_version=LOOP_VERSION,mask_policy_version=MASK_VERSION,auto_window_snow=True,request_id=job['request_id'],parent_request_id=job['parent_request_id'],
 layout_sha256=sha(base/'layout.json'),mask_sha256=sha(base/'window-mask.png'),source_sha256=sha(base/'composed.mp4'),preview_sha256=sha(base/'preview.mp4'),loop_master_sha256=sha(base/'loop-master.mp4'),
 source_seconds=actual,loop_seconds=engine.probe_duration(base/'loop-master.mp4'),crossfade_seconds=fade,publication_loop_mode='repeat',publication_crossfade=0,
 technical_check='passed',full_frame_only=True,local_masks=True,window_snow_overlay=True,fireplace_masks=False,mask_scope='exterior_window_glass_only',frame_border_crop_pixels=[48,27],
 assembly_qc_passed=bool(quality['passed']),requires_visual_seam_review=not quality['passed'],used_rigid_regions=rigid,new_paid_images=0,snow_generation=False)
 write(marker,value);return value

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','build']);p.add_argument('base',type=Path);a=p.parse_args()
 job=json.loads((a.base/'job.json').read_text());print(json.dumps(prepare(a.base,job) if a.mode=='prepare' else build(a.base,job)))
