"""Scene-specific safe glass and foreground masks for Cabin 15."""
from cabin_window_snow import make_glass_mask,transform_box,WIDTH,HEIGHT,FRAME_BORDER_CROP
PARENT='cabin15-fixed-v14-20261121'
REQUEST='cabin15-snow-v14-20261122'
PANES=[[(903, 125), (1279, 56), (1279, 432), (1250, 436), (1221, 446), (903, 410)]]
OCCLUDERS=[[(1231, 432),
  (1279, 420),
  (1279, 720),
  (992, 720),
  (992, 486),
  (1102, 480),
  (1114, 452),
  (1208, 453)]]
PROTECTED=[(889, 180),
 (1000, 431),
 (1250, 450),
 (1150, 500),
 (650, 540),
 (770, 405),
 (300, 450)]
def make_mask():
 from PIL import Image,ImageDraw,ImageFilter,ImageChops
 mx,my=FRAME_BORDER_CROP
 mask=make_glass_mask(PANES,(WIDTH,HEIGHT),output_size=(1920*WIDTH/(WIDTH-2*mx),1080*HEIGHT/(HEIGHT-2*my)))
 excluded=Image.new('L',(WIDTH,HEIGHT),0);draw=ImageDraw.Draw(excluded)
 for polygon in OCCLUDERS:draw.polygon(polygon,fill=255)
 if OCCLUDERS:excluded=excluded.filter(ImageFilter.MaxFilter(9))
 safe=ImageChops.subtract(mask,excluded)
 mask=ImageChops.darker(safe,safe.filter(ImageFilter.GaussianBlur(.6)))
 if any(mask.getpixel(p)!=0 for p in PROTECTED):raise ValueError('Snow touches protected interior')
 return mask
