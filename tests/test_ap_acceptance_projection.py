"""Contract views retain raw evidence and audit independently failed criteria."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import unittest
from unittest.mock import patch
from kalmora.ap_output import validate_ap_row

from kalmora.ap_acceptance import compare_ap_acceptance, replay_ap_transactions
from kalmora.ap_transaction import APTransactionState
from kalmora.money import RateTable
from kalmora.ap_v0_projection import project_v0_output
import test_ap_acceptance as fixtures


class APProjectionAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.APAcceptanceTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.path = self.fixture.bundle / "deliverables/ap.jsonl"

    def raw(self, *rows):
        payload = b"".join((json.dumps(row, ensure_ascii=False) + "\n").encode() for row in rows)
        self.path.write_bytes(payload)
        return payload

    def audit(self, **options):
        return self.fixture.audit(**options)

    def test_known_metadata_projection_retains_bytes_values_and_real_factory_replay(self):
        row = deepcopy(self.fixture.row)
        row["action_data"] = {"evidence": "original notice", "unknown": None}
        row["lines"][0]["goods_receipts"] = ["GR-OBSERVED"]
        original = self.raw(row)
        failed = self.audit()
        self.assertEqual(failed["documents"][0]["criteria"]["contract"]["status"], "FAIL")
        result = self.audit(project_v0=True)
        self.assertEqual(result["output_sha256"], hashlib.sha256(original).hexdigest())
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(result["projection"]["changes"], [
            dict(line=1, doc_id="I1", pointer="/action_data", reason="V0_INTERNAL_METADATA", value=row["action_data"]),
            dict(line=1, doc_id="I1", pointer="/lines/0/goods_receipts", reason="V0_INTERNAL_METADATA", value=["GR-OBSERVED"])])
        self.assertEqual(result["replay"]["status"], "MATCH")
        self.assertEqual(result["accounting_summary"]["validated"], 1)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertFalse(result["accounting_summary"]["monthly_acceptance"])
        self.assertIn("RAW_OUTPUT_REQUIRES_CONTRACT_PROJECTION", result["blockers"])
        self.assertFalse(compare_ap_acceptance(failed, result)["compatible"])

    def test_optional_nonposting_nulls_are_absent_not_zero_and_reasons_are_unchanged(self):
        row = dict(doc_id="I1", document_type="INVOICE", decision="DUPLICATE", reasons=["DUPLICATE"],
                   duplicate_of="ORIGINAL", company=None, currency=None, net=None, tax=None, payable=None,
                   action=None, action_data={"internal": "source"})
        original = self.raw(row)
        projected = project_v0_output(original)
        view = json.loads(projected.projected_bytes)
        self.assertEqual(view["reasons"], ["DUPLICATE"])
        self.assertNotIn("net", view)
        result = self.audit(project_v0=True, replay=None)
        self.assertEqual(result["documents"][0]["accounting_status"], "VALIDATED")
        self.assertEqual(result["criteria_summary"]["transaction_replay"], {"ABSENT": 1})
        row["reasons"] = ["DUPLICATE", "PRICE_VARIANCE"]
        self.raw(row)
        self.assertEqual(self.audit(project_v0=True, replay=None)["documents"][0]["criteria"]["strict_row_validation"]["status"], "FAIL")

    def test_projection_does_not_repair_posting_money_scope_or_unknown_fields(self):
        row = deepcopy(self.fixture.row)
        row.update(net=None, action_data={"anything": True}, unrecognized="retain")
        row["lines"][0]["amount"] += 1
        original = self.raw(row)
        view = json.loads(project_v0_output(original).projected_bytes)
        self.assertIsNone(view["net"])
        self.assertEqual(view["unrecognized"], "retain")
        self.assertEqual(view["lines"][0]["amount"], row["lines"][0]["amount"])
        result = self.audit(project_v0=True, replay=None)
        self.assertEqual(result["documents"][0]["criteria"]["contract"]["status"], "FAIL")
        self.assertEqual(result["documents"][0]["criteria"]["journal_validation"]["status"], "PASS")
        self.assertEqual(self.path.read_bytes(), original)

    def test_documentary_unknown_does_not_hide_real_accounting_and_absent_replay(self):
        manifest = json.loads(self.fixture.source.manifest_path.read_bytes())
        artifact_path = self.fixture.source.manifest_path.parent / manifest["documents"][0]["attachments"][0]["artifact"]
        artifact = json.loads(artifact_path.read_bytes())
        unknown = dict(field="invoice.net", status="CONTRADICTORY", reason="unreadable")
        self.fixture.replace_prepared_artifact({**artifact, "unknowns": [unknown]})
        result = self.audit(replay=None, documentary_acceptance_reference="User instruction: provisional documentary base")
        criteria = result["documents"][0]["criteria"]
        self.assertEqual(criteria["documentary"]["status"], "INCOMPLETE")
        self.assertEqual(criteria["documentary"]["unknowns"][0]["status"], "CONTRADICTORY")
        for key in ("contract", "strict_row_validation", "master_scope", "journal_validation"):
            self.assertEqual(criteria[key]["status"], "PASS")
        self.assertEqual(criteria["transaction_replay"]["status"], "ABSENT")
        self.assertEqual(result["accounting_summary"]["validated"], 1)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("SOURCE_UNDERSTANDING_INCOMPLETE", result["blockers"])
        self.assertEqual(result["documentary_acceptance"]["status"], "PROVISIONAL_USER_ACCEPTANCE")

    def test_bad_contract_does_not_hide_po_scope_or_partner_and_balance(self):
        row = deepcopy(self.fixture.row)
        row["unrecognized"] = True
        row["lines"][0]["po"] = "NONEXISTENT"
        row["journal_entry"]["lines"][-1]["partner"] = "NONEXISTENT"
        row["journal_entry"]["lines"][-1]["credit"] += 1
        self.raw(row)
        result = self.audit(replay=None)
        criteria = result["documents"][0]["criteria"]
        self.assertEqual(criteria["contract"]["status"], "FAIL")
        self.assertEqual(criteria["master_scope"]["status"], "FAIL")
        self.assertEqual(criteria["journal_validation"]["status"], "FAIL")
        self.assertTrue(any("partner" in message for message in criteria["journal_validation"]["errors"]))
        self.assertEqual(result["journal_totals"], {})

    def test_optional_foreign_document_cents_are_not_shape_failure_but_are_inconclusive(self):
        row = deepcopy(self.fixture.row)
        row["currency"] = "USD"
        row["journal_entry"]["currency"] = "USD"
        for line in row["journal_entry"]["lines"]:
            line.pop("amount_doc", None)
            line.pop("currency", None)
        row["lines"][0].pop("po", None); row["lines"][0].pop("po_item", None)
        self.raw(row)
        criteria = self.audit(replay=None)["documents"][0]["criteria"]
        self.assertEqual(criteria["contract"]["status"], "PASS")
        self.assertEqual(criteria["document_currency_conservation"]["status"], "INCONCLUSIVE")
        self.assertEqual(criteria["strict_row_validation"]["status"], "FAIL")

    def test_foreign_invoice_local_fx_lines_need_no_document_currency_cents(self):
        request = self.fixture.engine.request(date="2026-07-01", currency="USD")
        rates = RateTable([dict(currency="USD", date="2026-07-01", rate="2")])
        proof = replay_ap_transactions([request], APTransactionState(), rates=rates, **self.fixture.options)
        row = json.loads(proof.rows_json)
        row["journal_entry"]["lines"].extend([
            dict(account="66800000", currency="EUR", debit=20, credit=0),
            dict(account="76800000", currency="EUR", debit=0, credit=20)])
        accounts = list(self.fixture.engine.context["accounts"]) + ["66800000", "76800000"]
        self.fixture.write("erp/chart_of_accounts.jsonl", [{"account": account} for account in accounts], lines=True)
        self.fixture.write("erp/purchase_orders.jsonl", [{"id": "PO-OTHER", "company": "1100", "vendor": "SUP-OTHER",
            "currency": "USD", "items": [{"item": 10}]}], lines=True)
        self.raw(row)
        criteria = self.audit(replay=None)["documents"][0]["criteria"]
        self.assertEqual(criteria["strict_row_validation"]["status"], "PASS")
        self.assertEqual(criteria["document_currency_conservation"]["status"], "PASS")
        self.assertEqual(criteria["journal_validation"]["status"], "PASS")

    def test_advance_coded_cent_mismatch_cannot_pass_conservation(self):
        request = self.fixture.engine.advance_request()
        request = replace(request, scope=replace(request.scope, invoice_date="2026-07-01"),
            posting=replace(request.posting, posting_date="2026-07-01",
                header=replace(request.posting.header, invoice_date="2026-07-01")))
        proof = replay_ap_transactions([request], APTransactionState(), **self.fixture.options)
        row = json.loads(proof.rows_json)
        row["doc_id"] = "I1"
        row["lines"][0]["amount"] += 1
        self.raw(row)
        criteria = self.audit(replay=None)["documents"][0]["criteria"]
        self.assertEqual(criteria["strict_row_validation"]["status"], "FAIL")
        self.assertEqual(criteria["document_currency_conservation"]["status"], "FAIL")
        self.assertIn("coded lines must conserve document net", criteria["document_currency_conservation"]["errors"])

    def test_duplicates_and_nonposting_journal_remain_visible(self):
        row = dict(doc_id="I1", document_type="INVOICE", decision="HOLD", reasons=["PRICE_VARIANCE"], journal_entry=None)
        self.raw(row)
        criteria = self.audit(project_v0=True, replay=None)["documents"][0]["criteria"]
        self.assertEqual(criteria["nonposting_journal"]["status"], "FAIL")
        self.raw(self.fixture.row, self.fixture.row)
        result = self.audit(replay=None)
        self.assertEqual(result["documents"][0]["accounting_status"], "INCONCLUSIVE")
        self.assertEqual(result["criteria_summary"]["contract"], {"AMBIGUOUS": 1})

    def test_invalid_json_and_nonobject_rows_are_not_lost_in_projection(self):
        for payload in (b'{"doc_id":"I1","doc_id":"OTHER"}\n', b'null\n', b'[]\n', b'{"x":NaN}\n'):
            with self.subTest(payload=payload):
                self.path.write_bytes(payload)
                self.assertEqual(project_v0_output(payload).projected_bytes, payload)
                result = self.audit(project_v0=True, replay=None)
                self.assertTrue(result["output_errors"])
                self.assertFalse(result["coverage"]["exact"])

    def test_malformed_decision_and_journal_lines_are_diagnostics_not_exceptions(self):
        for decision, lines in ((["POST"], [1]), ("POST", [1]), ("POST", None)):
            with self.subTest(decision=decision, lines=lines):
                row = deepcopy(self.fixture.row)
                row["decision"] = decision
                row["journal_entry"]["lines"] = lines
                self.raw(row)
                result = self.audit(project_v0=True, replay=None)
                self.assertTrue(result["output_errors"])
                self.assertEqual(result["documents"][0]["criteria"]["contract"]["status"], "FAIL")
                self.assertEqual(result["documents"][0]["accounting_status"], "NOT_VALIDATED")

    def test_cost_object_scope_is_checked_even_when_typed_header_is_invalid(self):
        row = deepcopy(self.fixture.row)
        row["net"] = None
        row["lines"][0]["cost_center"] = "CC-MISSING"
        self.raw(row)
        criteria = self.audit(replay=None)["documents"][0]["criteria"]
        self.assertEqual(criteria["contract"]["status"], "FAIL")
        self.assertEqual(criteria["master_scope"]["status"], "FAIL")
        self.assertIn("unknown coded-line cost_center", criteria["master_scope"]["errors"])

    def test_snapshot_is_checked_after_independent_document_validation(self):
        for target in (self.fixture.policy, self.path,
                       self.fixture.phase / "erp/vendors.jsonl"):
            with self.subTest(target=target):
                original = target.read_bytes()
                calls = 0
                def interleave(*args, **kwargs):
                    nonlocal calls
                    calls += 1
                    if calls == 2:
                        target.write_bytes(original + b"\n")
                    return validate_ap_row(*args, **kwargs)
                try:
                    with patch("kalmora.ap_acceptance.validate_ap_row", side_effect=interleave):
                        with self.assertRaisesRegex(ValueError, "changed during audit"):
                            self.audit()
                    self.assertEqual(calls, 2)
                finally:
                    target.write_bytes(original)

    def test_cli_requires_explicit_projection_and_records_provisional_scope(self):
        row = deepcopy(self.fixture.row); row["action_data"] = {"key": "retained"}
        original = self.raw(row)
        path = Path(__file__).resolve().parents[1] / "tools/validate_ap_delivery.py"
        spec = importlib.util.spec_from_file_location("projection_delivery_tool", path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        target = self.fixture.root / "projected-audit.json"
        args = ["--phase", str(self.fixture.phase), "--bundle", str(self.fixture.bundle),
                "--policy", str(self.fixture.policy), "--sources", str(self.fixture.source.manifest_path),
                "--report", str(target), "--project-v0", "--documentary-acceptance-reference", "User authorization"]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(module.main(args), 1)
        result = json.loads(target.read_bytes())
        self.assertEqual(result["accounting_summary"]["validated"], 1)
        self.assertEqual(result["replay"]["status"], "ABSENT")
        self.assertEqual(result["documentary_acceptance"]["reference"], "User authorization")
        self.assertEqual(self.path.read_bytes(), original)
        with self.assertRaises(ValueError):
            self.audit(documentary_acceptance_reference=" ")
        with self.assertRaises(TypeError):
            self.audit(project_v0="true")


if __name__ == "__main__":
    unittest.main()
