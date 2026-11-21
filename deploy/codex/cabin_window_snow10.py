"""Scene-specific glass boundaries for Cabin living room by waterfall."""
from cabin_window_snow import make_glass_mask,transform_box,WIDTH,HEIGHT,FRAME_BORDER_CROP
PARENT='cabin10-fixed-v15-20261121'
REQUEST='cabin10-snow2-v15-20261121'
PANES=[[(455,178),(482,184),(482,355),(455,355)],
[(662,113),(1222,38),(1213,356),(1195,361),(1181,374),(1165,401),(1152,422),(766,401),(756,395),(699,387),(696,360),(686,345),(661,338)]]
# Union of chair silhouettes sampled across the saved 10-second animation.
OCCLUDERS=[[(568,329),(690,329),(704,349),(711,376),(741,386),(774,392),
            (781,407),(779,455),(752,515),(570,552)],
           [(1280,346),(1215,347),(1192,354),(1177,369),(1163,389),(1149,414),
            (1142,435),(1001,443),(991,468),(1000,570),(1280,640)]]
PROTECTED=[(640,300),(650,100),(1235,200),(680,390),(1200,410),(500,540),(350,530),(280,350),(470,367),(900,440)]
def make_mask():
 mx,my=FRAME_BORDER_CROP
 # Reproduce the approved version exactly; new request IDs use the current default.
 frozen_inset={'cabin10-snow-v15-20261121':3,'cabin10-snow2-v15-20261121':3}
 options={'inset_output_px':frozen_inset[REQUEST]} if REQUEST in frozen_inset else {}
 mask=make_glass_mask(PANES,(WIDTH,HEIGHT),output_size=(1920*WIDTH/(WIDTH-2*mx),1080*HEIGHT/(HEIGHT-2*my)),**options)
 from PIL import Image,ImageDraw,ImageFilter,ImageChops
 excluded=Image.new('L',(WIDTH,HEIGHT),0);draw=ImageDraw.Draw(excluded)
 for polygon in OCCLUDERS:draw.polygon(polygon,fill=255)
 # Four source pixels cover observed residual motion, then feather toward glass.
 excluded=excluded.filter(ImageFilter.MaxFilter(9))
 safe=ImageChops.subtract(mask,excluded)
 mask=ImageChops.darker(safe,safe.filter(ImageFilter.GaussianBlur(.6)))
 if any(mask.getpixel(p)!=0 for p in PROTECTED):raise ValueError('Snow touches protected interior')
 return mask
