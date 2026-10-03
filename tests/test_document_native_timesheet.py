import unittest

from kalmora.documents.contracts import PageImage, ParsedBlock, ParsedDocument, digest
from kalmora.documents.native_timesheet import extract_native_timesheet


TITLE = "PARTE DE TRABAJO / HOJA DE HORAS"
HEADER = "Fecha                  Operario / categoría                  Tarea                                      Horas"


def source(text, *, page=1, images=(), warnings=(), media_type="application/pdf"):
    return ParsedDocument(
        "inbox/ap/test/timesheet.pdf", digest(b"native timesheet source"), media_type,
        "synthetic-pypdf-layout", (ParsedBlock(f"page.{page}", text, page),),
        tuple(images), tuple(warnings))


def row(date, operator, task, hours):
    return f"{date:<20}  {operator:<32}  {task:<44}  {hours}"


class NativeTimesheetTests(unittest.TestCase):
    def test_extracts_rows_and_preserves_literal_source_evidence(self):
        header = HEADER
        record = row("01/08/2026", "GRUA-AUTO-50", "Grúa autopropulsada 50 t", "3,0")
        document = source("\n".join([
            TITLE, "", "Obra / centro: Escola básica de Vila Serrana", "",
            "Periodo: 01/08/2026 – 31/08/2026", "", header, "", record, "",
            "Conforme cliente (firma y sello):",
        ]), page=2)

        result = extract_native_timesheet(document)

        self.assertEqual(result.status, "complete")
        self.assertEqual(result.table_pages, (2,))
        self.assertEqual(len(result.rows), 1)
        item = result.rows[0]
        self.assertEqual((item.date, item.operator, item.description, item.quantity),
                         ("01/08/2026", "GRUA-AUTO-50", "Grúa autopropulsada 50 t", "3,0"))
        facts = result.to_facts(document)
        prefix = "detail_lines.1."
        self.assertEqual(facts[prefix + "description"][0].value, "Grúa autopropulsada 50 t")
        self.assertEqual(facts[prefix + "quantity"][0].value, "3,0")
        self.assertEqual(facts[prefix + "uom"][0].value, "Horas")
        self.assertEqual(facts[prefix + "raw.Fecha"][0].value, "01/08/2026")
        self.assertEqual(facts[prefix + "raw.Operario / categoría"][0].value, "GRUA-AUTO-50")
        self.assertEqual(facts[prefix + "description"][0].evidence.quote, record)
        self.assertEqual(facts[prefix + "quantity"][0].evidence.field, "page.2")
        self.assertEqual(facts[prefix + "uom"][0].evidence.quote, header)
        self.assertEqual(facts[prefix + "uom"][0].evidence.page, 2)

    def test_preserves_duplicate_physical_entries_in_source_order(self):
        repeated = row("01/08/2026", "DUMPER-10", "Dúmper articulado 10 t", "8,0")
        document = source("\n".join([TITLE, HEADER, "", repeated, repeated, ""]))

        result = extract_native_timesheet(document)

        self.assertEqual(result.status, "complete")
        self.assertEqual([item.index for item in result.rows], [1, 2])
        self.assertEqual([item.date for item in result.rows], ["01/08/2026", "01/08/2026"])
        self.assertEqual([item.quantity for item in result.rows], ["8,0", "8,0"])
        self.assertEqual(len(result.to_facts(document)["detail_lines.1.quantity"]), 1)
        self.assertEqual(len(result.to_facts(document)["detail_lines.2.quantity"]), 1)

    def test_wrapped_or_malformed_dated_row_abstains_from_entire_table(self):
        document = source("\n".join([
            TITLE, HEADER, "",
            row("01/08/2026", "DUMPER-10", "Dúmper articulado 10 t", "8,0"),
            "04/08/2026  GRUA-AUTO-50  Grúa autopropulsada 50 t", "9,0", "",
        ]))

        result = extract_native_timesheet(document)

        self.assertEqual(result.status, "ambiguous")
        self.assertEqual(result.rows, ())
        self.assertEqual(result.to_facts(document), {})

    def test_invalid_calendar_date_and_hours_shape_abstain(self):
        bad_date = source("\n".join([TITLE, HEADER, "", row(
            "31/02/2026", "DUMPER-10", "Dúmper articulado 10 t", "8,0"), ""]))
        bad_hours = source("\n".join([TITLE, HEADER, "", row(
            "01/08/2026", "DUMPER-10", "Dúmper articulado 10 t", "8 h"), ""]))

        for document in (bad_date, bad_hours):
            with self.subTest(document=document):
                result = extract_native_timesheet(document)
                self.assertEqual(result.status, "ambiguous")
                self.assertEqual(result.to_facts(document), {})

    def test_dateless_first_row_and_continuation_after_blank_cannot_be_lost(self):
        for text in (
            '\n'.join([TITLE, HEADER, row('MISSING', 'DUMPER-10', 'Dúmper articulado 10 t', '8,0'),
                        row('01/08/2026', 'GRUA-50', 'Grúa', '3,0')]),
            '\n'.join([TITLE, HEADER, row('01/08/2026', 'DUMPER-10', 'Dúmper articulado', '8,0'),
                        '', 'description continuation 10 t']),
        ):
            self.assertEqual(extract_native_timesheet(source(text)).status, 'ambiguous')

    def test_requires_exact_title_and_ordered_delimited_header(self):
        untitled = source("\n".join([HEADER, "", row(
            "01/08/2026", "DUMPER-10", "Dúmper articulado 10 t", "8,0"), ""]))
        wrong_order = source("\n".join([
            TITLE,
            "Fecha                  Tarea                  Operario / categoría                  Horas",
            "", row("01/08/2026", "DUMPER-10", "Dúmper articulado 10 t", "8,0"), "",
        ]))

        self.assertEqual(extract_native_timesheet(untitled).status, "not_applicable")
        result = extract_native_timesheet(wrong_order)
        self.assertEqual(result.status, "ambiguous")
        self.assertEqual(result.to_facts(wrong_order), {})

    def test_scanned_or_vision_required_document_is_excluded(self):
        text = "\n".join([TITLE, HEADER, "", row(
            "01/08/2026", "DUMPER-10", "Dúmper articulado 10 t", "8,0"), ""])
        image_document = source(text, images=(PageImage(1, "image/png", b"png"),))
        flagged_document = source(text, warnings=("page.1:vision_required",))
        non_pdf = source(text, media_type="text/plain")

        self.assertEqual(extract_native_timesheet(image_document).reason,
                         "document_requires_vision")
        self.assertEqual(extract_native_timesheet(flagged_document).reason,
                         "document_requires_vision")
        self.assertEqual(extract_native_timesheet(non_pdf).status, "not_applicable")
        self.assertEqual(extract_native_timesheet(image_document).to_facts(image_document), {})

    def test_rows_from_two_titled_pages_keep_physical_page_order(self):
        first = "\n".join([TITLE, HEADER, "", row(
            "01/08/2026", "DUMPER-10", "Dúmper articulado 10 t", "8,0"), ""])
        second = "\n".join([TITLE, HEADER, "", row(
            "04/08/2026", "DUMPER-10", "Dúmper articulado 10 t", "8,0"), ""])
        document = ParsedDocument(
            "inbox/ap/test/timesheet.pdf", digest(b"two page native timesheet"),
            "application/pdf", "synthetic-pypdf-layout",
            (ParsedBlock("page.1", first, 1), ParsedBlock("page.2", second, 2)))

        result = extract_native_timesheet(document)

        self.assertEqual(result.status, "complete")
        self.assertEqual(result.table_pages, (1, 2))
        self.assertEqual([(item.index, item.page) for item in result.rows], [(1, 1), (2, 2)])
        self.assertEqual(result.to_facts(document)["detail_lines.2.quantity"][0].evidence.page, 2)


if __name__ == "__main__":
    unittest.main()
