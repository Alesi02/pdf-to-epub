"""Text-first PDF layout with complete crops for tables and complex notation."""
from collections import Counter
import html
import math
import re
import unicodedata
from statistics import median
import pdfplumber
from inspect_books import clean
from reflow import Event,FlowRenderer

BAD=re.compile(r'\(cid:\d+\)|[\ufffd\ufffe\ue000-\uf8ff]')
MATHFONT=re.compile(r'unknown|cmsy|cmmi|cmex|msam|msbm|symbol|math|stix|euclid',re.I)

def key(text):
    return re.sub(r'\d+','#',''.join(text.casefold().split()))

def visible_page(original):
    crop=original.cropbox or original.bbox
    bounds=(max(original.bbox[0],crop[0]),max(original.bbox[1],crop[1]),min(original.bbox[2],crop[2]),min(original.bbox[3],crop[3]))
    return original.crop(bounds,strict=False) if bounds!=original.bbox else original

class SourceHints(set):
    def __init__(self,headers,body_size,words):
        super().__init__(headers);self.body_size=body_size;self.words=words;self.images=Counter();self.overlay_pages=0

def running_headers(source):
    counts=Counter();sizes=Counter();words=Counter();images=Counter();overlay_pages=0; loose=Counter(); needs_ocr=0; ocr_indices=set()
    from outline import describe,infer_sections
    descriptors={};page_labels={}
    for i,original in enumerate(source.pages):
        p=visible_page(original);origin=p.bbox[1]
        lines=p.extract_text_lines()
        folios=remove_side_folios(p,lines)
        if folios:page_labels[i+1]=folios[0]
        if folios:lines=p.extract_text_lines()
        descriptors[i+1]=describe(lines,p.width,p.height)
        char_count=sum(len(c['text'].strip()) for c in p.chars)
        if char_count<20 and p.images and (scan_overlay(p) or not char_count): needs_ocr+=1;ocr_indices.add(i)
        loose.update({key(l['text']) for l in lines if len(l['text'])<130 and (l['top']-origin<p.height*.16 or l['bottom']-origin>p.height*.88)})
        edge={(key(l['text']),round((l['top']-origin)/p.height,2)) for l in lines if l['top']-origin<p.height*.16 or l['bottom']-origin>p.height*.86}
        counts.update(edge)
        if scan_overlay(p) and p.chars:overlay_pages+=1
        images.update(getattr(o.get('stream'),'objid',None) for o in p.images)
        for l in lines:
            words.update(w.casefold() for w in re.findall(r'[^\W\d_]+(?:-[^\W\d_]+)*',l['text']))
            if p.height*.16<l['top']-origin<p.height*.86:sizes.update(round(c['size'],1) for c in l['chars'] if c['text'].isalpha())
        original.close()
        if (i+1)%50==0:print(f'  Analizando estructura: {i+1}/{len(source.pages)}',flush=True)
    threshold=max(3,math.ceil(len(source.pages)*.02))
    hints=SourceHints({item for item,n in counts.items() if n>=threshold},sizes.most_common(1)[0][0] if sizes else 12,words)
    hints.images=images;hints.overlay_pages=overlay_pages
    hints.ocr_indices=ocr_indices
    hints.page_count=len(source.pages)
    hints.update(k for k,n in loose.items() if n>=threshold)
    hints.descriptors=descriptors;hints.sections=infer_sections(descriptors,hints);hints.page_labels=page_labels
    print(f'  Necesita OCR (reconocimiento óptico de caracteres): {needs_ocr} de {len(source.pages)} páginas. Puede demorar.' if needs_ocr else '  No necesita OCR (reconocimiento óptico de caracteres): ya tiene texto. Conversión más rápida.',flush=True)
    return hints

def remove_side_folios(page,lines):
    """A folio can sit beside the text, far from the top/bottom margin."""
    wide=[l for l in lines if len(l['text'])>=55 and l['x1']-l['x0']>page.width*.6]
    if len(wide)<3:return []
    left=median(l['x0'] for l in wide);right=median(l['x1'] for l in wide)
    words=pdfplumber.utils.extract_words(page.chars,x_tolerance=2,y_tolerance=3,return_chars=True)
    folios=[]
    for word in words:
        if re.fullmatch(r'\d{1,4}',word['text']) and (word['x1']<left-8 or word['x0']>right+8):
            folios.append(int(word['text']))
            for c in word['chars']:c['text']=''
    if folios:page.get_textmap.cache_clear()
    return folios

def is_margin(line,height,headers,origin=0):
    text=line['text'].strip();edge=line['top']-origin<height*.16 or line['bottom']-origin>height*.86
    if edge and (key(text) in headers or (key(text),round((line['top']-origin)/height,2)) in headers):return True
    # Production metadata varies by signature and is not a chapter heading.
    if edge and (re.match(r'^P\d+\s*:',text) or re.search(r'\bPrinter\s*:',text,re.I)):return True
    if line['top']-origin<height*.1 and re.search(r'^\d{1,4}\s|\s\d{1,4}$',text):
        cs=sorted((c for c in line.get('chars',[]) if c['text'].strip()),key=lambda c:c['x0'])
        # Running title and folio share a row, but are separated by a wide gap.
        # A numbered chapter heading has ordinary inter-word spacing.
        for a,b in zip(cs,cs[1:]):
            if b['x0']-a['x1']>25 and (a['text'].isdigit() or b['text'].isdigit()):return True
    return bool(re.fullmatch(r'\d{1,4}|[ivxlcdmIVXLCDM]{1,7}',text) and (line['bottom']-origin>height*.85 or line['top']-origin<height*.1))

def bbox(chars):
    return [min(c['x0'] for c in chars),min(c['top'] for c in chars),max(c['x1'] for c in chars),max(c['bottom'] for c in chars)]

def intersects(a,b,pad=0):
    return a[0]<b[2]+pad and b[0]<a[2]+pad and a[1]<b[3]+pad and b[1]<a[3]+pad

def combine(a,b):
    return [min(a[0],b[0]),min(a[1],b[1]),max(a[2],b[2]),max(a[3],b[3])]

def merge(regions):
    result=[]
    for region in regions:
        while True:
            hit=next((i for i,r in enumerate(result) if intersects(region,r,2)),None)
            if hit is None:break
            region=combine(region,result.pop(hit))
        result.append(region)
    return result

def undecodable_math(c):
    text=c['text'].strip()
    if BAD.search(text):return True
    if not text or text in ('·','•','∙','©','®','™'):return False
    # Readable punctuation/operators are ordinary text even in Symbol fonts.
    if all(t.isdigit() or t in '()[]{}=+-/<>:;,.!|_^' for t in text):return False
    if all(ord(t)>127 and unicodedata.category(t)[0] in ('S','L','P') for t in text):return False
    return bool(MATHFONT.search(c['fontname']))

def illustration_regions(page,headers):
    result=[]
    # Tiled backgrounds can look like several separate illustrations. A
    # native title/prose layer over those tiles takes precedence over them.
    decoration_ids=set()
    for o in page.images:
        if any(o['x0']<(c['x0']+c['x1'])/2<o['x1'] and o['top']<(c['top']+c['bottom'])/2<o['bottom'] for c in page.chars):
            decoration_ids.add(id(o))
    for o in page.images:
        r=[max(page.bbox[0],o['x0']),max(page.bbox[1],o['top']),min(page.bbox[2],o['x1']),min(page.bbox[3],o['bottom'])]
        w,h=r[2]-r[0],r[3]-r[1]
        if w<30 or h<25 or w*h>page.width*page.height*.6:continue
        repeated=getattr(headers,'images',{}).get(getattr(o.get('stream'),'objid',None),0)>=3
        edge=r[1]-page.bbox[1]<page.height*.17 or r[3]-page.bbox[1]>page.height*.9
        if (repeated or edge) and h<page.height*.14:continue
        overlaid=[c for c in page.chars if r[0]<(c['x0']+c['x1'])/2<r[2] and r[1]<(c['top']+c['bottom'])/2<r[3]]
        captions=[l for l in page.extract_text_lines() if re.match(r'^(?:FIGURE|FIGURA|FIG\.|TABLE|TABLA|GR[ÁA]FICO)\s*\d',l['text'],re.I) and min(abs(l['top']-r[3]),abs(l['bottom']-r[1]))<45]
        if overlaid and not captions:continue
        if decoration_ids and not captions and any(abs(o['x0']-other['x0'])<1 or abs(o['x0']-other['x1'])<1 or abs(o['x1']-other['x0'])<1 for other in page.images if id(other) in decoration_ids):continue
        if not captions and w<45 and h<60:continue
        result.append(r)
    return result

def overlay_prose(line):
    """Recognize narrative even when it contains a formula or a reference."""
    text=line['text'].strip()
    words=re.findall(r'(?<!\S)[^\W\d_]{3,}(?=[,;:.!?]?(?:\s|$))',text)
    words=[w for w in words if w.casefold() not in {'sin','cos','tan','log','lim','exp','max','min'}]
    if len(words)>=2 and sum(map(len,words))>=9:return True
    return bool(re.fullmatch(r'[\W\d_]*[^\W\d_]{4,}[\s:;,.!?]*',text))

def overlay_equations(page,lines,bitmap=None):
    """Use prose as hard boundaries around displays in an existing text layer.

    OCR glyph boxes can overlap adjacent rows even when the printed ink does
    not. Never expand a display into those rows or interpret a prose reference
    such as 'the result in (3.2)' as an equation label.
    """
    chars=[c for l in lines for c in l['chars']]
    if not chars:return []
    margin=min(c['x0'] for c in chars);right=max(c['x1'] for c in chars)
    prose=[l for l in lines if overlay_prose(l)]
    bands=sorted((bbox(l['chars'])[1],bbox(l['chars'])[3]) for l in prose)
    regions=[]
    for line in lines:
        if overlay_prose(line):continue
        text=line['text'];r=bbox(line['chars']);center=(r[1]+r[3])/2
        numbered=bool(re.search(r'\(\d+\.\d+[a-z]?\)\s*$',text))
        formula=bool(re.search(r'=|∫|∑',text)) and r[0]>margin+8
        if not (numbered or formula):continue
        # A detached subscript or inline expression is part of its prose row.
        if any(t<=center<=b for t,b in bands):continue
        above=[b for t,b in bands if b<center]
        below=[t for t,b in bands if t>center]
        top=max(above)+.6 if above else max(page.bbox[1],r[1]-12)
        bottom=min(below)-.6 if below else min(page.bbox[3],r[3]+12)
        if bottom-top>page.height*.25:
            top=max(top,r[1]-20);bottom=min(bottom,r[3]+20)
        if bottom>top:regions.append([margin,top,right,bottom])
    # Some existing OCR layers omit an entire displayed expression. Only use
    # a gap introduced by a colon, and verify that it actually contains ink.
    # This inspects pixels, without recognizing or changing any text.
    if bitmap is not None:
        from raster_region import ink_bounds
        prose_sorted=sorted(prose,key=lambda l:l['top'])
        for a,b in zip(prose_sorted,prose_sorted[1:]):
            top=a['bottom']+.6;bottom=b['top']-.6
            if a['text'].rstrip().endswith(':') and 12<bottom-top<page.height*.15:
                candidate=[margin,top,right,bottom]
                if not any(intersects(candidate,r) for r in regions):
                    ink=ink_bounds(bitmap,page,candidate)
                    if ink and ink[0]>margin+12 and ink[2]<right-10 and ink[2]-ink[0]>18:
                        regions.append(candidate)
    # Merge overlapping displays only, without the padding used for glyphs.
    result=[]
    for r in regions:
        hit=next((i for i,p in enumerate(result) if intersects(r,p)),None)
        if hit is None:result.append(r)
        else:result[hit]=combine(r,result[hit])
    # An OCR layer often flattens a superscript and confuses 1/I or Greek
    # letters. Preserve the printed expression instead of guessing variables.
    for line in prose:
        chars=sorted(line['chars'],key=lambda c:c['x0']);mapping=[];compact=''
        for c in chars:
            for t in c['text']:
                if not t.isspace():compact+=t;mapping.append(c)
        for match in re.finditer(r'\([-−–—][1Il]\)[A-Za-zα-ωΑ-Ω](?:[-−][A-Za-zα-ωΑ-Ω])?(?![\w−\-])',compact):
            r=bbox(mapping[match.start():match.end()])
            result.append([r[0]-.5,r[1]-2,r[2]+.5,r[3]+1])
    return result

def equation_regions(page,lines,bitmap=None):
    if getattr(page,'images',None) and scan_overlay(page):
        return overlay_equations(page,lines,bitmap)
    chars=list({id(c):c for l in lines for c in l['chars']}.values())
    def complete_row(seed):
        # The denominator can be much wider than the bar. Grow along the
        # printed row through normal word spaces, stopping at a column gap.
        if not seed:return seed
        size=max(c.get('size',c['bottom']-c['top']) for c in seed)
        center=sum((c['top']+c['bottom'])/2 for c in seed)/len(seed)
        row=sorted((c for c in chars if abs((c['top']+c['bottom'])/2-center)<size*.45),key=lambda c:c['x0'])
        groups=[]
        for c in row:
            if groups and c['x0']-max(p['x1'] for p in groups[-1])<=size:groups[-1].append(c)
            else:groups.append([c])
        ids={id(c) for c in seed}
        return [c for group in groups if any(id(c) in ids for c in group) for c in group]
    regions=[]
    # A fraction has text immediately above AND below its horizontal bar.
    # Underlines and page rules lack that pair and are ignored.
    for o in page.lines+page.rects+page.curves:
        x0,x1,y0,y1=o['x0'],o['x1'],o['top'],o['bottom']
        if not 8<x1-x0<page.width*.72 or y1-y0>1.8:continue
        roots=[c for c in chars if c['text']=='√' and abs(c['x1']-x0)<2 and abs(c['top']-y0)<3]
        if roots:
            radicand=[c for c in chars if x0-.5<=c['x0']<x1 and y0-1<c['top']<y0+12]
            if radicand:regions.append(combine([roots[0]['x0'],y0-.7,x1,y1],bbox(radicand+roots)))
            continue
        above=[c for c in chars if c['x0']<x1 and c['x1']>x0 and y0-8<c['bottom']<=y0+2 and c['top']<y0-2]
        below=[c for c in chars if c['x0']<x1 and c['x1']>x0 and y1-1<=c['top']<y1+8 and c['bottom']>y1+2]
        if above and below:
            def columns(cs):
                ordered=sorted(cs,key=lambda c:c['x0'])
                return 1+sum(b['x0']-a['x1']>12 for a,b in zip(ordered,ordered[1:]))
            if min(columns(above),columns(below))>=3:continue
            above=complete_row(above);below=complete_row(below)
            regions.append(combine([x0,y0,x1,y1],bbox(above+below)))
    for line in lines:
        text=line['text']
        code=any(re.search(r'courier|mono|consol',c['fontname'],re.I) for c in line['chars'])
        unique=list({id(c):c for c in line['chars']}.values())
        bad=[c for c in unique if undecodable_math(c) and not (code and not BAD.search(c['text']))]
        if not bad:continue
        context=not overlay_prose(line) and bool(re.search(r'[=+<>∫∑√{}]|\b(?:lim|sin|cos|log)\b',text) or len(bad)>max(2,len(unique)*.35))
        if context:regions.append(bbox(line['chars']))
        else:regions.extend(bbox([c]) for c in bad)
    regions=merge(regions)
    # Close glyphs and super/subscripts must be included completely, not sliced.
    for _ in range(4):
        expanded=[]
        for r in regions:
            nearby=[c for c in chars if r[0]<=(c['x0']+c['x1'])/2<=r[2] and r[1]<=(c['top']+c['bottom'])/2<=r[3]]
            expanded.append(combine(r,bbox(nearby)) if nearby else r)
        new=merge(expanded)
        if new==regions:break
        regions=new
    return regions

def clean_native(text):
    return ' '.join(text.replace('\u00ad','-').split()).replace('∙','•')

def choose_text(candidate,fallback):
    # PDFium exposes discretionary line-end hyphens as U+FFFE. Restore the
    # source hyphen first; the reflow stage can then join the split word.
    last=candidate.rstrip()[-1:]
    soft=last in ('\ufffe','\u00ad') or (bool(last) and ord(last)<32 and fallback.rstrip().endswith('-'))
    if soft and last not in ('\ufffe','\u00ad'):candidate=candidate.rstrip()[:-1]+'-'
    candidate=clean_native(candidate.replace('\ufffe','-') if soft else candidate)
    fallback=clean_native(fallback)
    if clean(candidate)==clean(fallback):return candidate,soft
    # Never accept a merely similar length: it can conceal omitted words.
    if BAD.search(fallback) and candidate and not BAD.search(candidate):
        return candidate,soft
    return fallback,soft

def ordered_lines(page):
    lines=merge_inline_rows(page.extract_text_lines(x_tolerance=2,y_tolerance=3))
    # Detect a sustained central gutter, not the spaces between a few words.
    chars=[c for c in page.chars if page.height*.16<c['top']-page.bbox[1]<page.height*.86 and c['text'].strip()]
    if len(chars)<300:return lines
    bins=[0]*int(page.width)
    for c in chars:
        for x in range(max(0,int(c['x0']-page.bbox[0])),min(len(bins),int(c['x1']-page.bbox[0])+1)):bins[x]+=1
    lo,hi=int(page.width*.35),int(page.width*.65)
    runs=[];start=None
    for x in range(lo,hi):
        if bins[x]<=1:
            if start is None:start=x
        elif start is not None:runs.append((start,x));start=None
    if start is not None:runs.append((start,hi))
    runs=[r for r in runs if r[1]-r[0]>=12]
    if not runs:return lines
    a,b=max(runs,key=lambda r:r[1]-r[0]);gutter=(a+b)/2+page.bbox[0]
    left=[c for c in chars if c['x1']<=gutter];right=[c for c in chars if c['x0']>=gutter]
    if min(len(left),len(right))<len(chars)*.25:return lines
    if max(min(c['top'] for c in left),min(c['top'] for c in right))-min(min(c['top'] for c in left),min(c['top'] for c in right))>page.height*.2:return lines
    result=[]
    for column,predicate in ((0,lambda c:c['x0']<gutter),(1,lambda c:c['x0']>=gutter)):
        sub=page.filter(lambda o:o.get('object_type')!='char' or predicate(o))
        for l in merge_inline_rows(sub.extract_text_lines(x_tolerance=2,y_tolerance=3)):l['column']=column;result.append(l)
    return result

def merge_inline_rows(lines):
    """Reattach superscripts/subscripts split into separate extraction rows."""
    rows=[]
    for line in sorted(lines,key=lambda l:l['top']):
        h=line['bottom']-line['top'];center=(line['top']+line['bottom'])/2
        match=next((r for r in reversed(rows[-4:]) if
            min(r['bottom'],line['bottom'])-max(r['top'],line['top'])>min(h,r['bottom']-r['top'])*.5 and
            abs((r['top']+r['bottom'])/2-center)<max(h,r['bottom']-r['top'])*.35),None)
        if match is None:rows.append(dict(line));continue
        chars=list({id(c):c for c in match['chars']+line['chars']}.values())
        r=bbox(chars)
        match.update(chars=chars,x0=r[0],top=r[1],x1=r[2],bottom=r[3],text=pdfplumber.utils.extract_text(chars,x_tolerance=2,y_tolerance=r[3]-r[1]))
    return rows

def scan_overlay(page):
    return any((o['x1']-o['x0'])*(o['bottom']-o['top'])>page.width*page.height*.6 for o in page.images)

def heading_candidate(text,font_size,body_size,bold):
    explicit=bool(re.match(r'^(?:SECCI[ÓO]N|CAP[IÍ]TULO|CHAPTER|§)\s*[IVXLCDM\d]+\b',text,re.I))
    # Printed contents entries and equations are not section destinations.
    if re.search(r'(?:\.\s*){3,}.*\d+\s*$',text):return False
    if explicit and len(text.split())>4 and re.search(r'\s\d+\s*$',text):return False
    if explicit:return True
    words=re.findall(r'(?<!\S)[^\W\d_]{4,}(?=[,;:.!?]?(?:\s|$))',text)
    if not words or re.search(r'[=∫∑√<>/\\_]|\(cid:',text):return False
    if sum(c.isalpha() for c in text)<len(text)*.65:return False
    return font_size>body_size*1.18 and len(text)<180 and (bold or font_size>body_size*1.4)

def native_events(page,pp,headers,format_prose,save_equation,audit=None,bitmap=None,ocr_words=None):
    from font_encoding import normalize_glyphs
    normalize_glyphs(page)
    remove_side_folios(page,page.extract_text_lines())
    all_lines=ordered_lines(page)
    # Decode circular list markers from vector fonts using their glyph family
    # and alignment with a prose row, rather than creating tiny bitmap boxes.
    circular=[l for l in all_lines if all(re.search(r'circle|dingbat|wingding',c['fontname'],re.I) for c in l['chars']) and l['text'].strip() not in ('®','©')]
    for marker in circular:
        targets=[l for l in all_lines if l is not marker and l not in circular and l['x0']>=marker['x1'] and l['top']<marker['bottom']+2 and l['bottom']>marker['bottom']-7]
        if targets:
            target=min(targets,key=lambda l:l['x0']-marker['x1'])
            for c in marker['chars']:c['text']='•'
            target['chars']=marker['chars']+target['chars'];target['text']='• '+target['text']
            all_lines.remove(marker)
    sections=getattr(headers,'sections',{}).get(page.page_number,[])
    protected=lambda l:any(s['top']-.5<=l['top'] and l['bottom']<=s['bottom']+.5 and s['left']-2<=l['x0']<=s['right']+2 for s in sections)
    lines=[l for l in all_lines if protected(l) or not is_margin(l,page.height,headers,page.bbox[1])]
    # A sparse page can consist entirely of genuine content near an edge.
    # Do not erase it solely because similar lines occur on other pages.
    if not lines and getattr(headers,'page_count',0)<=3 and any(not re.fullmatch(r'\d{1,4}|[ivxlcdmIVXLCDM]{1,7}', l['text'].strip()) for l in all_lines):
        lines=[l for l in all_lines if not re.fullmatch(r'\d{1,4}|[ivxlcdmIVXLCDM]{1,7}',l['text'].strip())]
    from table_layout import extract_tables
    tp=pp.get_textpage()
    table_events,table_ids=extract_tables(page,lines,save_equation)
    content_lines=[]
    for line in lines:
        chars=[c for c in line['chars'] if id(c) not in table_ids]
        if chars:
            line=dict(line,chars=chars);content_lines.append(line)
    regions=equation_regions(page,content_lines,bitmap)
    illustrations=illustration_regions(page,headers)
    table_boxes=[e.region for e in table_events]
    illustrations=[r for r in illustrations if not any(intersects(r,t) for t in table_boxes)]
    regions=[r for r in regions if not any(intersects(r,im) for im in illustrations)]
    all_regions=regions+illustrations
    events=list(table_events);text_count=0;headings=[];represented=set(table_ids)
    sizes=Counter(round(c['size'],1) for l in lines for c in l['chars'] if c['text'].strip())
    body_size=getattr(headers,'body_size',None) or (sizes.most_common(1)[0][0] if sizes else 12)
    kept_line_ids={id(l) for l in lines}
    excluded={id(c) for l in all_lines if id(l) not in kept_line_ids for c in l['chars']}
    source_ids={id(c) for c in page.chars if c['text'].strip() and id(c) not in excluded and page.bbox[0]<=(c['x0']+c['x1'])/2<=page.bbox[2] and page.bbox[1]<=(c['top']+c['bottom'])/2<=page.bbox[3]}
    def owned(c):
        center=((c['x0']+c['x1'])/2,(c['top']+c['bottom'])/2)
        return any(r[0]-.1<=center[0]<=r[2]+.1 and r[1]-.1<=center[1]<=r[3]+.1 for r in all_regions)
    try:
        for li,l in enumerate(content_lines):
            chars=[]
            for c in sorted(l['chars'],key=lambda c:c['x0']):
                if id(c) not in {id(x) for x in chars}:chars.append(c)
            fragments=[];fragment=[]
            for c in chars:
                if owned(c):
                    represented.add(id(c))
                    if fragment:fragments.append(fragment);fragment=[]
                else:fragment.append(c)
            if fragment:fragments.append(fragment)
            for fi,part in enumerate(fragments):
                r=bbox(part)
                raw=tp.get_text_bounded(r[0]-.1,page.root_page.height-r[3]-.1,r[2]+.1,page.root_page.height-r[1]+.1)
                fallback=pdfplumber.utils.extract_text(part,x_tolerance=2,y_tolerance=max(3,r[3]-r[1]))
                if fallback.lstrip().startswith('•'):
                    stripped=raw.lstrip();expected=clean(fallback.lstrip()[1:])
                    if clean(stripped)==expected:raw='• '+stripped
                    elif stripped and clean(stripped[1:])==expected:raw='• '+stripped[1:]
                text,soft=choose_text(raw,fallback)
                from outline import tracked_text
                tracked=tracked_text(part)
                if tracked:text=clean_native(tracked)
                if BAD.search(text):raise ValueError(f'Carácter sin decodificar fuera de una ecuación, página {page.page_number}.')
                if not text:continue
                if text.startswith(('·','•')):text='•'+text[1:]
                font_size=Counter(round(c['size'],1) for c in part).most_common(1)[0][0]
                bold=any('bold' in c['fontname'].lower() for c in part)
                heading=heading_candidate(text,font_size,body_size,bold) if not hasattr(headers,'sections') else False
                if heading:headings.append((text,page.page_number))
                kind='heading' if heading else 'text'
                if any(re.search(r'courier|mono|consol',c['fontname'],re.I) for c in part):kind='code'
                if font_size<body_size*.91 and r[1]-page.bbox[1]>page.height*.65:kind='note'
                if text.startswith('•'):kind='bullet';text=text[1:].lstrip()
                markup=format_prose(text,part)
                ident=f'source-{page.page_number}-{li}-{fi}'
                if audit:markup=audit.fragment(ident,text,markup)
                events.append(Event(r[1],r[0],r[3],markup,kind,text,ident,soft,l.get('column',0)))
                for c in part:
                    if id(c) in represented and c['text'].strip():raise ValueError(f'Carácter extraído dos veces, página {page.page_number}.')
                    represented.add(id(c))
                text_count+=1
        for r in regions:
            markup=save_equation(r)
            nearest=min(lines,key=lambda l:abs((l['top']+l['bottom'])/2-(r[1]+r[3])/2)+abs((l['x0']+l['x1'])/2-(r[0]+r[2])/2)*.02) if lines else {}
            events.append(Event(r[1],r[0],r[3],markup,'equation',column=nearest.get('column',0)))
        for r in illustrations:
            markup=save_equation(r,'figure')
            events.append(Event(r[1],r[0],r[3],markup,'figure'))
        if not source_ids<=represented:raise ValueError(f'Caracteres omitidos durante la extracción, página {page.page_number}.')
        if audit:audit.pages+=1;audit.glyphs+=len(source_ids)
    finally:tp.close()
    if hasattr(headers,'sections'):
        from outline import assemble_sections
        events,headings=assemble_sections(events,sections)
    return events,headings,text_count

def render_events(events):
    renderer=FlowRenderer()
    renderer.feed([Event(*e) if isinstance(e,tuple) else e for e in events])
    return ''.join(renderer.finish())
