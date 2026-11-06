"""Archive validation tests independent of old OCR profiles and reports."""
from pathlib import Path
import tempfile
import unittest
import zipfile
from convertir import validate
from math_epub import navigation_document
import xml.etree.ElementTree as ET

class ArchiveChecks(unittest.TestCase):
    def archive(self,href='text.xhtml#start',body='<p id="start">Original words</p>'):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        path=Path(folder.name)/'book.epub'
        with zipfile.ZipFile(path,'w') as z:
            z.writestr('mimetype','application/epub+zip',compress_type=zipfile.ZIP_STORED)
            z.writestr('EPUB/cover.svg','<svg xmlns="http://www.w3.org/2000/svg"/>')
            z.writestr('EPUB/text.xhtml','<html xmlns="http://www.w3.org/1999/xhtml"><body>'+body+'</body></html>')
            z.writestr('EPUB/nav.xhtml','<html xmlns="http://www.w3.org/1999/xhtml"><body><a href="'+href+'">Section</a></body></html>')
            z.writestr('EPUB/package.opf','<package xmlns="http://www.idpf.org/2007/opf"><manifest><item id="c" href="cover.svg" properties="cover-image"/><item id="n" href="nav.xhtml" properties="nav"/><item id="t" href="text.xhtml"/></manifest></package>')
        return path
    def test_valid_archive(self):
        self.assertTrue(validate(self.archive())['xml_valid'])
    def test_missing_navigation_target_is_rejected(self):
        with self.assertRaisesRegex(AssertionError,'Destino inexistente'):validate(self.archive('text.xhtml#missing'))
    def test_missing_resource_is_rejected(self):
        with self.assertRaisesRegex(AssertionError,'Recurso faltante'):validate(self.archive('lost.xhtml'))
    def test_changed_source_words_are_rejected(self):
        body='<p><span class="source-line" id="source-1">Changed words</span></p>'
        with self.assertRaisesRegex(AssertionError,'Texto diferente'):
            validate(self.archive('text.xhtml',body),expected={'source-1':'Original words'})
    def test_absent_headings_do_not_create_a_page_index(self):
        root=ET.fromstring(navigation_document('Book',[],1))
        ns={'h':'http://www.w3.org/1999/xhtml'}
        self.assertEqual(root.find('.//h:nav',ns).get('hidden'),'hidden')
        self.assertEqual([e.text for e in root.findall('.//h:a',ns)],['Book'])

if __name__=='__main__':unittest.main()
