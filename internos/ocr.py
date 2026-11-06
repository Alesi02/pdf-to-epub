"""Reconocimiento con el OCR de Windows y correcciones conservadoras."""
from pathlib import Path
import html
import json
import re
import subprocess
import tempfile
import unicodedata
from itertools import product
from functools import lru_cache
from reflow import Event

HERE = Path(__file__).resolve().parent
CONFUSIONS = {'0':'o', '1':'l', '5':'s', '8':'b'}

@lru_cache(maxsize=1)
def available_languages():
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(HERE/'ocr_windows.ps1'),'-List'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    return json.loads(result.stdout.decode('utf-8-sig')) if not result.returncode else []

def vocabulary(extra=()):
    words = {w.casefold() for w in extra}
    for name in ('es_ES.dic', 'en_US.dic', 'vocabulario.txt'):
        path = HERE/'diccionarios'/name
        if not path.exists():
            continue
        for line in path.read_text(encoding='utf-8-sig', errors='replace').splitlines():
            word = line.split('/')[0].split('\t')[0].strip()
            if word.isalpha(): words.add(word.casefold())
    return words

@lru_cache(maxsize=1)
def language_words():
    return {lang: {line.split('/')[0].casefold() for line in (HERE/'diccionarios'/name).read_text(encoding='utf-8-sig').splitlines()} for lang,name in [('es','es_ES.dic'),('en','en_US.dic')]}

def select_languages(candidates):
    """Choose per text row, allowing different languages on the same page."""
    if not candidates: return []
    dictionaries=language_words()
    def score(line):
        tokens=[t for t in re.findall(r'[^\W_]+',line['text'].casefold()) if any(c.isalpha() for c in t)]
        known=sum(len(t) for t in tokens if any(t in words for words in dictionaries.values()))
        return (known/max(1,sum(map(len,tokens))), known, -line['text'].count('\ufffd'))
    base=max(candidates,key=lambda c:sum(score(l)[1] for l in c['lines']))
    result=[]
    for line in base['lines']:
        boxes=line.get('words',[])
        if not boxes: continue
        top=min(w['y'] for w in boxes); bottom=max(w['y']+w['h'] for w in boxes)
        left=min(w['x'] for w in boxes);right=max(w['x']+w['w'] for w in boxes)
        options=[line]
        for candidate in candidates:
            if candidate is base: continue
            for other in candidate['lines']:
                b=other.get('words',[])
                if not b: continue
                t=min(w['y'] for w in b); d=max(w['y']+w['h'] for w in b)
                x=min(w['x'] for w in b);r=max(w['x']+w['w'] for w in b)
                if min(bottom,d)-max(top,t)>.6*max(bottom-top,d-t) and min(right,r)-max(left,x)>.6*max(right-left,r-x): options.append(other)
        result.append(max(options,key=score))
    return result

def accent_key(text):
    return ''.join(c for c in unicodedata.normalize('NFD',text.casefold()) if not unicodedata.combining(c))

def accent_index(words):
    result={}
    for word in words:result.setdefault(accent_key(word),set()).add(word)
    return result

def letter_variants(token):
    result=set()
    for old,new in [('m','in'),('m','rn'),('rn','m'),('cl','d'),('i','l'),('l','i')]:
        for match in re.finditer(re.escape(old),token):result.add(token[:match.start()]+new+token[match.end():])
    return result

def correct(text, words, index=None):
    # Accept a unique word supported by the dictionary or repeated document
    # vocabulary, using a bounded set of common OCR glyph confusions.
    def fix(match):
        token = match.group()
        digits = [i for i, c in enumerate(token) if c.isdigit()]
        if not 1<=len(digits)<=4 or len(token)<5 or not token[0].isalpha() or sum(c.isalpha() for c in token)<3:return token
        if token.isupper() and len(token)<8:return token
        options={'0':('o',),'1':('i','l'),'5':('s',),'8':('b',)}
        if any(token[i] not in options for i in digits):return token
        candidates=set()
        raw_candidates=[]
        for replacement in product(*(options[token[i]] for i in digits)):
            chars=list(token.casefold())
            for i,c in zip(digits,replacement):chars[i]=c
            candidate=''.join(chars)
            raw_candidates.append(candidate)
            known=lookup.get(accent_key(candidate),())
            if known:candidates.update(known)
            elif candidate in words:candidates.add(candidate)
        if not candidates:
            for raw in raw_candidates:
                for candidate in letter_variants(raw):
                    known=lookup.get(accent_key(candidate),())
                    if known:candidates.update(known)
                    elif candidate in words:candidates.add(candidate)
        if len(candidates)!=1:return token
        candidate=candidates.pop()
        return candidate.upper() if token.isupper() else candidate.capitalize() if token[0].isupper() else candidate
    lookup=index if index is not None else accent_index(words)
    return re.sub(r'(?<!\w)[^\W_]*\d[^\W_]*(?!\w)', fix, text, flags=re.UNICODE)

def recognize(bitmap, language):
    with tempfile.TemporaryDirectory(prefix='libro-ocr-') as temp:
        path = Path(temp)/'page.png'
        bitmap.save(path)
        cmd = ['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(HERE/'ocr_windows.ps1'),'-Image',str(path),'-Language',language]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:
            raise RuntimeError(result.stderr.decode('utf-8',errors='replace').strip() or 'No se pudo ejecutar el OCR de Windows.')
        data=json.loads(result.stdout.decode('utf-8-sig'))
        return select_languages(data['candidates']) if isinstance(data,dict) else data

def ocr_events(lines, page, bitmap, words, audit, save_equation, repeated=()):
    sx, sy = page.width/bitmap.width, page.height/bitmap.height
    events=[]
    from table_layout import scanned_regions
    table_boxes=scanned_regions(lines,bitmap)
    for region in table_boxes:
        mapped=[region[0]*sx+page.bbox[0],region[1]*sy+page.bbox[1],region[2]*sx+page.bbox[0],region[3]*sy+page.bbox[1]]
        events.append(Event(mapped[1],mapped[0],mapped[3],save_equation(mapped,'table'),'table'))
    # A caption next to a sizable ink-filled gap provides stronger evidence
    # of a figure than arbitrary whitespace or an isolated page number.
    from PIL import ImageOps
    for previous, caption in zip(lines,lines[1:]):
        a,b=previous.get('words',[]),caption.get('words',[])
        if not a or not b or not re.match(r'^\s*(?:fig(?:ura)?\.?|figure|gráfico|grafico)\s*\d',caption['text'],re.I): continue
        top=int(max(w['y']+w['h'] for w in a)+4); bottom=int(min(w['y'] for w in b)-4)
        if bottom-top<bitmap.height*.055: continue
        left=int(bitmap.width*.08);right=int(bitmap.width*.92)
        strip=bitmap.crop((left,top,right,bottom)).convert('L')
        ink=ImageOps.invert(strip).point(lambda p: 255 if p>80 else 0).getbbox()
        if not ink or (ink[2]-ink[0])*(ink[3]-ink[1])<bitmap.width*bitmap.height*.002: continue
        region=[(left+ink[0])*sx+page.bbox[0],(top+ink[1])*sy+page.bbox[1],(left+ink[2])*sx+page.bbox[0],(top+ink[3])*sy+page.bbox[1]]
        events.append(Event(region[1],region[0],region[3],save_equation(region,'figure'),'figure'))
    for i, line in enumerate(lines):
        boxes=line.get('words',[])
        if not boxes: continue
        boxes=[w for w in boxes if not any(r[0]<=w['x']+w['w']/2<=r[2] and r[1]<=w['y']+w['h']/2<=r[3] for r in table_boxes)]
        if not boxes:continue
        x=min(w['x'] for w in boxes)*sx+page.bbox[0]
        top=min(w['y'] for w in boxes)*sy+page.bbox[1]
        right=max(w['x']+w['w'] for w in boxes)*sx+page.bbox[0]
        bottom=max(w['y']+w['h'] for w in boxes)*sy+page.bbox[1]
        raw=(' '.join(w['text'] for w in boxes) if len(boxes)!=len(line.get('words',[])) else line['text']).strip()
        # Folios only at the edges. Repeated running titles are handled in a
        # later pass across pages, once their recurrence has been measured.
        edge=(top-page.bbox[1]<page.height*.14 or bottom-page.bbox[1]>page.height*.88)
        if edge and re.fullmatch(r'\d{1,4}|[ivxlcdmIVXLCDM]{1,7}',raw): continue
        if edge and re.sub(r'\d+','#',''.join(raw.casefold().split())) in repeated: continue
        text=raw
        formula=not edge and bool(re.search(r'[=∫∑√]',raw)) and len(re.findall(r'[^\W\d_]{4,}',raw))<2
        if formula:
            events.append(Event(top,x,bottom,save_equation([x,top,right,bottom]),'equation'))
        else:
            ident=f'ocr-{page.page_number}-{i}'
            markup=audit.fragment(ident,text,html.escape(text))
            events.append(Event(top,x,bottom,markup,'text',text,ident))
    audit.pages += 1
    from statistics import median
    heights=[e.bottom-e.top for e in events if e.kind=='text']
    normal=median(heights) if heights else 12
    for event in events:
        if event.kind=='text' and event.top-page.bbox[1]>page.height*.65 and event.bottom-event.top<normal*.9: event.kind='note'
    return events
