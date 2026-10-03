from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from kalmora.ap_output import build_ap_row
from kalmora.ap_phase_export import load_ap_task_inventory, write_phase_ap_jsonl


class PhaseExportTests(unittest.TestCase):
    def phase(self, directory, ids):
        root = Path(directory)
        path = root / "tasks/ap_documents.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(ids), encoding="utf-8")
        return root

    def row(self, ident):
        return build_ap_row(doc_id=ident, document_type="PROFORMA", decision="NOT_INVOICE", action="NONE")

    def test_task_inventory_and_receipt_bind_reproducible_one_row_per_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            phase = self.phase(root / "phase", ["B", "A"])
            attachments = phase / "inbox/ap/A"
            attachments.mkdir(parents=True)
            for name in ("one.pdf", "two.xml", "message.json"):
                (attachments / name).touch()
            output = root / "out/ap.jsonl"
            receipt = write_phase_ap_jsonl(output, (self.row(i) for i in ["B", "A"]), phase_path=phase)
            payload = output.read_bytes()
            self.assertEqual([json.loads(line)["doc_id"] for line in payload.splitlines()], ["A", "B"])
            self.assertEqual(receipt.row_count, 2)
            self.assertEqual(receipt.task_source, "tasks/ap_documents.json")
            self.assertEqual(receipt.task_sha256, hashlib.sha256((phase / receipt.task_source).read_bytes()).hexdigest())
            self.assertEqual(receipt.output_sha256, hashlib.sha256(payload).hexdigest())
            repeated = write_phase_ap_jsonl(output, [self.row("A"), self.row("B")], phase_path=phase, overwrite=True)
            self.assertEqual(asdict(repeated), asdict(receipt))

    def test_real_es_pt_mx_engine_rows_reach_phase_export_without_ledger_reposting(self):
        import test_ap_output_integration as factories

        builder = factories.APOutputIntegrationTests()
        builder.setUp()
        rows, states = [], []
        for company, currency, code in (("1100", "EUR", "S21"), ("2100", "EUR", "P23"), ("3100", "MXN", "M16")):
            row, result = builder.invoice(company, company=company, currency=currency, code=code)
            rows.append(row)
            states.append(result.state)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            phase = self.phase(root / "phase", [r["doc_id"] for r in rows])
            output = root / "ap.jsonl"
            receipt = write_phase_ap_jsonl(output, rows, phase_path=phase, tax_catalog=builder.catalog)
            self.assertEqual(receipt.row_count, 3)
            self.assertEqual([json.loads(line) for line in output.read_text().splitlines()], rows)
            self.assertEqual([state.events for state in states],
                             [((r["company"], "V1", r["currency"], r["doc_id"]),) for r in rows])

    def test_each_phase_uses_its_own_ids_without_a_fixed_count_or_filename_inference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            one = self.phase(root / "one", ["OLD"])
            two = self.phase(root / "two", ["NEW", "SECOND", "THIRD"])
            self.assertEqual(load_ap_task_inventory(one).doc_ids, ("OLD",))
            self.assertEqual(load_ap_task_inventory(two).doc_ids, ("NEW", "SECOND", "THIRD"))
            with self.assertRaisesRegex(ValueError, "coverage mismatch"):
                write_phase_ap_jsonl(root / "out.jsonl", [self.row("OLD")], phase_path=two)
            self.assertFalse((root / "out.jsonl").exists())

    def test_bad_inventory_or_rows_leave_destination_and_sources_intact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            phase = self.phase(root / "phase", ["A", "B"])
            output = root / "out.jsonl"
            output.write_bytes(b"existing")
            task_bytes = (phase / "tasks/ap_documents.json").read_bytes()
            for rows in ([self.row("A")], [self.row("A"), self.row("A")],
                         [self.row("A"), self.row("B"), self.row("EXTRA")],
                         [{**self.row("A"), "action": "UPDATE_BANK_DETAILS"}, self.row("B")]):
                with self.assertRaises(ValueError):
                    write_phase_ap_jsonl(output, rows, phase_path=phase, overwrite=True)
                self.assertEqual(output.read_bytes(), b"existing")
                self.assertEqual((phase / "tasks/ap_documents.json").read_bytes(), task_bytes)
            for ids in ({"doc_ids": ["A"]}, ["A", "A"], [""], [" A"], [True], [None], [["nested"]]):
                self.phase(phase, ids)
                with self.assertRaises(ValueError):
                    write_phase_ap_jsonl(output, [], phase_path=phase, overwrite=True)
                self.assertEqual(output.read_bytes(), b"existing")

    def test_export_cannot_overwrite_or_add_files_in_source_phase(self):
        with tempfile.TemporaryDirectory() as tmp:
            phase = self.phase(Path(tmp) / "phase", ["A"])
            source = phase / "tasks/ap_documents.json"
            before = source.read_bytes()
            for output in (source, phase / "submission/ap.jsonl"):
                with self.assertRaisesRegex(ValueError, "outside the source phase"):
                    write_phase_ap_jsonl(output, [self.row("A")], phase_path=phase, overwrite=True)
            self.assertEqual(source.read_bytes(), before)
            self.assertFalse((phase / "submission").exists())

    def test_golden_or_task_symlink_outside_phase_is_not_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            golden = self.phase(root / "golden", ["SECRET"])
            with self.assertRaises(ValueError):
                load_ap_task_inventory(golden)
            phase = self.phase(root / "phase", ["A"])
            task = phase / "tasks/ap_documents.json"
            task.unlink()
            task.symlink_to(golden / "tasks/ap_documents.json")
            with self.assertRaises(ValueError):
                load_ap_task_inventory(phase)

    @unittest.skipUnless(os.environ.get("KALMORA_PHASE_ERP"), "original ERP not configured")
    def test_original_development_task_inventory_is_the_only_source_of_expected_ids(self):
        phase = Path(os.environ["KALMORA_PHASE_ERP"]).parent
        inventory = load_ap_task_inventory(phase)
        original = (phase / "tasks/ap_documents.json").read_bytes()
        self.assertEqual(inventory.doc_ids, tuple(json.loads(original)))
        self.assertEqual(len(inventory.doc_ids), 305)
        self.assertEqual(inventory.source_sha256, hashlib.sha256(original).hexdigest())


if __name__ == "__main__":
    unittest.main()
