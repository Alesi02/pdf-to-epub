"""Detect tables and retain their original appearance as image crops."""
import re
from statistics import median
import pdfplumber
from reflow import Event

def column_groups(chars):
    words=pdfplumber.utils.extract_words(chars,x_tolerance=2,y_tolerance=3)
    groups=[];gap=max(5,median(c['size'] for c in chars)*.8) if chars else 6
    for word in words:
        if groups and word['x0']-groups[-1][1]<gap:groups[-1][1]=word['x1']
        else:groups.append([word['x0'],word['x1']])
    return groups

def column_cuts(groups,left,right):
    return [left-.5]+[(a[1]+b[0])/2 for a,b in zip(groups,groups[1:])]+[right+.5]

def table_candidates(page,lines):
    candidates=[]
    rules=[o for o in page.lines+page.rects if o['x1']-o['x0']>page.width*.4 and o['bottom']-o['top']<1.8]
    for caption in lines:
        if not re.match(r'^(?:TABLE|TABLA|CUADRO)\s*\d',caption['text'],re.I):continue
        below=sorted((o for o in rules if caption['bottom']<o['top']<caption['bottom']+400),key=lambda o:o['top'])
        if len(below)<3:continue
        first=below[0];same=[o for o in below if abs(o['x0']-first['x0'])<3 and abs(o['x1']-first['x1'])<3]
        if len(same)<3 or same[1]['top']-first['top']>40:continue
        header=[c for c in page.chars if first['top']<c['top'] and c['bottom']<same[1]['top'] and first['x0']-.5<c['x0']<first['x1']+.5]
        groups=column_groups(header)
        if len(groups)>=2:candidates.append((first['top'],same[2]['top'],first['x0'],first['x1'],groups))
    # Short data tables often have only a rule below the bold column labels,
    # without a caption or outer border. Require numeric rows and clear gutters.
    for rule in rules:
        headers=[l for l in lines if 0<rule['top']-l['bottom']<10 and sum(bool(re.search('bold',c['fontname'],re.I)) for c in l['chars'])>len(l['chars'])*.5]
        for header in headers:
            groups=column_groups(header['chars'])
            if len(groups)<3:continue
            cuts=column_cuts(groups,rule['x0'],rule['x1'])[1:-1]
            rows=[];last=rule['top']
            for l in sorted((l for l in lines if l['top']>rule['top']),key=lambda l:l['top']):
                if l['top']-last>20:break
                cs=l['chars']
                if not re.search(r'\d',l['text']):break
                if any(any(c['x0']<cut+2 and c['x1']>cut-2 for c in cs if c['text'].strip()) for cut in cuts):break
                bounds=[rule['x0']-.5]+cuts+[rule['x1']+.5]
                if sum(any(a<=(c['x0']+c['x1'])/2<b for c in cs) for a,b in zip(bounds,bounds[1:]))<2:break
                if l['x0']<rule['x0']-3 or l['x1']>rule['x1']+3:break
                rows.append(l);last=l['bottom']
            top=header['top']-.1
            previous=[l for l in lines if 0<=header['top']-l['bottom']<6 and len(column_groups(l['chars']))>=2 and all(re.search('bold',c['fontname'],re.I) for c in l['chars'])]
            if previous:top=min(l['top'] for l in previous)-.1
            if rows:candidates.append((top,rows[-1]['bottom']+.2,rule['x0'],rule['x1'],groups))
    return candidates

def aligned_regions(rows, width, height):
    """Strong numeric alignment across three rows; prose alone is insufficient."""
    merged=[]
    for row in sorted((r for r in rows if r['words']),key=lambda r:min(w['y'] for w in r['words'])):
        ws=row['words'];center=median(w['y']+w['h']/2 for w in ws);size=median(w['h'] for w in ws)
        if merged and abs(center-merged[-1][0])<size*.4:merged[-1][1]['words'].extend(ws)
        else:merged.append((center,{'words':list(ws)}))
    rows=[r for _,r in merged]
    eligible=[]
    for row in rows:
        words=sorted(row['words'],key=lambda w:w['x'])
        if len(words)<3: continue
        typical=median(w['h'] for w in words)
        groups=[]
        for word in words:
            if groups and word['x']-groups[-1][-1]['x']-groups[-1][-1]['w']<typical*1.25:groups[-1].append(word)
            else:groups.append([word])
        numeric=[g for g in groups if any(re.fullmatch(r'[-+−]?[\d.,%$€]+',w['text']) for w in g)]
        if len(groups)<3 or len(numeric)<2:continue
        eligible.append((row,groups,typical))
    result=[];run=[]
    def finish():
        if len(run)<3:return
        words=[w for row,_,_ in run for w in row['words']]
        result.append([min(w['x'] for w in words)-2,min(w['y'] for w in words)-2,max(w['x']+w['w'] for w in words)+2,max(w['y']+w['h'] for w in words)+2])
    for entry in sorted(eligible,key=lambda e:min(w['y'] for w in e[0]['words'])):
        row,groups,size=entry
        if run:
            previous,pg,ps=run[-1]
            gap=min(w['y'] for w in row['words'])-max(w['y']+w['h'] for w in previous['words'])
            anchors=[g[0]['x'] for g in groups]
            prior=[g[0]['x'] for g in pg]
            aligned=sum(any(abs(a-b)<max(size,ps) for b in prior) for a in anchors)
            if gap>max(size,ps)*1.8 or gap< -size*.5 or aligned<3:finish();run=[]
        run.append(entry)
    finish()
    # Include an adjacent aligned column-heading row above the numeric body.
    for region in result:
        above=[r for r in rows if 0<=region[1]-max(w['y']+w['h'] for w in r['words'])<median(w['h'] for w in r['words'])*1.7]
        for row in above:
            ws=sorted(row['words'],key=lambda w:w['x'])
            if len(ws)>=3 and sum(b['x']-a['x']-a['w']>a['h'] for a,b in zip(ws,ws[1:]))>=2:
                region[0]=min(region[0],min(w['x'] for w in ws)-2);region[1]=min(region[1],min(w['y'] for w in ws)-2);region[2]=max(region[2],max(w['x']+w['w'] for w in ws)+2)
    return result

def table_regions(page,lines):
    from native_layout import merge
    regions=[[left,top,right,bottom] for top,bottom,left,right,_ in table_candidates(page,lines)]
    objects=page.lines+page.rects
    horizontal=[o for o in objects if o['x1']-o['x0']>30 and abs(o['bottom']-o['top'])<2]
    vertical=[o for o in objects if o['bottom']-o['top']>12 and abs(o['x1']-o['x0'])<2]
    if len(horizontal)>=2 and len(vertical)>=2:
        finder=page.debug_tablefinder()
        # A one-cell frame containing formulas is a complete visual block,
        # even though pdfplumber does not classify it as a multi-cell table.
        for cell in finder.cells:
            x0,top,x1,bottom=cell
            if x1-x0<page.width*.25 or not 20<bottom-top<page.height*.5:continue
            enclosed=[l for l in lines if x0<=l['x0'] and l['x1']<=x1+2 and top<=l['top'] and l['bottom']<=bottom+2]
            if len(enclosed)>=2 and any(re.search(r'[=∫∑√]',l['text']) for l in enclosed):regions.append(list(cell))
        for table in finder.tables:
            if len(table.cells)<6 or len(table.rows)<2:continue
            x0,top,x1,bottom=table.bbox
            inside=[c for l in lines for c in l['chars'] if x0<=(c['x0']+c['x1'])/2<=x1 and top<=(c['top']+c['bottom'])/2<=bottom]
            occupied=sum(any(cell and cell[0]<=(c['x0']+c['x1'])/2<=cell[2] and cell[1]<=(c['top']+c['bottom'])/2<=cell[3] for c in inside) for cell in table.cells)
            if occupied>=4:regions.append(list(table.bbox))
    rows=[]
    for line in lines:
        words=pdfplumber.utils.extract_words(line['chars'],x_tolerance=2,y_tolerance=3)
        if words:rows.append({'words':[{'x':w['x0'],'y':w['top'],'w':w['x1']-w['x0'],'h':w['bottom']-w['top'],'text':w['text']} for w in words]})
    regions.extend(aligned_regions(rows,page.width,page.height))
    return merge(regions)

def scanned_regions(lines,bitmap):
    """Numeric alignment, plus captioned ruled tables in a scan."""
    regions=aligned_regions(lines,bitmap.width,bitmap.height)
    captions=[l for l in lines if re.match(r'^\s*(?:TABLE|TABLA|CUADRO)\s*\d',l.get('text',''),re.I) and l.get('words')]
    if captions:
        scale=min(1,1000/bitmap.width);small=bitmap.convert('L').resize((int(bitmap.width*scale),int(bitmap.height*scale)))
        pixels=small.load();rules=[]
        for y in range(small.height):
            start=None;best=(0,0)
            for x in range(small.width):
                if pixels[x,y]<110:
                    if start is None:start=x
                elif start is not None:
                    if x-start>best[1]-best[0]:best=(start,x)
                    start=None
            if start is not None and small.width-start>best[1]-best[0]:best=(start,small.width)
            if best[1]-best[0]>small.width*.25:
                if rules and y-rules[-1][0]<3:continue
                rules.append((y,best[0],best[1]))
        for caption in captions:
            bottom=max(w['y']+w['h'] for w in caption['words'])*scale
            below=[r for r in rules if bottom<r[0]<min(small.height,bottom+small.height*.6)]
            if len(below)<2 or below[0][0]-bottom>small.height*.08:continue
            first=below[0];same=[r for r in below if abs(r[1]-first[1])<4 and abs(r[2]-first[2])<4]
            next_caption=min((min(w['y'] for w in c['words'])*scale for c in captions if min(w['y'] for w in c['words'])*scale>bottom),default=small.height)
            bounded=[]
            for rule in same:
                if rule[0]>=next_caption or (bounded and rule[0]-bounded[-1][0]>small.height*.12):break
                bounded.append(rule)
            same=bounded
            if len(same)<2:continue
            regions.append([first[1]/scale,first[0]/scale,same[-1][2]/scale,same[-1][0]/scale])
    from native_layout import merge
    return merge(regions)

def extract_tables(page,lines,save_region):
    events=[];covered=set();regions=table_regions(page,lines)
    allowed={id(c) for l in lines for c in l['chars']}
    for region in regions:
        chars=[c for c in page.chars if id(c) in allowed and region[0]<=(c['x0']+c['x1'])/2<=region[2] and region[1]<=(c['top']+c['bottom'])/2<=region[3]]
        if not chars:continue
        region=[max(page.bbox[0],min(region[0],min(c['x0'] for c in chars))),max(page.bbox[1],min(region[1],min(c['top'] for c in chars))),min(page.bbox[2],max(region[2],max(c['x1'] for c in chars))),min(page.bbox[3],max(region[3],max(c['bottom'] for c in chars)))]
        covered.update(id(c) for c in chars)
        event=Event(region[1],region[0],region[3],save_region(region,'table'),'table');event.region=region
        words=pdfplumber.utils.extract_words(chars,x_tolerance=2,y_tolerance=3,extra_attrs=['size'])
        markers=[]
        for word in words:
            if not word['text'].isdigit():continue
            previous=[w for w in words if w['text'].isalpha() and len(w['text'])>=3 and 0<=word['x0']-w['x1']<w['size']*.5 and word['size']<w['size']*.85 and 0<w['bottom']-word['bottom']<w['size'] and abs(w['top']-word['top'])<w['size']*.5]
            if previous:markers.append(word['text'])
        event.note_numbers=markers
        events.append(event)
    return events,covered
