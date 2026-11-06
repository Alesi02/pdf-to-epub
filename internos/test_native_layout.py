import unittest
from types import SimpleNamespace
from native_layout import equation_regions,is_margin,key,render_events,overlay_equations,overlay_prose,heading_candidate

class NativeLayoutRegression(unittest.TestCase):
    def test_equations_and_printed_contents_are_not_headings(self):
        for text in ["oS/ot", "f 1 o '-", 'CAPÍTULO IV. MOMENTO CINÉTICO 95', 'CAPÍTULO II . . . . 25']:
            self.assertFalse(heading_candidate(text,20,10,True),text)
        self.assertTrue(heading_candidate('§ 15. Impulso',12,10,True))
    def char(self,text='A',top=10,bottom=20,font='Times-Roman'):
        return dict(text=text,x0=20,x1=30,top=top,bottom=bottom,size=10,fontname=font)
    def page(self,bar):
        return SimpleNamespace(width=600,lines=[bar],rects=[],curves=[])
    def test_underlined_title_does_not_become_an_image(self):
        bar=dict(x0=10,x1=200,top=21,bottom=22)
        lines=[dict(text='A TITLE',chars=[self.char()]),dict(text='Paragraph',chars=[self.char(top=40,bottom=50)])]
        self.assertEqual(equation_regions(self.page(bar),lines),[])
    def test_stacked_fraction_preserves_its_layout(self):
        bar=dict(x0=10,x1=100,top=22,bottom=22)
        lines=[dict(text='A',chars=[self.char()]),dict(text='B',chars=[self.char('B',24,34)])]
        regions=equation_regions(self.page(bar),lines)
        self.assertEqual(len(regions),1)
        self.assertLessEqual(regions[0][1],10)
        self.assertGreaterEqual(regions[0][3],34)
    def test_copyable_equation_and_bullet_stay_text(self):
        page=SimpleNamespace(width=600,lines=[],rects=[],curves=[])
        self.assertEqual(equation_regions(page,[dict(text='a = b + 1',chars=[self.char()])]),[])
        self.assertEqual(equation_regions(page,[dict(text='· Text',chars=[self.char('·',font='Symbol')])]),[])
    def test_running_header_and_folio_are_removed_but_body_number_is_kept(self):
        self.assertTrue(is_margin(dict(text='Running title',top=50,bottom=60),800,{key('Running title')}))
        self.assertTrue(is_margin(dict(text='7',top=760,bottom=770),800,set()))
        self.assertFalse(is_margin(dict(text='7',top=400,bottom=410),800,set()))
    def test_list_continuations_stay_inside_the_list_item(self):
        body=render_events([(10,0,20,'First line','bullet'),(22,0,32,'continued','text'),(34,0,44,'Second item','bullet')])
        self.assertEqual(body,'<ul><li>First line continued</li><li>Second item</li></ul>')

    def test_prose_with_equation_reference_remains_text(self):
        for text in ['por la fórmula (79.4) coinciden. Para ello es necesario que el radicando en (79.4)',
                     'donde la integración usa dV = dx dy dz', 'obtenemos:']:
            self.assertTrue(overlay_prose({'text':text}),text)
        self.assertFalse(overlay_prose({'text':'-in oif/ox = px, -ilioif/oz = pz. (15.4)'}))

    def test_overlay_formula_does_not_absorb_neighboring_prose(self):
        def line(text,top,bottom,x0,x1):
            c=self.char(text,top,bottom);c.update(x0=x0,x1=x1)
            return dict(text=text,chars=[c],top=top,bottom=bottom,x0=x0,x1=x1)
        lines=[line('Las funciones de la ecuación anterior',10,20,20,400),
               line('(3.2)',30,40,370,400),
               line('obtenemos:',50,60,20,100),
               line('De donde se sigue el resultado (3.2)',90,100,20,400)]
        page=SimpleNamespace(width=450,height=600,bbox=(0,0,450,600))
        regions=overlay_equations(page,lines)
        self.assertEqual(len(regions),1)
        self.assertGreater(regions[0][1],20)
        self.assertLess(regions[0][3],50)

if __name__=='__main__':unittest.main()
