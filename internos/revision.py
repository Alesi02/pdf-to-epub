"""Source-aware, formatting-preserving OCR review and explicit batch apply."""
import re
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from ocr import correct, vocabulary, accent_index,letter_variants

TOKEN=re.compile(r'(?<!\w)[^\W_]+(?!\w)',re.UNICODE)
ET.register_namespace('','http://www.w3.org/1999/xhtml')
ET.register_namespace('epub','http://www.idpf.org/2007/ops')

def text_runs(span):
    runs=[];pieces=[];offset=0
    def add(node,attribute,italic):
        nonlocal offset
        text=getattr(node,attribute) or ''
        if text:
            runs.append((node,attribute,offset,offset+len(text),italic));pieces.append(text);offset+=len(text)
    def walk(node,italic=False):
        italic=italic or node.tag.rsplit('}',1)[-1] in ('em','i') or 'font-style:italic' in node.get('style','').replace(' ','')
        add(node,'text',italic)
        for child in node:
            walk(child,italic);add(child,'tail',italic)
    walk(span)
    return ''.join(pieces),runs

def documents(archive):
    for name in archive.namelist():
        if name.endswith('.xhtml'):yield name,ET.fromstring(archive.read(name))

def source_spans(root):
    return (el for el in root.iter() if el.get('class')=='source-line')

def valid_enclitic(word,words):
    for suffix in ('nos','los','las','les','me','te','se','lo','la','le','os'):
        if word.endswith(suffix):
            stem=word[:-len(suffix)]
            if stem.endswith(('ar','er','ir')) and stem in words:return True
    return False

def suggestions(path,source=None):
    base=vocabulary();result=[]
    with zipfile.ZipFile(path) as z:
        docs=list(documents(z));counts=Counter()
        for name,root in docs:
            for span in source_spans(root):counts.update(m.group().casefold() for m in TOKEN.finditer(''.join(span.itertext())) if m.group().isalpha())
        common={w for w,n in counts.items() if n>=3 and len(w)>=4}
        words=base|common;index=accent_index(base)
        for name,root in docs:
            for span in source_spans(root):
                text,runs=text_runs(span)
                for match in TOKEN.finditer(text):
                    if any(italic and start<match.end() and match.start()<end for _,_,start,end,italic in runs):continue
                    old=match.group();new=correct(old,words,index)
                    if new==old and old.islower() and old.isalpha() and len(old)>=6 and old not in base and counts[old]<3 and not valid_enclitic(old,base):
                        likely=letter_variants(old)&common
                        likely={candidate for candidate in likely if not (len(candidate)==len(old)+1 and any(old[:i]+'rn'+old[i+1:]==candidate for i,c in enumerate(old) if c=='m'))}
                        if len(likely)==1:new=likely.pop()
                    if new!=old:
                        result.append({'file':name,'id':span.get('id'),'old':old,'new':new,'offset':match.start(),'context':text,'kind':'word'})
                        if source and sum(c.isdigit() for c in old)>1:
                            from review_evidence import tail_evidence
                            evidence=tail_evidence(str(Path(source).resolve()),span.get('id'),text,old,new)
                            if evidence and not any(italic and a<evidence['offset']+len(evidence['old']) and evidence['offset']<b for _,_,a,b,italic in runs):
                                result.append(dict(file=name,id=span.get('id'),context=text,**evidence))
    return result

def replace_text(span,start,old,new):
    text,runs=text_runs(span)
    end=start+len(old)
    if text[start:end]!=old:raise ValueError('El texto cambió durante la revisión.')
    changed=False
    for node,attribute,a,b,italic in runs:
        if a>=end or b<=start:continue
        if italic:raise ValueError('La corrección afecta texto en cursiva.')
        value=getattr(node,attribute)
        left=max(0,start-a);right=min(len(value),end-a)
        setattr(node,attribute,value[:left]+(new if not changed else '')+value[right:]);changed=True

def apply(path,selected,source=None):
    from convertir import validate
    path=Path(path)
    allowed={(x['file'],x['id'],x['old'],x['offset']) for x in suggestions(path,source)}
    changes={}
    for item in selected:
        key=(item.get('file'),item.get('id'),item.get('old'),item.get('new'),item.get('offset'))
        if (key[0],key[1],key[2],key[4]) not in allowed:raise ValueError('La sugerencia ya no coincide con el libro. Volvé a revisarlo.')
        if key[3]==key[2]:continue
        if not isinstance(key[3],str) or not key[3] or len(key[3])>2000 or not all(c.isprintable() for c in key[3]):raise ValueError('La corrección no es válida.')
        changes.setdefault((key[0],key[1]),[]).append(key)
    if not changes:return 0
    temp=path.with_suffix('.revision.tmp')
    try:
        with zipfile.ZipFile(path) as source,zipfile.ZipFile(temp,'w') as target:
            for entry in source.infolist():
                data=source.read(entry.filename)
                if any(name==entry.filename for name,ident in changes):
                    root=ET.fromstring(data)
                    for span in source_spans(root):
                        for _,_,old,new,offset in sorted(set(changes.get((entry.filename,span.get('id')),[])),key=lambda x:x[4],reverse=True):replace_text(span,offset,old,new)
                    data=ET.tostring(root,encoding='utf-8',xml_declaration=True)
                target.writestr(entry,data)
        validate(temp);temp.replace(path)
    finally:
        if temp.exists():temp.unlink()
    return sum(len(set(items)) for items in changes.values())
