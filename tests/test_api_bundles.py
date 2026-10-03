"""Run bundles, closer guards, documents, landing and MCP, on the small synthetic phase of test_api."""
import asyncio
import io
import json
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

try:
    from test_api import FILES, MESSAGE, PHASE, TABLES, build_zip
except ImportError:  # run as tests.test_api_bundles
    from tests.test_api import FILES, MESSAGE, PHASE, TABLES, build_zip

try:
    from fastapi.testclient import TestClient
    from kalmora.api.app import create_app
    HAVE_API = True
except ImportError:
    HAVE_API = False
try:
    from mcp.shared.memory import create_connected_server_and_client_session
    from kalmora.mcp.server import create_server
    HAVE_MCP = True
except ImportError:
    HAVE_MCP = False

from kalmora.app.container import Services, Settings
from kalmora.app.params import valid_phase_name
from kalmora.bundle import RunBundle
from kalmora.evaluation.gateway import EvaluatorGateway
from kalmora.infra.closer import CommandCloser

# a close command that leaves a small, realistic bundle
WRITE_BUNDLE = """
import sys
from kalmora.bundle import RunBundle
b = RunBundle(sys.argv[1])
b.write_deliverable("ap", [{"doc_id": "API1", "document_type": "INVOICE", "decision": "REJECT", "reasons": ["X"]}])
b.write_deliverable("ic", [{"pair": ["1100", "1000"], "cause": "INTEREST_DAY_COUNT", "adjustment": []}])
b.event("ap:API1", "EXTRACT", step="read", result="PASS", summary="read the invoice")
b.event("ap:API1", "CHECK", step="bank_details", result="FAIL", policy_ref="2.2.3", evidence=[{"kind": "erp", "file": "erp/vendors.jsonl", "key": "V1", "field": "bank.iban"}])
b.event("ap:API1", "DECIDE", result="INFO", confidence=0.8)
b.event("ic:1000-1100/INTEREST_DAY_COUNT", "MATCH", result="PASS")
b.attention("ap:API1", "FRAUD_SIGNAL", "P0", "IBAN differs", impact=4202872, recommendation={"decision": "HOLD"})
b.attention("ic:1000-1100/INTEREST_DAY_COUNT", "AGENT_DOUBT", "P2", "Day count")
b.manifest(models=[{"provider": "x", "name": "m", "calls": 2}], cost_usd_total=0.5)
"""


def wait_for(client, run_id):
    for _ in range(200):
        run = client.get(f"/v1/runs/{run_id}").json()["data"]
        if run["status"] != "running":
            return run
        time.sleep(0.05)
    raise AssertionError("run did not finish")


@unittest.skipUnless(HAVE_API, "needs the 'api' and 'dev' extras")
class BundleApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        cls.run_dir = cls.root / "runs"
        cls.settings = Settings(data_dir=cls.root / "data", run_dir=cls.run_dir, submissions_dir=cls.root / "subs",
                                close_command=(sys.executable, "-c", WRITE_BUNDLE, "{out}", "{phase}"))
        cls.services = Services(cls.settings)
        cls.client = TestClient(create_app(cls.services), raise_server_exceptions=False)
        assert cls.client.post("/v1/packages", files={"archive": ("p.zip", build_zip())}).status_code == 202
        cls.phase = "/v1/phases/phase_dev"
        started = cls.client.post(f"{cls.phase}/runs")
        assert started.status_code == 202, started.text
        cls.run_id = started.json()["data"]["run_id"]
        cls.finished = wait_for(cls.client, cls.run_id)

    @classmethod
    def tearDownClass(cls):
        cls.services.close()
        cls._tmp.cleanup()

    def data(self, url, **params):
        response = self.client.get(url, params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]

    def assertProblem(self, response, status, code):
        self.assertEqual(response.status_code, status, response.text)
        self.assertEqual(response.json()["code"], code)

    # closer ---------------------------------------------------------------
    def test_run_completes_with_a_deliverables_summary(self):
        self.assertEqual(self.finished["status"], "completed")
        self.assertEqual(self.finished["models"][0]["calls"], 2)  # the command's own manifest fields are kept
        self.assertEqual(self.finished["deliverables"]["ap"], {"present": True, "rows": 1})
        self.assertEqual(self.finished["deliverables"]["bank_rec"], {"present": False, "rows": 0})

    def test_a_second_run_of_the_same_phase_is_refused_while_one_is_running(self):
        slow = CommandCloser((sys.executable, "-c", "import time; time.sleep(0.6)"), self.root / "slow")
        first = slow.start("phase_dev", self.root, "2026-07")
        from kalmora.app.errors import DomainError
        with self.assertRaises(DomainError) as caught:
            slow.start("phase_dev", self.root, "2026-07")
        self.assertEqual(caught.exception.code, "run.busy")
        slow.start("phase_other", self.root, "2026-07")  # another phase is independent
        time.sleep(1.0)
        self.assertEqual(json.loads((self.root / "slow" / first / "manifest.json").read_text())["status"], "failed")
        slow.start("phase_dev", self.root, "2026-07")  # free again once the first ended

    def test_http_maps_the_busy_guard_to_409(self):
        settings = Settings(data_dir=self.root / "data", run_dir=self.root / "busy",
                            close_command=(sys.executable, "-c", "import time; time.sleep(0.5)"))
        services = Services(settings)
        services.ingest.restore()
        client = TestClient(create_app(services), raise_server_exceptions=False)
        self.assertEqual(client.post(f"{self.phase}/runs").status_code, 202)
        self.assertProblem(client.post(f"{self.phase}/runs"), 409, "run.busy")
        services.close()

    def test_exit_zero_without_deliverables_is_a_failure(self):
        closer = CommandCloser((sys.executable, "-c", "pass"), self.root / "empty")
        run_id = closer.start("phase_dev", self.root, "2026-07")
        for _ in range(100):
            manifest = json.loads((self.root / "empty" / run_id / "manifest.json").read_text())
            if manifest["status"] != "running":
                break
            time.sleep(0.05)
        self.assertEqual(manifest["status"], "failed")
        self.assertEqual(manifest["exit_code"], 0)
        self.assertIn("no deliverables", manifest["error"])

    def test_orphaned_running_runs_are_closed_on_recovery(self):
        orphan = self.run_dir / "00000000-0000-0000-0000-00000000000a"
        orphan.mkdir()
        (orphan / "manifest.json").write_text(json.dumps({"run_id": orphan.name, "status": "running", "dataset": "phase_dev"}))
        self.assertEqual(self.services.recover_runs(), 1)
        recovered = self.data(f"/v1/runs/{orphan.name}")
        self.assertEqual((recovered["status"], recovered["interrupted"], recovered["exit_code"]), ("failed", True, -2))
        self.assertEqual(self.services.recover_runs(), 0)  # nothing left to recover

    def test_phase_names_are_validated(self):
        for good in ("phase_dev", "phase-test", "p1.2"):
            self.assertTrue(valid_phase_name(good), good)
        for bad in ("-rf", "--out", ".hidden", "a b", "a/b", "", "x" * 65, ".."):
            self.assertFalse(valid_phase_name(bad), bad)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, value in FILES.items():
                archive.writestr(f"participant/-sneaky/{name}", json.dumps(value))
        response = self.client.post("/v1/packages", files={"archive": ("s.zip", buffer.getvalue())})
        self.assertProblem(response, 400, "package.invalid")
        self.assertIn("-sneaky", response.json()["detail"])

    # run-scoped deliverables --------------------------------------------------
    def test_run_deliverables_and_structure_check(self):
        base = f"/v1/runs/{self.run_id}"
        files = self.data(f"{base}/submission")["files"]
        self.assertEqual((files["ap"]["rows"], files["ic"]["rows"], files["close"]["present"]), (1, 1, False))
        self.assertEqual(self.data(f"{base}/submission/ap")["items"][0]["doc_id"], "API1")
        self.assertProblem(self.client.get(f"{base}/submission/close"), 404, "submission.not_found")
        self.assertProblem(self.client.get(f"{base}/submission/zzz"), 400, "request.invalid")
        check = self.data(f"{base}/submission:check")
        self.assertEqual(check["checked"], ["ap", "ic"])
        self.assertTrue(check["ok"] or check["problems"])  # the fixture ic row has no company on its lines: reported, not crashed
        bad = self.run_dir / self.run_id / "deliverables" / "ap.jsonl"
        original = bad.read_text()
        bad.write_text(json.dumps({"doc_id": "API1", "decision": "MAYBE"}) + "\n")
        problems = self.data(f"{base}/submission:check")["problems"]
        bad.write_text(original)
        self.assertTrue(any(p["module"] == "ap" for p in problems))
        self.assertProblem(self.client.get("/v1/runs/not-a-run/submission"), 404, "run.not_found")

    def test_run_evaluation_needs_the_evaluator_and_a_golden(self):
        self.assertProblem(self.client.get(f"/v1/runs/{self.run_id}/evaluation"), 404, "evaluation.unavailable")
        enabled = Services(self.settings, EvaluatorGateway(self.root / "evaluator", self.root / "evals"))
        enabled.ingest.restore()
        client = TestClient(create_app(enabled), raise_server_exceptions=False)
        self.assertProblem(client.get(f"/v1/runs/{self.run_id}/evaluation"), 404, "evaluation.unavailable")  # no golden
        enabled.close()

    def test_run_without_a_named_phase_cannot_be_evaluated(self):
        folder = self.run_dir / "00000000-0000-0000-0000-00000000000b"
        folder.mkdir()
        (folder / "manifest.json").write_text(json.dumps({"run_id": folder.name, "status": "completed"}))
        enabled = Services(self.settings, EvaluatorGateway(self.root / "evaluator", self.root / "evals"))
        client = TestClient(create_app(enabled), raise_server_exceptions=False)
        self.assertProblem(client.get(f"/v1/runs/{folder.name}/evaluation"), 409, "run.phase_unknown")
        enabled.close()

    # trace -------------------------------------------------------------------
    def test_events_filters(self):
        base = f"/v1/runs/{self.run_id}/events"
        self.assertEqual(self.data(base)["total"], 4)
        self.assertEqual(self.data(base, item="ap:API1")["total"], 3)
        self.assertEqual([e["step"] for e in self.data(base, item="ap:API1", result="FAIL")["items"]], ["bank_details"])
        self.assertEqual(self.data(base, kind="DECIDE")["items"][0]["confidence"], 0.8)
        self.assertEqual(self.data(base, step="read")["total"], 1)
        self.assertEqual([e["seq"] for e in self.data(base, item="ap:API1")["items"]], [1, 2, 3])
        self.assertProblem(self.client.get(base, params={"kind": "NOPE"}), 400, "request.invalid")
        self.assertProblem(self.client.get(base, params={"bogus": 1}), 400, "request.invalid")

    def test_attention_is_sorted_by_priority_and_filtered(self):
        base = f"/v1/runs/{self.run_id}/attention"
        self.assertEqual([a["priority"] for a in self.data(base)["items"]], ["P0", "P2"])
        self.assertEqual(self.data(base, priority="P2")["items"][0]["kind"], "AGENT_DOUBT")
        self.assertEqual(self.data(base, item="ap:API1")["items"][0]["impact"], 4202872)
        self.assertProblem(self.client.get(base, params={"priority": "P9"}), 400, "request.invalid")

    def test_item_collects_row_trace_and_attention(self):
        item = self.data(f"/v1/runs/{self.run_id}/items/ap:API1")
        self.assertEqual((item["task"], item["key"], item["row"]["decision"]), ("ap", "API1", "REJECT"))
        self.assertEqual(len(item["events"]), 3)
        self.assertEqual(item["attention"][0]["priority"], "P0")
        ic = self.data(f"/v1/runs/{self.run_id}/items/ic:1000-1100/INTEREST_DAY_COUNT")  # pair order does not matter
        self.assertEqual(ic["row"]["cause"], "INTEREST_DAY_COUNT")
        self.assertProblem(self.client.get(f"/v1/runs/{self.run_id}/items/ap:NOPE"), 404, "item.not_found")
        self.assertProblem(self.client.get(f"/v1/runs/{self.run_id}/items/zz:1"), 400, "request.invalid")

    def test_item_without_a_delivery_file_still_returns_its_trace(self):
        bundle = RunBundle(self.run_dir / self.run_id)
        bundle.event("close:ACCRUAL/1100/V1", "ESTIMATE", result="INFO")
        item = self.data(f"/v1/runs/{self.run_id}/items/close:ACCRUAL/1100/V1")
        self.assertIsNone(item["row"])
        self.assertEqual(item["events"][-1]["kind"], "ESTIMATE")

    def test_corrupt_trace_is_reported(self):
        folder = self.run_dir / "00000000-0000-0000-0000-00000000000c" / "trace"
        folder.mkdir(parents=True)
        (folder.parent / "manifest.json").write_text(json.dumps({"run_id": folder.parent.name, "status": "completed"}))
        (folder / "events.jsonl").write_text('{"ok": 1}\n{broken\n')
        self.assertProblem(self.client.get(f"/v1/runs/{folder.parent.name}/events"), 422, "bundle.invalid")

    # overrides ---------------------------------------------------------------
    def test_overrides_are_recorded_and_attached_to_their_item(self):
        base = f"/v1/runs/{self.run_id}/overrides"
        attention_id = self.data(f"/v1/runs/{self.run_id}/attention", item="ap:API1")["items"][0]["attention_id"]
        created = self.client.post(base, json={"attention_id": attention_id, "decision": "POST", "note": "called the vendor", "user": "ana"})
        self.assertEqual(created.status_code, 201, created.text)
        self.assertTrue(created.json()["data"]["ts"].endswith("Z"))
        self.assertEqual(self.client.post(base, json={"item": "ar_cash:BL1", "decision": "SKIP"}).status_code, 201)
        listed = self.data(base)
        self.assertEqual([o.get("user") for o in listed["items"]], ["ana", None])
        self.assertEqual(self.data(f"/v1/runs/{self.run_id}/items/ap:API1")["overrides"][0]["note"], "called the vendor")
        for body, code in (({"decision": "POST"}, "request.invalid"), ({"item": "ap:A", "attention_id": "x", "decision": "POST"}, "request.invalid"),
                           ({"item": "ap:A"}, "request.invalid"), ({"item": "ap:A", "decision": "POST", "ts": "now"}, "request.invalid"),
                           ({"item": "nope", "decision": "POST"}, "request.invalid"), ([], "request.invalid")):
            self.assertProblem(self.client.post(base, json=body), 400, code)
        self.assertProblem(self.client.post(base, json={"attention_id": "att-9999", "decision": "POST"}), 404, "attention.not_found")

    # documents and landing ---------------------------------------------------------
    def test_attachments_and_landing(self):
        with tempfile.TemporaryDirectory() as directory:
            buffer = io.BytesIO(build_zip((f"{PHASE}/inbox/ap/API1/factura.xml", b"<Facturae/>")))
            services = Services(Settings(data_dir=Path(directory) / "d", run_dir=Path(directory) / "r"))
            client = TestClient(create_app(services), raise_server_exceptions=False)
            self.assertEqual(client.post("/v1/packages", files={"archive": ("a.zip", buffer.getvalue())}).status_code, 202)
            listed = client.get(f"{self.phase}/documents/API1/attachments").json()["data"]["attachments"]
            self.assertEqual([a["name"] for a in listed], ["factura.xml"])
            self.assertEqual((listed[0]["size"], len(listed[0]["sha256"]), listed[0]["listed_in_message"]), (11, 64, False))
            self.assertProblem(client.get(f"{self.phase}/documents/NOPE/attachments"), 404, "document.not_found")
            landing = client.get(f"{self.phase}/landing").json()["data"]
            self.assertEqual(landing["counts"]["inbound_item"], 1)
            self.assertEqual(len(landing["tables"]), 8)
            self.assertEqual(client.get(f"{self.phase}/landing/inbound_item").json()["data"]["total"], 1)
            self.assertEqual(client.get(f"{self.phase}/landing/source_file", params={"limit": 5}).json()["data"]["next_cursor"] is not None, True)
            self.assertProblem(client.get(f"{self.phase}/landing/nope"), 404, "landing.table_not_found")
            self.assertProblem(client.get(f"{self.phase}/landing/inbound_item", params={"nope": "1"}), 400, "request.invalid")
            services.close()


class BundleWriterTests(unittest.TestCase):
    def test_events_get_ids_and_per_item_sequence(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = RunBundle(directory)
            first = bundle.event("ap:A", "CHECK", result="PASS")
            bundle.event("ap:B", "CHECK")
            third = bundle.event("ap:A", "DECIDE", confidence=0.5)
            self.assertEqual((first["event_id"], first["seq"], third["event_id"], third["seq"]), ("e-000001", 1, "e-000003", 2))
            reopened = RunBundle(directory)  # appending to an existing trace continues the numbering
            self.assertEqual(reopened.event("ap:C", "POST")["event_id"], "e-000004")
            self.assertEqual(len((Path(directory) / "trace" / "events.jsonl").read_text().splitlines()), 4)

    def test_invalid_input_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = RunBundle(directory)
            for call in (lambda: bundle.event("ap:A", "NOPE"), lambda: bundle.event("zz:A", "CHECK"),
                         lambda: bundle.event("ap:", "CHECK"), lambda: bundle.event("ap:A", "CHECK", result="MAYBE"),
                         lambda: bundle.event("ap:A", "CHECK", confidence=1.5),
                         lambda: bundle.event("ap:A", "CHECK", evidence=[{"kind": "tea"}]),
                         lambda: bundle.attention("ap:A", "AGENT_DOUBT", "P7", "t"),
                         lambda: bundle.attention("ap:A", "AGENT_DOUBT", "P1", "t", impact=1.5),
                         lambda: bundle.write_deliverable("payroll", [])):
                with self.assertRaises(ValueError):
                    call()
            self.assertFalse((Path(directory) / "trace" / "events.jsonl").exists())

    def test_deliverables_are_written_atomically_and_manifest_merges(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = RunBundle(directory)
            path = bundle.write_deliverable("ap", [{"doc_id": "A"}, {"doc_id": "B"}])
            self.assertEqual(len(path.read_text().splitlines()), 2)
            self.assertEqual(list((Path(directory) / "deliverables").glob("*.tmp")), [])
            bundle.manifest(status="running")
            bundle.manifest(cost_usd_total=1.0)
            self.assertEqual(json.loads((Path(directory) / "manifest.json").read_text()), {"status": "running", "cost_usd_total": 1.0})


@unittest.skipUnless(HAVE_API and HAVE_MCP, "needs the 'api' extra and the mcp package")
class McpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        root = Path(cls._tmp.name)
        cls.services = Services(Settings(data_dir=root / "d", run_dir=root / "r"))
        TestClient(create_app(cls.services)).post("/v1/packages", files={"archive": ("p.zip", build_zip())})
        cls.server = create_server(cls.services)

    @classmethod
    def tearDownClass(cls):
        cls.services.close()
        cls._tmp.cleanup()

    def call(self, name, **arguments):
        async def go():
            async with create_connected_server_and_client_session(self.server._mcp_server) as client:
                return await client.call_tool(name, arguments)
        return asyncio.run(go())

    def test_every_tool_is_read_only(self):
        async def go():
            async with create_connected_server_and_client_session(self.server._mcp_server) as client:
                return (await client.list_tools()).tools
        tools = asyncio.run(go())
        self.assertGreaterEqual(len(tools), 25)
        self.assertTrue(all(t.annotations and t.annotations.readOnlyHint and not t.annotations.destructiveHint for t in tools))
        names = {t.name for t in tools}
        self.assertFalse(names & {"start_run", "add_override", "upload_package", "ingest_package"})
        self.assertNotIn("get_run_evaluation", names)  # off while the evaluator is off

    def test_tools_answer_with_the_http_envelope(self):
        result = self.call("get_balances", company="1000", account="57200001")
        self.assertFalse(result.isError)
        body = result.structuredContent
        self.assertEqual(body["data"]["items"][0]["balance"], -4000)
        self.assertEqual(body["meta"]["phase"], "phase_dev")

    def test_the_only_loaded_phase_is_the_default(self):
        self.assertEqual(self.call("get_balance_summary", company="1100").structuredContent["data"]["debit_total"], 500)

    def test_domain_errors_become_tool_errors_with_a_code(self):
        result = self.call("get_journal_entry", entry_id="NOPE")
        self.assertTrue(result.isError)
        self.assertEqual(json.loads(result.content[0].text.split(": ", 1)[-1])["code"], "entry.not_found")

    def test_limits_are_capped(self):
        body = self.call("query_journal", limit=1000, header_only=False).structuredContent
        self.assertEqual(len(body["data"]["items"]), 3)
        self.assertIn("lines", body["data"]["items"][0])

    def test_simulate_and_validate(self):
        entry = {"company": "1000", "posting_date": "2026-07-31", "lines": [
            {"account": "60000000", "debit": 3000, "credit": 0, "cost_center": "CC-1000-DIR"},
            {"account": "57200001", "debit": 0, "credit": 3000}]}
        self.assertTrue(self.call("validate_entry", entry=entry).structuredContent["data"]["valid"])
        simulated = self.call("simulate_entry", entry=entry, event_id="E", stage="s").structuredContent["data"]
        self.assertTrue(simulated["valid"])
        self.assertEqual(self.call("get_balances", company="1000", account="57200001").structuredContent["data"]["items"][0]["balance"], -4000)


if __name__ == "__main__":
    unittest.main()
