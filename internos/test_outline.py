import unittest
from outline import infer_sections,printed_entries,choose_navigation,assemble_sections
from reflow import Event,ContentAudit
from math_epub import navigation_document
import xml.etree.ElementTree as ET

def line(text,top,size=10,font='Body',bold=False,italic=False,left=50,right=400):
    return dict(text=text,top=top,bottom=top+size,left=left,right=right,size=size,font=font,bold=bold,italic=italic,uniform=True,width=500,height=700)

BODY='A long paragraph providing the ordinary typeface of the document for comparison'

class OutlineTests(unittest.TestCase):
    def test_drop_cap_is_not_a_heading_and_centered_title_stays_together(self):
        roman=line('VII',100,size=14,font='Heading-Bold',bold=True,left=195,right=225)
        a=line('A CENTERED TITLE',140,size=13,left=110,right=310)
        b=line('CONTINUED',157,size=13,left=170,right=250)
        cap=line('H',210,size=24,font='Decorative',left=50,right=73)
        prose=line('ere begins a long ordinary paragraph with the content of the chapter',218,size=14,left=75,right=400)
        pages={1:[roman,a,b,cap,prose,line(BODY,234,size=14)]}
        sections=infer_sections(pages)[1]
        self.assertEqual(len(sections),1)
        self.assertEqual(sections[0]['label'],'VII A CENTERED TITLE CONTINUED')
    def test_unstyled_heading_can_be_identified_by_its_separation(self):
        pages={1:[line('Background',70),line(BODY,110),line(BODY,125)]}
        self.assertEqual([s['label'] for s in infer_sections(pages)[1]],['Background'])
    def test_smaller_heading_style_and_italic_continuation_are_recognized(self):
        pages={1:[line('CHAPTER I',70,size=10,font='Heading'),line('A SMALLER TITLE',95,size=9,font='Heading-Bold',bold=True),line('ITS ITALIC CONTINUATION',109,size=9,font='Heading-Italic',italic=True),line(BODY,150,size=11),line(BODY,166,size=11)]}
        sections=infer_sections(pages)
        self.assertEqual(len(sections[1]),1)
        self.assertEqual(sections[1][0]['label'],'CHAPTER I A SMALLER TITLE ITS ITALIC CONTINUATION')
    def test_table_caption_is_not_a_book_section(self):
        pages={1:[line('Table 2. Example',70,font='Heading-Bold',bold=True),line(BODY,110),line(BODY,125)]}
        self.assertEqual(infer_sections(pages)[1],[])
    def test_aligned_column_labels_are_not_section_titles(self):
        header=line('NAME PARTY DISTRICT',70,font='Heading-Bold',bold=True);header['columns']=2
        self.assertEqual(infer_sections({1:[header,line(BODY,110),line(BODY,125)]})[1],[])
    def test_without_printed_index_uses_same_size_bold_section_titles(self):
        pages={1:[line('First section',70,font='Body-Bold',bold=True),line(BODY,105),line(BODY,120)],2:[line('Second section',70,font='Body-Bold',bold=True),line(BODY,105),line(BODY,120)]}
        sections=infer_sections(pages)
        nav=choose_navigation([],[],sections,{},[1,2])
        self.assertEqual([e[0] for e in nav],['First section','Second section'])
        self.assertTrue(all(len(e)==3 for e in nav))
    def test_roman_number_and_wrapped_title_form_one_destination(self):
        pages={3:[line('III',70,bold=True,font='Heading'),line('A LONG TITLE,',95,font='Heading'),line('CONTINUED ON THE NEXT LINE',110,font='Heading'),line(BODY,150),line(BODY,165)]}
        sections=infer_sections(pages)
        self.assertEqual(len(sections[3]),1)
        self.assertEqual(sections[3][0]['label'],'III A LONG TITLE, CONTINUED ON THE NEXT LINE')
    def test_wrapped_printed_index_omits_author_and_separates_blocks(self):
        lines=[line('ÍNDICE GENERAL',20,bold=True),line('Prólogo I /',50,right=170),line('A long opening title',62,right=250),line('An Author 7',74,italic=True,right=400),line('Anexo I / 90',100,right=400),line('a) A supplementary document',124,right=250),line('A new part',150,right=250),line('Prólogo',180,right=170),line('Second opening title',192,right=250),line('Another Author 100',204,italic=True,right=400)]
        result=printed_entries(lines,200)
        self.assertEqual(result,[('Prólogo I: A long opening title',7),('Anexo I',90),('Prólogo Second opening title',100)])
    def test_repeated_title_resolves_using_printed_destination(self):
        sections={10:[dict(label='Introduction',page=10,anchor='s10',top=70)],100:[dict(label='Introduction',page=100,anchor='s100',top=70)]}
        nav=choose_navigation([], [('Introduction',100)],sections,{100:100},list(range(1,101)))
        self.assertEqual(nav[0],('Introduction',100,'s100'))
    def test_multiline_heading_preserves_source_audit_and_exact_anchor(self):
        audit=ContentAudit();events=[]
        for i,text in enumerate(['A title','continued']):
            markup=audit.fragment(str(i),text,text);events.append(Event(70+i*15,50,80+i*15,markup,'text',text,str(i)))
        section=dict(label='A title continued',page=3,anchor='section-3-0',top=70,bottom=95,left=50,right=400)
        events,entries=assemble_sections(events,[section]);self.assertEqual(len(events),1)
        audit.verify({'test.xhtml':('<body>'+events[0].markup+'</body>').encode()})
        nav=ET.fromstring(navigation_document('Book',entries,1))
        self.assertEqual(nav.find('.//{*}a').get('href'),'p0003.xhtml#section-3-0')
    def test_heading_later_on_page_links_to_its_actual_epub_chunk(self):
        from book_structure import resolve_fragment_links
        resources={'text-000.xhtml':b'<body><span id="page-3"/>Earlier text</body>','text-001.xhtml':b'<body><h2 id="section-3-0">Later section</h2></body>','nav.xhtml':b'<body><a href="#section-3-0">Later section</a></body>'}
        resolve_fragment_links(resources)
        self.assertIn(b'href="text-001.xhtml#section-3-0"',resources['nav.xhtml'])
    def test_plain_prose_and_end_of_page_signature_are_not_sections(self):
        pages={1:[line(BODY,70),line(BODY,85),line('A short continuation',100),line('AUTHOR',600,font='Heading')]}
        self.assertEqual(infer_sections(pages)[1],[])
