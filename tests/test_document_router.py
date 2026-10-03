import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from kalmora.documents.contracts import Candidate, ParsedBlock, ParsedDocument, PageImage, ResolutionRequest, ResolutionResult
from kalmora.documents.router import DocumentRouter, ParseError


class RouterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.folder = self.root / 'inbox/ap/doc'
        self.folder.mkdir(parents=True)
        self.router = DocumentRouter(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_independent_sources_and_exact_xml_json(self):
        xml = b'<Facturae><InvoiceNumber>A</InvoiceNumber><Total>12.3400</Total><Total>13.3400</Total></Facturae>'
        (self.folder/'invoice.xml').write_bytes(xml)
        message = '{"subject": "Invoice", "observed": 12.3400000000000000001}'
        (self.folder/'message.json').write_text(message)
        parsed = self.router.parse_folder('inbox/ap/doc')
        self.assertFalse(parsed.errors)
        self.assertEqual(len(parsed.documents), 2)
        invoice = next(d for d in parsed.documents if d.media_type == 'application/xml')
        self.assertEqual(invoice.source_sha256, hashlib.sha256(xml).hexdigest())
        self.assertEqual([b.text for b in invoice.blocks], ['A', '12.3400', '13.3400'])
        self.assertEqual(invoice.blocks[2].source_field, '/Facturae/Total[2]')
        mail = next(d for d in parsed.documents if d.media_type == 'application/json')
        self.assertEqual(mail.blocks[0].text, message)

    def test_xml_attributes_and_errors_are_not_facts(self):
        (self.folder/'cfdi.xml').write_text('<c:Comprobante xmlns:c="urn:cfdi" Total="32542.30"><c:Emisor Rfc="ABC"/></c:Comprobante>')
        cfdi = self.router.parse('inbox/ap/doc/cfdi.xml')
        self.assertEqual([(b.source_field,b.text) for b in cfdi.blocks], [('/Comprobante/@Total','32542.30'),('/Comprobante/Emisor[1]/@Rfc','ABC')])
        (self.folder/'broken.xml').write_text('<broken>')
        (self.folder/'entity.xml').write_text('<!DOCTYPE x [<!ENTITY y "boom">]><x>&y;</x>')
        folder = self.router.parse_folder('inbox/ap/doc')
        self.assertEqual(len(folder.documents), 1)
        self.assertEqual({e.category for e in folder.errors}, {'invalid_xml'})

    def test_path_boundary_symlinks_golden_and_missing(self):
        for relative in ('../outside', 'golden/x.json', '/tmp/x', 'erp/vendors.jsonl', 'inbox/../../outside'):
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                self.router.parse(relative)
        golden = self.root/'golden'
        golden.mkdir()
        (golden/'answers.json').write_text('{}')
        (self.folder/'linked.json').symlink_to(golden/'answers.json')
        with self.assertRaises(ValueError):
            self.router.parse('inbox/ap/doc/linked.json')
        with self.assertRaises(ParseError) as error:
            self.router.parse('inbox/ap/doc/missing.pdf')
        self.assertEqual(error.exception.category, 'missing_source')

    def test_parsed_roundtrip_image_hash_and_context_invalidation(self):
        document = ParsedDocument('inbox/ap/d/a.pdf', 'a'*64, 'application/pdf', 'parser-v1',
                                  (ParsedBlock('page.1','original text',1),),
                                  (PageImage(1,'image/png',b'image bytes'),))
        restored = ParsedDocument.from_dict(document.to_dict())
        self.assertEqual(restored,document)
        value = document.to_dict(); value['images'][0]['base64'] = 'YmFk'
        with self.assertRaises(ValueError): ParsedDocument.from_dict(value)
        request = ResolutionRequest(document,(Candidate('one',{'vendor':'A'}),),{'remaining_milli':1000})
        changed = ResolutionRequest(document,request.candidates,{'remaining_milli':999})
        other_candidate = ResolutionRequest(document,(Candidate('one',{'vendor':'B'}),),request.context)
        self.assertNotEqual(request.sha256,changed.sha256)
        self.assertNotEqual(request.sha256,other_candidate.sha256)
        with self.assertRaises(ValueError): ResolutionRequest(document,(Candidate('one',{}),Candidate('one',{})))

    def test_preparsed_snapshot_is_bound_to_source_path_and_hash(self):
        source = b"synthetic original PDF bytes"
        source_path = self.folder / "notice.pdf"
        source_path.write_bytes(source)
        normalized = self.root / "normalized_sources" / self.root.name / "inbox/ap/doc/notice.pdf.json"
        normalized.parent.mkdir(parents=True)
        document = ParsedDocument("inbox/ap/doc/notice.pdf", hashlib.sha256(source).hexdigest(),
                                  "application/pdf", "source-router-test",
                                  (ParsedBlock("page.1", "payment evidence", 1),))
        normalized.write_text(json.dumps(document.to_dict()), encoding="utf-8")
        router = DocumentRouter(self.root, use_preparsed=True,
                                normalized_dir=self.root / "normalized_sources")
        self.assertEqual(router.parse("inbox/ap/doc/notice.pdf").blocks[0].text, "payment evidence")

        source_path.write_bytes(b"changed source bytes")
        with self.assertRaises(ParseError) as error:
            router.parse("inbox/ap/doc/notice.pdf")
        self.assertEqual(error.exception.category, "preparsed_source_hash_mismatch")

    def test_nonfinite_json_and_unsupported_are_explicit(self):
        (self.folder/'message.json').write_text('{"amount": NaN}')
        (self.folder/'file.bin').write_bytes(b'unknown')
        folder = self.router.parse_folder('inbox/ap/doc')
        self.assertEqual(len(folder.documents),0)
        self.assertEqual({e.category for e in folder.errors},{'invalid_json','unsupported_format'})

    def test_explicit_empty_xml_and_resolution_roundtrip(self):
        (self.folder/'empty.xml').write_text('<Facturae><TaxIdentificationNumber/></Facturae>')
        document = self.router.parse('inbox/ap/doc/empty.xml')
        self.assertEqual(document.blocks[0].text,'')
        self.assertEqual(document.blocks[0].source_field,'/Facturae/TaxIdentificationNumber[1]')
        result = ResolutionResult('AMBIGUOUS',(),(),'No unique candidate')
        self.assertEqual(ResolutionResult.from_dict(result.to_dict()),result)
        with self.assertRaises(ValueError): ResolutionResult('SELECTED',(1,),(),'wrongID')

    def _pdf(self, pages=1, raster=False, inherited=False):
        try:
            from pypdf import PdfWriter
            from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject, NumberObject
        except ImportError:
            self.skipTest('requires documents extra')
        writer = PdfWriter()
        inherited_xobjects = DictionaryObject()
        for _ in range(pages):
            page = writer.add_blank_page(612, 792)
            if inherited:
                page.pop(NameObject('/Resources'), None)
            if raster:
                # The pixel stream need not be decodable to route the complete
                # page safely: resource inspection must not decode its pixels.
                image = DecodedStreamObject(); image.set_data(b'\xff')
                image.update({NameObject('/Type'): NameObject('/XObject'),
                              NameObject('/Subtype'): NameObject('/Image'),
                              NameObject('/Width'): NumberObject(1), NameObject('/Height'): NumberObject(1)})
                xobject = writer._add_object(image)
                if inherited:
                    inherited_xobjects[NameObject('/Im0')] = xobject
                else:
                    page[NameObject('/Resources')] = DictionaryObject({
                        NameObject('/XObject'): DictionaryObject({NameObject('/Im0'): xobject})})
        if inherited and raster:
            writer._pages.get_object()[NameObject('/Resources')] = DictionaryObject({
                NameObject('/XObject'): inherited_xobjects})
        path = self.folder / 'synthetic.pdf'; writer.write(path)
        return 'inbox/ap/doc/synthetic.pdf'

    def _pdf_with_native_text(self, content):
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
        writer = PdfWriter()
        page = writer.add_blank_page(612, 792)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                                 NameObject('/Subtype'): NameObject('/Type1'),
                                 NameObject('/BaseFont'): NameObject('/Helvetica'),
                                 NameObject('/Encoding'): NameObject('/WinAnsiEncoding')})
        page[NameObject('/Resources')] = DictionaryObject({
            NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject(); stream.set_data(content)
        page[NameObject('/Contents')] = writer._add_object(stream)
        path = self.folder / 'native-text.pdf'; writer.write(path)
        return 'inbox/ap/doc/native-text.pdf'

    def test_textless_vector_page_reaches_full_page_rendering(self):
        relative = self._pdf()
        document = self.router.parse(relative)
        self.assertEqual(document.blocks, (ParsedBlock('page.1', '', 1),))
        self.assertFalse(document.images)
        self.assertIn('page.1:vision_required', document.warnings)

    def test_native_text_is_preserved_even_when_raster_layer_requires_review(self):
        relative = self._pdf(raster=True)
        text = 'Native invoice number I123, amount 123.45, description original.'
        with patch('pypdf._page.PageObject.extract_text', return_value=text):
            document = self.router.parse(relative)
        self.assertEqual(document.blocks[0].text, text)
        self.assertIn('page.1:raster_content', document.warnings)
        self.assertIn('page.1:vision_required', document.warnings)
        self.assertFalse(document.images)

    def test_inherited_page_resources_route_to_full_page_rendering(self):
        relative = self._pdf(raster=True, inherited=True)
        document = self.router.parse(relative)
        self.assertIn('page.1:raster_content', document.warnings)
        self.assertIn('page.1:vision_required', document.warnings)

    def test_native_text_fragments_restore_boundaries_without_changing_layout_block(self):
        # Separate native text objects can be adjacent in the content stream,
        # causing full-page text extraction to join the stamp and amount.
        content = (b'BT /F1 12 Tf 72 700 Td (ADUANA DE VALENCIA) Tj ET '
                   b'BT /F1 12 Tf 193 700 Td (27.910,28 EUR) Tj ET')
        document = self.router.parse(self._pdf_with_native_text(content))
        self.assertEqual(document.parser_version, 'source-router-v3/pypdf-6.19.0')
        self.assertEqual(document.blocks[0].id, 'page.1')
        self.assertEqual(document.blocks[0].text, 'ADUANA DE VALENCIA27.910,28 EUR')
        fragments = document.blocks[1:]
        self.assertEqual([block.id for block in fragments], [
            'page.1.fragment.1', 'page.1.fragment.2'])
        self.assertEqual([block.text for block in fragments], [
            'ADUANA DE VALENCIA', '27.910,28 EUR'])
        self.assertEqual([block.page for block in fragments], [1, 1])
        self.assertEqual([block.source_field for block in fragments], [
            'page.1.fragment.1', 'page.1.fragment.2'])

    def test_partial_fragment_capture_is_bounded_and_routes_for_visual_review(self):
        content = (b'BT /F1 12 Tf 72 700 Td (Native text one) Tj ET '
                   b'BT /F1 12 Tf 193 700 Td (Native text two) Tj ET')
        with patch('kalmora.documents.router.MAX_PDF_FRAGMENTS_PER_PAGE', 1):
            document = self.router.parse(self._pdf_with_native_text(content))
        self.assertEqual([block.id for block in document.blocks], [
            'page.1', 'page.1.fragment.1'])
        self.assertIn('page.1:text_fragment_limit', document.warnings)
        self.assertIn('page.1:vision_required', document.warnings)

    def test_long_corrupted_layer_and_page_extraction_failure_are_recoverable(self):
        relative = self._pdf(pages=2)
        text = 'Invoice with unreadable \ufffd glyph and private \ue001 glyph, total 123.45'
        with patch('pypdf._page.PageObject.extract_text', side_effect=[text, ValueError('bad font')]):
            document = self.router.parse(relative)
        self.assertEqual([block.text for block in document.blocks], [text, ''])
        self.assertIn('page.1:suspect_text_layer', document.warnings)
        self.assertIn('page.2:text_extraction_failed', document.warnings)
        self.assertEqual(sum(w.endswith(':vision_required') for w in document.warnings), 2)

    def test_clean_native_layer_does_not_force_vision_and_page_limit_is_explicit(self):
        relative = self._pdf()
        with patch('pypdf._page.PageObject.extract_text', return_value='Invoice total 123.45, original reference I123'):
            document = self.router.parse(relative)
        self.assertFalse(document.warnings)
        self.assertFalse(document.images)
        with patch('kalmora.documents.router.MAX_PDF_PAGES', 1):
            self._pdf(pages=2)
            with self.assertRaises(ParseError) as error:
                self.router.parse(relative)
        self.assertEqual(error.exception.category, 'page_limit')
