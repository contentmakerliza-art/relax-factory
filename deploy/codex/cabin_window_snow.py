"""One owner-requested window-Snow prototype, measured on its normalized frame.

These polygons are independent of measurement rectangles. The fireplace, cat,
chairs, table, ceiling and window frames receive no Snow compositing.
"""
WIDTH,HEIGHT=1280,720
PARENT='cabin03-fixed-v13-20261121'
REQUEST='cabin03-snow4-v13-20261121'
FRAME_BORDER_CROP=(48,27)
PANES=[
    [(0,74),(8,77),(8,557),(0,559)],
    [(341,104),(429,128),(429,388),(374,399),(360,435),(357,499),(341,502)],
    [(501,133),(785,85),(785,510),(683,498),(682,470),(673,456),(655,450),
     (651,429),(628,411),(598,401),(554,392),(501,393)],
    [(879,71),(1275,14),(1275,415),(1263,429),(1253,451),(1240,478),(1226,492),
     (1191,494),(1190,499),(1048,499),(1047,532),(879,516)],
]
PROTECTED=[(210,450),(515,487),(830,580),(1140,570),(640,30),(819,300),(1060,515),
           (485,250),(1265,445),(985,542)]


def make_glass_mask(polygons, size, *, output_size=(1920,1080), inset_output_px=3, feather_output_px=1):
    """Inset glass in final-frame pixels; feather only inward, never onto frames."""
    import math
    from PIL import Image,ImageDraw,ImageFilter,ImageChops
    width,height=size;out_width,out_height=output_size
    if min(width,height,out_width,out_height)<=0 or inset_output_px<0 or feather_output_px<0:
        raise ValueError('Invalid mask dimensions or margin')
    radius=math.ceil(inset_output_px*max(width/out_width,height/out_height))
    image=Image.new('L',size,0);draw=ImageDraw.Draw(image)
    for polygon in polygons:draw.polygon(polygon,fill=255)
    safe=image.filter(ImageFilter.MinFilter(2*radius+1)) if radius else image
    blur=feather_output_px*max(width/out_width,height/out_height)
    softened=safe.filter(ImageFilter.GaussianBlur(blur)) if blur else safe
    return ImageChops.darker(safe,softened)


def make_mask():
    # Preserve the exact recipe of the already delivered reading-room prototype.
    from PIL import Image,ImageDraw,ImageFilter
    if REQUEST!='cabin03-snow4-v13-20261121':
        mx,my=FRAME_BORDER_CROP
        image=make_glass_mask(PANES,(WIDTH,HEIGHT),output_size=(1920*WIDTH/(WIDTH-2*mx),1080*HEIGHT/(HEIGHT-2*my)))
        if any(image.getpixel(point)!=0 for point in PROTECTED):raise ValueError('Snow touches protected interior')
        return image
    image=Image.new('L',(WIDTH,HEIGHT),0);draw=ImageDraw.Draw(image)
    for polygon in PANES:draw.polygon(polygon,fill=255)
    # Retreat inside the glass before softening edges, never feather into furniture.
    image=image.filter(ImageFilter.MinFilter(9)).filter(ImageFilter.GaussianBlur(1))
    if any(image.getpixel(point)!=0 for point in PROTECTED):raise ValueError('Snow touches protected interior')
    return image


def transform_box(box):
    import math
    x,y,w,h=box;mx,my=FRAME_BORDER_CROP
    scale=WIDTH/(WIDTH-2*mx)
    left=max(3,math.floor((x-mx)*scale));top=max(3,math.floor((y-my)*scale))
    right=min(WIDTH-3,math.ceil((x+w-mx)*scale));bottom=min(HEIGHT-3,math.ceil((y+h-my)*scale))
    if right-left<12 or bottom-top<12:raise ValueError('QA box lost after border crop')
    return [left,top,right-left,bottom-top]
