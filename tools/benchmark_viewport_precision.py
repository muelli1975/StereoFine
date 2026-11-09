from math import ceil, floor
from statistics import median
from time import perf_counter

import numpy as np
from PIL import Image
from stereofine.anaglyph import DEFAULT_BLOCK_ROWS, make_anaglyph
from stereofine.geometry import _apply_black_mask, _make_triangle_mask, apply_floating_window_masks

LANCZOS = Image.Resampling.LANCZOS

def canonical_border(w,h,side,direction,max_px):
    # Match the original polygon's absolute-coordinate scan lines before slicing.
    # The extra width supplies the filter support at the interior edge.
    width=min(w,max_px+6)
    origin=0 if side=='left' else w-width
    sw,sh,mx=w*4,h*4,max_px*4
    y=np.arange(sh,dtype=np.float32)
    dx=np.float32(mx)/np.float32(sh)
    x0=mx if side=='left' else sw-mx
    if direction=='bottom':
        y-=sh
    if (side,direction) in (('left','top'),('right','bottom')):
        dx=-dx
    diagonal=y*dx+np.float32(x0)
    x=np.arange(origin*4,(origin+width)*4,dtype=np.int32)
    if side=='left':
        filled=x[None,:] <= np.ceil(diagonal-np.float32(.5)).astype(np.int32)[:,None]
    else:
        filled=x[None,:] >= np.floor(diagonal+np.float32(.5)).astype(np.int32)[:,None]
    raster=Image.fromarray(filled.astype(np.uint8)*255)
    return origin,raster.resize((width,h),LANCZOS)


def roi_mask(w,h,side,direction,max_px,box):
    x,y,x1,y1=box
    result=Image.new('L',(x1-x,y1-y),0)
    end=min(w,max_px+6)
    if (side=='left' and x>=end) or (side=='right' and x1<=w-end):
        return result
    origin,strip=canonical_border(w,h,side,direction,max_px)
    start,stop=max(x,origin),min(x1,origin+strip.width)
    result.paste(strip.crop((start-origin,y,stop-origin,y1)),(start-x,0))
    return result


def mask_probe():
    cases=[(392,257,7),(1280,720,8),(3000,2000,21),(5472,3648,82),(5472,3647,131),
           (4285,2856,64),(4285,2857,115),(4040,2693,61),(3852,2567,116),(4000,2247,120)]
    for w,h,m in cases:
        for side in ('left','right'):
            for direction in ('top','bottom'):
                full=np.asarray(_make_triangle_mask(w,h,side,direction,m))
                orig,strip=canonical_border(w,h,side,direction,m)
                array=np.asarray(strip)
                missing=np.count_nonzero(full[:,:orig])+np.count_nonzero(full[:,orig+array.shape[1]:])
                differing=np.count_nonzero(full[:,orig:orig+array.shape[1]]!=array)
                assert missing+differing==0, ('MASK_DIFF',w,h,side,direction,m,missing,differing)
    print('checked',len(cases)*4,'complete masks',flush=True)


def viewport(left,right,gray,direction,raw_box,display):
    h,w=left.shape[:2]
    x,y,x1,y1=map(float,np.float32(raw_box))
    margin_x=ceil(3*max(1.,(x1-x)/display[0]))+2
    margin_y=ceil(3*max(1.,(y1-y)/display[1]))+2
    ox,oy=max(0,floor(x)-margin_x),max(0,floor(y)-margin_y)
    ex,ey=min(w,ceil(x1)+margin_x),min(h,ceil(y1)+margin_y)
    box=(ox,oy,ex,ey)
    a,b=left[oy:ey,ox:ex],right[oy:ey,ox:ex]
    if direction:
        max_px=round(w*.022)
        a=_apply_black_mask(a,roi_mask(w,h,'left',direction,max_px,box))
        b=_apply_black_mask(b,roi_mask(w,h,'right',direction,max_px,box))
    if gray:
        # Same full-width 128-row block shapes and positions as the reference.
        # Only the viewport and halo carry original pixels, the dot is pointwise.
        first=oy//DEFAULT_BLOCK_ROWS*DEFAULT_BLOCK_ROWS
        last=min(h,ceil(ey/DEFAULT_BLOCK_ROWS)*DEFAULT_BLOCK_ROWS)
        padded=[]
        for eye in (a,b):
            scratch=np.zeros((last-first,w,3),dtype=np.uint8)
            scratch[oy-first:ey-first,ox:ex]=eye
            padded.append(scratch)
        rendered=make_anaglyph(*padded,gray=True)[oy-first:ey-first,ox:ex]
    else:
        rendered=make_anaglyph(a,b)
    return Image.fromarray(rendered).resize(display,LANCZOS,box=(x-ox,y-oy,x1-ox,y1-oy))


def image_probe():
    rng=np.random.default_rng(142)
    for w,h in ((1921,1283),(4285,2857),(5472,3648)):
        left,right=(rng.integers(0,256,size=(h,w,3),dtype=np.uint8) for _ in range(2))
        display=(1024,700)
        scale=.8
        width,height=display[0]/scale,display[1]/scale
        boxes=[(0,0,width,height),(w-width,h-height,w,h),(113.7,201.3,113.7+width,201.3+height),
               (31.37,19.53,31.37+width,19.53+height)]
        for gray in (False,True):
            for direction in (None,'top','bottom'):
                start=perf_counter()
                original=Image.fromarray(make_anaglyph(*apply_floating_window_masks(left,right,
                    top_permille=22 if direction=='top' else 0,
                    bottom_permille=22 if direction=='bottom' else 0),gray=gray))
                full_time=perf_counter()-start
                samples=[]
                for raw_box in boxes:
                    reference=original.resize(display,LANCZOS,box=raw_box)
                    start=perf_counter()
                    candidate=viewport(left,right,gray,direction,raw_box,display)
                    samples.append(perf_counter()-start)
                    diff=np.count_nonzero(np.asarray(reference)!=np.asarray(candidate))
                    assert diff==0, ('VIEW_DIFF',w,h,gray,direction,raw_box,diff)
                print('VIEW',w,h,gray,direction,round(full_time,3),round(median(samples),3),flush=True)
                del original

if __name__=='__main__':
    mask_probe()
    image_probe()
    print('72 zoom viewports pixel-identical',flush=True)
