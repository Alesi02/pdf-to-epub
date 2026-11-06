"""Reconstrucción de notas y del índice impreso sin líderes de puntos."""
import html
import re
from reflow import Event

def title_key(text):
    return re.sub(r'[^\w]+','',text.casefold())

def printed_contents(events):
    texts=[e.text.strip() for e in events if e.text]
    heading=any(re.fullmatch(r'índice(?: general)?|indice(?: general)?|contents|table of contents|contenido',t,re.I) for t in texts)
    entries=[]; dotted=0
    for text in texts:
        match=re.match(r'^(.+?)(?:\s*\.{2,}\s*|\s+(?:\.\s+){2,}|\s{2,})(\d{1,4})\s*$',text)
        if not match and heading: match=re.match(r'^(.+?\D)\s+(\d{1,4})\s*$',text)
        if match:
            label=re.sub(r'(?:\.\s*)+$','',match[1]).strip()
            if len(label)>2:
                entries.append((label,int(match[2])))
                if re.search(r'(?:\.\s*){2,}',text): dotted+=1
    return entries if len(entries)>=2 and (heading or dotted>=3) else []

def footnotes(events, page):
    notes=sorted([e for e in events if e.kind=='note'],key=lambda e:e.top)
    groups=[]
    for note in notes:
        match=re.match(r'^\s*(\d{1,3}|[*†‡])(?:[.)]?\s+)(?=[^\W\d_])',note.text)
        if match:
            number=match[1]
            reference=any(html.unescape(re.sub(r'<[^>]+>','',m[1])).strip()==number for e in events if e.kind!='note' for m in re.finditer(r'<sup>(.*?)</sup>',e.markup))
            if number=='0' or not (re.search(r'[^\W\d_]{3,}',note.text) or reference):match=None
        if match: groups.append((match[1],[note]))
        elif groups: groups[-1][1].append(note)
        else: note.kind='text'
    consumed=set()
    for group_index,(number,parts) in enumerate(groups):
        ident=f'footnote-{page}-{group_index}';ref=f'ref-{ident}';linked=False
        for event in events if number else []:
            if event.kind in ('note','footnote'): continue
            for match in re.finditer(r'<sup>(.*?)</sup>',event.markup):
                if html.unescape(re.sub(r'<[^>]+>','',match[1])).strip()!=number:continue
                link=f'<a epub:type="noteref" role="doc-noteref" href="#{ident}" id="{ref}">'+match[0]+'</a>'
                event.markup=event.markup[:match.start()]+link+event.markup[match.end():]
                linked=True;break
            if linked:break
            if number in getattr(event,'note_numbers',[]):
                event.markup+=f' <a epub:type="noteref" role="doc-noteref" href="#{ident}" id="{ref}">Nota {html.escape(number)}</a>'
                linked=True;break
        graphics=[e for e in events if e.kind in ('equation','inline-equation') and e.top>=parts[0].top-1 and e.bottom<=parts[-1].bottom+8]
        ordered=sorted(parts+graphics,key=lambda e:(e.top,e.left))
        markup=' '.join(p.markup for p in ordered)
        if linked: markup+=f' <a href="#{ref}" aria-label="Volver al texto">↩</a>'
        first=parts[0]
        first.markup=f'<aside epub:type="footnote" role="doc-footnote" id="{ident}">{markup}</aside>'
        first.kind='footnote'
        consumed.update(id(p) for p in parts[1:])
        consumed.update(id(p) for p in graphics)
    return [e for e in events if id(e) not in consumed]

def resolve_fragment_links(resources):
    destinations={}
    for name,blob in resources.items():
        if name.endswith('.xhtml'):
            for ident in re.findall(r'\bid="([^"]+)"',blob.decode('utf-8')): destinations[ident]=name
    for name,blob in list(resources.items()):
        if not name.endswith('.xhtml'): continue
        text=blob.decode('utf-8')
        text=re.sub(r'href="#([^"]+)"',lambda m:'href="'+destinations.get(m[1],name)+'#'+m[1]+'"',text)
        resources[name]=text.encode('utf-8')
