import hashlib
import unittest

from kalmora.ap_pipeline import source_rejection_stage
from kalmora.ap_rejections import CFDI_FIELDS, evaluate_rejections
from kalmora.facts import DocumentFacts, Evidence, Fact


def fact(value, source, field):
    return Fact(value, Evidence(source, field, quote=str(value)))


def document(source, net, tax, gross):
    values = {"net_cents": net, "tax_cents": tax, "gross_cents": gross}
    return DocumentFacts(hashlib.sha256(source.encode()).hexdigest(), "synthetic-normalized-v1",
                         {key: [fact(value, source, key)] for key, value in values.items()
                          if value is not None})


def rejection_fields(sources):
    policy = {"recipient_nif": "R12345678", "recipient_company": "3100", "order_company": "3100",
              "isp_required": False, "vat_check_applicable": True,
              "vat_lines": [{"applied_rate": "0.16", "applicable_rate": "0.16"}],
              "withholding_required": False, "certification_applicable": False,
              "cfdi_applicable": True}
    fields = {key: [fact(value, "synthetic/policy", key)] for key, value in policy.items()}
    for source in sources:
        for key, candidates in source.fields.items():
            fields.setdefault(key, []).extend(candidates)
    for name, source in zip(("cfdi_pdf", "cfdi_xml"), sources):
        view = {key: (source.fields[key][0].value if key.endswith("_cents") else key)
                for key in CFDI_FIELDS if not key.endswith("_cents") or key in source.fields}
        fields[name] = [fact(view, "synthetic/" + name, name)]
    return fields


class SourceRejectionIntegrationTests(unittest.TestCase):
    def test_balanced_sources_with_different_totals_reach_cfdi_mismatch(self):
        for month, identifier, net in (("2026-09", "OTHER-73", 10000),
                                       ("2027-02", "API004469", 25000)):
            with self.subTest(month=month, identifier=identifier):
                pdf = document(f"inbox/ap/{identifier}/{month}.pdf", net, net * 16 // 100,
                               net * 116 // 100)
                xml = document(f"inbox/ap/{identifier}/{month}.xml", net + 10000,
                               (net + 10000) * 16 // 100, (net + 10000) * 116 // 100)
                fields = rejection_fields((pdf, xml))
                self.assertEqual(evaluate_rejections(fields).status, "UNKNOWN")
                for order in ((pdf, xml), (xml, pdf)):
                    stage = source_rejection_stage(fields, amount_sources=order)
                    self.assertEqual((stage.status, stage.reason), ("REJECT", "CFDI_MISMATCH"))
                    arithmetic = next(c for c in stage.checks if c.code == "ARITHMETIC_ERROR")
                    self.assertFalse(arithmetic.violation)
                    self.assertEqual({e.document for e in arithmetic.evidence},
                                     {pdf.fields["net_cents"][0].evidence.document,
                                      xml.fields["net_cents"][0].evidence.document})
                self.assertEqual(len(fields["gross_cents"]), 2)

    def test_real_arithmetic_error_keeps_precedence_over_cfdi_mismatch(self):
        pdf = document("invoice.pdf", 10000, 1600, 11600)
        xml = document("invoice.xml", 20000, 3200, 23201)
        stage = source_rejection_stage(rejection_fields((pdf, xml)), amount_sources=(pdf, xml))
        self.assertEqual((stage.status, stage.reason), ("REJECT", "ARITHMETIC_ERROR"))

    def test_incomplete_source_does_not_become_arithmetically_valid(self):
        pdf = document("invoice.pdf", 10000, 1600, 11600)
        xml = document("invoice.xml", 20000, 3200, None)
        stage = source_rejection_stage(rejection_fields((pdf, xml)), amount_sources=(pdf, xml))
        self.assertEqual((stage.status, stage.reason), ("UNKNOWN", None))
        arithmetic = next(c for c in stage.checks if c.code == "ARITHMETIC_ERROR")
        self.assertTrue(any(xml.source_sha256 in note for note in arithmetic.diagnostics))

    def test_proven_arithmetic_error_is_not_hidden_by_an_incomplete_source(self):
        pdf = document("invoice.pdf", 10000, 1600, 11601)
        xml = document("invoice.xml", 20000, 3200, None)
        stage = source_rejection_stage(rejection_fields((pdf, xml)), amount_sources=(pdf, xml))
        self.assertEqual((stage.status, stage.reason), ("REJECT", "ARITHMETIC_ERROR"))

    def test_earlier_identifier_conflict_stays_unknown(self):
        pdf = document("invoice.pdf", 10000, 1600, 11600)
        xml = document("invoice.xml", 20000, 3200, 23200)
        fields = rejection_fields((pdf, xml))
        fields["recipient_nif"].append(fact(None, "invoice.xml", "recipient_nif"))
        stage = source_rejection_stage(fields, amount_sources=(pdf, xml))
        self.assertEqual((stage.status, stage.reason), ("UNKNOWN", None))

    def test_missing_source_and_fractional_money_stay_unknown(self):
        pdf = document("invoice.pdf", 10000, 1600, 11600)
        xml = document("invoice.xml", 20000, 3200, 23200)
        fields = rejection_fields((pdf, xml))
        self.assertEqual(source_rejection_stage(fields, amount_sources=()).status, "UNKNOWN")
        malformed = document("invoice.xml", 20000.0, 3200, 23200)
        self.assertEqual(source_rejection_stage(fields, amount_sources=(pdf, malformed)).status, "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
