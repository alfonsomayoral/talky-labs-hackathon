import json
from pathlib import Path
import unittest


class CoverageTests(unittest.TestCase):
    def test_policy_inventory(self):
        data = json.loads((Path(__file__).resolve().parents[1] / "docs/coverage.json").read_text())
        rules = data["rules"]
        ids = [rule["rule_id"] for rule in rules]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual({r["policy_section"] for r in rules}, set(range(1, 7)))
        required = '''INVOICE CREDIT_NOTE DOWN_PAYMENT_REQUEST PROFORMA VENDOR_STATEMENT FACTORING_NOTICE
        TAX_GARNISHMENT_ORDER BANK_DETAILS_CHANGE CONTRACTOR_TAX_CERTIFICATE POST POST_PAYMENT_BLOCK HOLD
        REJECT DUPLICATE NOT_INVOICE NONE REGISTER_ALTERNATIVE_PAYEE REGISTER_EMBARGO UPDATE_BANK_DETAILS
        UPDATE_CONTRACTOR_CERTIFICATE CONTRACTOR_CERTIFICATE_EXPIRED MANDATORY_FIELD_MISSING WRONG_ADDRESSEE
        ISP_NOT_APPLIED VAT_RATE_INCORRECT WITHHOLDING_MISSING ARITHMETIC_ERROR CERTIFICATION_CUMULATIVE_BILLED
        CFDI_MISMATCH VENDOR_NOT_IN_MASTER BANK_DETAILS_CHANGED QTY_NOT_RECEIVED PRICE_VARIANCE
        SKIP_PENDING_APPROVAL PENALTY NETTING_AP OVERPAYMENT_DUPLICATE FACTORED_MISDIRECTED NON_CUSTOMER
        BANK_FEE_NOT_BOOKED INTEREST_NOT_BOOKED LOAN_INTEREST_NOT_BOOKED CARD_SETTLEMENT_NOT_BOOKED
        DIRECT_DEBIT_NOT_BOOKED RETURNED_DIRECT_DEBIT FX_RATE_DIFFERENCE FACTORING_CHARGES_NOT_BOOKED
        POOLING_NOT_BOOKED UNRECORDED_RECEIPT BOOK_AMOUNT_ERROR WRONG_BANK_ACCOUNT BOOK_DUPLICATE BANK_ERROR
        OUTSTANDING_PAYMENT TRANSFER_IN_TRANSIT PRIOR_PERIOD_BANK_ITEM FX_REVALUATION ACCRUAL PREPAID
        WIP_REVENUE FX_REVAL BAD_DEBT DOUBTFUL_RECLASS INVOICE_IN_TRANSIT INTEREST_DAY_COUNT
        WRONG_TRADING_PARTNER DUPLICATE_POSTING'''.split()
        covered = {code for r in rules for code in r["required_variants"]}
        self.assertFalse(set(required) - covered)
        for row in rules:
            self.assertTrue(row["issues"])
            self.assertLessEqual(len(row["issues"]), 4)
            self.assertTrue(all(27 <= issue <= 113 for issue in row["issues"]))
            self.assertIn(row["status"], {"planned", "m0_delivered"})
            self.assertTrue(row["acceptance"])
            self.assertEqual(len(row["july_cases"]), len(set(row["july_cases"])))
            self.assertEqual(row["july_case_count"], len(row["july_cases"]))
            selector = row.get("july_evidence_selector")
            if selector:
                self.assertLessEqual(row["july_case_count"], data["golden_rows"][selector["task"]])
                self.assertTrue(all(case.startswith(selector["task"] + ":") for case in row["july_cases"]))
            self.assertTrue(row["july_count_meaning"])
            self.assertEqual(set(row["issue_titles"]), {str(n) for n in row["issues"]})
        by_id = {r["rule_id"]: r for r in rules}
        self.assertEqual(by_id["P1-08"]["status"], "planned")
        self.assertIn(34, by_id["P1-07"]["issues"])
        self.assertIn(33, by_id["P1-03"]["issues"])
        markdown = (Path(__file__).resolve().parents[1] / "docs/coverage.md").read_text()
        for rule_id in ids:
            self.assertIn("| " + rule_id + " |", markdown)
        self.assertEqual(data["golden_rows"], {"ap": 305, "ar_billing": 26, "ar_cash": 32,
                                              "bank_rec": 12, "ic": 5, "close": 76})
