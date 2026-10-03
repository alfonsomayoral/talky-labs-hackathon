from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from kalmora.ap_output import APHeader, build_ap_row, validate_ap_row, write_ap_jsonl


class APOutputTests(unittest.TestCase):
    def setUp(self):
        self.header = APHeader("1100", "V1", "INV1", "2026-07-01", "EUR", 10000, 2100, 12100, 1500, 0, 10600)
        self.lines = [{"amount": 10000, "account": "62300000", "cost_center": "CC1", "wbs": None,
                       "tax_code": "S21", "po": None, "po_item": None}]
        self.entry = {"company": "1100", "currency": "EUR", "document_date": "2026-07-01", "reference": "INV1", "lines": [
            {"account": "62300000", "debit": 10000, "credit": 0, "cost_center": "CC1"},
            {"account": "47200000", "debit": 2100, "credit": 0},
            {"account": "47510000", "debit": 0, "credit": 1500, "partner": "V1"},
            {"account": "41000000", "debit": 0, "credit": 10600, "partner": "V1", "amount_doc": 10600, "assignment": "INV1"}]}
        self.context = {"companies": {"1100"}, "partners": {"V1"}, "accounts": {"62300000", "47200000", "47510000", "41000000"},
                        "cost_centers": {"CC1": {"company": "1100"}}}

    def posted(self, **kw):
        options = dict(doc_id="DOC1", document_type="INVOICE", decision="POST", header=self.header, lines=self.lines,
                       journal_entry=self.entry, context=self.context)
        options.update(kw)
        return build_ap_row(**options)

    def test_post_credit_and_payment_block_are_valid_and_snapshot_inputs(self):
        row = self.posted()
        self.assertEqual(validate_ap_row(row, self.context), ())
        row["journal_entry"]["lines"][0]["debit"] = 1
        self.assertEqual(self.entry["lines"][0]["debit"], 10000)
        credit = deepcopy(self.entry)
        credit["lines"] = [{**line, "debit": line["credit"], "credit": line["debit"]} for line in credit["lines"]]
        self.posted(document_type="CREDIT_NOTE", journal_entry=credit)
        self.posted(decision="POST_PAYMENT_BLOCK", payment_block="CONTRACTOR_CERTIFICATE_EXPIRED", payee={"type": "FACTOR"})
        with self.assertRaises(ValueError):
            self.posted(decision="POST_PAYMENT_BLOCK")

    def test_nonposting_decisions_have_no_journal_and_exact_reason_or_action(self):
        for decision, reasons in (("HOLD", ("PRICE_VARIANCE",)), ("REJECT", ("ARITHMETIC_ERROR",))):
            row = build_ap_row(doc_id="N1", document_type="INVOICE", decision=decision, reasons=reasons)
            self.assertNotIn("journal_entry", row)
            with self.assertRaises(ValueError):
                build_ap_row(doc_id="N1", document_type="INVOICE", decision=decision, reasons=reasons, journal_entry=self.entry)
        duplicate = build_ap_row(doc_id="D2", document_type="INVOICE", decision="DUPLICATE", duplicate_of="D1")
        self.assertEqual(duplicate["duplicate_of"], "D1")
        build_ap_row(doc_id="NOTICE", document_type="FACTORING_NOTICE", decision="NOT_INVOICE", action="REGISTER_ALTERNATIVE_PAYEE")
        for bad in (dict(decision="UNKNOWN"), dict(decision="REJECT", reasons=("PRICE_VARIANCE",)),
                    dict(decision="DUPLICATE", duplicate_of="N1"), dict(decision="NOT_INVOICE", action="NONE")):
            with self.assertRaises(ValueError):
                build_ap_row(doc_id="N1", document_type="INVOICE", **bad)

    def test_balanced_journal_cannot_hide_bad_header_scope_or_supplier(self):
        for field, value in (("net", 10001), ("tax", 2101), ("payable", 10599), ("invoice_number", "OTHER"),
                             ("company", "1910"), ("vendor_id", "V2"), ("invoice_date", "2026-07-02")):
            with self.assertRaises(ValueError, msg=field):
                self.posted(header=replace(self.header, **{field: value}))
        for field, value in (("amount_doc", 10599), ("currency", "USD"), ("assignment", "OTHER")):
            entry = deepcopy(self.entry)
            entry["lines"][-1][field] = value
            with self.assertRaises(ValueError):
                self.posted(journal_entry=entry)

    def test_coded_line_ownership_positions_and_cents(self):
        for fields in (dict(wbs="W1"), dict(cost_center="FOREIGN"), dict(po="PO1", po_item=None),
                       dict(po="PO1", po_item=0), dict(amount=9999), dict(tax_code=""), dict(amount=True)):
            lines = [{**self.lines[0], **fields}]
            with self.assertRaises(ValueError):
                self.posted(lines=lines)
        context = {**self.context, "cost_centers": {"CC1": {"company": "1910"}}}
        with self.assertRaises(ValueError):
            self.posted(context=context)

    def test_foreign_advance_application_conserves_document_payable(self):
        header = APHeader("1100", "V1", "INV1", "2026-07-01", "USD", 10000, 0, 10000, 0, 0, 7000)
        lines = [{**self.lines[0], "tax_code": "SEX"}]
        entry = {"company": "1100", "currency": "USD", "document_date": header.invoice_date, "reference": header.invoice_number, "lines": [
            {"account": "62300000", "debit": 9050, "credit": 0, "cost_center": "CC1"},
            {"account": "40700000", "debit": 0, "credit": 2690, "partner": "V1", "amount_doc": 3000, "currency": "USD"},
            {"account": "41000000", "debit": 0, "credit": 6360, "partner": "V1", "amount_doc": 7000, "currency": "USD"}]}
        self.posted(header=header, lines=lines, journal_entry=entry, context=None)
        entry["lines"][1]["amount_doc"] = 2999
        with self.assertRaises(ValueError):
            self.posted(header=header, lines=lines, journal_entry=entry, context=None)

    def test_writer_exact_inventory_atomic_failure_and_stable_bytes(self):
        a = self.posted()
        b = build_ap_row(doc_id="DOC2", document_type="PROFORMA", decision="NOT_INVOICE", action="NONE")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "ap.jsonl"
            write_ap_jsonl(path, [b, a], expected_doc_ids=["DOC1", "DOC2"])
            original = path.read_bytes()
            self.assertEqual([json.loads(line)["doc_id"] for line in original.splitlines()], ["DOC1", "DOC2"])
            write_ap_jsonl(path, [a, b], expected_doc_ids=["DOC2", "DOC1"], overwrite=True)
            self.assertEqual(path.read_bytes(), original)
            for rows, expected in (([a], ["DOC1", "DOC2"]), ([a, a], ["DOC1"]), ([a, b], ["DOC1"]),
                                   ([{**a, "decision": "HOLD"}, b], ["DOC1", "DOC2"])):
                with self.assertRaises(ValueError):
                    write_ap_jsonl(path, rows, expected_doc_ids=expected, overwrite=True)
                self.assertEqual(path.read_bytes(), original)
            with self.assertRaises(FileExistsError):
                write_ap_jsonl(path, [a, b], expected_doc_ids=["DOC1", "DOC2"])
            self.assertEqual(list(Path(folder).glob(".ap-*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
