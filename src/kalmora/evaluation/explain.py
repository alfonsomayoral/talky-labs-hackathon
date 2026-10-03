"""Line-level explanation of the scorer's journal-entry matching."""
from collections import defaultdict
from types import ModuleType
from typing import Any

CAP = 25


def diff(field: str, expected: Any, actual: Any, kind: str = "mismatch", count: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"field": field, "expected": expected, "actual": actual, "kind": kind}
    if count is not None:
        result["count"] = count
    return result


def capped(items: list[Any]) -> tuple[list[Any], int]:
    return items[:CAP], len(items)


def status_of(score: float) -> str:
    if score >= 1 - 1e-9:
        return "exact"
    return "miss" if score <= 0 else "partial"


def _view(line: tuple[Any, ...]) -> dict[str, Any]:
    account, amount, partner, cost_center, wbs = line
    return {"account": account, "amount": amount, "partner": partner, "cost_center": cost_center, "wbs": wbs}


def explain_lines(scorer: ModuleType, gold: Any, sub: Any, company: str | None, tolerance: int = 2) -> dict[str, Any]:
    """Repeat ``je_match`` greedy matching and keep the lines that did not match.

    The score equals ``scorer.je_match``; callers reconcile the two.
    """
    expected = [scorer.norm_line(a, amt, p, cc, w) for _, a, amt, p, cc, w in scorer.je_lines(gold, company)]
    actual = [scorer.norm_line(a, amt, p, cc, w) for _, a, amt, p, cc, w in scorer.je_lines(sub, company)]
    if not expected and not actual:
        return {"score": 1.0, "missing": [], "extra": []}
    pool: dict[tuple[Any, ...], list[tuple[Any, ...]]] = defaultdict(list)
    for line in actual:
        pool[(line[0], line[2], line[3], line[4])].append(line)
    missing: list[dict[str, Any]] = []
    hits = 0
    for line in expected:
        candidates = pool.get((line[0], line[2], line[3], line[4]), [])
        best = min(candidates, key=lambda c: abs(c[1] - line[1]), default=None)
        if best is not None and abs(best[1] - line[1]) <= tolerance:
            candidates.remove(best)
            hits += 1
        else:
            missing.append(_view(line))
    extra = [_view(line) for lines in pool.values() for line in lines]
    return {"score": hits / max(len(expected), len(actual)), "missing": missing, "extra": extra}


def entry_diffs(field: str, explanation: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    if explanation["missing"]:
        items, count = capped(explanation["missing"])
        result.append(diff(field + ".lines", items, None, "missing", count))
    if explanation["extra"]:
        items, count = capped(explanation["extra"])
        result.append(diff(field + ".lines", None, items, "extra", count))
    return result
