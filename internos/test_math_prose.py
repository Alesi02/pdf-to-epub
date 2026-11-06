import unittest
import xml.etree.ElementTree as ET
from math_epub import suspicious, prose_markup, bookmark_entries
from unittest.mock import Mock

class MathProseRegression(unittest.TestCase):
    def test_superscript_and_subscript_remain_native_markup(self):
        chars=[dict(text='x',fontname='Times-Roman',size=10,x0=0,matrix=(1,0,0,1,0,100)),
               dict(text='2',fontname='Times-Roman',size=6,x0=5,matrix=(1,0,0,1,5,104)),
               dict(text='y',fontname='Times-Roman',size=10,x0=10,matrix=(1,0,0,1,10,100)),
               dict(text='1',fontname='Times-Roman',size=6,x0=15,matrix=(1,0,0,1,15,98))]
        markup=prose_markup('x2y1',chars)
        self.assertIn('<sup>2</sup>',markup);self.assertIn('<sub>1</sub>',markup)
    def line(self,text,font='Times-Roman'):
        return {'text':text,'chars':[{'text':c,'fontname':font,'size':11,'x0':i} for i,c in enumerate(text)]}
    def test_italic_sentence_is_text(self):
        line=self.line('There are three convergence theorems.','Times-Italic')
        self.assertFalse(suspicious(line))
        rendered=prose_markup(line['text'],line['chars'])
        self.assertEqual(''.join(ET.fromstring('<p>'+rendered+'</p>').itertext()),line['text'])
        self.assertIn('<em>',rendered)
    def test_duplicate_ligature_does_not_rasterize_sentence(self):
        line=self.line('is too often not defined.')
        line['chars'].insert(18,{'text':'ﬁ','fontname':'Times-Roman','size':11,'x0':17.5})
        self.assertFalse(suspicious(line))
        self.assertEqual(''.join(ET.fromstring('<p>'+prose_markup(line['text'],line['chars'])+'</p>').itertext()),line['text'])
    def test_equation_and_unknown_math_font_stay_original(self):
        self.assertTrue(suspicious(self.line('f(x) = 0')))
        self.assertTrue(suspicious(self.line('f(x)','unknown')))

class BookmarkRegression(unittest.TestCase):
    def test_bookmarks_without_page_do_not_block_conversion(self):
        bookmarks=[]
        for index in (None,-1,0,2,3):
            bookmark=Mock()
            bookmark.get_dest.return_value.get_index.return_value=index
            bookmark.get_title.return_value='Título'
            bookmarks.append(bookmark)
        no_destination=Mock()
        no_destination.get_dest.return_value=None
        bookmarks.append(no_destination)
        class Pdf:
            def __len__(self):return 3
            def get_toc(self):return iter(bookmarks)
        self.assertEqual(bookmark_entries(Pdf()),[('Título',1),('Título',3)])
        for bookmark in bookmarks[:-1]:
            bookmark.get_dest.return_value.get_index.assert_called_once()

if __name__=='__main__':unittest.main()
