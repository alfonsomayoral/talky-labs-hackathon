import hashlib
import json
from pathlib import Path
import tempfile
import unittest

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
