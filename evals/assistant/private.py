"""Real-data cases, generated locally from a competition phase directory (never committed: the repository is public).

    python -m evals.assistant run --private <participant>/phase_dev --run-dir <server run dir> --live-mcp http://127.0.0.1:8000/mcp/

The entities each question is about are sampled from the data with a fixed rule, the expected values are computed by
the oracles from the same files, and the run bundles the B cases need are written to ``--run-dir`` (the folder the
API process reads) as a stand-in for the future orchestrator: they copy the golden. The assistant never sees the golden."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from kalmora.assistant.model import Step
from kalmora.bundle import RunBundle
from kalmora.knowledge import parse_policy

from . import graders as g
from .cases import BASE, Case, Params, T, build_cases, es, no_money_amounts, order
from .oracles import Data, deliverable


def sample_params(data: Data) -> Params:
    by_entries = Counter(e["company"] for e in data.journal)
    local = [c for c, v in data.companies.items() if v["currency"] == "EUR"]
    foreign = next(c for c, v in data.companies.items() if v["currency"] != "EUR")
    cost_centers: dict[str, list[str]] = {}
    for row in (data.dir / "erp/cost_centers.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(row)
        cost_centers.setdefault(r["company"], []).append(r["id"])
    cash = Counter(a for (c, a), v in data.balances.items() if a.startswith("572") and c in local and v != 0)
    account = next(a for a, n in cash.most_common() if n >= 2)
    holders = [c for c in sorted(local, key=lambda c: -by_entries[c]) if data.balances.get((c, account))]
    entry_company = next(c for c in holders if c in cost_centers)
    company2 = next(c for c in holders if c != entry_company)
    bank = max((b for b in data.bank_accounts.values() if b["currency"] == "EUR"), key=lambda b: len(data.bank_lines(b["id"])))
    lines = sorted((l["amount"] for l in data.bank_lines(bank["id"]) if l["amount"] > 0), reverse=True)
    threshold = lines[min(5, len(lines) - 1)] // 100_000 * 100_000 or 100_000
    expense = next(l["account"] for e in data.journal if e["company"] == entry_company for l in e["lines"]
                   if l["account"].startswith("6") and l.get("cost_center"))
    open_key = next(k for k, v in data.open_items.items() if k[1].startswith("400") and k[2] and k[3] and v != 0 and
                    sum(1 for kk in data.open_items if kk[:3] == k[:3]) == 1)
    usd = sorted({r["date"] for r in data.fx if r["currency"] == "USD"})
    published = set(usd)
    gap = next(d for d, nxt in zip(usd, usd[1:]) if nxt > d and (day := __import__("datetime").date.fromisoformat(d) + __import__("datetime").timedelta(days=1)).isoformat() not in published and d > "2026-01-01")
    gap_day = (__import__("datetime").date.fromisoformat(gap) + __import__("datetime").timedelta(days=1)).isoformat()
    month = data.tasks["close"]["month"]
    return Params(company=entry_company, company2=company2, foreign_company=foreign, foreign_currency=data.companies[foreign]["currency"],
                  bank_company=bank["company"], bank_gl=bank["gl_account"], bank_account=bank["id"], open_company=open_key[0],
                  open_account=open_key[1], vendor=open_key[2], entry_company=entry_company, fx_currency="USD", fx_gap_day=gap_day,
                  money_threshold=threshold, month=month, phase=data.dir.name, tol_pct="2", tol_eur="150", real_policy=True,
                  cost_center=cost_centers[entry_company][0], expense_account=expense, cash_account=account, cash_company2=company2)


def make_runs(phase_dir: Path, run_dir: Path) -> dict[str, str]:
    """Stand-in bundles built from the golden (the assistant is never given the golden itself)."""
    golden = phase_dir / "golden"
    if not golden.is_dir():
        raise SystemExit(f"{golden} not found: the stand-in runs for the B cases are built from it")
    ids = {"full": "00000000-1111-0000-0000-000000000001", "notrace": "00000000-1111-0000-0000-000000000002",
           "running": "00000000-1111-0000-0000-000000000003", "failed": "00000000-1111-0000-0000-000000000004",
           "nobank": "00000000-1111-0000-0000-000000000005"}
    base = {"dataset": phase_dir.name, "month": json.loads((phase_dir / "tasks/close.json").read_text())["month"]}
    rows = {t: [json.loads(l) for l in (golden / f"{t}.jsonl").read_text().splitlines() if l.strip()] for t in ("ap", "ar_billing", "ar_cash", "bank_rec", "ic", "close")}
    for name, run_id in ids.items():
        b = RunBundle(run_dir / run_id)
        b.manifest(run_id=run_id, status={"running": "running", "failed": "failed"}.get(name, "completed"), started_at="2026-10-03T10:00:00Z",
                   exit_code=1 if name == "failed" else 0, **base, **({"cost_usd_total": 0.42, "models": [{"provider": "stand-in", "name": "copy-golden", "calls": 0}]} if name == "full" else {}),
                   **({"error": "The command exited 1."} if name == "failed" else {}))
        if name in ("full", "notrace", "nobank"):
            for task, data in rows.items():
                if not (name == "nobank" and task == "bank_rec"):
                    b.write_deliverable(task, data)
        if name == "full":
            holds = [r for r in rows["ap"] if r["decision"] == "HOLD"]
            for r in rows["ap"][:60]:
                b.event(f"ap:{r['doc_id']}", "DECIDE", result="INFO", summary=f"Decisión {r['decision']}", confidence=0.9)
            if holds:
                b.attention(f"ap:{holds[0]['doc_id']}", "AGENT_DOUBT", "P1", "Revisar la retención", policy_ref="§2.2.3")
            if len(holds) > 1:
                b.attention(f"ap:{holds[1]['doc_id']}", "POLICY_EXCEPTION", "P2", "Revisar la segunda retención")
    return ids


def real_policy_cases(p: Params) -> list[Case]:
    nt = [*BASE, g.no_tools(), g.policy_refs_valid()]
    return [
        Case("C15", "C", "¿Qué retención de garantía se aplica?", [*nt, g.rubric([("5 ?%", "5 por ciento"), "garant", "obra"], 1.0), g.cites_policy("§2.3")], needs=("real-policy",)),
        Case("C16", "C", "¿Qué se provisiona como deterioro de clientes?", [*nt, g.rubric(["180", "365", ("50 ?%", "50 por ciento"), ("100 ?%", "100 por ciento")], 0.75), g.cites_policy("§5")], needs=("real-policy",)),
        Case("C17", "C", "¿Qué es el 5 al millar en México?", [*nt, g.rubric([("0,5 ?%", "0.5 ?%", "0,5 por ciento", "medio por ciento"), "63100000"], 1.0), g.cites_policy("§3.1")], needs=("real-policy",)),
        Case("C18", "C", "¿Qué pasa si un cliente paga menos de lo que debe sin motivo conocido?", [*nt, g.rubric(["parcial", ("resto", "abiert", "pendiente")], 1.0), g.cites_policy("§3.2")], needs=("real-policy",)),
        Case("C04r", "C", "¿A qué tipo de cambio se convierte una factura en divisa?", [*nt, g.rubric(["SYN-BCE", ("fecha de la factura", "fecha factura", "d[ií]a de la factura")], 1.0), g.cites_policy("§1")], needs=("real-policy",))]


def private_b_cases(data: Data, run_dir: Path, runs: dict[str, str]) -> list[Case]:
    full, notrace, running, failed, nobank = (runs[k] for k in ("full", "notrace", "running", "failed", "nobank"))
    ap = deliverable(run_dir, full, "ap")
    holds = [r for r in ap if r["decision"] == "HOLD"]
    reasons = Counter(code for r in ap for code in r.get("reasons") or [])
    common = lambda *extra: [*BASE, g.no_repeated_calls(), *extra]
    cases = [
        Case("B01", "B", "¿Cómo ha ido el cierre?", common(g.says_number(len(ap)), g.says_any("completad", "terminad", "finalizad", "completed"), g.max_calls(3)), run="full", star=True),
        Case("B03", "B", "¿Cuántas facturas se han retenido y por qué motivos?",
             common(g.says_number(len(holds)), *[g.says_all(code) for code, _ in reasons.most_common(2)], g.queried_at_most("query_journal", 0), g.max_calls(3)), run="full", star=True),
        Case("B07", "B", "Resume el cierre", common(g.says_any("en curso", "running", "sigue ejecut", "todavía", "aún", "no ha terminado"), no_money_amounts()), run="running", star=True),
        Case("B08", "B", "Resume el cierre", common(g.says_any("fall", "failed", "error"), no_money_amounts()), run="failed"),
        Case("B09", "B", "¿Qué entregables hay?", common(g.says_all("bank_rec"), g.says_any("falta", "no hay", "ausente", "no se ha", "no existe", "no consta", "no está", name="absent")), run="nobank", star=True),
        Case("B11", "B", "¿Cuánto ha costado este cierre?", common(g.says_any("0,42", "0.42")), run="full"),
        Case("J01", "J", "¿Por qué se retuvo ap:%s?" % (holds[0]["doc_id"] if holds else "X"), common(g.says_any("sin traza", "no hay traza", "no consta traza", "no dej", "se infiere", "derivad", "fila entregada", "no se registr", "probablemente", name="honest_about_trace")), run="notrace", star=True)]
    if holds:
        h = holds[0]
        cases.append(Case("B04", "B", f"¿Por qué se retuvo ap:{h['doc_id']}?", common(*[g.says_all(code) for code in (h.get("reasons") or [])[:2]], g.cites_policy("§2.2"), g.policy_refs_valid(), g.calls("get_run_item")), run="notrace", star=True))
        cases.append(Case("B02", "B", "¿Qué debo revisar primero?", common(order(f"ap:{holds[0]['doc_id']}", f"ap:{holds[1]['doc_id']}") if len(holds) > 1 else g.says_ids([f"ap:{h['doc_id']}"]), g.calls("list_run_attention")), run="full", star=True))
    return cases


def private_environment(phase_dir: Path, run_dir: Path | None, live_url: str | None):
    from .run import Environment
    if run_dir is None or live_url is None:
        raise SystemExit("--private needs --run-dir (the API's run folder) and --live-mcp")
    phase_dir = Path(phase_dir)
    data = Data(phase_dir)
    params = sample_params(data)
    runs = make_runs(phase_dir, Path(run_dir))
    cases = [c for c in build_cases(data, params, Path(run_dir), None) if c.suite not in ("F",) and c.world == "base" and c.dataset == params.phase and c.id not in ("J02",) or c.id == "J02"]
    cases = [c for c in cases if not (c.suite == "B" or c.id in ("J01", "J06", "A10"))]
    cases += private_b_cases(data, Path(run_dir), runs) + real_policy_cases(params)
    for c in cases:
        c.dataset = params.phase if c.dataset not in (None, "phase_test") else c.dataset
    env = Environment(data, params, runs, Path(run_dir), {}, live_url=live_url)
    env.valid_refs = set(parse_policy((phase_dir.parent / "POLITICAS_CONTABLES.md").read_text(encoding="utf-8"))["anchors"])
    return env, cases
