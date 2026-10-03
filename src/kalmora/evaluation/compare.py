"""Per-entity comparison of a submission with the golden, one function per module.

Every function returns a module result with entities and a reconciliation block.
Averaged modules get their entity scores by calling the original scoring function
on a one-entity slice; set-based modules repeat the scorer's rule and are
reconciled against the original number. A mismatch is reported, never hidden.
"""
from collections import Counter, defaultdict
from types import ModuleType
from typing import Any

from .exceptions import KNOWN_EXCEPTIONS
from .explain import capped, diff, entry_diffs, explain_lines, status_of

Rows = list[dict[str, Any]]
Result = dict[str, Any]
TOLERANCE = 1e-9
POSTED = ("POST", "POST_PAYMENT_BLOCK")
AP_PARTS = ("header", "coding", "po_match", "journal_entry", "reasons", "payee_and_block")
AP_AMOUNTS = ("net", "tax", "gross", "withholding", "retention", "payable")


def _check(name: str, official: float, derived: float) -> dict[str, Any]:
    return {"name": name, "official": official, "derived": derived, "ok": abs(official - derived) <= TOLERANCE}


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 1.0


def _entity(module: str, ident: str, score: float | None, status: str, diffs: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    entity: dict[str, Any] = {"id": ident, "score": None if score is None else round(score, 6),
                              "status": status, "diffs": diffs}
    entity.update(extra)
    if (module, ident) in KNOWN_EXCEPTIONS and status != "exact":
        entity["notes"] = [KNOWN_EXCEPTIONS[module, ident]]
    return entity


def _unscored(pairs: list[tuple[str, Any, Any]]) -> list[dict[str, Any]]:
    """Differences in fields the official scorer ignores; they never change a score."""
    return [diff(field, expected, actual, "unscored") for field, expected, actual in pairs if expected != actual]


def _multiset(items: list[Any]) -> list[Any]:
    return sorted(items, key=repr)


def _missing(module: str, ident: str, score: float, field: str) -> dict[str, Any]:
    return _entity(module, ident, score, "missing", [diff(field, "present", None, "missing")])


def _module(score: float, entities: list[dict[str, Any]], extras: list[Any], checks: list[dict[str, Any]],
            total: int, **extra: Any) -> Result:
    counts = Counter(entity["status"] for entity in entities)
    result: Result = {"score": score, "entities": entities, "extra_rows": extras,
                      "status_counts": dict(counts), "total": total,
                      "unscored_differences": sum(len(e.get("unscored", [])) for e in entities),
                      "answered": total - counts.get("missing", 0),
                      "reconciliation": {"ok": all(check["ok"] for check in checks), "checks": checks}}
    result.update(extra)
    return result


def _index(rows: Rows, key: str) -> dict[Any, dict[str, Any]]:
    return {row.get(key): row for row in rows}


# ---------------------------------------------------------------------- AP
def _ap_applicable(g: dict[str, Any]) -> set[str]:
    parts: set[str] = set()
    if g["decision"] in POSTED:
        parts |= {"header", "coding"}
        if any(line.get("po") for line in g.get("lines", [])):
            parts.add("po_match")
        if g.get("journal_entry"):
            parts.add("journal_entry")
        if g.get("payee") or g.get("payment_block"):
            parts.add("payee_and_block")
    if (g["decision"] in ("HOLD", "REJECT", "POST_PAYMENT_BLOCK") and g.get("reasons")) or g["decision"] == "DUPLICATE":
        parts.add("reasons")
    return parts


def _ap_diffs(S: ModuleType, g: dict[str, Any], s: dict[str, Any], parts: dict[str, float]) -> list[dict[str, Any]]:
    diffs: list[dict[str, Any]] = []
    if s.get("decision") != g["decision"]:
        diffs.append(diff("decision", g["decision"], s.get("decision")))
    applicable = _ap_applicable(g)
    if "header" in applicable:
        for field in ("company", "vendor_id", "invoice_date"):
            if s.get(field) != g.get(field):
                diffs.append(diff(field, g.get(field), s.get(field)))
        if S.norm_num(s.get("invoice_number")) != S.norm_num(g.get("invoice_number")):
            diffs.append(diff("invoice_number", g.get("invoice_number"), s.get("invoice_number")))
        for field in AP_AMOUNTS:
            if not S.amount_ok(s.get(field), g.get(field)):
                diffs.append(diff(field, g.get(field), s.get(field)))
    if "reasons" in applicable:
        if g["decision"] == "DUPLICATE":
            if s.get("duplicate_of") != g.get("duplicate_of"):
                diffs.append(diff("duplicate_of", g.get("duplicate_of"), s.get("duplicate_of")))
        elif not set(g.get("reasons") or []) & set(s.get("reasons") or []):
            diffs.append(diff("reasons", g.get("reasons"), s.get("reasons")))
    if "payee_and_block" in applicable:
        if g.get("payee") and (s.get("payee") or {}).get("type") != g["payee"].get("type"):
            diffs.append(diff("payee", g["payee"], s.get("payee")))
        if g.get("payment_block") and s.get("payment_block") != g["payment_block"]:
            diffs.append(diff("payment_block", g["payment_block"], s.get("payment_block")))
    if "coding" in applicable and parts["coding"] < 1:
        keys = {(l.get("account"), l.get("cost_center"), l.get("wbs"), l.get("tax_code")) for l in s.get("lines", [])}
        lost = [{"account": l["account"], "cost_center": l.get("cost_center"), "wbs": l.get("wbs"),
                 "tax_code": l["tax_code"], "amount": l["amount"]}
                for l in g.get("lines", []) if (l["account"], l.get("cost_center"), l.get("wbs"), l["tax_code"]) not in keys]
        if lost:
            items, count = capped(lost)
            diffs.append(diff("lines.coding", items, None, "missing", count))
    if "po_match" in applicable and parts["po_match"] < 1:
        pos = {(l.get("po"), l.get("po_item")) for l in s.get("lines", []) if l.get("po")}
        lost_po = [{"po": l["po"], "po_item": l["po_item"], "amount": l["amount"]}
                   for l in g.get("lines", []) if l.get("po") and (l["po"], l["po_item"]) not in pos]
        if lost_po:
            items, count = capped(lost_po)
            diffs.append(diff("lines.po", items, None, "missing", count))
    if "journal_entry" in applicable:
        diffs += entry_diffs("journal_entry", explain_lines(S, g["journal_entry"], s.get("journal_entry"), g["company"]))
    return diffs


def compare_ap(S: ModuleType, gold: Rows, sub: Rows) -> Result:
    by_id = _index(sub, "doc_id")
    entities: list[dict[str, Any]] = []
    slices: list[dict[str, Any]] = []
    applicable: list[set[str]] = []
    confusion: Counter[tuple[str, str | None]] = Counter()
    for g in gold:
        s = by_id.get(g["doc_id"])
        score, parts = S.score_ap([g], [s] if s else [])
        slices.append(parts)
        applicable.append(_ap_applicable(g))
        confusion[g["decision"], (s or {}).get("decision")] += 1
        if s is None:
            entities.append(_missing("ap", g["doc_id"], score, "row"))
        else:
            diffs = _ap_diffs(S, g, s, parts)
            unscored = _unscored([("document_type", g.get("document_type"), s.get("document_type")),
                                  ("currency", g.get("currency"), s.get("currency")),
                                  ("action", g.get("action"), s.get("action")) if "action" in g else ("action", None, None),
                                  ("journal_entry.present", bool(g.get("journal_entry")), bool(s.get("journal_entry")))])
            entities.append(_entity("ap", g["doc_id"], score, status_of(score), diffs, decision=g["decision"], unscored=unscored))
    gold_ids = {g["doc_id"] for g in gold}
    extras = [row.get("doc_id") for row in sub if row.get("doc_id") not in gold_ids]
    official_score, official = S.score_ap(gold, sub)
    classes: list[str] = sorted({g["decision"] for g in gold} | {str(s["decision"]) for s in sub if s.get("decision")})
    tp: Counter[str] = Counter()
    fp: Counter[str] = Counter()
    fn: Counter[str] = Counter()
    for g in gold:
        sd = (by_id.get(g["doc_id"]) or {}).get("decision")
        if sd == g["decision"]:
            tp[g["decision"]] += 1
        else:
            fn[g["decision"]] += 1
            if sd:
                fp[sd] += 1
    macro = sum(S.f1(tp[c], fp[c], fn[c]) for c in classes) / max(1, len(classes))
    checks = [_check("ap.decision_macro_f1", official["decision_macro_f1"], macro)]
    for part in AP_PARTS:
        values = [parts[part] for parts, wanted in zip(slices, applicable) if part in wanted]
        checks.append(_check("ap." + part, official[part], _mean(values)))
    matrix = [{"golden": a, "submitted": b, "count": n} for (a, b), n in sorted(confusion.items(), key=lambda item: (item[0][0], item[0][1] or ''))]
    return _module(official_score, entities, extras, checks, len(gold),
                   decision_f1=official["per_decision_f1"], decision_confusion=matrix)


# ---------------------------------------------------------------------- AR billing
def compare_ar_billing(S: ModuleType, gold: Rows, sub: Rows) -> Result:
    by_id = _index(sub, "billing_item")
    entities, scores = [], []
    for g in gold:
        s = by_id.get(g["billing_item"])
        score = S.score_ar_billing([g], [s] if s else [])[0]
        scores.append(score)
        if s is None:
            entities.append(_missing("ar_billing", g["billing_item"], score, "row"))
            continue
        diffs: list[dict[str, Any]] = []
        if s.get("expected") != g["expected"]:
            diffs.append(diff("expected", g["expected"], s.get("expected")))
        elif g["expected"] == "INVOICE":
            gi, si = g["invoice"], s.get("invoice") or {}
            for field in ("tax_code", "due_date"):
                if si.get(field) != gi[field]:
                    diffs.append(diff("invoice." + field, gi[field], si.get(field)))
            for field in ("net", "tax", "retention", "payable"):
                if not S.amount_ok(si.get(field), gi[field]):
                    diffs.append(diff("invoice." + field, gi[field], si.get(field)))
            if gi.get("face") and any((si.get("face") or {}).get(k) != gi["face"].get(k)
                                      for k in ("oficina_contable", "organo_gestor", "unidad_tramitadora")):
                diffs.append(diff("invoice.face", gi["face"], si.get("face")))
            diffs += entry_diffs("journal_entry", explain_lines(S, g.get("journal_entry"), s.get("journal_entry"), g["company"]))
        unscored: list[dict[str, Any]] = []
        if g["expected"] == "INVOICE" and s.get("expected") == "INVOICE":
            gi, si = g["invoice"], s.get("invoice") or {}
            unscored = _unscored([
                ("invoice.date", gi.get("date"), si.get("date")),
                ("invoice.currency", gi.get("currency"), si.get("currency")),
                ("invoice.deductions", _multiset([(d.get("code"), d.get("amount"), d.get("account")) for d in gi.get("deductions") or []]),
                 _multiset([(d.get("code"), d.get("amount"), d.get("account")) for d in si.get("deductions") or []]))])
        entities.append(_entity("ar_billing", g["billing_item"], score, status_of(score), diffs, unscored=unscored))
    gold_ids = {g["billing_item"] for g in gold}
    extras = [r.get("billing_item") for r in sub if r.get("billing_item") not in gold_ids]
    official = S.score_ar_billing(gold, sub)[0]
    return _module(official, entities, extras, [_check("ar_billing.mean", official, _mean(scores))], len(gold))


# ---------------------------------------------------------------------- AR cash
def _counter_diffs(field: str, expected: Counter[Any], actual: Counter[Any]) -> list[dict[str, Any]]:
    diffs = []
    lost, added = expected - actual, actual - expected
    if lost:
        items, count = capped([{"ref": k[0], "amount": k[1], "n": n} for k, n in lost.items()])
        diffs.append(diff(field, items, None, "missing", count))
    if added:
        items, count = capped([{"ref": k[0], "amount": k[1], "n": n} for k, n in added.items()])
        diffs.append(diff(field, None, items, "extra", count))
    return diffs


def compare_ar_cash(S: ModuleType, gold: Rows, sub: Rows) -> Result:
    by_id = _index(sub, "bank_line")
    entities, scores = [], []
    for g in gold:
        s = by_id.get(g["bank_line"])
        score = S.score_ar_cash([g], [s] if s else [])[0]
        scores.append(score)
        if s is None:
            entities.append(_missing("ar_cash", g["bank_line"], score, "row"))
            continue
        diffs: list[dict[str, Any]] = []
        if s.get("customer") != g["customer"]:
            diffs.append(diff("customer", g["customer"], s.get("customer")))
        ga = Counter((a.get("invoice") or a.get("pagare"), a["amount"]) for a in g["applications"])
        sa = Counter((a.get("invoice") or a.get("pagare"), int(a.get("amount") or 0)) for a in s.get("applications", []))
        diffs += _counter_diffs("applications", ga, sa)
        gr = Counter((r["type"], r["amount"]) for r in g["residuals"])
        sr = Counter((r.get("type"), int(r.get("amount") or 0)) for r in s.get("residuals", []))
        diffs += _counter_diffs("residuals", gr, sr)
        diffs += entry_diffs("adjustment", explain_lines(S, g["adjustment"], s.get("adjustment") or [], g["company"]))
        unscored = _unscored([("residuals.invoice", _multiset([(r["type"], r.get("invoice")) for r in g["residuals"]]),
                               _multiset([(r.get("type"), r.get("invoice")) for r in s.get("residuals", [])]))])
        entities.append(_entity("ar_cash", g["bank_line"], score, status_of(score), diffs, unscored=unscored))
    gold_ids = {g["bank_line"] for g in gold}
    extras = [r.get("bank_line") for r in sub if r.get("bank_line") not in gold_ids]
    official = S.score_ar_cash(gold, sub)[0]
    return _module(official, entities, extras, [_check("ar_cash.mean", official, _mean(scores))], len(gold))


# ---------------------------------------------------------------------- bank reconciliation
def compare_bank(S: ModuleType, gold: Rows, sub: Rows) -> Result:
    by_id = _index(sub, "account")
    entities, scores = [], []
    for g in gold:
        s = by_id.get(g["account"])
        score = S.score_bank([g], [s] if s else [])[0]
        scores.append(score)
        if s is None:
            entities.append(_missing("bank_rec", g["account"], score, "row"))
            continue
        gp = {(b, k) for m in g["matches"] for b in m["bank_lines"] for k in m["book_lines"]}
        sp = {(b, k) for m in s.get("matches", []) for b in m.get("bank_lines", []) for k in m.get("book_lines", [])}
        diffs: list[dict[str, Any]] = []
        for kind, pairs in (("missing", sorted(gp - sp)), ("extra", sorted(sp - gp))):
            if pairs:
                items, count = capped([{"bank_line": b, "book_line": k} for b, k in pairs])
                diffs.append(diff("matches", items if kind == "missing" else None, items if kind == "extra" else None, kind, count))
        gu = {("B", x["bank_line"]): x["category"] for x in g["unmatched_bank"]} | {("L", x["book_line"]): x["category"] for x in g["unmatched_book"]}
        su = {("B", x.get("bank_line")): x.get("category") for x in s.get("unmatched_bank", [])} | {("L", x.get("book_line")): x.get("category") for x in s.get("unmatched_book", [])}
        for kind, keys in (("missing", [k for k in gu if k not in su]), ("extra", [k for k in su if k not in gu])):
            if keys:
                source = gu if kind == "missing" else su
                items, count = capped([{"side": k[0], "line": k[1], "category": source[k]} for k in keys])
                diffs.append(diff("unmatched", items if kind == "missing" else None, items if kind == "extra" else None, kind, count))
        wrong = [{"side": k[0], "line": k[1], "expected": v, "actual": su[k]} for k, v in gu.items() if k in su and su[k] != v]
        if wrong:
            items, count = capped(wrong)
            diffs.append(diff("unmatched.category", items, None, "mismatch", count))
        gadj = [l for a in g["adjustments"] for l in a["lines"]]
        sadj = [l for a in s.get("adjustments", []) for l in a.get("lines", [])]
        diffs += entry_diffs("adjustments", explain_lines(S, gadj, sadj, g["company"]))
        unscored = _unscored([("adjustments.category", _multiset([a["category"] for a in g["adjustments"]]),
                               _multiset([a.get("category") for a in s.get("adjustments", [])])),
                              ("company", g["company"], s.get("company"))])
        entities.append(_entity("bank_rec", g["account"], score, status_of(score), diffs, company=g["company"], unscored=unscored))
    gold_ids = {g["account"] for g in gold}
    extras = [r.get("account") for r in sub if r.get("account") not in gold_ids]
    official = S.score_bank(gold, sub)[0]
    return _module(official, entities, extras, [_check("bank_rec.mean", official, _mean(scores))], len(gold))


# ---------------------------------------------------------------------- intercompany
def compare_ic(S: ModuleType, gold: Rows, sub: Rows) -> Result:
    gk = {(tuple(sorted(g["pair"])), g["cause"]): g for g in gold}
    sk = {(tuple(sorted(s.get("pair", []))), s.get("cause")): s for s in sub}
    entities, adjustments = [], []
    for key, g in gk.items():
        ident = f"{'-'.join(key[0])}:{key[1]}"
        s = sk.get(key)
        if s is None:
            adjustments.append(0.0)
            entities.append(_missing("ic", ident, 0.0, "row"))
            continue
        explanation = explain_lines(S, g["adjustment"], s.get("adjustment") or [], None)
        adjustments.append(explanation["score"])
        diffs = entry_diffs("adjustment", explanation)
        unscored = _unscored([("amount", g.get("amount"), s.get("amount")),
                              ("responsible", g.get("responsible"), s.get("responsible"))])
        entities.append(_entity("ic", ident, explanation["score"], status_of(explanation["score"]), diffs, unscored=unscored))
    extras = [f"{'-'.join(k[0])}:{k[1]}" for k in sk if k not in gk]
    tp = len(set(gk) & set(sk))
    detection = S.f1(tp, len(set(sk) - set(gk)), len(set(gk) - set(sk)))
    derived = 0.6 * detection + 0.4 * _mean(adjustments)
    official = S.score_ic(gold, sub)[0]
    return _module(official, entities, extras, [_check("ic.total", official, derived)], len(gold))


# ---------------------------------------------------------------------- close
def _close_amount(row: dict[str, Any]) -> int:
    return 1 if row.get("type") == "DOUBTFUL_RECLASS" else int(row.get("amount") or 0)


def compare_close(S: ModuleType, gold: Rows, sub: Rows) -> Result:
    G: dict[Any, int] = defaultdict(int)
    S_: dict[Any, int] = defaultdict(int)
    grows: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    srows: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for g in gold:
        G[S.close_key(g)] += _close_amount(g)
        grows[S.close_key(g)].append({"je": g.get("je"), "period": g.get("period"), "amount": g.get("amount")})
    for s in sub:
        S_[S.close_key(s)] += _close_amount(s)
        srows[S.close_key(s)].append({"amount": s.get("amount"), "has_entry": bool(s.get("journal_entry"))})
    entities, hits = [], 0.0
    for key, expected in G.items():
        ident = "|".join(str(part) for part in key)
        if key not in S_:
            entities.append(_entity("close", ident, 0.0, "missing", [diff("amount", expected, None, "missing")],
                                    golden_rows=grows[key]))
            continue
        tolerance = 0.15 if key[0] == "ACCRUAL" else 0.0
        delta = abs(S_[key] - expected)
        if delta <= max(100, abs(expected) * tolerance):
            score, status = 1.0, "exact"
        elif delta <= abs(expected) * 0.5:
            score, status = 0.4, "partial"
        else:
            score, status = 0.0, "miss"
        hits += score
        diffs = [] if status == "exact" else [diff("amount", expected, S_[key], "mismatch")]
        unscored = _unscored([("rows", len(grows[key]), len(srows[key])),
                              ("journal_entry.present", True, all(r["has_entry"] for r in srows[key]))])
        entities.append(_entity("close", ident, score, status, diffs, golden_rows=grows[key], submitted_rows=srows[key],
                                unscored=unscored))
    extras = ["|".join(str(part) for part in key) for key in S_ if key not in G]
    derived = S.f1(hits, len(S_) - hits, len(G) - hits) if G or S_ else 1.0
    official = S.score_close(gold, sub)[0]
    return _module(official, entities, extras, [_check("close.f1", official, derived)], len(G),
                   golden_rows=len(gold), submitted_rows=len(sub))


# ---------------------------------------------------------------------- trial balance
def compare_tb(S: ModuleType, evaluator_dir: str, subs: dict[str, Rows]) -> Result:
    truth = {(r["company"], r["account"]): r["balance"] for r in S.load(f"{evaluator_dir}/golden/trial_balance_truth.jsonl")}
    recorded = {(r["company"], r["account"]): r["balance"] for r in S.load(f"{evaluator_dir}/golden/trial_balance_recorded.jsonl")}
    team: dict[Any, int] = defaultdict(int, recorded)
    for name, rows in subs.items():
        for r in rows:
            entries: list[tuple[Any, Any]] = []
            if name in ("ap", "ar_billing") and r.get("journal_entry"):
                entries.append((r.get("company"), r["journal_entry"]))
            if name in ("ar_cash", "ic") and r.get("adjustment"):
                entries.append((r.get("company"), r["adjustment"]))
            if name == "bank_rec":
                for a in r.get("adjustments", []):
                    entries.append((r.get("company"), a.get("lines", [])))
            if name == "close" and r.get("journal_entry"):
                entries.append((r.get("company"), r["journal_entry"]))
            for company, entry in entries:
                for c, account, amount, *_ in S.je_lines(entry, company):
                    team[(c, account)] += amount
    keys = set(truth) | set(team)
    diff_total = sum(abs(truth.get(k, 0) - team.get(k, 0)) for k in keys)
    base = sum(abs(truth.get(k, 0) - recorded.get(k, 0)) for k in keys) or 1
    entities = []
    for key in sorted(keys):
        if truth.get(key, 0) == team.get(key, 0):
            continue
        entities.append({"id": f"{key[0]}/{key[1]}", "score": None, "status": "differs",
                         "truth": truth.get(key, 0), "recorded": recorded.get(key, 0),
                         "submission": team.get(key, 0), "delta": team.get(key, 0) - truth.get(key, 0),
                         "diffs": [diff("balance", truth.get(key, 0), team.get(key, 0))]})
    needing = sum(1 for k in keys if truth.get(k, 0) != recorded.get(k, 0))
    official_score, official = S.score_tb(evaluator_dir, subs)
    derived = max(0.0, 1 - diff_total / base)
    checks = [_check("trial_balance.score", official_score, derived),
              _check("trial_balance.abs_difference_eur", official["abs_difference_eur"], round(diff_total / 100, 2))]
    return _module(official_score, entities, [], checks, len(keys),
                   keys_needing_adjustment=needing, keys_still_different=len(entities),
                   abs_difference_cents=diff_total, recorded_vs_truth_cents=base)
