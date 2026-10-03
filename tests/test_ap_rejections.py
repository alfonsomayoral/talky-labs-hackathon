from decimal import Decimal
import unittest

from kalmora.ap_rejections import (
    CFDI_FIELDS, REJECTION_CODES, RuleCheck, evaluate_ordered_checks,
    evaluate_rejections, rejection_checks, spanish_standard_vat_rate,
)
from kalmora.facts import Evidence, Fact


def fact(value, field="source", document="invoice.pdf"):
    return (Fact(value, Evidence(document, field)),)


def valid_fields():
    return {key: fact(value, key) for key, value in {
        "recipient_nif": "B12345678", "recipient_company": "1910", "order_company": "1910",
        "isp_required": False, "charged_vat_cents": 2100, "vat_check_applicable": True,
        "vat_lines": [{"applied_rate": "0.21", "applicable_rate": "0.21"}],
        "withholding_required": False, "withholding_cents": 0,
        "net_cents": 10000, "tax_cents": 2100, "gross_cents": 12100,
        "certification_applicable": False, "cfdi_applicable": False,
    }.items()}


class RejectionTests(unittest.TestCase):
    def test_all_eight_reasons_computed_and_ordered(self):
        pdf = {key: 10000 if key.endswith("_cents") else key for key in CFDI_FIELDS}
        cases = (
            {"recipient_nif": None},
            {"recipient_company": "1100"},
            {"isp_required": True},
            {"vat_lines": [{"applied_rate": "0.21", "applicable_rate": "0.10"}]},
            {"withholding_required": True},
            {"gross_cents": 12101},
            {"certification_applicable": True, "billed_net_cents": 90000,
             "certification_current_cents": 10000, "certification_cumulative_cents": 90000},
            {"cfdi_applicable": True, "cfdi_pdf": pdf, "cfdi_xml": dict(pdf, net_cents=9999)},
        )
        for index, changes in enumerate(cases):
            with self.subTest(code=REJECTION_CODES[index]):
                fields = valid_fields() | {key: fact(value, key) for key, value in changes.items()}
                stage = evaluate_rejections(fields)
                self.assertEqual((stage.status, stage.reason), ("REJECT", REJECTION_CODES[index]))
                self.assertTrue(stage.checks[index].evidence)
                # All later violations cannot replace the first one.
                checks = tuple(RuleCheck(code, i >= index, (Evidence("synthetic", code),))
                               for i, code in enumerate(REJECTION_CODES))
                self.assertEqual(evaluate_ordered_checks(reversed(checks), REJECTION_CODES, "REJECT").reason,
                                 REJECTION_CODES[index])

    def test_missing_conflicting_and_explicit_missing_are_distinct(self):
        for unknown in ((), fact("B1") + fact("B2", document="invoice.xml"), fact(123)):
            fields = valid_fields() | {"recipient_nif": unknown, "recipient_company": fact("1100")}
            stage = evaluate_rejections(fields)
            self.assertEqual((stage.status, stage.reason), ("UNKNOWN", None))
            self.assertEqual(len(stage.checks[0].evidence), len(unknown))
        for missing in (None, "", "   "):
            self.assertEqual(evaluate_rejections(valid_fields() | {"recipient_nif": fact(missing)}).reason,
                             "MANDATORY_FIELD_MISSING")
        fields = valid_fields() | {"recipient_nif": fact("B1") + fact("B1", document="copy.xml")}
        self.assertEqual(evaluate_rejections(fields).status, "CLEAR")

    def test_nonapplicability_requires_explicit_boolean(self):
        fields = valid_fields()
        for flag in ("isp_required", "vat_check_applicable", "withholding_required",
                     "certification_applicable", "cfdi_applicable"):
            with self.subTest(flag=flag):
                unknown = fields | {flag: ()}
                self.assertEqual(evaluate_rejections(unknown).status, "UNKNOWN")
                invalid = fields | {flag: fact(0)}
                self.assertEqual(evaluate_rejections(invalid).status, "UNKNOWN")
        fields["withholding_required"] = fact(False)
        fields.pop("withholding_cents")
        self.assertEqual(evaluate_rejections(fields).status, "CLEAR")

    def test_vat_policy_reduced_mixed_and_reverse_charge(self):
        for activity in ("WASTE_COLLECTION", "WASTE_TREATMENT", "STREET_CLEANING", "WATER"):
            rate = spanish_standard_vat_rate(fact(activity)[0])
            self.assertEqual(rate.value, Decimal("0.10"))
        self.assertEqual(spanish_standard_vat_rate(fact("OTHER_STANDARD")[0]).value, Decimal("0.21"))
        for activity in ("UNKNOWN", "EXEMPT", "PT", None):
            with self.assertRaises(ValueError):
                spanish_standard_vat_rate(fact(activity)[0])
        fields = valid_fields() | {"vat_lines": fact([
            {"applied_rate": "0.10", "applicable_rate": "0.10"},
            {"applied_rate": "0.21", "applicable_rate": "0.21"}])}
        self.assertEqual(evaluate_rejections(fields).status, "CLEAR")
        fields.update(isp_required=fact(True), charged_vat_cents=fact(0),
                      vat_check_applicable=fact(False))
        self.assertEqual(evaluate_rejections(fields).status, "CLEAR")

    def test_arithmetic_is_exact_and_not_net_of_withholding(self):
        fields = valid_fields() | {"withholding_required": fact(True), "withholding_cents": fact(1500)}
        self.assertEqual(evaluate_rejections(fields).status, "CLEAR")
        self.assertEqual(evaluate_rejections(fields | {"gross_cents": fact(10600)}).reason, "ARITHMETIC_ERROR")
        for value in (True, 12100.0, -1):
            self.assertEqual(evaluate_rejections(fields | {"gross_cents": fact(value)}).status, "UNKNOWN")

    def test_first_certification_and_pdf_xml_independence(self):
        fields = valid_fields() | {key: fact(value) for key, value in {
            "certification_applicable": True, "billed_net_cents": 10000,
            "certification_current_cents": 10000, "certification_cumulative_cents": 10000,
        }.items()}
        self.assertEqual(evaluate_rejections(fields).status, "CLEAR")
        pdf = {key: 10000 if key.endswith("_cents") else key for key in CFDI_FIELDS}
        fields.update(cfdi_applicable=fact(True), cfdi_pdf=fact(pdf), cfdi_xml=fact(dict(pdf)))
        self.assertEqual(evaluate_rejections(fields).status, "CLEAR")
        self.assertEqual(evaluate_rejections(fields | {"cfdi_xml": fact({"number": "different"})}).reason,
                         "CFDI_MISMATCH")
        self.assertEqual(evaluate_rejections(fields | {"cfdi_xml": fact({"number": "number"})}).status,
                         "UNKNOWN")

    def test_cumulative_billed_despite_line_rounding_cents(self):
        fields = valid_fields() | {key: fact(value) for key, value in {
            "certification_applicable": True, "certification_current_cents": 28037611,
            "certification_cumulative_cents": 525999861}.items()}
        for billed, reason in ((525999857, "CERTIFICATION_CUMULATIVE_BILLED"), (28037611, None)):
            stage = evaluate_rejections(fields | {"billed_net_cents": fact(billed)})
            self.assertEqual(stage.reason, reason)

    def test_gate_validation_and_no_input_mutation(self):
        fields = valid_fields()
        before = dict(fields)
        first = evaluate_rejections(fields)
        self.assertEqual(fields, before)
        self.assertEqual(first, evaluate_rejections(fields))
        self.assertEqual(len(rejection_checks(fields)), 8)
        self.assertFalse(hasattr(first, "journal_entry"))
        with self.assertRaises(ValueError):
            RuleCheck("X", False)
        with self.assertRaises(ValueError):
            evaluate_ordered_checks((first.checks[0], first.checks[0]), REJECTION_CODES, "REJECT")
        self.assertEqual(evaluate_ordered_checks((), REJECTION_CODES, "REJECT").status, "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
