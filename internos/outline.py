"""Document-wide section inference and layout-aware printed contents."""
from collections import Counter
from statistics import median
import html
import re
import unicodedata
from difflib import SequenceMatcher
from reflow import Event

CONTENTS=re.compile(r'^(?:índice(?: general)?|indice(?: general)?|table of contents|contents|contenido)\s*[:.]?$',re.I)
PREFIX=re.compile(r'^(?:prefacio|prólogo|prologo|preface|foreword|introducción|introduction|capítulo|capitulo|chapter|sección|section|título|titulo|title|parte|part|anexo|appendix)\b',re.I)
NUMBER=re.compile(r'^(?:[IVXLCDM]{1,9}|\d{1,3})[.)]?$',re.I)

def tracked_text(chars):
    letters=sorted((c for c in chars if c['text'].strip()),key=lambda c:c['x0'])
    if len(letters)<6:return None
    size=median(c['size'] for c in letters)
    gaps=[max(0,b['x0']-a['x1']) for a,b in zip(letters,letters[1:])]
    spacing=median(gaps)
    if spacing<size*.12:return None
    import pdfplumber
    return pdfplumber.utils.extract_text(chars,x_tolerance=spacing*1.5,y_tolerance=3)

def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKD',text.casefold()) if c.isalnum())

def describe(lines, width, height):
    result=[]
    for line in lines:
        chars=[c for c in line.get('chars',[]) if c['text'].strip()]
        if chars:
            size=Counter(round(c['size'],1) for c in chars).most_common(1)[0][0]
            font=Counter(c['fontname'] for c in chars).most_common(1)[0][0]
            italic=sum(bool(re.search(r'italic|oblique',c['fontname'],re.I)) for c in chars)>len(chars)*.5
            uniform=sum(c['fontname']==font for c in chars)>=len(chars)*.85
            ordered=sorted(chars,key=lambda c:c['x0'])
            columns=sum(b['x0']-a['x1']>size*2 for a,b in zip(ordered,ordered[1:]))
            kept=[c for c in chars if not (c['text'].isdigit() and c['size']<size*.8)]
            if len(kept)!=len(chars):
                import pdfplumber
                line=dict(line,text=pdfplumber.utils.extract_text(kept,x_tolerance=2,y_tolerance=3))
                uniform=sum(c['fontname']==font for c in kept)>=len(kept)*.85
            tracked=tracked_text(kept)
            if tracked:line=dict(line,text=tracked)
        else:
            words=line.get('words',[])
            if not words:continue
            size=median(w['h'] for w in words);font='';italic=False;uniform=True
            ordered=sorted(words,key=lambda w:w['x']);columns=sum(b['x']-a['x']-a['w']>size*2 for a,b in zip(ordered,ordered[1:]))
        result.append(dict(text=line['text'].strip(),top=line.get('top',min((w['y'] for w in line.get('words',[])),default=0)),bottom=line.get('bottom',max((w['y']+w['h'] for w in line.get('words',[])),default=0)),left=line.get('x0',min((w['x'] for w in line.get('words',[])),default=0)),right=line.get('x1',max((w['x']+w['w'] for w in line.get('words',[])),default=width)),size=size,font=font,bold=bool(re.search('bold|black|demi',font,re.I)),italic=italic,uniform=uniform,width=width,height=height))
        result[-1]['columns']=columns
    return result

def infer_sections(pages, repeated=()):
    """Use each page's body typography, whitespace and consistent heading styles."""
    result={}
    prose=Counter();prose_sizes=Counter()
    for lines in pages.values():
        for l in lines:
            if len(l['text'])>=55 and not l['text'].isupper() and not l['italic']:
                prose[l['font']]+=len(l['text']);prose_sizes[(l['font'],l['size'])]+=len(l['text'])
    prose_fonts={font for font,count in prose.items() if count>=max(prose.values(),default=1)*.08}
    ordinary_styles={style for style,count in prose_sizes.items() if count>=max(prose_sizes.values(),default=1)*.05}
    for number,lines in pages.items():
        if not lines:result[number]=[];continue
        body=Counter()
        for l in lines:
            if len(l['text'])>=55 and not l['text'].isupper():body[(l['font'],l['size'])]+=len(l['text'])
        bodyfont,bodysize=body.most_common(1)[0][0] if body else ('',median(l['size'] for l in lines))
        if body:bodysize=max(size for (font,size),count in body.items() if count>=max(body.values())*.25)
        selected=[]
        for i,l in enumerate(lines):
            text=l['text'];letters=[c for c in text if c.isalpha()]
            following=lines[i+1] if i+1<len(lines) else None
            # A decorative initial belongs to the overlapping prose row.
            dropcap=len(letters)==1 and following is not None and following['top']<l['bottom'] and following['text'][:1].islower()
            if dropcap:continue
            if not letters or len(text)>190 or CONTENTS.fullmatch(text) or (l['italic'] and not text.isupper()):continue
            if l.get('columns',0)>=2:continue
            if re.search(r'[=∫∑√<>]|\(cid:|\.{3,}\s*\d+\s*$',text):continue
            if re.match(r'^(?:ISBN|ISSN|https?://|www\.)',text,re.I):continue
            if re.match(r'^(?:TABLE|TABLA|CUADRO|FIGURE|FIGURA|FIG\.|GR[ÁA]FICO)\s*\d',text,re.I):continue
            edge=l['top']<l['height']*.16 or l['bottom']>l['height']*.86
            from native_layout import key
            if edge and (key(text) in repeated or (key(text),round(l['top']/l['height'],2)) in repeated) and not NUMBER.fullmatch(text):continue
            before=l['top']-lines[i-1]['bottom'] if i else l['size']*3
            after=lines[i+1]['top']-l['bottom'] if i+1<len(lines) else 0
            upper=len(letters)>=5 and sum(c.isupper() for c in letters)/len(letters)>.9
            styled=l['bold'] or (bool(bodyfont) and l['font'] not in prose_fonts and l['font']!=bodyfont)
            explicit=bool(PREFIX.match(text)) and len(text.split())<=12
            following=lines[i+1] if i+1<len(lines) else None
            isolated=(len(text)<=75 and len(text.split())<=10 and before>l['size']*1.4 and after>l['size']*1.4 and following is not None and len(following['text'])>=55)
            large=l['size']>=bodysize*1.18 and (l['font'],l['size']) not in ordinary_styles
            titlelike=len(text.split())<=23 and not text.endswith('-') and (upper or not re.search(r'[,;]$|[.!?]\s*$',text)) and l.get('uniform',True)
            if re.match(r'^\d+[.)-]',text) and after<l['size']*.65 and not upper:titlelike=False
            numbered_context=any(NUMBER.fullmatch(p['text']) and 0<l['top']-p['bottom']<p['size']*5 for p in lines[max(0,i-3):i])
            if upper and len(letters)<=6 and not l['bold'] and not large and l['top']>l['height']*.3 and not numbered_context:titlelike=False
            if upper and re.search(r'\b[A-ZÁÉÍÓÚÑ]\.\s',text) and not PREFIX.match(text):titlelike=False
            if NUMBER.fullmatch(text):
                following=lines[i+1] if i+1<len(lines) else None
                if following and following['text'].isupper() and len(following['text'])>5 and following['top']-l['bottom']<l['size']*3:selected.append(l)
            elif titlelike and l['size']>=bodysize*(.78 if styled else .92) and (isolated or large or ((upper or styled or explicit) and (before>l['size']*.65 or after>l['size']*.65 or (upper and styled)))):
                selected.append(l)
        groups=[]
        for line in selected:
            previous=groups[-1][-1] if groups else None
            gap=line['top']-previous['bottom'] if previous else 1e9
            same=previous and (abs(line['left']-previous['left'])<max(line['size']*2,20) or abs(line['right']-previous['right'])<max(line['size']*2,20) or abs((line['left']+line['right']-previous['left']-previous['right'])/2)<max(line['size'],previous['size']))
            prefix=previous and (NUMBER.fullmatch(previous['text']) or (PREFIX.match(previous['text']) and len(previous['text'].split())<=4) or re.fullmatch(r'\w+\s+(?:PARTE|PART)',previous['text'],re.I))
            between=previous and any(l['top']>previous['bottom']+.1 and l['bottom']<line['top']-.1 and l not in selected and not re.fullmatch(r'\d+',l['text']) for l in lines)
            if previous and not between and ((same and gap<max(previous['size'],line['size'])*.95 and .8<line['size']/previous['size']<1.25) or (prefix and gap<previous['size']*4)):
                groups[-1].append(line)
            else:groups.append([line])
        sections=[]
        for group in groups:
            label=' '.join(l['text'] for l in group)
            if NUMBER.fullmatch(label):continue
            sections.append(dict(label=label,page=number,anchor=f'section-{number}-{len(sections)}',top=group[0]['top'],bottom=group[-1]['bottom'],left=min(l['left'] for l in group),right=max(l['right'] for l in group)))
        result[number]=sections
    return result

def printed_entries(lines, page_count, continuation=False):
    """Resolve wrapped entries using their aligned folio column, not authors."""
    heading=any(CONTENTS.fullmatch(l['text']) for l in lines)
    candidates=[]
    for l in lines:
        match=re.search(r'\s+(\d{1,4})\s*$',l['text'])
        if match and 0<int(match[1])<=page_count+20:candidates.append((l,match))
    positions=Counter(round(l['right']/5) for l,m in candidates)
    aligned={x for x,n in positions.items() if n>=2}
    dotted=sum(bool(re.search(r'(?:\.\s*){2,}\d+\s*$',l['text'])) for l in lines)
    if not ((heading or continuation) and len(candidates)>=2 and aligned) and dotted<3:return []
    pending=[];entries=[];previous=None
    for l in lines:
        text=l['text']
        if CONTENTS.fullmatch(text):continue
        if previous and (l['top']-previous['bottom']>l['size']*.9 or abs(l['left']-previous['left'])>l['size']*4):pending=[]
        match=re.search(r'(?:\s+|\.{2,})(\d{1,4})\s*$',text)
        endpoint=match and int(match[1])<=page_count+20 and (round(l['right']/5) in aligned or re.search(r'(?:\.\s*){2,}\d+\s*$',text))
        if endpoint:
            tail=re.sub(r'[.\s/]+$','',text[:match.start()])
            if not l['italic'] or not pending:pending.append(tail)
            label=' '.join(p for p in pending if p).strip(' /').replace(' / ',': ')
            if label:entries.append((label,int(match[1])))
            pending=[]
        else:pending.append(text)
        previous=l
    return entries

def assemble_sections(events, sections):
    entries=[];removed=set();added=[]
    for section in sections:
        members=[e for e in events if id(e) not in removed and e.kind not in ('equation','table','figure','note','footnote','code') and section['top']-.5<=e.top and e.bottom<=section['bottom']+.5 and section['left']-2<=e.left<=section['right']+2]
        if not members:continue
        members.sort(key=lambda e:(e.top,e.left))
        markup=f'<span id="{section["anchor"]}"/>'+' '.join(e.markup for e in members)
        first=members[0]
        added.append(Event(first.top,first.left,members[-1].bottom,markup,'heading',' '.join(e.text for e in members)))
        removed.update(id(e) for e in members);entries.append((section['label'],section['page'],section['anchor']))
    return [e for e in events if id(e) not in removed]+added,entries

def choose_navigation(bookmarks, printed, sections, labels, pages):
    outline=[s for values in sections.values() for s in values]
    offsets=Counter(p-f for f,p in labels.items());offset=offsets.most_common(1)[0][0] if offsets else None
    restored=[]
    for label,folio in printed:
        key=normalized(label)
        scored=[(SequenceMatcher(None,key,normalized(s['label']),autojunk=False).ratio(),s) for s in outline]
        expected=labels.get(folio,folio+offset if offset is not None else folio)
        best=max(scored,key=lambda pair:(pair[0],-abs(pair[1]['page']-expected))) if scored else None
        if best and best[0]>=.74:
            s=best[1];restored.append((label,s['page'],s['anchor']))
        else:
            target=labels.get(folio) or (folio+offset if offset is not None else None)
            if target in pages:restored.append((label,target))
    valid_bookmarks=[e for e in bookmarks if not re.fullmatch(r'(?:page|página|pagina|\d)[\s\d._-]*',e[0],re.I)]
    primary=valid_bookmarks or restored
    # Extend the original structure with actual subsections, without duplicating
    # the cover, publishing credits or the same destination under another name.
    start=min((e[1] for e in primary),default=min(pages))
    entries=list(primary)
    destinations={(e[1],e[2] if len(e)>2 else '') for e in entries}
    for s in outline:
        if s['page']<start:continue
        if any(e[1]==s['page'] and (len(e)==2 or e[2]==s['anchor']) for e in entries):continue
        entries.append((s['label'],s['page'],s['anchor']))
    entries.sort(key=lambda e:(e[1],next((s['top'] for s in outline if len(e)>2 and s['anchor']==e[2]),0)))
    unique=[];seen=set()
    for e in entries:
        k=(normalized(e[0]),e[1])
        if k not in seen:unique.append(e);seen.add(k)
    return unique
