"""Glass and foreground exclusions for Cabin winter conservatory."""
from cabin_window_snow import make_glass_mask,transform_box,WIDTH,HEIGHT,FRAME_BORDER_CROP
PARENT='cabin11-fixed-v1-20261121'
REQUEST='cabin11-snow-v1-20261121'
PANES=[[(61,54),(78,68),(78,191),(61,185)],
       [(525,181),(618,194),(618,449),(525,450)],
       [(662,195),(736,171),(736,468),(662,454)],
       [(785,159),(924,111),(924,520),(785,480)],
       [(1002,91),(1279,3),(1279,620),(1002,539)]]
OCCLUDERS=[[(611,378),(697,378),(708,387),(712,435),(707,452),(712,458),(706,478),(696,523),(548,532),(542,494),(545,452),(582,437),(590,412),(601,385)],
           [(843,395),(926,406),(939,420),(935,459),(917,501),(895,564),
            (699,623),(680,546),(689,476),(790,462),(815,420)]]
PROTECTED=[(50,100),(88,140),(510,220),(640,320),(757,300),(958,350),
           (625,397),(690,405),(860,420),(900,449),(235,537),(400,449),(1000,570)]
def make_mask():
 from PIL import Image,ImageDraw,ImageFilter,ImageChops
 mx,my=FRAME_BORDER_CROP
 mask=make_glass_mask(PANES,(WIDTH,HEIGHT),output_size=(1920*WIDTH/(WIDTH-2*mx),1080*HEIGHT/(HEIGHT-2*my)))
 excluded=Image.new('L',(WIDTH,HEIGHT),0);draw=ImageDraw.Draw(excluded)
 for polygon in OCCLUDERS:draw.polygon(polygon,fill=255)
 excluded=excluded.filter(ImageFilter.MaxFilter(9))
 safe=ImageChops.subtract(mask,excluded)
 mask=ImageChops.darker(safe,safe.filter(ImageFilter.GaussianBlur(.6)))
 if any(mask.getpixel(p)!=0 for p in PROTECTED):raise ValueError('Snow touches protected interior')
 return mask
