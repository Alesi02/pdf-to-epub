import unittest
from types import SimpleNamespace
from book_structure import footnotes,printed_contents,resolve_fragment_links
from reflow import Event
from native_layout import undecodable_math,is_margin,key
from ocr import select_languages

class BookStructureTests(unittest.TestCase):
    def test_printed_contents_preserves_titles_without_dot_leaders(self):
        entries=printed_contents([SimpleNamespace(text=t) for t in ['Índice','Inicio ........ 7','Capítulo final . . . . 25']])
        self.assertEqual(entries,[('Inicio',7),('Capítulo final',25)])
    def test_notes_have_unique_destinations_and_return_links(self):
        events=[Event(10,10,20,'Texto<sup>1</sup> y otro<sup>2</sup>','text','Texto'),Event(700,10,710,'1 Nota','note','1 Nota'),Event(712,10,722,'Continuación','note','Continuación'),Event(725,10,735,'2 Otra','note','2 Otra')]
        result=footnotes(events,3)
        notes=[e for e in result if e.kind=='footnote']
        self.assertEqual(len(notes),2)
        self.assertIn('epub:type="noteref"',result[0].markup)
        self.assertIn('Continuación',notes[0].markup)
        self.assertIn('footnote-3-1',notes[1].markup)
        resources={'text.xhtml':result[0].markup.encode(),'notes.xhtml':''.join(e.markup for e in notes).encode()}
        resolve_fragment_links(resources)
        self.assertIn(b'href="notes.xhtml#footnote-3-0"',resources['text.xhtml'])
        self.assertIn(b'href="text.xhtml#ref-footnote-3-0"',resources['notes.xhtml'])
    def test_readable_symbols_are_never_rasterized_due_to_font_name(self):
        for symbol in [')','(','=','−','σ','ρ','1']:
            self.assertFalse(undecodable_math({'text':symbol,'fontname':'Symbol'}),symbol)
    def test_small_chart_labels_and_body_are_not_footnotes(self):
        events=[Event(600,10,610,'0.50 Asia','note','0.50 Asia'),Event(620,10,630,'donde el valor cambia','note','donde el valor cambia')]
        result=footnotes(events,1)
        self.assertTrue(all(e.kind=='text' for e in result))
    def test_repeated_author_header_can_move_vertically(self):
        self.assertTrue(is_margin({'text':'AUTHOR NAME','top':71,'bottom':81},800,{key('AUTHOR NAME')}))
    def test_languages_can_change_between_lines(self):
        def line(text,y): return {'text':text,'words':[{'x':10,'y':y,'w':300,'h':20}]}
        candidates=[{'language':'es','lines':[line('libro de lectura',10),line('tbe book bas text',50)]},{'language':'en','lines':[line('l1bro de lectura',10),line('the book has text',50)]}]
        result=select_languages(candidates)
        self.assertEqual(result[0]['text'],'libro de lectura')
        self.assertEqual(result[1]['text'],'the book has text')
