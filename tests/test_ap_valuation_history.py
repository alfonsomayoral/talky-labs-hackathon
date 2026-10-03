"""Optional source-only reconstruction; fixture IDs never affect solver logic."""
import os
from pathlib import Path
import unittest

from kalmora.ap_allocation import (
    ConsumptionState, InvoiceQuantityLine, OrderLine, OrderPortion, allocate_receipts,
)
from kalmora.ap_coding import CodingCatalog, CodingQuery
from kalmora.ap_journal import build_ap_journal
from kalmora.ap_orders import POCatalog, POQuery
from kalmora.ap_tax import TaxCatalog, TaxLine, calculate_ap_tax
from kalmora.ap_valuation import CostAssignment, OrderPrice, ValuationLine, value_ap_lines
from kalmora.ap_withholding import (
    WithholdingBase, WithholdingCatalog, calculate_ap_withholdings,
)
from kalmora.data import PhaseData
from kalmora.facts import Evidence
from kalmora.validation import validate_entry


@unittest.skipUnless(os.environ.get("KALMORA_PHASE_ERP"), "original ERP not configured")
class APValuationHistoryTests(unittest.TestCase):
    def test_original_price_difference_matches_complete_master_validated_journal(self):
        # The observed AP invoice, PO, SES and posted journal establish this
        # historical example. This is not documentary extraction or a July run.
        erp = Path(os.environ["KALMORA_PHASE_ERP"])
        data = PhaseData(erp.parent)
        invoice = data.get("ap_invoices", "API000186")
        po = data.get("purchase_orders", invoice["po_refs"][0])
        receipt = data.get("goods_receipts", "1000030109")
        original = next(entry for entry in data.iter_journal()
                        if entry["id"] == invoice["journal_entry"])
        self.assertEqual(invoice["decision"], "POST")
        self.assertEqual(invoice["po_refs"], [receipt["po"]])
        self.assertEqual(receipt["vendor"], invoice["vendor"])
        proof = (
            Evidence("erp/ap_invoices.jsonl", f"doc_id={invoice['doc_id']}.po_refs"),
            Evidence("erp/goods_receipts.jsonl", f"id={receipt['id']}"),
        )
        resolved = POCatalog.from_phase(data).resolve(
            POQuery("L", invoice["company"], invoice["vendor"], invoice["currency"],
                    receipt["quantity_milli"], po["items"][0]["uom"], proof,
                    po_reference=po["id"], po_item=receipt["po_item"],
                    receipt_references=(receipt["id"],), project=po["project"]),
            invoice_date=invoice["issue_date"],
        )
        self.assertEqual(resolved.status, "RESOLVED")
        selected = resolved.selected
        self.assertIsNotNone(selected)
        self.assertTrue(selected.evidence)
        before = ConsumptionState()
        allocation = allocate_receipts(
            company=invoice["company"], vendor=invoice["vendor"],
            currency=invoice["currency"], invoice_id=invoice["doc_id"],
            lines=[InvoiceQuantityLine("L", receipt["quantity_milli"], selected.uom,
                   (OrderPortion(selected.order, receipt["quantity_milli"], (receipt["id"],)),))],
            orders=[OrderLine(selected.order, selected.uom)], receipts=selected.receipts,
            state=before,
        )
        self.assertEqual(allocation.status, "ALLOCATED")
        self.assertEqual(sum(part.quantity_milli for part in allocation.allocations),
                         receipt["quantity_milli"])
        catalog = CodingCatalog.from_phase(data)
        coding = catalog.resolve(
            CodingQuery(invoice["company"], invoice["vendor"], invoice["currency"],
                        invoice["issue_date"], project=po["project"]),
            order=(catalog.order_record(selected.order, evidence=selected.evidence),),
        )
        self.assertEqual(coding.status, "RESOLVED")
        self.assertTrue(all(field.evidence for field in coding.fields))
        record = coding.record
        cost = CostAssignment(record.company, record.account, record.cost_center, record.wbs)
        scope = dict(company=invoice["company"], vendor=invoice["vendor"],
                     currency=invoice["currency"], invoice_date=invoice["issue_date"],
                     decision=invoice["decision"])
        valuation = value_ap_lines(
            **scope, invoice_id=invoice["doc_id"], gr_ir_account="40090000",
            lines=[ValuationLine("L", invoice["net"], cost, receipt["quantity_milli"])],
            allocation=allocation, prices=[OrderPrice(selected.order, selected.unit_price_cents)],
        )
        self.assertEqual([component.kind for component in valuation.components],
                         ["GR_IR", "PRICE_DIFFERENCE"])
        self.assertEqual(sum(component.amount_doc for component in valuation.components),
                         invoice["net"])
        company = next(row for row in data.companies if row["code"] == invoice["company"])
        tax = calculate_ap_tax(
            **scope, invoice_id=invoice["doc_id"], country=company["country"],
            lines=[TaxLine("L", invoice["net"], record.tax_code, account=record.account,
                           cost_center=record.cost_center, wbs=record.wbs)],
            catalog=TaxCatalog(data.table("tax_codes")),
        )
        withholding = calculate_ap_withholdings(
            **scope, invoice_id=invoice["doc_id"], country=company["country"],
            invoice_number=invoice["number"],
            bases=[WithholdingBase("L", invoice["net"], record.withholding_codes)],
            catalog=WithholdingCatalog(data.table("tax_codes")),
        )
        context = dict(
            companies={row["code"] for row in data.companies},
            accounts={row["account"] for row in data.table("chart_of_accounts")},
            partners={row["id"] for row in data.table("vendors")},
            cost_centers={row["id"]: row for row in data.table("cost_centers")},
            wbs={item["id"]: {"company": project["company"]}
                 for project in data.table("projects") for item in project["wbs"]},
        )
        result = build_ap_journal(
            **scope, doc_id=invoice["doc_id"], invoice_number=invoice["number"],
            posting_date=invoice["posted_on"], reconciliation_account=record.reconciliation_account,
            valuation=valuation, tax=tax, withholding=withholding, context=context,
        )
        # Source line numbers/text are descriptive metadata. Compare every
        # monetary/fiscal dimension, side, currency and assignment on every line.
        fields = ("account", "partner", "cost_center", "wbs", "currency", "amount_doc",
                  "debit", "credit", "assignment", "tax_code")
        def signature(lines):
            return [tuple(line.get(field) for field in fields) for line in lines]
        self.assertEqual(signature(result.journal_entry["lines"]), signature(original["lines"]))
        for field in ("company", "currency", "reference", "document_date", "posting_date",
                      "doc_type", "source"):
            self.assertEqual(result.journal_entry[field], original[field])
        self.assertEqual(result.payable_doc, invoice["payable"])
        self.assertEqual(validate_entry(result.journal_entry, context), [])
        self.assertEqual(before, ConsumptionState())  # Receipt state is still tentative.


if __name__ == "__main__":
    unittest.main()
