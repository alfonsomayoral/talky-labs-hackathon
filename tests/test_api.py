"""HTTP API tests on a small synthetic phase (needs the ``api`` and ``dev`` extras)."""
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

try:
    from fastapi.testclient import TestClient
    from kalmora.api.app import create_app
    HAVE_API = True
except ImportError:  # core installs have no web stack
    HAVE_API = False

from kalmora.app.container import Services, Settings
from kalmora.app.errors import DomainError
from kalmora.evaluation.boundary import check_boundary
from kalmora.evaluation.gateway import EvaluatorGateway

PHASE = "participant/phase_dev"
COMPANIES = [{"code": "1000", "name": "Holding", "short": "H", "country": "ES", "currency": "EUR", "role": "holding"},
             {"code": "1100", "name": "Construccion", "short": "C", "country": "ES", "currency": "EUR", "role": "construction"}]


def line(account, debit=0, credit=0, **extra):
    return {"account": account, "debit": debit, "credit": credit, **extra}


JOURNAL = [
    {"id": "1000-2026-1", "company": "1000", "doc_type": "KR", "posting_date": "2026-07-02", "reference": "F-1",
     "source": "AP", "currency": "EUR",
     "lines": [line("60000000", 10000, cost_center="CC-1000-DIR"),
               line("40000000", 0, 10000, partner="V1", assignment="F-1")]},
    {"id": "1000-2026-2", "company": "1000", "doc_type": "ZP", "posting_date": "2026-07-10", "reference": "P-1",
     "source": "F110", "currency": "EUR",
     "lines": [line("40000000", 4000, 0, partner="V1", assignment="F-1"), line("57200001", 0, 4000)]},
    {"id": "1100-2026-1", "company": "1100", "doc_type": "SA", "posting_date": "2026-07-05", "reference": "X",
     "source": "GL", "currency": "EUR",
     "lines": [line("57200001", 500, 0), line("10000000", 0, 500)]},
]
FILES = {
    "tasks/close.json": {"month": "2026-07", "steps": ["ACCRUAL", "DOUBTFUL_RECLASS"]},
    "tasks/ap_documents.json": ["API1"], "tasks/ar_billing_items.json": ["BILL-1"],
    "tasks/ar_receipts.json": ["BL1"], "tasks/bank_accounts.json": ["BIN-1100"],
    "tasks/intercompany.json": {"pairs": [["1000", "1100"]], "accounts": ["55200000"]},
    "erp/companies.json": COMPANIES,
    "erp/tax_codes.json": {"tax_codes": {"S21": {"country": "ES", "kind": "input", "rate": 2100}}},
}
TABLES = {
    "erp/chart_of_accounts.jsonl": [
        {"account": "10000000", "description": "Capital", "type": "BS", "open_items": False},
        {"account": "40000000", "description": "Proveedores", "type": "BS", "open_items": True},
        {"account": "57200001", "description": "Banco", "type": "BS", "open_items": False},
        {"account": "60000000", "description": "Compras", "type": "PL", "open_items": False}],
    "erp/cost_centers.jsonl": [{"id": "CC-1000-DIR", "company": "1000", "desc": "Direccion"}],
    "erp/vendors.jsonl": [{"id": "V1", "name": "Hierros del Norte", "companies": ["1000"], "rate": 1.5}],
    "erp/customers.jsonl": [{"id": "C1", "name": "Ayuntamiento"}],
    "erp/projects.jsonl": [{"id": "OB-1", "company": "1100", "wbs": [{"id": "OB-1.01", "desc": "Tierras"}]}],
    "erp/journal_entries.jsonl": JOURNAL,
    "erp/open_items.jsonl": [{"company": "1000", "account": "40000000", "partner": "V1", "assignment": "F-1", "balance": -6000}],
    "erp/fx_rates.jsonl": [{"date": "2026-07-01", "base": "EUR", "currency": "USD", "rate": 1.1, "source": "t"},
                           {"date": "2026-07-10", "base": "EUR", "currency": "USD", "rate": 1.25, "source": "t"}],
    "erp/bank_accounts.jsonl": [{"id": "BIN-1100", "company": "1100", "gl_account": "57200001", "currency": "EUR"}],
    "bank/BIN-1100/2026-07.lines.jsonl": [
        {"bank_line": "BL1", "booking_date": "2026-07-03", "value_date": "2026-07-03", "amount": 90000, "currency": "EUR", "text": "TRANSFERENCIA CLIENTE"},
        {"bank_line": "BL2", "booking_date": "2026-07-20", "value_date": "2026-07-20", "amount": -300, "currency": "EUR", "text": "COMISION"}],
}
MESSAGE = {"doc_id": "API1", "channel": "facturae", "received_at": "2026-07-02T08:00:00", "attachments": []}


def build_zip(extra_member: tuple[str, bytes] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, value in FILES.items():
            archive.writestr(f"{PHASE}/{name}", json.dumps(value))
        for name, rows in TABLES.items():
            archive.writestr(f"{PHASE}/{name}", "\n".join(json.dumps(r) for r in rows) + "\n")
        archive.writestr(f"{PHASE}/inbox/ap/API1/message.json", json.dumps(MESSAGE))
        if extra_member:
            archive.writestr(*extra_member)
    return buffer.getvalue()


@unittest.skipUnless(HAVE_API, "needs the 'api' and 'dev' extras")
class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        cls.settings = Settings(data_dir=cls.root / "data", run_dir=cls.root / "runs",
                                submissions_dir=cls.root / "submissions", max_upload_bytes=1024 * 1024)
        cls.services = Services(cls.settings, EvaluatorGateway(None, cls.root / "evals"))
        cls.client = TestClient(create_app(cls.services), raise_server_exceptions=False)
        response = cls.client.post("/v1/packages", files={"archive": ("p.zip", build_zip())})
        assert response.status_code == 202, response.text
        cls.upload = response.json()["data"]
        cls.phase = "/v1/phases/phase_dev"

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def data(self, url, **params):
        response = self.client.get(url, params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]

    def assertProblem(self, response, status, code):
        self.assertEqual(response.status_code, status, response.text)
        self.assertTrue(response.headers["content-type"].startswith("application/problem+json"))
        self.assertEqual(response.json()["code"], code)

    # ingestion ------------------------------------------------------------
    def test_upload_registers_and_loads(self):
        job = self.data(f"/v1/jobs/{self.upload['job_id']}")
        self.assertEqual(job["status"], "loaded")
        self.assertEqual(job["phases"], [{"phase": "phase_dev", "month": "2026-07", "status": "loaded"}])
        counts = job["load_reports"][0]["counts"]
        self.assertEqual((counts["journal_entries"], counts["open_item_keys"], counts["bank_lines"]), (3, 1, 2))
        self.assertEqual(self.upload["package_id"], self.data("/v1/packages")["items"][0]["package_id"])

    def test_load_report_compares_master_with_ledger(self):
        issues = {i["code"] for i in self.data(self.phase)["load_report"]["issues"]}
        self.assertIn("open_items.master_match", issues)  # master -6000 equals 10000 invoice - 4000 payment
        self.assertNotIn("open_items.master_mismatch", issues)
        self.assertNotIn("open_items.partner_null", issues)

    def test_reupload_is_idempotent(self):
        response = self.client.post("/v1/packages", files={"archive": ("p.zip", build_zip())})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"]["already_registered"])
        self.assertEqual(response.json()["data"]["package_id"], self.upload["package_id"])

    def test_bad_archives_are_refused(self):
        self.assertProblem(self.client.post("/v1/packages", files={"archive": ("x.zip", b"nope")}), 400, "package.invalid_archive")
        evil = build_zip(("participant/../escape.txt", b"x"))
        self.assertProblem(self.client.post("/v1/packages", files={"archive": ("e.zip", evil)}), 400, "package.unsafe_archive")
        self.assertProblem(self.client.post("/v1/packages"), 400, "request.invalid")
        self.assertFalse((self.root / "escape.txt").exists())

    def test_upload_limit(self):
        big = build_zip(("participant/phase_dev/pad.bin", b"0" * (2 * 1024 * 1024)))
        self.assertProblem(self.client.post("/v1/packages", files={"archive": ("b.zip", big)}), 413, "upload.too_large")

    def test_busy_guard_and_restore(self):
        services = Services(Settings(data_dir=self.root / "data", run_dir=self.root / "runs"))
        self.assertEqual(services.ingest.restore(), 1)  # memory rebuilt from the packages on disk
        self.assertEqual(services.list_phases()["data"][0]["counts"]["journal_entries"], 3)
        services.ingest._jobs.create("x" * 64)  # an unfinished job blocks a new ingestion
        archive = self.root / "again.zip"
        archive.write_bytes(build_zip(("participant/phase_dev/extra.txt", b"1")))
        with self.assertRaises(DomainError) as caught:
            services.ingest.start(archive)
        self.assertEqual(caught.exception.code, "ingestion.busy")

    # catalogue --------------------------------------------------------------
    def test_phases_and_meta(self):
        listing = self.client.get("/v1/phases").json()["data"]
        self.assertEqual([p["phase"] for p in listing], ["phase_dev"])
        body = self.client.get(f"{self.phase}/balances").json()
        self.assertEqual(body["meta"]["phase"], "phase_dev")
        self.assertEqual(body["meta"]["package_id"], self.upload["package_id"])
        self.assertTrue(body["meta"]["sources"][0]["path"].endswith("erp/journal_entries.jsonl"))
        self.assertEqual(len(body["meta"]["sources"][0]["sha256"]), 64)

    def test_collections_and_filters(self):
        self.assertEqual(self.data(f"{self.phase}/companies")["total"], 2)
        self.assertEqual(self.data(f"{self.phase}/accounts", type="PL")["items"][0]["account"], "60000000")
        self.assertEqual(self.data(f"{self.phase}/accounts", open_items="true")["total"], 1)
        self.assertEqual(self.data(f"{self.phase}/accounts", prefix="57")["total"], 1)
        self.assertEqual(self.data(f"{self.phase}/vendors", q="HIERROS")["total"], 1)
        self.assertEqual(self.data(f"{self.phase}/vendors", company="1100")["total"], 0)
        self.assertEqual(self.data(f"{self.phase}/tax-codes")["items"][0]["id"], "S21")
        self.assertEqual(self.data(f"{self.phase}/vendors/V1")["name"], "Hierros del Norte")
        self.assertProblem(self.client.get(f"{self.phase}/companies", params={"q": "x"}), 400, "request.invalid")
        self.assertProblem(self.client.get(f"{self.phase}/vendors/NOPE"), 404, "record.not_found")

    def test_decimals_are_strings(self):
        self.assertEqual(self.data(f"{self.phase}/vendors/V1")["rate"], "1.5")
        self.assertEqual(self.data(f"{self.phase}/fx-rates", currency="USD")["items"][0]["rate"], "1.1")

    def test_task_shapes(self):
        self.assertEqual(self.data(f"{self.phase}/tasks")["tasks"][0], "ap_documents")
        self.assertEqual(self.data(f"{self.phase}/tasks/ap_documents"), {"doc_ids": ["API1"]})
        self.assertEqual(self.data(f"{self.phase}/tasks/ar_billing_items"), {"billing_items": ["BILL-1"]})
        self.assertEqual(self.data(f"{self.phase}/tasks/ar_receipts"), {"bank_lines": ["BL1"]})
        self.assertEqual(self.data(f"{self.phase}/tasks/bank_accounts"), {"accounts": ["BIN-1100"]})
        self.assertEqual(self.data(f"{self.phase}/tasks/intercompany")["pairs"], [["1000", "1100"]])
        self.assertEqual(self.data(f"{self.phase}/tasks/close")["month"], "2026-07")
        self.assertProblem(self.client.get(f"{self.phase}/tasks/zzz"), 404, "task.not_found")

    def test_documents(self):
        self.assertEqual(self.data(f"{self.phase}/documents")["items"][0]["kind"], "ap")
        self.assertEqual(self.data(f"{self.phase}/documents/API1")["channel"], "facturae")
        self.assertEqual(self.data(f"{self.phase}/documents", kind="ar")["total"], 0)
        self.assertProblem(self.client.get(f"{self.phase}/documents", params={"kind": "xx"}), 400, "request.invalid")

    # accounting -------------------------------------------------------------
    def test_journal_filters(self):
        self.assertEqual(self.data(f"{self.phase}/journal-entries")["total"], 3)
        self.assertEqual(self.data(f"{self.phase}/journal-entries", company="1000")["total"], 2)
        self.assertEqual(self.data(f"{self.phase}/journal-entries", account="57200001")["total"], 2)
        self.assertEqual(self.data(f"{self.phase}/journal-entries", company="1100", account="57200001")["total"], 1)
        self.assertEqual(self.data(f"{self.phase}/journal-entries", partner="V1")["total"], 2)
        self.assertEqual(self.data(f"{self.phase}/journal-entries", doc_type="KR")["total"], 1)
        self.assertEqual(self.data(f"{self.phase}/journal-entries", reference="P-1")["total"], 1)
        self.assertEqual(self.data(f"{self.phase}/journal-entries", **{"from": "2026-07-05"})["total"], 2)
        self.assertEqual(self.data(f"{self.phase}/journal-entries", to="2026-07-04")["total"], 1)
        header = self.data(f"{self.phase}/journal-entries", include="header")["items"][0]
        self.assertNotIn("lines", header)
        self.assertEqual(header["line_count"], 2)
        self.assertProblem(self.client.get(f"{self.phase}/journal-entries", params={"from": "2026-13-01"}), 400, "request.invalid")

    def test_journal_order_entry_and_lines(self):
        ids = [e["id"] for e in self.data(f"{self.phase}/journal-entries")["items"]]
        self.assertEqual(ids, ["1000-2026-1", "1100-2026-1", "1000-2026-2"])  # by posting date
        entry = self.data(f"{self.phase}/journal-entries/1000-2026-2")
        self.assertEqual([l["book_line"] for l in entry["lines"]], ["1000-2026-2#1", "1000-2026-2#2"])
        lines = self.data(f"{self.phase}/journal-lines", account="57200001", company="1000")
        self.assertEqual((lines["total"], lines["items"][0]["entry_id"]), (1, "1000-2026-2"))
        self.assertProblem(self.client.get(f"{self.phase}/journal-entries/NOPE"), 404, "entry.not_found")

    def test_balances_and_summary(self):
        balances = {(b["company"], b["account"]): b["balance"] for b in self.data(f"{self.phase}/balances")["items"]}
        self.assertEqual(balances[("1000", "40000000")], -6000)
        self.assertEqual(balances[("1000", "57200001")], -4000)
        self.assertEqual(self.data(f"{self.phase}/balances", account_prefix="572")["total"], 2)
        self.assertEqual(self.data(f"{self.phase}/balances", company="1100", nonzero="true")["total"], 2)
        summary = self.data(f"{self.phase}/balances:summary")["companies"]
        self.assertTrue(all(s["net"] == 0 for s in summary))
        self.assertEqual(self.data(f"{self.phase}/balances:summary", company="1100")["debit_total"], 500)

    def test_open_items(self):
        items = self.data(f"{self.phase}/open-items")["items"]
        self.assertEqual(items, [{"company": "1000", "account": "40000000", "partner": "V1",
                                  "assignment": "F-1", "balance": -6000}])
        self.assertEqual(self.data(f"{self.phase}/open-items", source="master")["total"], 1)
        self.assertEqual(self.data(f"{self.phase}/open-items", partner="V9")["total"], 0)
        self.assertProblem(self.client.get(f"{self.phase}/open-items", params={"source": "x"}), 400, "request.invalid")

    # pagination and strictness ---------------------------------------------
    def test_pagination_walks_all_items_once(self):
        seen, cursor = [], None
        while True:
            params = {"limit": 1, **({"cursor": cursor} if cursor else {})}
            page = self.data(f"{self.phase}/journal-entries", **params)
            seen += [e["id"] for e in page["items"]]
            self.assertEqual(page["truncated"], page["next_cursor"] is not None)
            cursor = page["next_cursor"]
            if cursor is None:
                break
        self.assertEqual(sorted(seen), ["1000-2026-1", "1000-2026-2", "1100-2026-1"])

    def test_cursor_is_bound_to_its_query(self):
        cursor = self.data(f"{self.phase}/journal-entries", limit=1)["next_cursor"]
        self.assertProblem(self.client.get(f"{self.phase}/journal-entries", params={"limit": 1, "cursor": cursor, "company": "1000"}),
                           400, "page.cursor_invalid")
        self.assertProblem(self.client.get(f"{self.phase}/journal-entries", params={"cursor": "garbage"}), 400, "page.cursor_invalid")

    def test_bad_parameters(self):
        for params in ({"limit": 0}, {"limit": 1001}, {"limit": "abc"}, {"nope": 1}):
            self.assertProblem(self.client.get(f"{self.phase}/balances", params=params), 400, "request.invalid")

    # bank and fx --------------------------------------------------------------
    def test_bank(self):
        accounts = self.data(f"{self.phase}/bank-accounts")["items"]
        self.assertEqual(accounts[0]["months"], ["2026-07"])
        self.assertEqual(self.data(f"{self.phase}/bank-accounts", company="1000")["total"], 0)
        base = f"{self.phase}/bank-accounts/BIN-1100/lines"
        self.assertEqual(self.data(base)["total"], 2)
        self.assertEqual(self.data(base)["items"][0]["account"], "BIN-1100")
        self.assertEqual(self.data(base, month="2026-07")["total"], 2)
        self.assertEqual(self.data(base, month="2026-06")["total"], 0)
        self.assertEqual(self.data(base, min_amount=0)["items"][0]["bank_line"], "BL1")
        self.assertEqual(self.data(base, max_amount=0)["items"][0]["bank_line"], "BL2")
        self.assertEqual(self.data(base, q="comision")["total"], 1)
        self.assertEqual(self.data(base, **{"from": "2026-07-10"})["total"], 1)
        self.assertProblem(self.client.get(f"{self.phase}/bank-accounts/NOPE/lines"), 404, "bank_account.not_found")
        self.assertProblem(self.client.get(base, params={"month": "2026-7"}), 400, "request.invalid")

    def test_fx(self):
        exact = self.data(f"{self.phase}/fx-rates", currency="USD", date="2026-07-10")["items"][0]
        self.assertEqual((exact["rate"], exact["effective_date"]), ("1.25", "2026-07-10"))
        before = self.data(f"{self.phase}/fx-rates", currency="USD", date="2026-07-09")["items"][0]
        self.assertEqual((before["rate"], before["effective_date"]), ("1.1", "2026-07-01"))
        self.assertEqual(self.data(f"{self.phase}/fx-rates", currency="EUR", date="2026-07-09")["items"][0]["rate"], "1")
        self.assertEqual(self.data(f"{self.phase}/fx-rates", **{"from": "2026-07-05"})["total"], 1)
        self.assertProblem(self.client.get(f"{self.phase}/fx-rates", params={"currency": "USD", "date": "2026-06-30"}), 404, "fx_rate.not_found")
        self.assertProblem(self.client.get(f"{self.phase}/fx-rates", params={"date": "2026-07-01"}), 400, "request.invalid")

    # pure checks ----------------------------------------------------------------
    GOOD = {"company": "1000", "posting_date": "2026-07-31",
            "lines": [line("60000000", 3000, cost_center="CC-1000-DIR"), line("57200001", 0, 3000)]}

    def test_validate(self):
        post = lambda body: self.client.post(f"{self.phase}/entries:validate", json=body)
        self.assertEqual(post({"entry": self.GOOD}).json()["data"], {"valid": True, "diagnostics": []})
        late = {**self.GOOD, "posting_date": "2026-08-01"}
        self.assertFalse(post({"entry": late}).json()["data"]["valid"])
        self.assertTrue(post({"entry": late, "with_masters": False}).json()["data"]["valid"])
        unknown = {**self.GOOD, "lines": [line("99999999", 3000), line("57200001", 0, 3000)]}
        self.assertFalse(post({"entry": unknown}).json()["data"]["valid"])
        self.assertProblem(post({"nope": 1}), 422, "entry.invalid")
        self.assertProblem(post({"entry": self.GOOD, "with_masters": "yes"}), 400, "request.invalid")

    def test_simulate_leaves_the_book_untouched(self):
        body = {"entry": self.GOOD, "provenance": {"event_id": "E1", "stage": "fee"}}
        result = self.client.post(f"{self.phase}/entries:simulate", json=body).json()["data"]
        self.assertTrue(result["valid"])
        bank = next(d for d in result["balance_delta"] if d["account"] == "57200001")
        self.assertEqual((bank["before"], bank["delta"], bank["after"]), (-4000, -3000, -7000))
        again = self.client.post(f"{self.phase}/entries:simulate", json=body).json()["data"]
        self.assertTrue(again["valid"])  # same provenance twice: nothing was stored
        self.assertEqual(self.data(f"{self.phase}/balances", company="1000", account="57200001")["items"][0]["balance"], -4000)

    def test_simulate_clears_an_open_item(self):
        clear = {"company": "1000", "posting_date": "2026-07-31",
                 "lines": [line("40000000", 6000, partner="V1", assignment="F-1"), line("57200001", 0, 6000)]}
        result = self.client.post(f"{self.phase}/entries:simulate", json={"entry": clear, "provenance": {"event_id": "E", "stage": "p"}}).json()["data"]
        self.assertEqual(result["open_item_delta"][0]["after"], 0)

    def test_simulate_rejects_bad_input(self):
        bad = {**self.GOOD, "lines": [line("60000000", 3000, cost_center="CC-1000-DIR"), line("57200001", 0, 1)]}
        result = self.client.post(f"{self.phase}/entries:simulate", json={"entry": bad, "provenance": {"event_id": "E", "stage": "s"}}).json()["data"]
        self.assertFalse(result["valid"])
        self.assertEqual(result["balance_delta"], [])
        self.assertProblem(self.client.post(f"{self.phase}/entries:simulate", json={"entry": self.GOOD}), 400, "request.invalid")

    # runs, submission, evaluation, errors ---------------------------------------
    def test_runs(self):
        self.settings.run_dir.mkdir(parents=True, exist_ok=True)
        report = {"run_id": "11111111-1111-1111-1111-111111111111", "command": ["kalmora", "doctor"], "status": "completed",
                  "started_at": "2026-07-01T00:00:00+00:00", "ended_at": "2026-07-01T00:00:01+00:00",
                  "elapsed_seconds": 1.0, "cost": {"status": "no_llm", "total": "0"}, "calls": []}
        (self.settings.run_dir / f"{report['run_id']}.json").write_text(json.dumps(report))
        self.assertEqual(self.data("/v1/runs")["items"][0]["run_id"], report["run_id"])
        self.assertNotIn("calls", self.data("/v1/runs")["items"][0])
        self.assertEqual(self.data(f"/v1/runs/{report['run_id']}")["calls"], [])
        self.assertProblem(self.client.get("/v1/runs/not-a-run"), 404, "run.not_found")

    def test_submission_structure_check(self):
        folder = self.settings.submissions_dir / "phase_dev"
        self.assertProblem(self.client.get(f"{self.phase}/submission/ap"), 404, "submission.not_found")
        self.assertTrue(self.data(f"{self.phase}/submission:check")["ok"])
        folder.mkdir(parents=True)
        (folder / "ap.jsonl").write_text(json.dumps({"doc_id": "API1", "decision": "MAYBE"}) + "\n")
        self.assertEqual(self.data(f"{self.phase}/submission")["files"]["ap"], {"present": True, "rows": 1})
        self.assertEqual(self.data(f"{self.phase}/submission/ap")["total"], 1)
        check = self.data(f"{self.phase}/submission:check")
        self.assertFalse(check["ok"])
        self.assertEqual(check["problems"][0]["module"], "ap")
        (folder / "ap.jsonl").write_text("{broken\n")
        self.assertProblem(self.client.get(f"{self.phase}/submission/ap"), 422, "submission.invalid")
        self.assertProblem(self.client.get(f"{self.phase}/submission/zzz"), 400, "request.invalid")

    def test_evaluator_is_off_by_default(self):
        self.assertProblem(self.client.get(f"{self.phase}/evaluation"), 404, "evaluation.unavailable")
        self.assertProblem(self.client.get(f"{self.phase}/evaluation/ap"), 404, "evaluation.unavailable")

    def test_error_shapes(self):
        self.assertProblem(self.client.get("/v1/phases/phase_x"), 404, "phase.not_found")
        self.assertProblem(self.client.get("/v1/jobs/NOPE"), 404, "job.not_found")
        self.assertProblem(self.client.get("/v1/packages/NOPE"), 404, "package.not_found")
        self.assertProblem(self.client.get("/v1/nope"), 404, "route.not_found")
        self.assertProblem(self.client.post("/v1/phases"), 405, "method.not_allowed")
        self.assertProblem(self.client.get("/v1/phases/phase_dev/journal-entries/..%2Fx"), 404, "route.not_found")
        body = self.client.get("/v1/phases/phase_x").json()
        self.assertEqual(set(body), {"type", "title", "status", "code", "detail", "instance", "diagnostics"})

    def test_cors_allows_only_localhost_by_default(self):
        headers = {"Access-Control-Request-Method": "GET"}
        ok = self.client.options(f"{self.phase}/balances", headers={**headers, "Origin": "http://localhost:5173"})
        self.assertEqual(ok.headers.get("access-control-allow-origin"), "http://localhost:5173")
        bad = self.client.options(f"{self.phase}/balances", headers={**headers, "Origin": "http://evil.example"})
        self.assertNotIn("access-control-allow-origin", bad.headers)


class BoundaryTests(unittest.TestCase):
    def test_new_layers_do_not_import_the_evaluator(self):
        report = check_boundary()
        self.assertEqual(report["violations"], [])
        self.assertGreater(report["scanned_modules"], 60)


if __name__ == "__main__":
    unittest.main()
