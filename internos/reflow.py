"""Shared reflow state and in-memory content audit (no report files)."""
from dataclasses import dataclass
import html
import re
import xml.etree.ElementTree as ET

@dataclass
class Event:
    top:float
    left:float
    bottom:float
    markup:str
    kind:str
    text:str=''
    ident:str=''
    soft_cut:bool=False
    column:int=0

class ContentAudit:
    def __init__(self):
        self.expected={}
        self.pages=0
        self.glyphs=0
    def fragment(self,ident,text,markup):
        if ident in self.expected:raise ValueError('Fragmento de origen duplicado: '+ident)
        self.expected[ident]=text
        return f'<span class="source-line" id="{ident}">{markup}</span>'
    def remove_cut(self,ident):
        self.expected[ident]=self.expected[ident][:-1]
    def verify(self,resources):
        found={}
        for name,blob in resources.items():
            if not name.endswith('.xhtml'):continue
            root=ET.fromstring(blob)
            for element in root.iter():
                if element.get('class')=='source-line':
                    ident=element.get('id')
                    if ident in found:raise ValueError('Texto duplicado en el EPUB: '+ident)
                    found[ident]=''.join(element.itertext())
        if found.keys()!=self.expected.keys():raise ValueError('El EPUB contiene fragmentos omitidos o duplicados.')
        for ident,text in self.expected.items():
            if ' '.join(text.split())!=' '.join(found[ident].split()):raise ValueError('Cambio de texto no autorizado: '+ident)

class FlowRenderer:
    def __init__(self,audit=None,vocabulary=()):
        self.audit=audit;self.vocabulary=vocabulary
        self.blocks=[];self.parts=[];self.mode='p';self.in_list=False
        self.last=None;self.last_page=None;self.last_bottom=None;self.pending_anchor=''
    def flush(self):
        if self.parts:
            self.blocks.append('<'+self.mode+'>'+''.join(self.parts)+'</'+self.mode+'>');self.parts=[]
        self.last=None
    def close_list(self):
        if self.in_list:self.blocks.append('</ul>');self.in_list=False
    def can_join(self,event):
        if not self.last or not self.last.text.endswith('-') or not event.text:return False
        previous=re.search(r'([^\W\d_]+)-$',self.last.text)
        following=re.match(r'([^\W\d_]+)',event.text)
        if not previous or not following:return False
        left,right=previous[1],following[1]
        if self.last.soft_cut:return True
        return (left+right).casefold() in self.vocabulary and (left+'-'+right).casefold() not in self.vocabulary
    def add_text(self,event,new_page=False):
        if self.parts:
            if self.can_join(event):
                self.parts[-1]=re.sub(r'-(?=(?:</[^>]+>)*$)','',self.parts[-1])
                if self.audit and self.last.ident:self.audit.remove_cut(self.last.ident)
            elif not (self.last and ((re.search(r'\w-$',self.last.text) and re.match(r'\w',event.text)) or (len(self.last.text)==1 and self.last.text.isupper() and event.text[:1].islower() and self.last.bottom-self.last.top>(event.bottom-event.top)*1.5 and event.top<self.last.bottom))):
                self.parts.append(' ')
        self.parts.append(self.pending_anchor+event.markup);self.pending_anchor=''
        self.last=event;self.last_bottom=event.bottom
    def feed(self,events,page=None):
        new_page=page is not None and page!=self.last_page
        if page is not None:self.pending_anchor+=f'<span class="page-anchor" id="page-{page}"/>'
        # Keep short formulas within their prose row; display formulas stay blocks.
        for event in events:
            if event.kind=='equation' and event.bottom-event.top<=22:
                matches=[e for e in events if e.kind in ('text','bullet') and min(e.bottom,event.bottom)>max(e.top,event.top)]
                if matches:
                    event.kind='inline-equation';event.top=min(e.top for e in matches)
        events.sort(key=lambda e:(e.column,round(e.top/3)*3,e.left))
        for event in events:
            if event.kind=='text':
                indent=self.last is not None and event.left>self.last.left+10 and bool(re.search(r'[.!?:]$',self.last.text))
                if not new_page and self.last_bottom is not None and (event.top-self.last_bottom>7 or indent):
                    self.flush();self.close_list();self.mode='p'
                self.add_text(event,new_page);new_page=False
            elif event.kind=='inline-equation':
                self.add_text(event,new_page);new_page=False
            elif event.kind=='bullet':
                self.flush()
                if not self.in_list:self.blocks.append(self.pending_anchor+'<ul>');self.pending_anchor='';self.in_list=True
                self.mode='li';self.add_text(event);new_page=False
            else:
                self.flush();self.close_list();self.mode='p';self.last_bottom=None
                if event.kind=='footnote':
                    self.blocks.append(self.pending_anchor+event.markup);self.pending_anchor='';new_page=False
                    continue
                tag='h2' if event.kind=='heading' else 'aside' if event.kind=='note' else 'pre' if event.kind=='code' else 'figure'
                self.blocks.append(self.pending_anchor+f'<{tag}>'+event.markup+f'</{tag}>');self.pending_anchor=''
                new_page=False
        self.last_page=page
    def finish(self):
        self.flush();self.close_list()
        if self.pending_anchor:self.blocks.append(self.pending_anchor);self.pending_anchor=''
        return self.blocks

def split_blocks(blocks,limit=160000):
    chunks=[];current=[];size=0;list_depth=0
    for block in blocks:
        if current and not list_depth and (size+len(block)>limit or (block.startswith('<h2>') and size>25000)):
            chunks.append(''.join(current));current=[];size=0
        current.append(block);size+=len(block)
        list_depth+=block.count('<ul>')-block.count('</ul>')
    if current:chunks.append(''.join(current))
    return chunks
