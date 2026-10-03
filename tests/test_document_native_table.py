import unittest

from kalmora.documents.contracts import PageImage, ParsedBlock, ParsedDocument, digest
from kalmora.documents.native_table import extract_native_table


HEADER = "Descripción                         Cant.  Ud.  Precio   Importe"
PT_HEADER = "Descrição                                      Qtd.   Un.    Preço    Valor"


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
    def test_extracts_portuguese_header_rows_units_and_gr_references_literally(self):
        source_rows = [
            row("Hormigón HA-25/B/20/IIa – GR-053273 (04/08)", "16", "m3",
                "82,83", "1.325,28 EUR"),
            row("Material acondicionado", "2", "un", "10,00", "20,00"),
            row("Material em caixas", "1,5", "caixa", "4,00", "6,00"),
            row("Instalação de climatização", "0,3", "PA", "76.500,00", "22.950,00"),
        ]
        document = source([(1, "\n".join([
            PT_HEADER, *source_rows,
            "Incidência 1.351,28", "IVA 23% 310,79", "TOTAL 1.662,07 EUR",
        ]))])

        result = extract_native_table(document)

        self.assertEqual(result.status, "complete")
        self.assertEqual(result.expected_count, 4)
        self.assertEqual([item.description for item in result.rows], [
            "Hormigón HA-25/B/20/IIa – GR-053273 (04/08)",
            "Material acondicionado", "Material em caixas", "Instalação de climatização",
        ])
        self.assertEqual(result.rows[0].delivery_reference, "GR-053273")
        facts = result.to_facts(document)
        self.assertEqual(facts["line.1.delivery_reference"][0].value, "GR-053273")
        self.assertEqual(facts["line.1.unit_price"][0].value, "82,83")
        self.assertEqual(facts["line.1.amount"][0].value, "1.325,28")
        self.assertEqual(facts["line.1.amount"][0].evidence.quote, source_rows[0])

    def test_accepts_saco_unit_only_as_a_printed_literal(self):
        printed = row("Cemento CEM II 25 kg – AL-006347 (18/08)", "19", "saco",
                      "5,62", "106,78")
        document = source([(1, "\n".join([HEADER, printed, "Base imponible 106,78"]))])

        result = extract_native_table(document)

        self.assertEqual(result.status, "complete")
        self.assertEqual(result.expected_count, 1)
        self.assertEqual(result.rows[0].unit, "saco")
        self.assertEqual(result.to_facts(document)["line.1.uom"][0].value, "saco")

    def test_certification_totals_and_invoice_header_fields_are_not_detail_rows(self):
        document = source([(1, "\n".join([
            "Certificación nº: 05",
            "Periodo: 01/07/2026 – 31/07/2026",
            HEADER,
            row("Encofrado y desencofrado de muros", "288", "m2", "24,37", "7.018,56"),
            row("Colocación de ferralla", "14.210", "kg", "0,35", "4.973,50"),
            row("Vertido y vibrado de hormigón", "487,5", "m3", "15,04", "7.332,00"),
            row("Forjado reticular ejecutado", "150", "m2", "42,74", "6.411,00"),
            "Certificado a origen 70.739,93 EUR Base imponible 25.735,06",
            "Certificado anterior -45.004,87 EUR IVA ISP (0%) 0,00",
            "Importe de esta certificación 25.735,06 EUR TOTAL FACTURA 25.735,06 EUR",
            "Retención garantía 5 % -1.286,75",
            "Total a pagar 24.448,31 EUR",
        ]))])

        result = extract_native_table(document)

        self.assertEqual(result.status, "complete")
        self.assertEqual(result.expected_count, 4)
        self.assertEqual([item.description for item in result.rows], [
            "Encofrado y desencofrado de muros", "Colocación de ferralla",
            "Vertido y vibrado de hormigón", "Forjado reticular ejecutado",
        ])
        self.assertEqual(len(result.to_facts(document)), 20)
        self.assertNotIn("Certificado a origen", [row.description for row in result.rows])

    def test_explicit_code_column_splits_only_unambiguous_uppercase_code_prefixes(self):
        header = "Código                 Descripción                  Cant.  Ud.  Precio  Importe"
        separated = [
            "ESCOBA-VIA             Cepillo de barrido viario – AL-035831 (11/08)  51 ud 18,24 930,24",
            "BOLSA-RES              Bolsas de basura industriales 120 l (caja) – AL-035838 (11/08)  42 caja 23,64 992,88",
        ]
        joined = (
            "CONTENEDOR-1100Contenedor carga trasera 1.100 l – AL-035832 (20/08)  "
            "3 ud 207,44 622,32"
        )
        document = source([(1, "\n".join([header, *separated, joined, "Base imponible 2.545,44"]))])

        result = extract_native_table(document)

        self.assertEqual(result.status, "complete")
        self.assertEqual(result.expected_count, 3)
        self.assertEqual([row.material for row in result.rows], ["ESCOBA-VIA", "BOLSA-RES", None])
        self.assertEqual(result.rows[0].description, "Cepillo de barrido viario – AL-035831 (11/08)")
        self.assertEqual(result.rows[2].description,
                         "CONTENEDOR-1100Contenedor carga trasera 1.100 l – AL-035832 (20/08)")
        facts = result.to_facts(document)
        self.assertEqual(facts["line.1.material"][0].value, "ESCOBA-VIA")
        self.assertEqual(facts["line.1.material"][0].evidence.quote, separated[0])
        self.assertNotIn("line.3.material", facts)

    def test_without_explicit_code_header_keeps_code_like_description_prefix(self):
        printed = row("ESCOBA-VIA Cepillo de barrido viario – AL-035831", "51", "ud",
                      "18,24", "930,24")
        document = source([(1, "\n".join([HEADER, printed, "Base imponible 930,24"]))])

        result = extract_native_table(document)

        self.assertEqual(result.status, "complete")
        self.assertEqual(result.rows[0].description, "ESCOBA-VIA Cepillo de barrido viario – AL-035831")
        self.assertIsNone(result.rows[0].material)
        self.assertNotIn("line.1.material", result.to_facts(document))

    def test_portuguese_wrapped_description_and_malformed_currency_abstain(self):
        wrapped = source([(1, "\n".join([
            PT_HEADER,
            "Hormigón HA-25/B/20/IIa – descripción con continuación",
            row("GR-053273 (04/08)", "16", "m3", "82,83", "1.325,28"),
        ]))])
        malformed = source([(1, "\n".join([
            PT_HEADER,
            row("Hormigón HA-25/B/20/IIa – GR-053273", "16", "m3",
                "EUR 82,83", "1.325,28"),
        ]))])

        wrapped_result = extract_native_table(wrapped)
        malformed_result = extract_native_table(malformed)

        self.assertEqual(wrapped_result.status, "ambiguous")
        self.assertEqual(wrapped_result.to_facts(wrapped), {})
        self.assertEqual(malformed_result.status, "ambiguous")
        self.assertEqual(malformed_result.to_facts(malformed), {})

    def test_explicit_timesheet_supplement_does_not_change_invoice_table_status(self):
        invoice = source([
            (1, "\n".join([
                PT_HEADER,
                row("Dúmper articulado", "2", "día", "347,76", "695,52"),
                "Incidência 695,52", "IVA 23% 159,97", "TOTAL 855,49 EUR",
            ])),
            (2, "\n".join([
                "PARTE DE TRABAJO / HOJA DE HORAS",
                "Fecha                          Operario / categoría                          Tarea                               Horas",
                "01/08/2026                    DUMPER-10                                 Dúmper articulado 10 t              8,0",
            ])),
        ])

        result = extract_native_table(invoice)

        self.assertEqual(result.status, "complete")
        self.assertEqual(result.expected_count, 1)

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

    def test_explicit_company_page_and_test_disclaimer_footers_are_ignored(self):
        document = source([(1, "\n".join([
            HEADER,
            row("Acero corrugado – AL-063373", "1.380", "kg", "1,30", "1.794,00"),
            "Moreno y Mora Ferralla Industrial, S.L.U. · Avenida de la Industria 51 · "
            "37782 Villafranca de Orbe · B23231205",
            "Página 1",
            "Synthetic test document – no fiscal validity",
        ]))])

        result = extract_native_table(document)

        self.assertEqual(result.status, "complete")
        self.assertEqual(result.expected_count, 1)
        self.assertEqual(result.rows[0].description, "Acero corrugado – AL-063373")
        self.assertEqual(result.rows[0].delivery_reference, "AL-063373")

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
        reversed_header = source([(1, "\n".join([
            "Descripción  Precio  Importe  Cant.  Ud.",
            row("Arena lavada", "1", "t", "10,00", "10,00"),
        ]))])
        unsupported_unit = source([(1, "\n".join([
            HEADER,
            row("Servicio especial", "1", "container", "20,00", "20,00"),
        ]))])

        self.assertEqual(extract_native_table(no_header).status, "not_applicable")
        self.assertEqual(extract_native_table(reversed_header).status, "not_applicable")
        self.assertEqual(extract_native_table(reversed_header).to_facts(reversed_header), {})
        result = extract_native_table(unsupported_unit)
        self.assertEqual(result.status, "ambiguous")
        self.assertEqual(result.to_facts(unsupported_unit), {})


if __name__ == "__main__":
    unittest.main()
