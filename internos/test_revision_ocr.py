import tempfile
import unittest
import zipfile
from pathlib import Path
from ocr import correct, vocabulary
from revision import suggestions, apply

class ReviewTests(unittest.TestCase):
    def test_correction_is_suggested_only_with_dictionary_evidence(self):
        words=vocabulary()
        self.assertEqual(correct('un pa1ito y x1z',words),'un palito y x1z')
        self.assertEqual(correct('transpos1c10n d1recc10n H2O',words),'transposición dirección H2O')
    def test_valid_reflexive_verbs_are_protected(self):
        from revision import valid_enclitic
        words=vocabulary()
        for word in ['representarnos','encontrarnos','tenernos']:self.assertTrue(valid_enclitic(word,words),word)
    def test_formatted_line_does_not_hide_plain_text_typos(self):
        import xml.etree.ElementTree as ET
        from revision import text_runs,replace_text
        root=ET.fromstring('<span>se refiere a <em>f</em> y a la transpos1c10n <em>pa1ito</em></span>')
        text,runs=text_runs(root);start=text.index('transpos1c10n')
        self.assertFalse(any(italic and a<start+12 and start<b for _,_,a,b,italic in runs))
        replace_text(root,start,'transpos1c10n','transposición')
        self.assertEqual(root.find('em').text,'f')
        self.assertIn('transposición',''.join(root.itertext()))
        self.assertEqual(root.findall('em')[1].text,'pa1ito')
    def test_user_selects_and_edits_a_suggestion(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'book.epub'
            with zipfile.ZipFile(path,'w') as z:
                z.writestr('mimetype','application/epub+zip',compress_type=zipfile.ZIP_STORED)
                z.writestr('EPUB/a.xhtml','<html xmlns="http://www.w3.org/1999/xhtml"><body><p><span class="source-line" id="source-1-0-0"><em>f</em> un pa1ito ausentes ausente ausente ausente cafés café café café <em>pa1ito</em></span></p></body></html>')
                z.writestr('EPUB/nav.xhtml','<html xmlns="http://www.w3.org/1999/xhtml"><body/></html>')
                z.writestr('EPUB/cover.svg','<svg xmlns="http://www.w3.org/2000/svg"/>')
                z.writestr('EPUB/package.opf','<package xmlns="http://www.idpf.org/2007/opf"><manifest><item id="c" href="cover.svg" properties="cover-image"/><item id="n" href="nav.xhtml" properties="nav"/></manifest></package>')
            matches=suggestions(path);self.assertEqual(len(matches),1);self.assertEqual(matches[0]['new'],'palito')
            matches[0]['new']='palillo';apply(path,matches)
            with zipfile.ZipFile(path) as z: self.assertIn('un palillo',z.read('EPUB/a.xhtml').decode())
            self.assertEqual(suggestions(path),[])

if __name__=='__main__': unittest.main()
