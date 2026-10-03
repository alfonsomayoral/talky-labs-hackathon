import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from kalmora.ap_rejection_sources import invoice_sources, rejection_stage
from kalmora.data import PhaseData
from kalmora.facts import DocumentFacts, Evidence, Fact

COMPANIES = [{"code": "1100", "country": "ES", "tax_id": "A11000000", "vat_id": "ESA11000000"},
             {"code": "1200", "country": "ES", "tax_id": "B12000000", "vat_id": "ESB12000000"},
             {"code": "2100", "country": "PT", "tax_id": "500000021", "vat_id": "PT500000021"},
             {"code": "3100", "country": "MX", "tax_id": "KCM010101AB1", "vat_id": None}]
VENDORS = [
    {"id": "V1", "tax_id": "B00000001", "vat_id": "ESB00000001", "companies": ["1100", "1200"],
     "default_tax_code": "S21", "withholding": None},
    {"id": "V2", "tax_id": "B00000002", "vat_id": "ESB00000002", "companies": ["1100"],
     "default_tax_code": "SISP", "withholding": None},
    {"id": "V3", "tax_id": "00000003Z", "vat_id": "ES00000003Z", "companies": ["1100"],
     "default_tax_code": "S21", "withholding": "IRPF15"},
    {"id": "V4", "tax_id": "MXV010101AB4", "vat_id": None, "companies": ["3100"],
     "default_tax_code": "M16", "withholding": None},
    {"id": "V5", "tax_id": "A00000005", "vat_id": "ESA00000005", "companies": ["2100"],
     "default_tax_code": "S21", "withholding": None},
]
ORDERS = [{"id": "4500000001", "company": "1100", "vendor": "V1",
           "items": [{"item": 10, "tax_code": "S21"}]}]
TAX_CODES = {"tax_codes": {
    "S21": {"country": "ES", "kind": "input", "rate": 2100},
    "SISP": {"country": "ES", "kind": "reverse", "rate": 2100},
    "M16": {"country": "MX", "kind": "input", "rate": 1600}}}


def source(name, digit="a", **values):
    return DocumentFacts(digit * 64, "test", {
        key: [Fact(value, Evidence(name, key))] for key, value in values.items()})


def invoice(name="invoice.pdf", **overrides):
    values = dict(supplier_tax_id="B00000001", recipient_tax_id="A11000000", po_reference="4500000001",
                  net_cents=10000, tax_cents=2100, gross_cents=12100, payable_cents=12100, tax_rate_e4=2100)
    values.update(overrides)
    return source(name, **{key: value for key, value in values.items() if value is not ...})


class RejectionSourcesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        (root / "erp").mkdir()
        (root / "tasks").mkdir()
        (root / "tasks/close.json").write_text(json.dumps({"month": "2026-07"}))
        (root / "erp/companies.json").write_text(json.dumps(COMPANIES))
        (root / "erp/tax_codes.json").write_text(json.dumps(TAX_CODES))
        for name, rows in (("vendors", VENDORS), ("purchase_orders", ORDERS)):
            (root / f"erp/{name}.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
        cls.data = PhaseData(root)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def stage(self, *sources):
        return rejection_stage(sources, {}, self.data)

    def assertRejects(self, reason, *sources):
        stage = self.stage(*sources)
        self.assertEqual((stage.status, stage.reason), ("REJECT", reason), stage.checks)

    def test_ordinary_invoice_clears_with_master_and_order_evidence(self):
        stage = self.stage(invoice())
        self.assertEqual(stage.status, "CLEAR", stage.checks)
        addressee = stage.checks[1]
        self.assertIn(Evidence("erp/purchase_orders.jsonl", "id=4500000001.company"), addressee.evidence)

    def test_explicitly_absent_recipient_nif(self):
        self.assertRejects("MANDATORY_FIELD_MISSING", invoice(recipient_tax_id=None))

    def test_unobserved_recipient_nif_stays_unknown(self):
        stage = self.stage(invoice(recipient_tax_id=...))
        self.assertEqual((stage.status, stage.reason), ("UNKNOWN", None))

    def test_recipient_differs_from_ordering_company(self):
        self.assertRejects("WRONG_ADDRESSEE", invoice(recipient_tax_id="ESB12000000"))

    def test_works_subcontractor_charging_vat(self):
        self.assertRejects("ISP_NOT_APPLIED", invoice(supplier_tax_id="B00000002", po_reference=...))

    def test_rate_differs_from_order_tax_code(self):
        self.assertRejects("VAT_RATE_INCORRECT", invoice(tax_rate_e4=1000, tax_cents=1000, gross_cents=11000,
                                                         payable_cents=11000))

    def test_professional_without_withholding_from_gross_equal_payable(self):
        self.assertRejects("WITHHOLDING_MISSING", invoice(supplier_tax_id="00000003Z", po_reference=...))

    def test_withholding_printed_as_negative_deduction(self):
        self.assertEqual(self.stage(invoice(supplier_tax_id="00000003Z", po_reference=..., withholding_cents=-1500,
                                            payable_cents=10600)).status, "CLEAR")

    def test_line_levy_and_zero_rated_component_are_not_vat_rates(self):
        levy = invoice()
        levy.fields["line.3.tax_rate_e4"] = [Fact(511, Evidence("invoice.pdf", "line.3.tax_rate"))]
        exempt = invoice()
        exempt.fields["tax_rate_e4"].append(Fact(0, Evidence("invoice.pdf", "tax_rate")))
        exempt.fields["tax_cents"].append(Fact(0, Evidence("invoice.pdf", "tax")))
        for source in (levy, exempt):
            self.assertEqual(self.stage(source).status, "CLEAR")

    def test_foreign_code_for_posting_company_is_not_rate_checked(self):
        self.assertEqual(self.stage(invoice(supplier_tax_id="A00000005", recipient_tax_id="PT500000021",
                                            po_reference=..., tax_rate_e4=0, tax_cents=0, gross_cents=10000,
                                            payable_cents=10000)).status, "CLEAR")

    def test_total_is_not_base_plus_tax(self):
        self.assertRejects("ARITHMETIC_ERROR", invoice(gross_cents=12000, payable_cents=12000))

    def test_xml_gross_is_payable_plus_withholding(self):
        xml = invoice("invoice.xml", gross_cents=..., payable_cents=10600, withholding_cents=1500,
                      supplier_tax_id="00000003Z", po_reference=...)
        xml.fields["raw.xml./Facturae/FileHeader[1]/SchemaVersion[1]"] = [Fact("3.2.2", Evidence("invoice.xml", "/"))]
        self.assertEqual(self.stage(xml).status, "CLEAR")

    def test_certification_billed_at_cumulative_amount(self):
        self.assertRejects("CERTIFICATION_CUMULATIVE_BILLED", invoice(
            supplier_tax_id="B00000002", po_reference=..., tax_cents=0, gross_cents=30000, payable_cents=30000,
            net_cents=30000, tax_rate_e4=..., certification_current_cents=10000,
            certification_previous_cents=20000))

    def test_cfdi_xml_differs_from_pdf(self):
        mx = dict(supplier_tax_id="MXV010101AB4", recipient_tax_id="KCM010101AB1", po_reference=...,
                  tax_rate_e4=1600, document_number="A-15", document_date="2026-07-03", currency="MXN")
        pdf = invoice(**mx, tax_cents=1600, gross_cents=11600, payable_cents=11600, net_cents=...,
                      line_count=1, **{"line.1.amount_cents": 10000})
        # The XML total disagrees with its own base + tax: that is a PDF/XML mismatch, not arithmetic.
        xml = invoice("cfdi.xml", **{**mx, "document_number": "15"}, gross_cents=..., payable_cents=11700)
        xml.fields["raw.series"] = [Fact("A", Evidence("cfdi.xml", "/Comprobante/@Serie"))]
        xml.fields["raw.xml./Comprobante/@Version"] = [Fact("4.0", Evidence("cfdi.xml", "/Comprobante/@Version"))]
        self.assertRejects("CFDI_MISMATCH", pdf, xml)
        same = invoice("cfdi.xml", **{**mx, "document_number": "15"}, tax_cents=1600, gross_cents=...,
                       payable_cents=11600)
        same.fields.update({key: xml.fields[key] for key in ("raw.series", "raw.xml./Comprobante/@Version")})
        self.assertEqual(self.stage(pdf, same).status, "CLEAR")

    def test_explicit_recipient_absence_from_unknowns_or_parsed_xml(self):
        def attachment(facts, unknowns=()):
            return SimpleNamespace(path=next(iter(facts.fields.values()))[0].evidence.document, unknowns=unknowns,
                                   normalized=SimpleNamespace(facts=facts),
                                   classification=SimpleNamespace(document_type="INVOICE"))
        pdf = attachment(invoice(recipient_tax_id=...), ({"field": "recipient_tax_id", "status": "MISSING",
                                                          "reason": "not printed"},))
        xml = invoice("invoice.xml", recipient_tax_id=...)
        xml.fields["raw.xml./Facturae/FileHeader[1]/SchemaVersion[1]"] = [Fact("3.2.2", Evidence("invoice.xml", "/"))]
        silent = attachment(invoice(recipient_tax_id=...))
        for item in (pdf, attachment(xml)):
            self.assertRejects("MANDATORY_FIELD_MISSING", *invoice_sources([item]))
        self.assertEqual(self.stage(*invoice_sources([silent])).status, "UNKNOWN")

    def test_earlier_violation_wins_over_later_one(self):
        self.assertRejects("WRONG_ADDRESSEE", invoice(recipient_tax_id="ESB12000000", tax_rate_e4=1000))


if __name__ == "__main__":
    unittest.main()
