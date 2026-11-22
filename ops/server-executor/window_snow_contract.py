"""Validated, scene-specific window masks. No network or generation side effects."""
import hashlib,json,math,re
VERSION='2026-11-22-auto-window-mask-v1'
WIDTH,HEIGHT=1280,720

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
def polygon_area(points):return abs(sum(x*v-u*y for (x,y),(u,v) in zip(points,points[1:]+points[:1])))/2

def validate_plan(value):
 if value.get('verdict') not in ('READY','UNCERTAIN'):raise ValueError('Unknown layout verdict')
 if value['verdict']!='READY':raise ValueError('Layout uncertainty: '+str(value.get('notes',''))[:500])
 for name in ['glass','foreground']:
  rows=value.get(name)
  if not isinstance(rows,list) or len(rows)>100 or (name=='glass' and not rows):raise ValueError('Missing or oversized layout')
  for row in rows:
   points=row.get('polygon');label=row.get('label')
   if not isinstance(label,str) or not label.strip() or len(label)>120:raise ValueError('Invalid region label')
   if not isinstance(points,list) or not 3<=len(points)<=120:raise ValueError('Invalid polygon')
   for point in points:
    if not isinstance(point,list) or len(point)!=2 or any(type(v) is not int for v in point):raise ValueError('Coordinates must be integer pairs')
    if not 0<=point[0]<WIDTH or not 0<=point[1]<HEIGHT:raise ValueError('Polygon outside source frame')
   if polygon_area(points)<12:raise ValueError('Degenerate polygon')
   clean=points[:-1] if points[-1]==points[0] else points
   def cross(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
   edges=list(zip(clean,clean[1:]+clean[:1]))
   for i,(a,b) in enumerate(edges):
    for j,(u,v) in enumerate(edges):
     if j<=i+1 or (i==0 and j==len(edges)-1):continue
     if cross(a,b,u)*cross(a,b,v)<0 and cross(u,v,a)*cross(u,v,b)<0:raise ValueError('Self-intersecting polygon')
 margin=value.get('inset_fullhd_px')
 if type(margin) is not int or not 4<=margin<=12:raise ValueError('Unsafe Full HD inset')
 boxes=value.get('rigid_regions')
 if not isinstance(boxes,list) or not 3<=len(boxes)<=6:raise ValueError('Need three to six rigid measurement regions')
 for box in boxes:
  if len(box)!=4 or any(type(v) is not int for v in box):raise ValueError('Bad rigid region')
  x,y,w,h=box
  if not (3<=x and 3<=y and 24<=w<=200 and 24<=h<=160 and x+w<=1277 and y+h<=717):raise ValueError('Rigid region outside frame')
 return value

def schema():
 point={'type':'array','items':{'type':'integer'},'minItems':2,'maxItems':2}
 region={'type':'object','additionalProperties':False,'properties':{'label':{'type':'string'},'polygon':{'type':'array','items':point,'minItems':3,'maxItems':120}},'required':['label','polygon']}
 return {'type':'object','additionalProperties':False,'properties':{
  'verdict':{'type':'string','enum':['READY','UNCERTAIN']},
  'glass':{'type':'array','items':region},'foreground':{'type':'array','items':region},
  'inset_fullhd_px':{'type':'integer','minimum':4,'maximum':12},
  'rigid_regions':{'type':'array','items':{'type':'array','items':{'type':'integer'},'minItems':4,'maxItems':4},'minItems':3,'maxItems':6},
  'notes':{'type':'string'}},'required':['verdict','glass','foreground','inset_fullhd_px','rigid_regions','notes']}

def make_mask(plan):
 from PIL import Image,ImageDraw,ImageFilter,ImageChops
 validate_plan(plan)
 # Final output is cropped by 48/27 at native size, then enlarged to Full HD.
 radius=math.ceil(plan['inset_fullhd_px']*1184/1920)
 glass=Image.new('L',(WIDTH,HEIGHT),0);draw=ImageDraw.Draw(glass)
 for row in plan['glass']:draw.polygon([tuple(p) for p in row['polygon']],fill=255)
 glass=glass.filter(ImageFilter.MinFilter(2*radius+1))
 foreground=Image.new('L',glass.size,0);draw=ImageDraw.Draw(foreground)
 for row in plan['foreground']:draw.polygon([tuple(p) for p in row['polygon']],fill=255)
 foreground=foreground.filter(ImageFilter.MaxFilter(2*(radius+2)+1))
 safe=ImageChops.subtract(glass,foreground)
 mask=ImageChops.darker(safe,safe.filter(ImageFilter.GaussianBlur(.65)))
 fraction=sum(mask.histogram()[1:])/(WIDTH*HEIGHT)
 if not .005<=fraction<=.85:raise ValueError('Implausible glass coverage')
 if ImageChops.multiply(mask,foreground).getbbox():raise ValueError('Snow overlaps excluded foreground')
 return mask

def retained_rigid_regions(plan):
 # Camera-border crop may discard an otherwise valid measurement rectangle.
 # Drop that measurement only; never change AI glass or foreground polygons.
 boxes=[box for box in plan['rigid_regions'] if box[0]>=48 and box[1]>=27 and box[0]+box[2]<=1232 and box[1]+box[3]<=693]
 if len(boxes)<3:raise ValueError('Need at least three textured rigid regions inside retained rectangle x=48..1232,y=27..693')
 return boxes

def transform_box(box):
 x,y,w,h=box;s=1280/1184
 left=max(3,math.floor((x-48)*s));top=max(3,math.floor((y-27)*s))
 right=min(1277,math.ceil((x+w-48)*s));bottom=min(717,math.ceil((y+h-27)*s))
 if right-left<12 or bottom-top<12:raise ValueError('Region lost after fixed border crop')
 return [left,top,right-left,bottom-top]

def job_id(parent,source_sha,decision=''):
 if not re.fullmatch(r'cabin\d{2}-[a-z0-9-]+',parent):raise ValueError('Only Cabin sources are supported')
 if not re.fullmatch('[a-f0-9]{64}',source_sha):raise ValueError('Invalid source checksum')
 return parent[:7]+'-auto-'+digest({'parent':parent,'source':source_sha,'decision':decision,'policy':VERSION})[:16]
