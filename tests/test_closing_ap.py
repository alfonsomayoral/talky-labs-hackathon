import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kalmora import closing


def _phase(root: Path) -> Path:
    phase = root / "phase_dev"
    (phase / "tasks").mkdir(parents=True)
    (phase / "tasks" / "close.json").write_text(json.dumps({"month": "2026-07", "steps": []}), encoding="utf-8")
    return phase


class APEngineTest(unittest.TestCase):
    def test_m1_decisions_replace_v0_rows_and_the_rest_stay_v0(self):
        v0 = [{"doc_id": "A1", "decision": "POST"}, {"doc_id": "A2", "decision": "HOLD"}]
        m1 = {"A2": {"doc_id": "A2", "decision": "REJECT", "reasons": ["WRONG_ADDRESSEE"]}}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "out" / "ap.jsonl"
            target.parent.mkdir()
            notes = []
            with mock.patch("kalmora.v0.solve.solve_ap", return_value=(v0, 0)), \
                    mock.patch.object(closing, "_m1_rows", return_value=(m1, {"decided_count": 1})):
                stats = closing._ap(_phase(root), target, root, notes)
            rows = closing.read_rows(target)
        self.assertEqual([r["decision"] for r in rows], ["POST", "REJECT"])
        self.assertEqual(stats["engines"], {"m1": 1, "v0": 1})
        self.assertEqual({n["item"]: n["summary"] for n in notes if n["step"] == "engine"},
                         {"ap:A1": "Decidido por v0 (M1 no lo resolvió)", "ap:A2": "Decidido por M1 con evidencia"})

    def test_m1_failure_falls_back_to_v0_and_is_reported(self):
        v0 = [{"doc_id": "A1", "decision": "POST"}]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "out" / "ap.jsonl"
            target.parent.mkdir()
            with mock.patch("kalmora.v0.solve.solve_ap", return_value=(v0, 0)), \
                    mock.patch.object(closing, "_m1_rows", side_effect=ValueError("boom")):
                stats = closing._ap(_phase(root), target, root, [])
            self.assertEqual(closing.read_rows(target), v0)
        self.assertEqual(stats["engines"], {"m1": 0, "v0": 1})
        self.assertEqual(stats["m1_error"], "ValueError: boom")

    def test_posting_date_is_the_close_month_end_with_its_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            fact = closing._month_end_fact(_phase(Path(tmp)))
        self.assertEqual(fact.value, "2026-07-31")
        self.assertEqual((fact.evidence.document, fact.evidence.field, fact.evidence.quote),
                         ("tasks/close.json", "month", "2026-07"))


if __name__ == "__main__":
    unittest.main()
