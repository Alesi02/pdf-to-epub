"""Conversión a EPUB con texto, notas y recortes del original."""
from pathlib import Path
from collections import Counter
import html
import io
import difflib
import re
import zipfile
from datetime import datetime, timezone
import uuid
from statistics import median
import pdfplumber
import pypdfium2 as pdfium
from inspect_books import fingerprint, clean, LIGATURES

MATH_FONT = re.compile(r'unknown|symbol|math|cmsy|cmmi|cmex|msam|msbm|stix|mtmi|mtsy|euclid', re.I)
MATH_CHAR = re.compile(r'[=<>^_+±×÷]|[\u0370-\u03ff\u2070-\u209f\u2190-\u22ff\ufffd\ufffe]|\(cid:')
NS='http://www.w3.org/1999/xhtml'
EPUB='http://www.idpf.org/2007/ops'
CSS='''body{font-family:serif;line-height:1.5;margin:5%}p{margin:.6em 0;text-align:justify}h1,h2{line-height:1.25}img{max-width:100%;height:auto}img.inline-math{display:inline-block}figure{margin:.6em 0;break-inside:avoid;text-align:center}figure img{vertical-align:middle}.cover{text-align:center}.cover img{max-height:95vh;object-fit:contain}table{border-collapse:collapse;width:100%;font-size:.9em}td{padding:.25em .6em;vertical-align:top;text-align:left}nav li{margin:.4em 0}a{color:inherit}.page-anchor{display:inline}pre{white-space:pre-wrap;margin:.3em 0}aside{font-size:.85em;margin:1em 0;border-top:1px solid #888}h2{break-after:avoid}'''

def page_xml(title,body):
    return (f'<?xml version="1.0" encoding="utf-8"?><html xmlns="{NS}" xmlns:epub="{EPUB}" lang="und"><head><title>{html.escape(title)}</title><link rel="stylesheet" href="style.css"/></head><body>{body}</body></html>').encode()

def suspicious(line):
    chars=line['chars']
    if MATH_CHAR.search(line['text']):return True
    # Italic prose and repeated ligature glyphs do not imply mathematics.
    if any(MATH_FONT.search(c['fontname']) for c in chars):return True
    sizes=[c['size'] for c in chars if c['text'].strip()]
    if sizes and min(sizes)<max(sizes)*.8:return True
    return False

def prose_markup(text,chars):
    source=[]
    sizes=Counter(round(c.get('size',0),1) for c in chars if c['text'].strip())
    main_size=sizes.most_common(1)[0][0] if sizes else 0
    bases=[c['matrix'][5] for c in chars if 'matrix' in c and c.get('size',0)>=main_size*.9]
    baseline=median(bases) if bases else None
    for c in sorted(chars,key=lambda c:c['x0']):
        font=c['fontname']
        style=('i' if 'Italic' in font or 'Oblique' in font else '')+('b' if 'Bold' in font else '')
        if baseline is not None and 'matrix' in c and c.get('size',main_size)<main_size*.85:
            if c['matrix'][5]>baseline+main_size*.15:style+='s'
            elif c['matrix'][5]<baseline-main_size*.08:style+='u'
        source.extend((t,style) for t in c['text'].translate(LIGATURES) if not t.isspace())
    target=''.join(c for c in text if not c.isspace())
    styles=['']*len(target)
    for a,b,n in difflib.SequenceMatcher(None,''.join(c for c,_ in source),target,autojunk=False).get_matching_blocks():
        for k in range(n):styles[b+k]=source[a+k][1]
    runs=[];index=0;style=''
    for c in text:
        if not c.isspace():style=styles[index];index+=1
        if runs and runs[-1][1]==style:runs[-1][0]+=c
        else:runs.append([c,style])
    result=[]
    for value,style in runs:
        value=html.escape(value)
        if 'i' in style:value='<em>'+value+'</em>'
        if 'b' in style:value='<strong>'+value+'</strong>'
        if 's' in style:value='<sup>'+value+'</sup>'
        if 'u' in style:value='<sub>'+value+'</sub>'
        result.append(value)
    return ''.join(result)

def prose_lines(page):
    result=[]
    for line in page.extract_text_lines(x_tolerance=2,y_tolerance=3):
        if not suspicious(line):
            result.append(line);continue
        parts=[];part=[]
        for c in sorted(line['chars'],key=lambda c:c['x0']):
            if MATH_FONT.search(c['fontname']) or MATH_CHAR.search(c['text']):
                if part:parts.append(part);part=[]
            else:part.append(c)
        if part:parts.append(part)
        for chars in parts:
            text=pdfplumber.utils.extract_text(chars,x_tolerance=2,y_tolerance=3)
            if len(re.findall(r'[A-Za-z]',text))<6:continue
            result.append({'text':text,'chars':chars,
                'x0':min(c['x0'] for c in chars),'x1':max(c['x1'] for c in chars),
                'top':min(c['top'] for c in chars),'bottom':max(c['bottom'] for c in chars)})
    return result

def bookmark_entries(pdf):
    entries=[]
    for bookmark in pdf.get_toc():
        destination=bookmark.get_dest()
        index=destination.get_index() if destination is not None else None
        # A bookmark can be a group or external link without a page index.
        if not isinstance(index,int) or not 0<=index<len(pdf):continue
        title=bookmark.get_title().strip()
        if title:entries.append((title,index+1))
    return entries

def navigation_document(title,entries,first_page):
    if entries:
        body='<nav epub:type="toc" id="toc"><h1>Índice</h1><ol>'+''.join(
            f'<li><a href="p{entry[1]:04d}.xhtml#{entry[2] if len(entry)>2 else "page-"+str(entry[1])}">{html.escape(entry[0])}</a></li>' for entry in entries)+'</ol></nav>'
    else:
        # EPUB requires a navigation document even without section structure.
        # It stays outside the reading sequence and contains no page index.
        body=(f'<nav epub:type="toc" id="toc" hidden="hidden"><ol><li>'
              f'<a href="p{first_page:04d}.xhtml#page-{first_page}">{html.escape(title)}</a>'
              '</li></ol></nav>')
    return page_xml('Índice' if entries else title,body)

def convert_math(path,output_dir,validator,language='auto'):
    path=Path(path);output_dir=Path(output_dir)
    title=path.stem;digest=fingerprint(path)
    resources={'style.css':CSS.encode()};spine=['cover.xhtml','nav.xhtml']
    pages=[];headings=[];text_count=0;image_count=0;covered_chars=0
    from native_layout import running_headers,native_events,scan_overlay,visible_page
    from reflow import ContentAudit,FlowRenderer,split_blocks
    from raster_region import crop_region
    from book_structure import printed_contents,footnotes,resolve_fragment_links
    from outline import describe,infer_sections,printed_entries as parse_contents,assemble_sections,choose_navigation
    printed_entries=[];labels={};note_blocks=[]
    resources['images/cover.svg']=(f'<svg xmlns="http://www.w3.org/2000/svg" width="600" height="800" viewBox="0 0 600 800"><rect width="600" height="800" fill="#f3efe5"/><text x="300" y="370" text-anchor="middle" font-size="18" fill="#222">'+html.escape(title[:65])+'</text></svg>').encode()
    resources['cover.xhtml']=page_xml(title,'<h1>'+html.escape(title)+'</h1>')
    spine=['nav.xhtml']
    with pdfplumber.open(path) as source, pdfium.PdfDocument(str(path)) as pdf:
        bookmarks=bookmark_entries(pdf)
        headers=running_headers(source)
        labels.update({folio:page for page,folio in headers.page_labels.items()})
        from ocr import recognize, ocr_events, vocabulary
        words=vocabulary(headers.words)
        ocr_pages={}; edge_counts=Counter()
        for i,original in enumerate(source.pages):
            if i not in headers.ocr_indices:continue
            page=visible_page(original)
            pp=pdf[i]; bitmap=pp.render(scale=2).to_pil().convert('RGB')
            lines=recognize(bitmap,language); ocr_pages[i]=lines
            for line in lines:
                boxes=line.get('words',[])
                if not boxes: continue
                top=min(w['y'] for w in boxes)/bitmap.height
                bottom=max(w['y']+w['h'] for w in boxes)/bitmap.height
                if top<.14 or bottom>.88:
                    edge_counts[re.sub(r'\d+','#',''.join(line['text'].casefold().split()))]+=1
            pp.close();original.close()
            print(f'  OCR: {i+1}/{len(source.pages)} páginas',flush=True)
        repeated={key for key,count in edge_counts.items() if count>=3}
        for index,lines in ocr_pages.items():
            pp=pdf[index];width,height=pp.get_size();pp.close()
            # OCR coordinates use the bitmap rendered at scale 2.
            headers.descriptors[index+1]=describe(lines,width*2,height*2)
        headers.sections=infer_sections(headers.descriptors,headers)
        audit=ContentAudit();flow=FlowRenderer(audit,headers.words)
        overlay_notice=False;previous_contents=False
        for i,original in enumerate(source.pages):
            number=i+1;pp=pdf[i]
            page=visible_page(original).dedupe_chars(tolerance=.1)
            overlay=scan_overlay(page)
            bitmap=pp.render(scale=2 if i in ocr_pages else 3).to_pil().convert('RGB') if overlay or i in ocr_pages else None
            def save_equation(region,kind='equation'):
                nonlocal bitmap,image_count
                if bitmap is None:bitmap=pp.render(scale=3).to_pil().convert('RGB')
                crop,width=crop_region(bitmap,page,region,padding=0 if overlay else 1.5)
                buf=io.BytesIO();crop.save(buf,format='PNG')
                name=f'images/equation-{number:04d}-{image_count:04d}.png';resources[name]=buf.getvalue();image_count+=1
                label='Tabla' if kind=='table' else 'Ilustración' if kind=='figure' else 'Ecuación'
                return f'<img src="{name}" style="width:{width/12:.3f}em" alt="{label} del original, página {number}"/>'
            if headers.overlay_pages>len(source.pages)*.5 and not overlay_notice:
                print('  PDF con capa de texto previa: no necesita OCR; el texto se conserva para revisión manual.',flush=True)
                overlay_notice=True
            if i in ocr_pages:
                events=ocr_events(ocr_pages[i],page,bitmap,words,audit,save_equation,repeated)
                sections=[dict(s,top=s['top']/2,bottom=s['bottom']/2,left=s['left']/2,right=s['right']/2) for s in headers.sections.get(number,[])]
                events,detected=assemble_sections(events,sections);count=len(events)
            else:
                events,detected,count=native_events(page,pp,headers,prose_markup,save_equation,audit,bitmap,words)
            raw_lines=ocr_pages[i] if i in ocr_pages else page.extract_text_lines()
            for line in raw_lines:
                t=line['text'].strip()
                if re.fullmatch(r'\d{1,4}',t):
                    if i in ocr_pages:
                        boxes=line.get('words',[]);y=min((w['y'] for w in boxes),default=bitmap.height/2)/bitmap.height
                    else: y=(line['top']-page.bbox[1])/page.height
                    if y<.12 or y>.88: labels[int(t)]=number
            from types import SimpleNamespace
            contents=parse_contents(headers.descriptors.get(number,[]),len(pdf),previous_contents) if number<=len(pdf)*.2+5 or number>=len(pdf)*.8 else []
            if not contents:contents=printed_contents([SimpleNamespace(text=l['text']) for l in raw_lines]) if number<=len(pdf)*.2+5 or number>=len(pdf)*.8 else []
            previous_contents=bool(contents)
            if contents:
                printed_entries.extend(contents)
                for event in events:
                    if event.ident:audit.expected.pop(event.ident,None)
                # Table cells can own source fragments inside a single event.
                for ident in list(audit.expected):
                    if ident.startswith((f'source-{number}-',f'ocr-{number}-',f'table-{number}-')):audit.expected.pop(ident,None)
                events=[];detected=[]
            else:
                events=footnotes(events,number)
                note_blocks.extend(e.markup for e in events if e.kind=='footnote')
                events=[e for e in events if e.kind!='footnote']
            headings.extend(detected);text_count+=count
            flow.feed(events,number);pages.append(number)
            pp.close();original.close()
            if number%25==0:print(f'  Texto adaptable y ecuaciones: {number}/{len(pdf)} páginas',flush=True)
    page_files={}
    if not audit.expected and not image_count:
        raise ValueError('No se detectó texto ni contenido gráfico en el libro; no se creó un EPUB vacío.')
    for ci,body in enumerate(split_blocks(flow.finish())):
        name=f'text-{ci:03d}.xhtml'
        resources[name]=page_xml(title,body);spine.append(name)
        for page_number in re.findall(r'id="page-(\d+)"',body):page_files[int(page_number)]=name
    if set(page_files)!=set(pages):raise ValueError('Faltan destinos internos de páginas del PDF.')
    if note_blocks:
        resources['notes.xhtml']=page_xml('Notas','<h1>Notas</h1>'+''.join(note_blocks));spine.append('notes.xhtml')
    anchors={entry[2] for entry in headings if len(entry)>2}
    sections={n:[s for s in values if s['anchor'] in anchors] for n,values in headers.sections.items()}
    entries=choose_navigation(bookmarks,printed_entries,sections,labels,pages)
    nav=navigation_document(title,entries,pages[0]).decode('utf8')
    # A section later on a PDF page can belong to a different EPUB chunk
    # from that page's initial anchor. Resolve using the actual destination ID.
    nav=re.sub(r'p(\d+)\.xhtml#([^"<>]+)',lambda m:'#'+m[2],nav)
    resources['nav.xhtml']=nav.encode('utf8')
    resolve_fragment_links(resources)
    if not entries:spine.remove('nav.xhtml')
    audit.verify(resources)
    uid='urn:uuid:'+str(uuid.uuid5(uuid.NAMESPACE_URL,digest+'-math-v1'))
    manifest=[];ids={}
    for i,name in enumerate(resources):
        ids[name]=f'i{i}'
        media='image/png' if name.endswith('.png') else 'image/svg+xml' if name.endswith('.svg') else 'text/css' if name.endswith('.css') else 'application/xhtml+xml'
        props=' properties="nav"' if name=='nav.xhtml' else ' properties="cover-image"' if name=='images/cover.svg' else ''
        manifest.append(f'<item id="i{i}" href="{name}" media-type="{media}"{props}/>')
    stamp=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    resources['package.opf']=(f'<?xml version="1.0" encoding="utf-8"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="book-id">{uid}</dc:identifier><dc:title>{html.escape(title)}</dc:title><dc:language>und</dc:language><meta property="dcterms:modified">{stamp}</meta><meta property="rendition:layout">reflowable</meta></metadata><manifest>'+''.join(manifest)+'</manifest><spine>'+''.join(f'<itemref idref="{ids[n]}"/>' for n in spine)+'</spine></package>').encode()
    output_dir.mkdir(parents=True,exist_ok=True)
    dest=output_dir/(path.stem+'.epub');temp=dest.with_suffix('.epub.tmp')
    try:
        with zipfile.ZipFile(temp,'w',compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr('mimetype','application/epub+zip',compress_type=zipfile.ZIP_STORED)
            z.writestr('META-INF/container.xml','<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="EPUB/package.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
            for n,b in resources.items():z.writestr('EPUB/'+n,b)
        validator(temp)
        temp.replace(dest)
    finally:
        if temp.exists():temp.unlink()
    print(f'  Control de contenido: {audit.pages} páginas; {len(audit.expected)} fragmentos comprobados sin omisiones ni duplicados.',flush=True)
    print(f'  EPUB listo: {dest.name}; {len(pages)} páginas, {len(entries)} entradas de índice, {text_count} líneas de texto y {image_count} ecuaciones o ilustraciones originales.',flush=True)
    return dest
