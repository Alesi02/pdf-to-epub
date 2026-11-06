"""Re-read only a suspicious short mathematical tail, anchored by a known word."""
from functools import lru_cache
from difflib import SequenceMatcher
from pathlib import Path
import re
from ocr import recognize,accent_key,vocabulary

@lru_cache(maxsize=48)
def tail_evidence(source,ident,context,word,corrected):
    match=re.match(r'(?:source|ocr)-(\d+)-',ident)
    if not match:return None
    token=re.search(r'(?<!\w)'+re.escape(word)+r'(?!\w)',context)
    if not token:return None
    remainder=context[token.end():]
    if not re.search(r'\b[a-z]{2,3}\s+[A-Z][a-z](?:\s*[·.,])?\s*$',remainder):return None
    import pdfplumber
    import pypdfium2 as pdfium
    number=int(match[1])-1
    with pdfplumber.open(source) as doc:
        page=doc.pages[number];lines=page.extract_text_lines()
        if not lines:return None
        line=max(lines,key=lambda l:SequenceMatcher(None,accent_key(l['text']),accent_key(context),autojunk=False).ratio())
        if SequenceMatcher(None,accent_key(line['text']),accent_key(context),autojunk=False).ratio()<.75:return None
        with pdfium.PdfDocument(source) as pdf:
            pp=pdf[number]
            image=pp.render(scale=3).to_pil().convert('RGB')
            crop=image.crop((max(0,int(line['x0']*3)-12),max(0,int(line['top']*3)-36),min(image.width,int(line['x1']*3)+12),min(image.height,int(line['bottom']*3)+36)))
            pp.close()
    recognized=recognize(crop,'auto')
    if not recognized:return None
    text=max((l['text'] for l in recognized),key=lambda t:SequenceMatcher(None,accent_key(t),accent_key(context),autojunk=False).ratio())
    tokens=list(re.finditer(r'[^\W_]+',text))
    anchors=[t for t in tokens if accent_key(t.group())==accent_key(corrected)]
    if len(anchors)!=1:return None
    new=text[anchors[0].end():].strip();old=remainder.strip()
    words=vocabulary()
    if not new or new==old or len(new)>60:return None
    if any(len(t)>2 and t.casefold() not in words for t in re.findall(r'[^\W\d_]+',new)):return None
    return {'old':old,'new':new,'offset':token.end()+len(remainder)-len(remainder.lstrip()),'kind':'fragment'}
