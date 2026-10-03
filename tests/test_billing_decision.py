from dataclasses import replace
import unittest
from kalmora.billing import BillingType, Decision, build_ar_billing
from kalmora.billing.inputs import ExtraService, ServiceFacts
from kalmora.facts import Evidence
from billing_support import BillingCase


class DecisionTests(BillingCase):
    def test_pending_work_preserves_amount_wbs_evidence_without_invoice(self):
        evidence = (Evidence("cert.pdf", "approval", 1, "PENDIENTE"),)
        run = self.run_item(self.cert(approved=False, evidence=evidence))
        self.assertEqual(run.results[0].decision, Decision.SKIP_PENDING_APPROVAL)
        self.assertIsNone(run.results[0].journal_entry)
        self.assertIsNone(run.results[0].invoice)
        self.assertEqual((run.pending_wip[0].amount, run.pending_wip[0].evidence), (30000, evidence))
        self.assertEqual([x.wbs for x in run.pending_wip[0].lines], ["P1.01", "P1.02"])

    def test_pending_bad_amounts_or_unobserved_approval_are_unresolved(self):
        for facts in (self.cert(approved=False, current=30001), self.cert(approved="false")):
            self.assertEqual(len(self.run_item(facts).unresolved), 1)

    def test_extras_require_explicit_conformity(self):
        facts = ServiceFacts("2026-07", 10000, (ExtraService("O1", "Extra", 2000, True),
                                                ExtraService("O2", "Pendiente", 3000, False)))
        run = self.run_item(facts, self.item(BillingType.SERVICE_MONTHLY))
        self.assertEqual(run.results[0].invoice.net, 12000)
        self.assertIn("O2", run.results[0].diagnostics[0])
        bad = replace(facts, extras=(ExtraService("O3", "Sin aprobación", 2000, "true"),))
        self.assertEqual(len(self.run_item(bad, self.item(BillingType.SERVICE_MONTHLY)).unresolved), 1)

    def test_existing_service_invoice_blocks_rebilling(self):
        self.tables["ar_invoices"] = [dict(id="INV1", contract="CV1", company="1100", kind="invoice", date="2026-07-31")]
        self.assertEqual(len(self.run_item(ServiceFacts("2026-07", 10000), self.item(BillingType.SERVICE_MONTHLY)).unresolved), 1)

    def test_duplicate_ids_and_duplicate_period_coverage(self):
        item = self.item()
        with self.assertRaises(ValueError):
            build_ar_billing(self.data(), [item, item], {item.id: self.cert()})
        other = replace(item, id="B2")
        run = build_ar_billing(self.data(), [item, other], {i.id: self.cert() for i in (item, other)})
        self.assertEqual(([r.item.id for r in run.results], [r.item.id for r in run.unresolved]), (["B1"], ["B2"]))
