"""Recover glyph names from the PDF's own font encoding; never run OCR."""
import re
from pdfminer.pdftypes import resolve1
from pdfminer.psparser import literal_name
from pdfminer.encodingdb import name2unicode

ALIASES={'angbracketleft':'⟨','angbracketright':'⟩','prime':'′','radicalbig':'√'}

def normalize_glyphs(page):
    encodings={}
    resources=resolve1(page.root_page.page_obj.resources)
    for ref in resolve1(resources.get('Font',{})).values():
        font=resolve1(ref);encoding=resolve1(font.get('Encoding',{}))
        if not isinstance(encoding,dict):continue
        mapping={};code=0
        for entry in resolve1(encoding.get('Differences',[])):
            if isinstance(entry,int):code=entry
            else:mapping[code]=literal_name(entry);code+=1
        encodings[literal_name(font.get('BaseFont',''))]=mapping
    for c in page.chars:
        match=re.fullmatch(r'\(cid:(\d+)\)',c['text'])
        if not match:continue
        glyph=encodings.get(c['fontname'],{}).get(int(match[1]))
        if not glyph:continue
        c['glyph_name']=glyph
        if glyph=='circlecopyrt':
            inside=[o for o in page.chars if o is not c and o['text'] in ('R','C') and c['x0']<=o['x0'] and o['x1']<=c['x1']+1 and abs(o['top']-c['top'])<c['size']]
            if inside:
                c['text']='®' if inside[0]['text']=='R' else '©'
                for o in inside:o['text']=''
                continue
        value=ALIASES.get(glyph)
        if value is None:
            try:value=name2unicode(glyph)
            except (KeyError,ValueError):continue
        if value and value.isprintable():c['text']=value
    # In certain Type 1 math fonts the bounding box is shifted one line up.
    # The radical's adjoining overbar supplies its actual vertical position.
    bars=[o for o in page.lines+page.rects+page.curves if o['bottom']-o['top']<1.8 and o['x1']>o['x0']]
    for c in page.chars:
        if c['text']!='√':continue
        adjoining=[o for o in bars if abs(o['x0']-c['x1'])<2 and abs(o['top']-c['bottom'])<2]
        if adjoining:
            bar=adjoining[0];delta=bar['top']-.7-c['top']
            c['top']+=delta;c['bottom']+=delta;c['doctop']+=delta
