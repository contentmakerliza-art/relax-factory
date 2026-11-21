"""Scene-specific glass boundaries for Cabin living room by waterfall."""
from cabin_window_snow import make_glass_mask,transform_box,WIDTH,HEIGHT,FRAME_BORDER_CROP
PARENT='cabin10-fixed-v15-20261121'
REQUEST='cabin10-snow-v15-20261121'
PANES=[[(455,178),(482,184),(482,355),(455,355)],
[(662,113),(1222,38),(1213,356),(1195,361),(1181,374),(1165,401),(1152,422),(766,401),(756,395),(699,387),(696,360),(686,345),(661,338)]]
PROTECTED=[(640,300),(650,100),(1235,200),(680,390),(1200,410),(500,540),(350,530),(280,350),(470,367),(900,440)]
def make_mask():
 mx,my=FRAME_BORDER_CROP
 mask=make_glass_mask(PANES,(WIDTH,HEIGHT),output_size=(1920*WIDTH/(WIDTH-2*mx),1080*HEIGHT/(HEIGHT-2*my)))
 if any(mask.getpixel(p)!=0 for p in PROTECTED):raise ValueError('Snow touches protected interior')
 return mask
