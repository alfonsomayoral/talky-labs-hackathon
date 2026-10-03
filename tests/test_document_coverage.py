import unittest

from kalmora.documents.contracts import ParsedBlock, ParsedDocument, digest
from kalmora.documents.coverage import native_row_coverage
from kalmora.facts import Fact, Evidence


def document(pages, *, media_type="application/pdf", images=()):
    blocks = tuple(ParsedBlock(f"page.{number}", text, number)
                   for number, text in pages)
    return ParsedDocument("inbox/ap/test/invoice.pdf", digest(b"source"), media_type,
                          "test-router", blocks, images)


HEADER = "Descripción                         Cant.  Ud.  Precio   Importe"


class NativeRowCoverageTests(unittest.TestCase):
    def test_detects_missing_rows_from_native_26_line_table(self):
        rows = [f"Material {number:02} {number + 1} kg 1,00 2,00" for number in range(26)]
        source = document([(1, HEADER + "\n" + "\n".join(rows))])
        fields = {f"line.{number}.amount": [] for number in range(1, 26)}

        result = native_row_coverage(source, fields)

        self.assertEqual(result.status, "incomplete")
        self.assertEqual(result.expected_count, 26)
        self.assertEqual(result.observed_count, 25)
        self.assertEqual(result.missing_count, 1)
        self.assertEqual(result.reason, "native_table_rows_missing")

    def test_repeated_source_rows_remain_distinct_and_page_continuations_count(self):
        source = document([
            (1, HEADER + "\n" + "Same material 1 kg 1,00 1,00"),
            (2, "Wrapped description continued\nSame material 1 kg 1,00 1,00"),
        ])
        fields = {f'line.{page}.amount': [Fact('1,00', Evidence(source.path, f'page.{page}', page, '1,00'))]
                  for page in (1, 2)}

        result = native_row_coverage(source, fields)

        self.assertEqual(result.status, "complete")
        self.assertEqual(result.expected_count, 2)
        self.assertEqual(result.observed_count, 2)
        self.assertEqual(result.table_pages, (1, 2))
        self.assertEqual(dict(result.source_row_counts), {1: 1, 2: 1})

    def test_headers_totals_and_numeric_prose_are_not_rows(self):
        source = document([(1, "\n".join([
            HEADER,
            "Base imponible 1.234,00",
            "IVA 21% 259,14",
            "TOTAL FACTURA 1.493,14 EUR",
            "Se pagará en 30 días; referencia 12 kg 1,00 2,00",
        ]))])

        result = native_row_coverage(source, {})

        self.assertEqual(result.status, "not_applicable")
        self.assertIsNone(result.expected_count)
        self.assertEqual(result.missing_count, 0)
        self.assertEqual(result.reason, 'no_recognized_priced_rows')

    def test_image_only_page_and_non_pdf_are_not_applicable(self):
        image_only = document([(1, "")])
        non_pdf = document([(1, HEADER)], media_type="application/xml")

        self.assertEqual(native_row_coverage(image_only, {}).reason, "no_native_page_text")
        self.assertEqual(native_row_coverage(non_pdf, {}).reason, "not_pdf")

    def test_unrecognized_header_does_not_claim_a_row_check(self):
        source = document([(1, "Cant. Ud. Precio Importe\n1 kg 1,00 2,00")])

        result = native_row_coverage(source, {})

        self.assertEqual(result.status, "not_applicable")
        self.assertEqual(result.reason, "no_recognized_table_header")

    def test_canonical_page_layout_blocks_are_used_once(self):
        source = ParsedDocument("inbox/ap/test/invoice.pdf", digest(b"source"),
            "application/pdf", "test-router", (
                ParsedBlock("page.1", HEADER + "\nA 1 kg 1,00 2,00", 1),
                ParsedBlock("visitor.1", HEADER + "\nA 1 kg 1,00 2,00", 1),
            ))

        result = native_row_coverage(source, {"line.1.amount": [Fact('1,00',
            Evidence(source.path, 'page.1', 1, '1,00'))]})

        self.assertEqual(result.expected_count, 1)
        self.assertEqual(result.status, "complete")

    def test_duplicate_first_page_ids_cannot_hide_missing_second_page_rows(self):
        source = document([(1, HEADER + '\nA 1 kg 1,00 1,00\nB 1 kg 1,00 1,00'),
                           (2, HEADER + '\nC 1 kg 1,00 1,00\nD 1 kg 1,00 1,00\nE 1 kg 1,00 1,00')])
        fields = {f'line.{index}.amount': [Fact('1,00', Evidence(source.path, 'page.1', 1, '1,00'))]
                  for index in range(1, 6)}
        result = native_row_coverage(source, fields)
        self.assertEqual(result.status, 'incomplete')
        self.assertEqual(result.missing_count, 3)
        self.assertEqual(dict(result.observed_row_counts), {1: 5})


if __name__ == "__main__":
    unittest.main()
