from collections import Counter
from decimal import Decimal
from dataclasses import replace
import importlib.util
import json
import os
import tempfile
from pathlib import Path
import unittest

from kalmora.billing import BillingType, build_ar_billing, load_items, to_row, write_billing
from kalmora.billing.inputs import (CertificationFacts, Chapter, ExtraService, PlantMwh, PlantSettlement,
                                    PpaFacts, RevisionFacts, ServiceFacts, SettlementFacts)
from kalmora.data import PhaseData
from kalmora.facts import Evidence
from billing_support import BillingCase, REAL
from source_snapshot_support import snapshot_router


def annotated_facts(row):
    values = dict(row["facts"])
    values["evidence"] = tuple(Evidence(**e) for e in values["evidence"])
    kind = BillingType(row["type"])
    if kind is BillingType.OBRA_CERTIFICATION:
        values["chapters"] = tuple(Chapter(**x) for x in values["chapters"])
        return CertificationFacts(**values)
    if kind is BillingType.SERVICE_MONTHLY:
        values["extras"] = tuple(ExtraService(**x) for x in values["extras"])
        return ServiceFacts(**values)
    if kind is BillingType.PRICE_REVISION:
        values["months"] = tuple(values["months"])
        return RevisionFacts(**values)
    if kind is BillingType.PPA:
        values["plants"] = tuple(PlantMwh(**x) for x in values["plants"])
        values["price_mwh_cents"] = Decimal(values["price_mwh_cents"])
        return PpaFacts(**values)
    values["plants"] = tuple(PlantSettlement(**x) for x in values["plants"])
    return SettlementFacts(**values)


class OutputTests(BillingCase):
    def test_publishes_invoice_and_wip_files_in_new_directory(self):
        run = self.run_item(self.cert(approved=False))
        target = write_billing(run, self.root / "out")
        ar = json.loads((target / "ar_billing.jsonl").read_text())
        wip = json.loads((target / "pending_wip.jsonl").read_text())
        self.assertEqual(set(ar), {"billing_item", "company", "expected"})
        self.assertEqual((wip["amount"], len(wip["lines"])), (30000, 2))
        with self.assertRaises(FileExistsError):
            write_billing(run, target)

    def test_unresolved_run_never_publishes(self):
        run = self.run_item(self.cert(current=1))
        with self.assertRaises(ValueError):
            write_billing(run, self.root / "out")
        self.assertFalse((self.root / "out").exists())

    def test_missing_wip_and_duplicate_rows_never_publish(self):
        run = self.run_item(self.cert(approved=False))
        for bad in (replace(run, pending_wip=()), replace(run, results=run.results * 2)):
            with self.assertRaises(ValueError):
                write_billing(bad, self.root / "out")
        self.assertFalse((self.root / "out").exists())


@unittest.skipUnless((REAL / "erp").is_dir(), "development source package unavailable")
class JulyOutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = PhaseData(REAL)
        cls.annotations = json.loads((Path(__file__).parent / "fixtures/billing-july.json").read_text())
        cls.billing_run = build_ar_billing(cls.data, load_items(cls.data), {k: annotated_facts(v) for k, v in cls.annotations.items()})

    def test_source_annotations_are_grounded_in_normalized_reader(self):
        router = snapshot_router(REAL)
        for id, row in self.annotations.items():
            doc = router.parse(f"inbox/ar/billing/{id}/documento.pdf")
            self.assertEqual(row["source_sha256"], doc.source_sha256)
            for evidence in row["facts"]["evidence"]:
                self.assertTrue(any(b.page == evidence["page"] and evidence["quote"] in b.text for b in doc.blocks), id)

    def test_snapshot_reader_refuses_missing_stale_and_misbound_sources(self):
        router = snapshot_router(REAL)
        id = next(iter(self.annotations))
        relative = f"inbox/ar/billing/{id}/documento.pdf"
        document = router.parse(relative)
        with tempfile.TemporaryDirectory() as tmp:
            phase, normalized = Path(tmp) / "phase_dev", Path(tmp) / "normalized"
            source = phase / relative
            source.parent.mkdir(parents=True)
            source.write_bytes((REAL / relative).read_bytes())
            reader = type(router)(phase, use_preparsed=True, normalized_dir=normalized)
            snapshot = normalized / "phase_dev" / (relative + ".json")
            snapshot.parent.mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "missing_preparsed"):
                reader.parse(relative)
            for changes, error in ((dict(source_sha256="0" * 64), "source_hash"),
                                   (dict(path="inbox/ar/other.pdf"), "path_mismatch"),
                                   (dict(schema_version=999), "invalid_preparsed")):
                snapshot.write_text(json.dumps(document.to_dict() | changes))
                with self.assertRaisesRegex(ValueError, error):
                    reader.parse(relative)

    def test_complete_task_inventory_pending_and_face(self):
        self.assertEqual(self.billing_run.unresolved, ())
        self.assertEqual([r.item.id for r in self.billing_run.results], self.data.table("tasks/ar_billing_items"))
        self.assertEqual(Counter(r.decision.value for r in self.billing_run.results), {"INVOICE": 25, "SKIP_PENDING_APPROVAL": 1})
        self.assertEqual(sum(bool(r.invoice and r.invoice.face) for r in self.billing_run.results), 18)
        self.assertEqual(len(self.billing_run.pending_wip), 1)
        self.assertTrue(self.billing_run.pending_wip[0].evidence)

    def test_official_evaluator_and_unscored_invoice_details(self):
        evaluator_phase = Path(os.environ.get("KALMORA_EVALUATOR_PHASE", REAL))
        golden = evaluator_phase / "golden/ar_billing.jsonl"
        if not golden.is_file():
            self.skipTest("explicit development evaluator unavailable")
        scorer_path = Path(os.environ.get("KALMORA_SCORER", evaluator_phase.parent / "score.py"))
        spec = importlib.util.spec_from_file_location("official_score", scorer_path)
        scorer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(scorer)
        gold = [json.loads(line) for line in golden.read_text().splitlines() if line.strip()]
        rows = [to_row(r) for r in self.billing_run.results]
        self.assertEqual(scorer.score_ar_billing(gold, rows), (1.0, dict(items=26, answered=26)))
        by_id = {row["billing_item"]: row for row in rows}
        for g in gold:
            s = by_id[g["billing_item"]]
            if g["expected"] != "INVOICE":
                continue
            for field in ("date", "currency", "gross", "deductions"):
                self.assertEqual(s["invoice"][field], g["invoice"][field], (g["billing_item"], field))
            shape = lambda inv: Counter((x["amount"], x["account"], x.get("cost_center"), x.get("wbs")) for x in inv["lines"])
            self.assertEqual(shape(s["invoice"]), shape(g["invoice"]))
