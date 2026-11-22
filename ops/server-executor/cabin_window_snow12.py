"""Scene-specific safe glass and foreground masks for Cabin 12."""
from cabin_window_snow import make_glass_mask,transform_box,WIDTH,HEIGHT,FRAME_BORDER_CROP
PARENT='cabin12-fixed-v2-20261121'
REQUEST='cabin12-snow-v2-20261122'
PANES=[[(725, 183), (751, 174), (751, 243), (725, 247)],
 [(763, 170), (792, 160), (792, 234), (763, 239)],
 [(725, 256), (750, 253), (750, 315), (725, 317)],
 [(763, 250), (792, 244), (792, 313), (763, 314)],
 [(719, 332), (744, 332), (744, 402), (719, 400)],
 [(758, 331), (787, 329), (787, 407), (758, 404)],
 [(718, 416), (743, 418), (743, 487), (718, 481)],
 [(756, 418), (787, 423), (787, 495), (756, 490)],
 [(829, 154), (1079, 79), (1079, 552), (829, 500)],
 [(1148, 59), (1245, 29), (1245, 155), (1148, 171)],
 [(1263, 23), (1279, 18), (1279, 145), (1263, 150)],
 [(1143, 183), (1244, 166), (1244, 288), (1143, 293)],
 [(1261, 162), (1279, 159), (1279, 287), (1261, 288)],
 [(1143, 320), (1235, 318), (1235, 444), (1143, 437)],
 [(1255, 318), (1279, 317), (1279, 449), (1255, 447)],
 [(1140, 454), (1235, 462), (1235, 587), (1140, 565)],
 [(1254, 465), (1279, 466), (1279, 597), (1254, 593)]]
OCCLUDERS=[]
PROTECTED=[(757, 230),
 (748, 370),
 (803, 300),
 (1102, 300),
 (1252, 210),
 (1210, 303),
 (1200, 450),
 (625, 450),
 (190, 550),
 (330, 450)]
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
