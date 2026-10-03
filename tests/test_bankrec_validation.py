from collections import Counter
from dataclasses import replace
import importlib.util
import json
import os
from pathlib import Path
import unittest

from kalmora.bankrec import Category, build_bank_rec, to_row
from kalmora.bankrec import adjust as adj
from kalmora.bankrec.book import load_book
from kalmora.bankrec.model import Difference
from kalmora.bankrec.statements import read_statements
from kalmora.bankrec.validate import reconciliation
from kalmora.data import PhaseData
from kalmora.documents.contracts import ParsedDocument, digest
from test_bankrec_run import SyntheticPhase
from test_bankrec_adjust import builder
from bankrec_support import bank

REAL = Path(os.environ.get("KALMORA_PHASE_DEV", Path(__file__).resolve().parents[1] / "participant/phase_dev"))


class ValidationTests(SyntheticPhase):
    def validate(self, result, statement_changes=None):
        data = PhaseData(self.root)
        statements = read_statements(data, result.account, "2026-07")
        books, _, _ = load_book(data, [result.account], "2026-06", "2026-07-31")
        statement = statements[-1]
        if statement_changes:
            statement = replace(statement, **statement_changes)
        return reconciliation(result, statement, {x.id: x for s in statements for x in s.lines},
                              {x.id: x for x in books[result.account.id]})

    def test_detects_reuse_coverage_currency_balance_and_unexplained_difference(self):
        results, _ = self.run_july()
        r = results["BIN-1100"]
        self.assertEqual(self.validate(r), [])
        variants = [replace(r, matches=r.matches * 2), replace(r, unmatched_bank=()),
                    replace(r, statement_opening=r.statement_opening + 1),
                    replace(r, matches=(replace(r.matches[0], difference=Difference(Category.FX_RATE_DIFFERENCE, 1)),))]
        for bad in variants:
            self.assertTrue(self.validate(bad))
        self.assertTrue(self.validate(r, dict(lines=tuple(replace(x, currency="USD") for x in read_statements(PhaseData(self.root), r.account, "2026-07")[-1].lines))))

    def test_all_invalid_statements_return_unresolved_instead_of_crashing(self):
        for path in (self.root / "bank").glob("*/*.n43"):
            path.write_text("broken")
        _, run = self.run_july()
        self.assertEqual((len(run.results), len(run.unresolved)), (0, 2))

    def test_returned_fee_cannot_be_consumed_twice(self):
        b = builder(receipts={"RC1": "C1", "RC2": "C2"})
        adj.returned(b, [bank("B1", "2026-07-14", -100, "DEVOLUCION RECIBO", receipt="RC1"),
                         bank("B2", "2026-07-14", -200, "DEVOLUCION RECIBO", receipt="RC2"),
                         bank("B3", "2026-07-14", -10, "COMISION DEVOLUCION RECIBO")])
        self.assertEqual(len(b.out), 2)
        self.assertEqual(Counter(k for a in b.out for k in a.causes), {"B1": 1, "B2": 1, "B3": 1})
        self.assertEqual(sum(x.debit for a in b.out for x in a.lines if x.account == "62600000"), 10)


@unittest.skipUnless((REAL / "bank").is_dir(), "development source package unavailable")
class JulyValidationTests(unittest.TestCase):
    def test_normalized_bank_snapshots_are_bound_to_all_originals(self):
        normalized = Path(os.environ.get("KALMORA_NORMALIZED_SOURCES", REAL.parent / "normalized_sources"))
        count = 0
        for source in (REAL / "bank").glob("*/*"):
            if source.suffix not in {".n43", ".xml", ".csv"}:
                continue
            relative = source.relative_to(REAL).as_posix()
            snapshot = normalized / REAL.name / (relative + ".json")
            doc = ParsedDocument.from_dict(json.loads(snapshot.read_text()))
            self.assertEqual(doc.source_sha256, digest(source.read_bytes()), relative)
            self.assertIn(doc.path, {relative, f"{REAL.name}/{relative}"})
            self.assertTrue(doc.blocks)
            count += 1
        self.assertEqual(count, 48)

    def test_scorer_and_exact_category_comparison_document_only_three_source_charges(self):
        data = PhaseData(REAL)
        run = build_bank_rec(data)
        self.assertEqual([d for r in run.results for d in r.diagnostics if d.startswith(("validation:", "identity:"))], [])
        phase = Path(os.environ.get("KALMORA_EVALUATOR_PHASE", REAL))
        if not (phase / "golden/bank_rec.jsonl").is_file():
            self.skipTest("explicit development evaluator unavailable")
        spec = importlib.util.spec_from_file_location("official_score", os.environ.get("KALMORA_SCORER", phase.parent / "score.py"))
        scorer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(scorer)
        gold = [json.loads(x) for x in (phase / "golden/bank_rec.jsonl").read_text().splitlines() if x.strip()]
        rows = [to_row(r) for r in run.results]
        self.assertAlmostEqual(scorer.score_bank(gold, rows)[0], 0.9951178451178451)
        by_id = {r["account"]: r for r in rows}
        def adjustments(row):
            return Counter((row["account"], a["category"], x["account"], x["debit"] - x["credit"],
                            x.get("partner"), x.get("cost_center"), x.get("wbs"))
                           for a in row["adjustments"] for x in a["lines"])
        extra, missing = Counter(), Counter()
        for g in gold:
            s = by_id[g["account"]]
            groups = lambda row: Counter((tuple(sorted(m["bank_lines"])), tuple(sorted(m["book_lines"]))) for m in row["matches"])
            self.assertEqual(groups(s), groups(g))
            for key, ref in (("unmatched_bank", "bank_line"), ("unmatched_book", "book_line")):
                self.assertEqual({x[ref]: x["category"] for x in s[key]}, {x[ref]: x["category"] for x in g[key]})
            extra.update(adjustments(s) - adjustments(g))
            missing.update(adjustments(g) - adjustments(s))
        expected = Counter()
        for account, vendor, amount in (("CMA-1100", "V100028", 107141), ("CMA-1100", "V100028", 215748),
                                         ("CMA-1200", "V100039", 264496)):
            expected[(account, "DIRECT_DEBIT_NOT_BOOKED", "41000000", amount, vendor, None, None)] += 1
            expected[(account, "DIRECT_DEBIT_NOT_BOOKED", "57200002", -amount, None, None, None)] += 1
        self.assertEqual(missing, Counter())
        self.assertEqual(extra, expected)
