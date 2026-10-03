import unittest

from kalmora.documents.contracts import PageImage, ParsedBlock, ParsedDocument, digest
from kalmora.documents.native_table import extract_native_table


HEADER = "Descripción                         Cant.  Ud.  Precio   Importe"


def source(pages):
    return ParsedDocument(
        "inbox/ap/test/invoice.pdf",
        digest(b"native table source"),
        "application/pdf",
        "synthetic-pypdf-layout",
        tuple(ParsedBlock(f"page.{page}", text, page) for page, text in pages),
    )


def row(description, quantity, unit, price, amount):
    return f"{description:<45}{quantity:>10} {unit:<4}{price:>12} {amount:>12}"


class NativeTableTests(unittest.TestCase):
    def test_extracts_26_explicit_rows_and_keeps_literal_source_evidence(self):
        source_rows = [row(f"Material {index:02}", f"{index},25", "t", "19,53", "455,24")
                       for index in range(1, 27)]
        document = source([(1, "\n".join([HEADER, *source_rows, "Base imponible 11.836,24"]))])

        result = extract_native_table(document)

        self.assertEqual(result.status, "complete")
        self.assertEqual(result.expected_count, 26)
        self.assertEqual([item.index for item in result.rows], list(range(1, 27)))
        self.assertEqual(result.rows[-1].description, "Material 26")
        self.assertEqual(result.rows[-1].quantity, "26,25")
        self.assertEqual(result.rows[-1].amount, "455,24")

        facts = result.to_facts(document)
        self.assertEqual(len(facts), 130)
        fact = facts["line.26.amount"][0]
        self.assertEqual(fact.value, "455,24")
        self.assertEqual(fact.evidence.document, document.path)
        self.assertEqual(fact.evidence.field, "page.1")
        self.assertEqual(fact.evidence.page, 1)
        self.assertEqual(fact.evidence.quote, source_rows[-1])
        self.assertIn(fact.value, fact.evidence.quote)

    def test_extracts_96_rows_in_physical_page_order(self):
        page_one = [row(f"Acero corrugado – AL-063{index:03} (04/08)", "1.670", "kg",
                        "1,30", "2.171,00") for index in range(41)]
        page_two = [row(f"Malla electrosoldada – AL-064{index:03} (05/08)", "854", "m2",
                        "4,30", "3.672,20") for index in range(55)]
        document = source([
            (1, "\n".join([HEADER, *page_one])),
            (2, "\n".join([HEADER, *page_two])),
            (3, "Base imponible 233.326,97\nIVA 21% 48.998,66\nTOTAL FACTURA 282.325,63 EUR"),
        ])

        result = extract_native_table(document)

        self.assertEqual(result.status, "complete")
        self.assertEqual(result.expected_count, 96)
        self.assertEqual(result.table_pages, (1, 2))
        self.assertEqual(result.rows[40].page, 1)
        self.assertEqual(result.rows[41].page, 2)
        self.assertEqual(result.rows[-1].index, 96)
        self.assertEqual(result.to_facts(document)["line.96.amount"][0].evidence.page, 2)
        self.assertEqual(result.rows[0].delivery_reference, "AL-063000")
        self.assertEqual(result.to_facts(document)["line.1.delivery_reference"][0].value,
                         "AL-063000")

    def test_identical_rows_on_separate_physical_lines_are_not_deduplicated(self):
        repeated = row("Servicio de transporte", "1", "ud", "20,00", "20,00")
        document = source([(1, "\n".join([HEADER, repeated, repeated]))])

        result = extract_native_table(document)

        self.assertEqual(result.status, "complete")
        self.assertEqual(result.expected_count, 2)
        self.assertEqual([item.index for item in result.rows], [1, 2])
        self.assertEqual(result.rows[0].quote, result.rows[1].quote)

    def test_multiline_description_abstains_instead_of_joining_rows(self):
        document = source([(1, "\n".join([
            HEADER,
            row("Servicio de bombeo", "1", "h", "50,00", "50,00"),
            "de hormigón con operador",
            row("Alquiler de equipo", "2", "día", "80,00", "160,00"),
        ]))])

        result = extract_native_table(document)

        self.assertEqual(result.status, "ambiguous")
        self.assertEqual(len(result.rows), 2)
        self.assertEqual(result.reason, "unsupported_or_wrapped_table_text_on_pages:1")
        self.assertEqual(result.to_facts(document), {})

    def test_numeric_description_continuation_after_final_row_abstains(self):
        document = source([(1, "\n".join([
            HEADER,
            row("Certificación de trabajos realizados durante el ejercicio", "1", "ud",
                "1.200,00", "1.200,00"),
            "2026",
        ]))])

        result = extract_native_table(document)

        self.assertEqual(result.status, "ambiguous")
        self.assertEqual(result.reason, "unsupported_or_wrapped_table_text_on_pages:1")
        self.assertEqual(result.to_facts(document), {})

    def test_total_lines_do_not_become_rows_and_image_only_page_is_not_applicable(self):
        document = source([(1, "\n".join([
            HEADER,
            row("Arena 0/4 lavada", "2,50", "t", "19,53", "48,83"),
            "Base imponible 48,83",
            "IVA 21% 10,25",
            "TOTAL FACTURA 59,08 EUR",
            "Synthetic test document – no fiscal validity",
        ]))])

        result = extract_native_table(document)
        image_only = source([(1, "")])

        self.assertEqual(result.status, "complete")
        self.assertEqual(result.expected_count, 1)
        self.assertEqual(extract_native_table(image_only).status, "not_applicable")

    def test_native_table_with_any_image_or_vision_required_page_abstains(self):
        native = source([(1, "\n".join([HEADER, row("Arena lavada", "1", "t", "10,00", "10,00")]))])
        image = PageImage(2, "image/png", b"image bytes")
        with_image = ParsedDocument(
            native.path, native.source_sha256, native.media_type, native.parser_version,
            native.blocks, (image,), native.warnings)
        with_warning = ParsedDocument(
            native.path, native.source_sha256, native.media_type, native.parser_version,
            native.blocks, (), ("page.2:vision_required",))

        self.assertEqual(extract_native_table(with_image).status, "ambiguous")
        self.assertEqual(extract_native_table(with_image).reason, "document_requires_vision")
        self.assertEqual(extract_native_table(with_warning).status, "ambiguous")

    def test_unrecognized_header_and_unsupported_unit_abstain(self):
        no_header = source([(1, "Cant. Ud. Precio Importe\n1 kg 1,00 2,00")])
        unsupported_unit = source([(1, "\n".join([
            HEADER,
            row("Servicio especial", "1", "container", "20,00", "20,00"),
        ]))])

        self.assertEqual(extract_native_table(no_header).status, "not_applicable")
        result = extract_native_table(unsupported_unit)
        self.assertEqual(result.status, "ambiguous")
        self.assertEqual(result.to_facts(unsupported_unit), {})


if __name__ == "__main__":
    unittest.main()
