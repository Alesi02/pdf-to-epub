#!/usr/bin/env python3
"""Conversión de PDF a EPUB, con OCR cuando falta la capa de texto."""
from pathlib import Path
import argparse
import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parent.parent
XHTML='http://www.w3.org/1999/xhtml'
EPUB='http://www.idpf.org/2007/ops'
NS={'h':XHTML,'opf':'http://www.idpf.org/2007/opf','epub':EPUB}

def validate(path,expected=None):
    import posixpath
    from urllib.parse import unquote
    with zipfile.ZipFile(path) as z:
        names=set(z.namelist());first=z.infolist()[0]
        assert first.filename=='mimetype' and first.compress_type==zipfile.ZIP_STORED
        assert z.read('mimetype')==b'application/epub+zip'
        assert z.testzip() is None
        docs={n:ET.fromstring(z.read(n)) for n in names if n.endswith(('.xhtml','.opf','.ncx','.xml'))}
        ids={n:{e.attrib['id'] for e in d.iter() if 'id' in e.attrib} for n,d in docs.items()}
        for n,d in docs.items():
            all_ids=[e.attrib['id'] for e in d.iter() if 'id' in e.attrib]
            assert len(all_ids)==len(set(all_ids)),f'ID duplicado en {n}'
        links=0
        for name,doc in docs.items():
            for el in doc.iter():
                for attr in ('href','src'):
                    ref=el.get(attr)
                    if ref is None or re.match(r'^[a-z]+:',ref):continue
                    target,_,fragment=unquote(ref).partition('#')
                    target=posixpath.normpath(posixpath.join(posixpath.dirname(name),target)) if target else name
                    assert target in names,f'Recurso faltante: {name} -> {ref}'
                    if fragment:assert fragment in ids.get(target,set()),f'Destino inexistente: {name} -> {ref}'
                    links+=1
        found={}
        for name,doc in docs.items():
            for el in doc.iter():
                if el.get('class')=='source-line':
                    ident=el.get('id');assert ident not in found,f'Texto duplicado: {ident}'
                    found[ident]=(' '.join(''.join(c.itertext()) for c in el) if el.tag.endswith('}tr') else ''.join(el.itertext()))
        if expected is not None:
            assert set(found)==set(expected),'Faltan líneas o hay líneas duplicadas'
            for ident,text in expected.items():assert ' '.join(found[ident].split())==' '.join(text.split()),f'Texto diferente: {ident}'
        opf=docs['EPUB/package.opf'];items=opf.findall('opf:manifest/opf:item',NS)
        covers=[i for i in items if i.get('properties')=='cover-image'];assert len(covers)==1
        assert len([i for i in items if i.get('properties')=='nav'])==1
        return {'xml_valid':True,'internal_links_checked':links,'source_lines_preserved':len(found),
                'source_coverage_ok':expected is not None,'text_matches_audited_extraction':expected is not None,
                'cover_present':True}

def main():
    parser=argparse.ArgumentParser(description='Convierte PDF a EPUB adaptable.')
    parser.add_argument('pdf',nargs='*',type=Path,help='PDF seleccionados para convertir.')
    parser.add_argument('--salida',type=Path,default=ROOT/'epub')
    parser.add_argument('--validar',type=Path,help='Verifica un EPUB existente.')
    parser.add_argument('--idioma',default='auto',help='auto: compara todos los idiomas OCR instalados; también admite es,en.')
    args=parser.parse_args()
    if args.validar:
        print(json.dumps(validate(args.validar),ensure_ascii=False,indent=2));return 0
    paths=args.pdf or sorted(ROOT.glob('*.pdf'))
    if not paths:parser.error('No hay archivos PDF seleccionados.')
    from math_epub import convert_math
    errors=[]
    for path in paths:
        try:
            print(f'Procesando {path.name}...',flush=True)
            convert_math(path,args.salida,validate,language=args.idioma)
        except Exception as exc:
            errors.append((path.name,str(exc)))
            print(f'  ERROR: {exc}',file=sys.stderr,flush=True)
    return 1 if errors else 0

if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr,'reconfigure'):sys.stderr.reconfigure(encoding='utf-8')
    raise SystemExit(main())
