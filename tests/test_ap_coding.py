from dataclasses import replace
import unittest

from kalmora.ap_coding import CodingCatalog, CodingQuery, CodingRecord, CostObject
from kalmora.ap_allocation import OrderKey
from kalmora.facts import Evidence


class CodingTests(unittest.TestCase):
    def setUp(self):
        self.companies = [{"code": "1100", "country": "ES"}, {"code": "1910", "country": "ES"},
                          {"code": "3100", "country": "MX"}]
        self.vendors = [{"id": "V1", "default_gl_account": "62900000", "default_tax_code": "S21",
                         "reconciliation_account": "41000000", "withholding": None}]
        self.accounts = [{"account": value} for value in
                         ("62900000", "62300000", "60000000", "21300000", "40000000", "41000000", "40300000", "47200000")]
        self.centers = [{"id": "CC1", "company": "1100"}, {"id": "CC2", "company": "1100"},
                        {"id": "CC-UTE", "company": "1910"}]
        self.projects = [{"id": "P1", "company": "1100", "wbs": [{"id": "W1"}, {"id": "W2"}]},
                         {"id": "P2", "company": "1100", "wbs": [{"id": "W3"}]},
                         {"id": "P-UTE", "company": "1910", "wbs": [{"id": "W-UTE"}]}]
        self.tax = {"tax_codes": {"S21": {"country": "ES", "kind": "input"},
                                  "SEX": {"country": "ES", "kind": "exempt"},
                                  "SISP": {"country": "ES", "kind": "reverse"},
                                  "M16": {"country": "MX", "kind": "input"},
                                  "R21": {"country": "ES", "kind": "output"}},
                    "withholdings": {"IRPF15": {}, "IRPF7": {}, "MXISR10": {}, "MXIVAR": {}}}
        self.query = CodingQuery("1100", "V1", "EUR", "2026-07-31", context="Professional fee")
        self.evidence = (Evidence("synthetic", "coding"),)

    def catalog(self, history=()):
        return CodingCatalog(companies=self.companies, vendors=self.vendors, accounts=self.accounts,
            cost_centers=self.centers, projects=self.projects, tax_codes=self.tax, history=history)

    def record(self, **kwargs):
        return CodingRecord("1100", "V1", "EUR", evidence=self.evidence, **kwargs)

    def history(self, **kwargs):
        fields = dict(account="62300000", tax_code="S21", reconciliation_account="41000000",
                      cost_center="CC1", recorded_on="2026-06-30", context="Professional fee")
        fields.update(kwargs)
        return self.record(**fields)

    def field(self, result, name):
        return next(field for field in result.fields if field.field == name)

    def test_per_field_precedence_and_supplier_defaults(self):
        history = self.history(account="60000000", tax_code="SEX")
        doc = self.record(account="21300000")
        po = self.record(account="62900000", tax_code="SISP", wbs="W1")
        result = self.catalog((history,)).resolve(replace(self.query, project="P1"), document=(doc,), order=(po,))
        self.assertEqual(result.status, "RESOLVED")
        self.assertEqual((result.record.account, result.record.tax_code, result.record.wbs,
                          result.record.reconciliation_account, result.record.withholding_codes),
                         ("21300000", "SISP", "W1", "41000000", ()))
        self.assertEqual([f.source for f in result.fields], ["document", "order", "vendor", "order", "vendor"])
        self.assertTrue(all(f.evidence for f in result.fields))

    def test_missing_object_stays_incomplete_and_no_context_does_not_borrow_history(self):
        catalog = self.catalog((self.history(),))
        missing = catalog.resolve(replace(self.query, context=None))
        self.assertEqual(missing.status, "INCOMPLETE")
        self.assertEqual(self.field(missing, "cost_object").status, "MISSING")
        self.assertIsNone(missing.record)
        contextual = catalog.resolve(self.query)
        self.assertEqual(contextual.status, "RESOLVED")
        self.assertEqual(contextual.record.cost_center, "CC1")

    def test_known_vendor_company_restriction_cannot_be_relabelled(self):
        self.vendors[0]["companies"] = ["1100"]
        catalog = self.catalog((self.history(),))
        self.assertEqual(catalog.resolve(self.query).status, "RESOLVED")
        foreign = replace(self.query, company="1910")
        source = replace(self.record(account="62300000", tax_code="S21", reconciliation_account="41000000",
                                     cost_center="CC-UTE", withholding_codes=()), company="1910")
        with self.assertRaises(ValueError):
            catalog.resolve(foreign, document=(source,))

    def test_history_ambiguity_never_uses_latest_or_mode_and_equal_records_preserve_evidence(self):
        history = (self.history(), self.history(cost_center="CC2", recorded_on="2026-07-01"),
                   self.history(recorded_on="2026-07-02"))
        catalog = self.catalog(history)
        result = catalog.resolve(self.query)
        self.assertEqual(result.status, "AMBIGUOUS")
        field = self.field(result, "cost_object")
        self.assertEqual(field.candidates, (CostObject("CC1"), CostObject("CC2")))
        self.assertEqual(len(field.evidence), 3)
        doc = self.record(cost_center="CC1")
        self.assertEqual(catalog.resolve(self.query, document=(doc,)).status, "RESOLVED")
        same = self.catalog((self.history(), self.history())).resolve(self.query)
        self.assertEqual(same.status, "RESOLVED")

    def test_conflicting_document_or_order_blocks_lower_tiers(self):
        catalog = self.catalog((self.history(),))
        first, second = self.record(account="62900000"), self.record(account="62300000")
        for source in ("document", "order"):
            result = catalog.resolve(self.query, **{source: (first, second)})
            self.assertEqual(result.status, "AMBIGUOUS")
            self.assertEqual(self.field(result, "account").source, source)

    def test_cc_and_wbs_are_one_unit_and_validate_company_project(self):
        catalog = self.catalog((self.history(),))
        doc, po = self.record(cost_center="CC1"), self.record(wbs="W1")
        result = catalog.resolve(self.query, document=(doc,), order=(po,))
        self.assertEqual((result.record.cost_center, result.record.wbs), ("CC1", None))
        invalid = (self.record(cost_center="CC1", wbs="W1"), self.record(cost_center="CC-UTE"),
                   self.record(wbs="W-UTE"), self.record(cost_center="unknown"))
        for record in invalid:
            self.assertEqual(catalog.resolve(self.query, document=(record,)).status, "INVALID")
        query = replace(self.query, project="P1")
        self.assertEqual(catalog.resolve(query, document=(self.record(wbs="W3"),)).status, "INVALID")
        self.assertEqual(catalog.resolve(query, document=(self.record(cost_center="CC1"),)).status, "INVALID")
        with self.assertRaises(ValueError):
            catalog.resolve(replace(self.query, project="P-UTE"))

    def test_strict_history_date_scope_context_and_foreign_sources(self):
        for changed in (dict(recorded_on="2026-07-31"), dict(recorded_on="2026-08-01"),
                        dict(context="Different service"), dict(company="1910"), dict(vendor="V2"), dict(currency="USD")):
            historic = replace(self.history(), **changed)
            self.assertEqual(self.catalog((historic,)).resolve(self.query).status, "INCOMPLETE")
        equal_context = self.history(context="  PROFESSIONAL   FEE ")
        self.assertEqual(self.catalog((equal_context,)).resolve(self.query).status, "RESOLVED")
        for field, value in (("company", "1910"), ("vendor", "V2"), ("currency", "USD")):
            with self.assertRaises(ValueError):
                self.catalog().resolve(self.query, document=(replace(self.record(account="62900000"), **{field: value}),))

    def test_accounts_tax_and_withholding_are_validated_without_fallback(self):
        catalog = self.catalog((self.history(),))
        for record in (self.record(account="47200000"), self.record(account="99999999"),
                       self.record(tax_code="R21"), self.record(tax_code="M16"),
                       self.record(reconciliation_account="47200000"),
                       self.record(withholding_codes=("MXISR10",)),
                       self.record(withholding_codes=("IRPF15", "IRPF7"))):
            self.assertEqual(catalog.resolve(self.query, document=(record,)).status, "INVALID")
        self.vendors[0]["withholding"] = "IRPF15"
        result = self.catalog((self.history(),)).resolve(self.query)
        self.assertEqual(result.record.withholding_codes, ("IRPF15",))
        no_withholding = self.record(withholding_codes=())
        result = self.catalog((self.history(),)).resolve(self.query, document=(no_withholding,))
        self.assertEqual(result.record.withholding_codes, ())
        self.assertEqual(self.field(result, "withholding_codes").source, "document")
        self.vendors[0].pop("withholding")
        result = self.catalog((self.history(),)).resolve(self.query)
        self.assertEqual(result.status, "INCOMPLETE")
        self.assertEqual(self.field(result, "withholding_codes").status, "MISSING")

    def test_master_snapshot_and_no_posting_or_mutation(self):
        catalog = self.catalog((self.history(),))
        before = catalog.resolve(self.query)
        self.vendors[0]["default_gl_account"] = "47200000"
        self.centers[0]["company"] = "1910"
        self.assertEqual(catalog.resolve(self.query), before)
        self.assertFalse(hasattr(before, "journal_entry"))
        with self.assertRaises(ValueError):
            catalog.resolve(replace(self.query, context="   "))
        with self.assertRaises(ValueError):
            catalog.resolve(self.query, document=(CodingRecord("1100", "V1", "EUR", account="62900000"),))

    def test_source_adapter_joins_company_invoice_currency_and_visibility(self):
        owner = self
        invoice = dict(company="1100", vendor="V1", currency="EUR", doc_id="I1", decision="POST",
                       journal_entry="J1", issue_date="2026-06-01", received_on="2026-06-02", posted_on="2026-06-03")
        entry = dict(company="1100", id="J1", posting_date="2026-06-03", lines=[
            dict(account="62300000", cost_center="CC1", tax_code="S21", currency="EUR", text="Professional fee"),
            dict(account="21300000", cost_center="CC2", tax_code="S21", currency="USD", text="Professional fee"),
            dict(account="70500000", cost_center="CC2", tax_code="R21", currency="EUR", text="Professional fee"),
            dict(account="41000000", partner="V1"), dict(account="40000900", partner="V1")])
        po = dict(id="PO1", company="1100", vendor="V1", currency="EUR", items=[
            dict(item=10, gl_account="60000000", tax_code="SISP", wbs="W1")])
        class Source:
            companies = owner.companies
            def table(self, name):
                return {"ap_invoices": [invoice], "vendors": owner.vendors, "chart_of_accounts": owner.accounts,
                        "cost_centers": owner.centers, "projects": owner.projects, "tax_codes": owner.tax,
                        "purchase_orders": [po]}[name]
            def iter_journal(self):
                yield dict(entry, company="1910")  # Same journal id cannot cross company.
                yield entry
        self.vendors[0].pop("reconciliation_account")  # Missing master field can use contextual history.
        catalog = CodingCatalog.from_phase(Source())
        result = catalog.resolve(self.query)
        self.assertEqual(result.status, "RESOLVED")
        self.assertEqual((result.record.account, result.record.cost_center), ("62900000", "CC1"))
        self.assertTrue(any("#line=4.account" in e.field for e in self.field(result, "reconciliation_account").evidence))
        key = OrderKey("1100", "V1", "EUR", "PO1", 10)
        self.vendors[0]["reconciliation_account"] = "41000000"
        catalog = CodingCatalog.from_phase(Source())
        order = catalog.order_record(key, evidence=self.evidence)
        result = catalog.resolve(replace(self.query, project="P1"), order=(order,))
        self.assertEqual((result.record.account, result.record.wbs, result.record.tax_code),
                         ("60000000", "W1", "SISP"))
        with self.assertRaises(KeyError):
            catalog.order_record(replace(key, vendor="V2"), evidence=self.evidence)
        with self.assertRaises(ValueError):
            catalog.order_record(key, evidence=())
        invoice["received_on"] = "2026-08-01"
        self.assertEqual(CodingCatalog.from_phase(Source()).resolve(self.query).status, "INCOMPLETE")

    def test_current_supplier_master_precedes_conflicting_historical_treatment(self):
        self.vendors[0]["withholding"] = "IRPF15"
        historical = self.history(account="60000000", tax_code="SEX", reconciliation_account="40000000",
                                  withholding_codes=("IRPF7",))
        catalog = self.catalog((historical,))
        result = catalog.resolve(self.query)
        self.assertEqual(result.status, "RESOLVED")
        self.assertEqual((result.record.account, result.record.tax_code, result.record.reconciliation_account,
                          result.record.withholding_codes, result.record.cost_center),
                         ("62900000", "S21", "41000000", ("IRPF15",), "CC1"))
        self.assertEqual([f.source for f in result.fields], ["vendor", "vendor", "vendor", "history", "vendor"])
        # Only an explicit current document/PO override can change a known master treatment.
        current = self.record(account="60000000", tax_code="SEX", reconciliation_account="40000000",
                              withholding_codes=("IRPF7",))
        overridden = catalog.resolve(self.query, document=(current,))
        self.assertEqual((overridden.record.account, overridden.record.tax_code,
                          overridden.record.reconciliation_account, overridden.record.withholding_codes),
                         ("60000000", "SEX", "40000000", ("IRPF7",)))
        for name in ("default_gl_account", "default_tax_code", "reconciliation_account", "withholding"):
            self.vendors[0].pop(name)
        fallback = self.catalog((historical,)).resolve(self.query)
        self.assertEqual(fallback.status, "RESOLVED")
        self.assertTrue(all(f.source == "history" for f in fallback.fields))


if __name__ == "__main__":
    unittest.main()
