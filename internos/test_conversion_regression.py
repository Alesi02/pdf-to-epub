import unittest
from types import SimpleNamespace
import xml.etree.ElementTree as ET
from PIL import Image,ImageDraw
from native_layout import choose_text
from raster_region import crop_region
from reflow import Event,FlowRenderer,ContentAudit,split_blocks

class ConversionRegression(unittest.TestCase):
    def test_discretionary_hyphen_is_recovered_from_pdf_control(self):
        text,soft=choose_text('independent publish\x02','independent publish-')
        self.assertEqual(text,'independent publish-');self.assertTrue(soft)
    def test_similar_length_wrong_selection_is_rejected(self):
        self.assertEqual(choose_text('the missing value','the original value')[0],'the original value')
    def test_word_continues_across_source_pages(self):
        audit=ContentAudit();flow=FlowRenderer(audit)
        a=audit.fragment('a','publish-','publish-');b=audit.fragment('b','ing company','ing company')
        flow.feed([Event(20,0,30,a,'text','publish-','a',True)],1)
        flow.feed([Event(20,0,30,b,'text','ing company','b')],2)
        xml='<body>'+''.join(flow.finish())+'</body>'
        self.assertEqual(''.join(ET.fromstring(xml).itertext()),'publishing company')
        self.assertEqual(len(ET.fromstring(xml).findall('p')),1)
        audit.verify({'body.xhtml':xml.encode()})
    def test_real_compound_hyphen_is_preserved(self):
        flow=FlowRenderer(vocabulary={'scary-sounding'})
        flow.feed([Event(0,0,10,'scary-','text','scary-'),Event(12,0,22,'sounding','text','sounding')])
        self.assertIn('scary-sounding',''.join(flow.finish()))
    def test_drop_cap_joins_the_first_word(self):
        flow=FlowRenderer()
        flow.feed([Event(0,0,30,'I','text','I'),Event(4,15,14,'n this chapter','text','n this chapter')])
        self.assertIn('In this chapter',''.join(flow.finish()))
    def test_crop_offset_does_not_shift_formula(self):
        image=Image.new('RGB',(400,600),'white');ImageDraw.Draw(image).rectangle((60,120,100,160),fill='black')
        page=SimpleNamespace(width=200,height=300,bbox=(100,200,300,500))
        crop,width=crop_region(image,page,(130,260,150,280),padding=0)
        self.assertEqual(crop.size,(40,40));self.assertEqual(crop.getextrema(),((0,0),(0,0),(0,0)))
        self.assertEqual(width,20)
    def test_empty_crop_is_not_delivered(self):
        image=Image.new('RGB',(200,300),'white');page=SimpleNamespace(width=200,height=300,bbox=(0,0,200,300))
        with self.assertRaises(ValueError):crop_region(image,page,(20,20,40,40))
    def test_content_audit_detects_missing_and_changed_words(self):
        a=ContentAudit();markup=a.fragment('x','original words','original words')
        with self.assertRaises(ValueError):a.verify({'x.xhtml':b'<body/>'})
        with self.assertRaises(ValueError):a.verify({'x.xhtml':('<body>'+markup.replace('original','altered')+'</body>').encode()})
    def test_chunking_does_not_break_lists(self):
        chunks=split_blocks(['<ul>','<li>one</li>','<li>two</li>','</ul>','<p>next</p>'],limit=10)
        for chunk in chunks:ET.fromstring('<body>'+chunk+'</body>')

if __name__=='__main__':unittest.main()
