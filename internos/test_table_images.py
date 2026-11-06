import unittest
from types import SimpleNamespace
from PIL import Image,ImageDraw
from ocr import ocr_events
from reflow import ContentAudit,FlowRenderer
from table_layout import scanned_regions

def row(texts,y):
    return {'text':' '.join(texts),'words':[{'text':t,'x':40+i*150,'y':y,'w':60,'h':18} for i,t in enumerate(texts)]}

class TableImages(unittest.TestCase):
    def test_scanned_numeric_cells_are_replaced_once_and_prose_is_preserved(self):
        lines=[{'text':'Un párrafo anterior al cuadro.','words':[{'text':'Un párrafo anterior al cuadro.','x':40,'y':25,'w':400,'h':18}]},row(['Nombre','Precio','Volumen'],100),row(['A','10','100'],130),row(['B','20','200'],160),row(['C','30','300'],190),{'text':'El texto continúa después.','words':[{'text':'El texto continúa después.','x':40,'y':260,'w':380,'h':18}]}]
        bitmap=Image.new('RGB',(600,800),'white');ImageDraw.Draw(bitmap).rectangle((40,100,400,208),outline='black')
        audit=ContentAudit();crops=[]
        def save(region,kind='equation'):
            crops.append((region,kind));return '<img src="table.png" alt="Tabla"/>'
        events=ocr_events(lines,SimpleNamespace(width=600,height=800,bbox=(0,0,600,800),page_number=1),bitmap,set(),audit,save)
        flow=FlowRenderer(audit);flow.feed(events,1);body=''.join(flow.finish())
        self.assertEqual(len(crops),1);self.assertEqual(crops[0][1],'table')
        self.assertIn('Un párrafo anterior',body);self.assertIn('El texto continúa',body)
        self.assertNotIn('Volumen',body);self.assertNotIn('<table',body)
        self.assertEqual(body.count('table.png'),1)
        audit.verify({'body.xhtml':('<body>'+body+'</body>').encode()})
    def test_captioned_text_only_grid_in_scan_is_a_single_image_region(self):
        image=Image.new('RGB',(600,800),'white');draw=ImageDraw.Draw(image)
        for y in (100,140,180,220):draw.line((40,y,500,y),fill='black',width=2)
        for x in (40,200,350,500):draw.line((x,100,x,220),fill='black',width=2)
        lines=[{'text':'Tabla 1. Categorías','words':[{'text':'Tabla 1. Categorías','x':40,'y':60,'w':180,'h':18}]},row(['Primera','Segunda','Tercera'],110),row(['rojo','verde','azul'],150)]
        regions=scanned_regions(lines,image)
        self.assertEqual(len(regions),1)
        self.assertLessEqual(regions[0][1],100);self.assertGreaterEqual(regions[0][3],220)
    def test_ordinary_prose_with_numbers_is_not_a_table(self):
        lines=[{'text':'En 1990 se publicó este texto.','words':[{'text':'En 1990 se publicó este texto.','x':40,'y':y,'w':400,'h':18}]} for y in (100,130,160)]
        self.assertEqual(scanned_regions(lines,Image.new('RGB',(600,800),'white')),[])
