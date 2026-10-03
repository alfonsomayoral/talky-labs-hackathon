"""Submission diagnostics the official score does not report.

They never change a score. Checks that need the golden are skipped when it is not
provided (``--structure-only``).
"""
import calendar
from typing import Any, cast

from ..model.journal_entry import JournalEntry
from ..validation import validate_entry

Rows = list[dict[str, Any]]
ID_FIELDS = {"ap": "doc_id", "ar_billing": "billing_item", "ar_cash": "bank_line", "bank_rec": "account"}
AMOUNT_FIELDS = {"ap": ("net", "tax", "gross", "withholding", "retention", "payable"),
                 "ar_billing": (), "ar_cash": ("amount",), "bank_rec": (), "ic": ("amount",), "close": ("amount",)}


def _diagnostic(module: str, entity: Any, code: str, severity: str, message: str, **detail: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"module": module, "entity": entity, "code": code, "severity": severity, "message": message}
    if detail:
        result["detail"] = detail
    return result


def row_id(module: str, row: dict[str, Any]) -> Any:
    if module == "ic":
        pair, cause = row.get("pair"), row.get("cause")
        return f"{'-'.join(sorted(pair))}:{cause}" if isinstance(pair, list) and cause else None
    if module == "close":
        target = next((row[k] for k in ("vendor", "invoice", "item", "customer", "billing_item") if row.get(k)), None)
        return f"{row.get('type')}|{row.get('company')}|{target}" if row.get("type") else None
    return row.get(ID_FIELDS[module])


def entries_of(module: str, row: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Return the submitted journal entries of one row as ``(label, {company, lines})``."""
    if module in ("ap", "ar_billing", "close"):
        entry = row.get("journal_entry")
        return [("journal_entry", entry)] if isinstance(entry, dict) else []
    if module in ("ar_cash", "ic"):
        lines = row.get("adjustment")
        pairs: list[tuple[str, Any]] = [("adjustment", lines)] if isinstance(lines, list) else []
    else:
        pairs = [(f"adjustments[{i}]", a.get("lines")) for i, a in enumerate(row.get("adjustments") or [])
                 if isinstance(a, dict) and isinstance(a.get("lines"), list)]
    result = []
    for label, lines in pairs:
        if not lines:  # the golden has valid empty adjustments
            continue
        first = next((l.get("company") for l in lines if isinstance(l, dict) and l.get("company")), None)
        result.append((label, {"company": row.get("company") or first, "lines": lines}))
    return result


def phase_ids(phase: Any, journal_ids: set[str]) -> dict[str, set[str]]:
    """Identities available in the solver inputs, for attribution checks."""
    tasks = phase.tasks
    bank_lines = {row.get("bank_line") for row in phase.table("bank_lines")}
    return {"ap": set(tasks.get("ap_documents", [])), "ar_billing": set(tasks.get("ar_billing_items", [])),
            "ar_cash": set(tasks.get("ar_receipts", [])), "bank_rec": set(tasks.get("bank_accounts", [])),
            "journal": journal_ids, "bank_line": {b for b in bank_lines if b}}


def check_submission(subs: dict[str, Rows], month: str, ids: dict[str, set[str]],
                     gold: dict[str, Rows] | None = None) -> list[dict[str, Any]]:
    year, number = (int(part) for part in month.split("-"))
    month_end = f"{month}-{calendar.monthrange(year, number)[1]:02d}"
    gold_company = {module: {row_id(module, g): g.get("company") for g in rows} for module, rows in (gold or {}).items()}
    found: list[dict[str, Any]] = []
    for module, rows in subs.items():
        seen: set[Any] = set()
        for row in rows:
            ident = row_id(module, row)
            if ident is None:
                found.append(_diagnostic(module, None, "ROW_KEY_MISSING", "error", "row has no identifying key"))
                continue
            if ident in seen and module != "close":
                found.append(_diagnostic(module, ident, "DUPLICATE_ROW", "warning", "id repeated; the scorer keeps the last row"))
            seen.add(ident)
            if module in ID_FIELDS and ident not in ids[module]:
                found.append(_diagnostic(module, ident, "UNKNOWN_ENTITY", "error", "id does not exist in the phase inputs"))
            for field in AMOUNT_FIELDS[module]:
                if field in row and row[field] is not None and type(row[field]) is not int:
                    found.append(_diagnostic(module, ident, "NON_INTEGER_AMOUNT", "warning",
                                             f"{field} must be integer cents; the scorer coerces it silently", value=row[field]))
            if module == "bank_rec":
                for match in row.get("matches") or []:
                    for book in match.get("book_lines") or []:
                        if str(book).split("#")[0] not in ids["journal"]:
                            found.append(_diagnostic(module, ident, "UNKNOWN_BOOK_LINE", "error", "book line not in the journal", book_line=book))
                for item in row.get("unmatched_bank") or []:
                    if item.get("bank_line") not in ids["bank_line"]:
                        found.append(_diagnostic(module, ident, "UNKNOWN_BANK_LINE", "error", "bank line not in the statements", bank_line=item.get("bank_line")))
            expected_company = gold_company.get(module, {}).get(ident) if gold else None
            if expected_company and row.get("company") not in (None, expected_company):
                found.append(_diagnostic(module, ident, "COMPANY_MISMATCH", "error",
                                         "row company differs from the golden", expected=expected_company, actual=row.get("company")))
            for label, entry in entries_of(module, row):
                problems = validate_entry(cast(JournalEntry, entry))
                for problem in problems:
                    found.append(_diagnostic(module, ident, "ENTRY_RULE", "warning", f"{label}: {problem}"))
                if expected_company:
                    for line in entry["lines"]:
                        if isinstance(line, dict) and line.get("company") not in (None, expected_company):
                            found.append(_diagnostic(module, ident, "COMPANY_MISMATCH", "error",
                                                     f"{label}: line company differs from the golden",
                                                     expected=expected_company, actual=line.get("company")))
                            break
                    if entry.get("company") not in (None, expected_company):
                        found.append(_diagnostic(module, ident, "COMPANY_MISMATCH", "error",
                                                 f"{label}: entry company differs from the golden",
                                                 expected=expected_company, actual=entry.get("company")))
                posting = entry.get("posting_date")
                if isinstance(posting, str):
                    if not posting.startswith(month):
                        found.append(_diagnostic(module, ident, "POSTING_OUTSIDE_PERIOD", "error",
                                                 f"{label}: posting_date outside {month}", value=posting))
                    elif module == "close" and posting != month_end:
                        found.append(_diagnostic(module, ident, "CLOSE_NOT_MONTH_END", "warning",
                                                 f"{label}: close entries are dated the last day of the month", value=posting))
                for line in entry["lines"]:
                    if isinstance(line, dict) and str(line.get("account", "")).startswith("555") and line.get("partner"):
                        found.append(_diagnostic(module, ident, "SCORER_PARTNER_CONVENTION", "info",
                                                 f"{label}: the golden leaves 55500000 lines without partner and the scorer requires that",
                                                 account=line.get("account"), partner=line.get("partner")))
                        break
    # Validate the actual reference independently, even when a submitted row is
    # missing or correct. Reference defects never exempt submitted entries.
    for module, rows in (gold or {}).items():
        for row in rows:
            for label, entry in entries_of(module, row):
                for problem in validate_entry(cast(JournalEntry, entry)):
                    found.append(_diagnostic(module, row_id(module, row), "REFERENCE_ENTRY_RULE", "warning",
                                             f"{label}: reference violates accounting rule: {problem}", source="golden"))
    return found
