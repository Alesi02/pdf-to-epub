"""Optional regressions for the source PDFs that exposed the extraction bugs."""
from pathlib import Path
import os
import unittest
import xml.etree.ElementTree as ET
import pdfplumber
import pypdfium2 as pdfium
from native_layout import native_events,visible_page,equation_regions,ordered_lines
from math_epub import prose_markup,page_xml
from reflow import ContentAudit,FlowRenderer
from raster_region import crop_region

ROOT=Path(__file__).resolve().parent.parent
SAMPLES=Path(os.environ.get('PDF_EPUB_SAMPLE_DIR',str(ROOT/'tests'/'samples')))
QUANT=next((ROOT/'epub').glob('Quantitative Trading*.pdf'),None)
if QUANT is None:QUANT=next(SAMPLES.glob('Quantitative Trading*.pdf'),None)
LANDAU=next(SAMPLES.glob('Landau*.pdf'),None) or next(ROOT.glob('Landau*.pdf'),None)
IAMC=next(SAMPLES.glob('IAMC*.pdf'),None) or next(ROOT.glob('IAMC*.pdf'),None)

class SourceSamples(unittest.TestCase):
    def test_note_marker_inside_a_formula_frame_keeps_its_link(self):
        from book_structure import footnotes
        self.assertIsNotNone(IAMC)
        with pdfplumber.open(IAMC) as source,pdfium.PdfDocument(str(IAMC)) as pdf:
            page=visible_page(source.pages[10]).dedupe_chars(tolerance=.1);pp=pdf[10]
            events,_,_=native_events(page,pp,set(),prose_markup,lambda *args:'<img src="test.png"/>',ContentAudit())
            events=footnotes(events,11)
            panels=[e for e in events if e.kind=='table' and 'Nota 7' in e.markup]
            self.assertEqual(len(panels),1)
            self.assertIn('epub:type="noteref"',panels[0].markup)
            self.assertTrue(any(e.kind=='footnote' and 'Volver al texto' in e.markup for e in events))
            pp.close()

    def test_framed_formulas_are_complete_images_without_leftover_text(self):
        self.assertIsNotNone(IAMC)
        root,crops=self.page(IAMC,11)
        self.assertEqual(len(crops),3)
        self.assertEqual(len(root.findall('.//{*}img')),3)
        text=''.join(root.itertext())
        self.assertIn('Ahondando un poco más',text)
        self.assertNotIn('Rotación del Activo No Corriente',text)
        self.assertNotIn('Stock de Productos en Proceso',text)
        self.assertTrue(any(r[0]<89 and r[2]>539 and r[1]<316 and r[3]>371 for r in crops))
        self.assertTrue(any(r[0]<89 and r[2]>539 and r[1]<492 and r[3]>577 for r in crops))

    def test_unframed_fraction_covers_the_full_wider_denominator(self):
        self.assertIsNotNone(IAMC)
        with pdfplumber.open(IAMC) as source:
            page=visible_page(source.pages[10]);lines=ordered_lines(page)
            regions=equation_regions(page,lines)
            for expected in ['Activo No Corriente','Activo Corriente','Stock de Productos en Proceso']:
                line=next(l for l in lines if l['text']==expected)
                self.assertTrue(any(r[0]<=line['x0'] and r[2]>=line['x1'] and r[1]<=line['top'] and r[3]>=line['bottom'] for r in regions),expected)

    def page(self,path,number):
        crops=[]
        with pdfplumber.open(path) as source,pdfium.PdfDocument(str(path)) as pdf:
            page=visible_page(source.pages[number-1]).dedupe_chars(tolerance=.1)
            pp=pdf[number-1];bitmap=pp.render(scale=2).to_pil().convert('RGB')
            audit=ContentAudit()
            def save(region,kind='equation'):
                crop_region(bitmap,page,region)
                crops.append(region)
                return '<img src="test.png"/>'
            events,_,_=native_events(page,pp,set(),prose_markup,save,audit,bitmap)
            flow=FlowRenderer(audit);flow.feed(events,number)
            xml=page_xml('Test',''.join(flow.finish()))
            audit.verify({'test.xhtml':xml})
            return ET.fromstring(xml),crops

    def test_titles_and_registered_marks_are_native_text(self):
        self.assertIsNotNone(QUANT,'No se encontró el PDF original de Quantitative Trading')
        for n,expected in [(53,'Backtesting'),(54,'MATLAB®'),(101,'Execution'),(189,'′')]:
            with self.subTest(page=n):
                root,crops=self.page(QUANT,n)
                self.assertIn(expected,''.join(root.itertext()))
                self.assertEqual(crops,[])

    def test_tables_are_preserved_as_original_images(self):
        self.assertIsNotNone(QUANT,'No se encontró el PDF original de Quantitative Trading')
        for n,columns in [(60,5),(61,5),(62,5),(63,4),(171,3)]:
            with self.subTest(page=n):
                root,crops=self.page(QUANT,n)
                table=root.find('.//{*}table')
                self.assertIsNone(table)
                self.assertTrue(crops)
                self.assertIsNotNone(root.find('.//{*}figure/{*}img'))

    def test_radical_does_not_include_neighboring_prose(self):
        self.assertIsNotNone(QUANT,'No se encontró el PDF original de Quantitative Trading')
        root,crops=self.page(QUANT,66)
        self.assertEqual(len(crops),3)
        self.assertTrue(all(r[2]-r[0]<30 and r[3]-r[1]<18 for r in crops))
        self.assertIn('uncorrelated',''.join(root.itertext()))

    @unittest.skipUnless(LANDAU,'Optional source PDF is not present')
    def test_equation_references_and_explanations_remain_text(self):
        root,crops=self.page(LANDAU,344)
        text=''.join(root.itertext())
        self.assertIn('por la fórmula (79.4) coinciden',text)
        self.assertIn('de donde se sigue',text)
        self.assertGreaterEqual(len(crops),6)
        self.assertFalse(any(r[1]<488 and r[3]>480 for r in crops))

if __name__=='__main__':unittest.main()
