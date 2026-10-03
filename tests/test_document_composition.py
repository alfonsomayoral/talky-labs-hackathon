from dataclasses import replace
import unittest

from kalmora.documents.composition import compose_native_invoice
from kalmora.documents.contracts import ParsedBlock, ParsedDocument, digest
from kalmora.facts import DocumentFacts, Evidence, Fact


class NativeCompositionTests(unittest.TestCase):
    def setUp(self):
        text = 'FACTURA F-1 / F-2\nDescripción Cantidad Unidad Precio Importe\nBolt 2 ud 1,00 2,00\nBolt 2 ud 1,00 2,00\nBase imponible 4,00\nSupplemental source detail'
        self.source = ParsedDocument('inbox/ap/a/invoice.pdf', digest(text.encode()),
            'application/pdf', 'test', (ParsedBlock('page.1', text, 1),))
        proof = Evidence(self.source.path, 'page.1', 1, 'FACTURA F-1 / F-2')
        self.headers = DocumentFacts(self.source.source_sha256, 'recorded-model-v1',
            {'invoice_number': [Fact('F-1', proof), Fact('F-2', proof)],
             'detail_lines.1.description': [Fact('Supplemental source detail', Evidence(self.source.path,
                 'page.1', 1, 'Supplemental source detail'))]})

    def test_physical_duplicates_preserve_headers_conflicts_and_supplemental_facts(self):
        combined = compose_native_invoice(self.source, self.headers)
        self.assertEqual(combined.facts.fields['line_count'][0].value, 2)
        self.assertEqual(combined.facts.fields['line.2.amount'][0].value, '2,00')
        self.assertEqual(combined.facts.fields['invoice_number'], self.headers.fields['invoice_number'])
        self.assertEqual(combined.facts.fields['detail_lines.1.description'], self.headers.fields['detail_lines.1.description'])
        self.assertNotEqual(combined.facts.extractor_version, self.headers.extractor_version)
        self.assertEqual(combined.provenance['superseded_model_fields'], [])
        self.assertNotIn('line_count', combined.provenance['native_fields'])

    def test_projection_is_explicit_and_keeps_original_capture_identity(self):
        old = replace(self.headers, fields={**self.headers.fields,
            'line.1.quantity': [Fact('1,00', Evidence(self.source.path, 'page.1', 1, 'Bolt 2 ud 1,00 2,00'))]})
        with self.assertRaisesRegex(ValueError, 'explicit archived'):
            compose_native_invoice(self.source, old)
        projected = compose_native_invoice(self.source, old, project_recorded_rows=True)
        self.assertEqual(projected.facts.fields['line.1.quantity'][0].value, '2')
        self.assertEqual(projected.provenance['recorded_model_extractor_version'], old.extractor_version)
        self.assertEqual(projected.provenance['superseded_model_fields'], ['line.1.quantity'])
        self.assertEqual(old.fields['line.1.quantity'][0].value, '1,00')

    def test_changed_source_and_partial_native_table_fail_closed(self):
        with self.assertRaisesRegex(ValueError, 'different original'):
            compose_native_invoice(self.source, replace(self.headers, source_sha256='0' * 64))
        wrapped = replace(self.source, blocks=(ParsedBlock('page.1',
            'Descripción Cantidad Unidad Precio Importe\nLong wrapped\nBolt 2 ud 1,00 2,00', 1),))
        with self.assertRaisesRegex(ValueError, 'not safely complete'):
            compose_native_invoice(wrapped, self.headers)

    def test_native_timesheet_survives_projection_of_misclassified_model_invoice_rows(self):
        page_two = ('PARTE DE TRABAJO / HOJA DE HORAS\n'
                    'Fecha    Operario / categoría    Tarea    Horas\n'
                    '01/08/2026    DUMPER-10    Dúmper articulado 10 t    8,0\n')
        source = replace(self.source, blocks=(*self.source.blocks, ParsedBlock('page.2', page_two, 2)))
        headers = replace(self.headers, fields={'invoice_number': self.headers.fields['invoice_number']})
        combined = compose_native_invoice(source, headers)
        self.assertEqual(combined.facts.fields['detail_lines.1.quantity'][0].value, '8,0')
        self.assertEqual(combined.facts.fields['detail_lines.1.uom'][0].value, 'Horas')
        self.assertEqual(combined.facts.fields['detail_line_count'][0].value, 1)
        self.assertEqual(combined.facts.fields['detail_lines.1.quantity'][0].evidence.page, 2)
        self.assertIn('detail_line_count', combined.provenance['derived_fields'])


if __name__ == '__main__':
    unittest.main()
