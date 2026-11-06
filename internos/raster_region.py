"""Map PDF layout coordinates to the rendered visible crop box."""
import math

def ink_bounds(bitmap,page,region):
    sx=bitmap.width/page.width;sy=bitmap.height/page.height
    x0=max(0,math.ceil((region[0]-page.bbox[0])*sx))
    y0=max(0,math.ceil((region[1]-page.bbox[1])*sy))
    x1=min(bitmap.width,math.floor((region[2]-page.bbox[0])*sx))
    y1=min(bitmap.height,math.floor((region[3]-page.bbox[1])*sy))
    if x1<=x0 or y1<=y0:return None
    mask=bitmap.crop((x0,y0,x1,y1)).convert('L').point(lambda p:255 if p<150 else 0)
    box=mask.getbbox()
    if box is None:return None
    return [page.bbox[0]+(x0+box[0])/sx,page.bbox[1]+(y0+box[1])/sy,
            page.bbox[0]+(x0+box[2])/sx,page.bbox[1]+(y0+box[3])/sy]

def crop_region(bitmap,page,region,padding=1.5):
    sx=bitmap.width/page.width;sy=bitmap.height/page.height
    x0=max(0,math.floor((region[0]-page.bbox[0]-padding)*sx))
    y0=max(0,math.floor((region[1]-page.bbox[1]-padding)*sy))
    x1=min(bitmap.width,math.ceil((region[2]-page.bbox[0]+padding)*sx))
    y1=min(bitmap.height,math.ceil((region[3]-page.bbox[1]+padding)*sy))
    if x1<=x0 or y1<=y0:raise ValueError('El recorte solicitado está fuera del área visible del PDF.')
    image=bitmap.crop((x0,y0,x1,y1))
    if image.convert('L').getextrema()[0]>248:raise ValueError('Se detectó un recorte vacío; se canceló la conversión para evitar perder una ecuación.')
    return image,(x1-x0)/sx
