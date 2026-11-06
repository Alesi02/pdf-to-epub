"""Interfaz local para convertir y revisar libros."""
import base64
import io
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import webbrowser
import threading
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from revision import suggestions, apply

ROOT=Path(__file__).resolve().parent.parent
OUTPUT=ROOT/'epub'
TOKEN=secrets.token_urlsafe(24)
SESSION=tempfile.TemporaryDirectory(prefix='libros-sesion-')
SOURCES={}
JOBS={}
REVIEW_LOCK=threading.Lock()

@lru_cache(maxsize=16)
def recognized_page(source, index, language):
    import pypdfium2 as pdfium
    from ocr import recognize
    pdf=pdfium.PdfDocument(str(source));page=pdf[index]
    try: return recognize(page.render(scale=2).to_pil().convert('RGB'),language)
    finally: page.close();pdf.close()

def preview(source, item):
    import pypdfium2 as pdfium
    match=re.match(r'(?:source|ocr)-(\d+)-(\d+)',item['id'])
    if not match: raise ValueError('No se pudo localizar la página original.')
    index=int(match[1])-1
    pdf=pdfium.PdfDocument(str(source)); page=pdf[index]
    try:
        image=page.render(scale=2).to_pil().convert('RGB')
        if item['id'].startswith('ocr-'):
            lines=recognized_page(str(source),index,item.get('language','es'))
            n=int(match[2]); boxes=lines[n]['words'] if n<len(lines) else []
            if boxes:
                left=min(w['x'] for w in boxes); top=min(w['y'] for w in boxes)
                right=max(w['x']+w['w'] for w in boxes); bottom=max(w['y']+w['h'] for w in boxes)
                image=image.crop((max(0,int(left)-30),max(0,int(top)-35),min(image.width,int(right)+30),min(image.height,int(bottom)+35)))
        else:
            import pdfplumber
            with pdfplumber.open(source) as doc:
                p=doc.pages[index]
                lines=p.extract_text_lines()
                needle=' '.join(item['context'].split()).casefold()
                line=next((l for l in lines if needle in ' '.join(l['text'].split()).casefold() or ' '.join(l['text'].split()).casefold() in needle),None)
                if line:
                    image=image.crop((max(0,int(line['x0']*2)-30),max(0,int(line['top']*2)-35),min(image.width,int(line['x1']*2)+30),min(image.height,int(line['bottom']*2)+35)))
        buffer=io.BytesIO();image.save(buffer,format='PNG',optimize=True)
        return base64.b64encode(buffer.getvalue()).decode('ascii')
    finally: page.close();pdf.close()

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def reply(self,status,data,kind='application/json; charset=utf-8'):
        body=json.dumps(data,ensure_ascii=False).encode() if isinstance(data,dict) else data
        self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(body)
    def route(self):
        prefix='/'+TOKEN+'/';path=urlsplit(self.path).path
        return path[len(prefix):] if path.startswith(prefix) else None
    def do_GET(self):
        if self.route()=='': return self.reply(200,(ROOT/'internos'/'index.html').read_bytes(),'text/html; charset=utf-8')
        if self.route()=='status':
            job=parse_qs(urlsplit(self.path).query).get('job',[''])[0]
            return self.reply(200,{'status':JOBS.get(job,'Analizando si necesita OCR…')})
        if self.route()=='languages':
            from ocr import available_languages
            return self.reply(200,{'languages':available_languages()})
        self.reply(404,{'error':'No encontrado'})
    def do_POST(self):
        route=self.route()
        if route is None: return self.reply(403,{'error':'Acceso denegado'})
        try:
            if route=='open':
                OUTPUT.mkdir(exist_ok=True);os.startfile(OUTPUT);return self.reply(200,{'ok':True})
            length=int(self.headers.get('Content-Length','0'))
            if route in ('preview','apply'):
                if length>2_000_000: raise ValueError('La revisión es demasiado grande.')
                data=json.loads(self.rfile.read(length));key=data['book']
                if key not in SOURCES: raise ValueError('El libro ya no está disponible en esta sesión.')
                source,target,language=SOURCES[key]
                if route=='preview':
                    item=data['item'];item['language']=language
                    return self.reply(200,{'image':preview(source,item)})
                with REVIEW_LOCK:
                    items=suggestions(target,source) if data.get('all') else data['items']
                    count=apply(target,items,source)
                    remaining=suggestions(target,source)
                return self.reply(200,{'suggestions':remaining,'applied':count})
            if route!='convert': return self.reply(404,{'error':'No encontrado'})
            query=parse_qs(urlsplit(self.path).query)
            name=query.get('name',[''])[0].replace('\\','/').split('/')[-1]
            language=query.get('language',['auto'])[0]
            job=query.get('job',[''])[0][:100]
            if Path(name).suffix.lower()!='.pdf' or not re.fullmatch(r'auto|[a-z]{2,3}(?:,[a-z]{2,3})*',language): raise ValueError('Seleccioná un PDF válido.')
            if length<=0: raise ValueError('El archivo está vacío.')
            key=secrets.token_urlsafe(18);folder=Path(SESSION.name)/key;folder.mkdir()
            source=folder/name
            with source.open('wb') as stream:
                while length:
                    chunk=self.rfile.read(min(1024*1024,length))
                    if not chunk: raise ValueError('La carga se interrumpió.')
                    stream.write(chunk);length-=len(chunk)
            JOBS[job]='Analizando si necesita OCR…'
            process=subprocess.Popen([sys.executable,'-u',str(ROOT/'internos'/'convertir.py'),str(source),'--salida',str(OUTPUT),'--idioma',language],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            log=[];ocr_status=''
            for raw in process.stdout:
                line=raw.decode('utf-8',errors='replace').strip();log.append(line)
                if 'necesita OCR' in line or 'Necesita OCR' in line: ocr_status=line
                JOBS[job]=ocr_status+' · '+line if ocr_status and line!=ocr_status else line
            if process.wait(): raise ValueError('\n'.join(log[-8:]))
            target=OUTPUT/(Path(name).stem+'.epub')
            for old in [k for k,v in SOURCES.items() if v[1]==target]: del SOURCES[old]
            SOURCES[key]=(source,target,language)
            self.reply(200,{'name':target.name,'book':key,'suggestions':suggestions(target,source)})
        except Exception as error: self.reply(400,{'error':str(error)})

if __name__=='__main__':
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    url=f'http://127.0.0.1:{server.server_port}/{TOKEN}/'
    print('PDF a EPUB está abierto. Mantené esta ventana abierta mientras usás la aplicación.\n'+url,flush=True)
    webbrowser.open(url)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close();SESSION.cleanup()
