"""Deterministic AR cash application using ERP and bank statement evidence.

The bank movement is already posted to 572/555 by the input ERP. This engine
only proposes the application adjustment; it never reposts the bank movement.
N43 references/concepts enrich the abbreviated movement twin when available.
No inbox attachment, PDF, XML, OCR or CSV is read here.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from fractions import Fraction
from itertools import combinations
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable, cast

from ..data import PhaseData
from ..bankrec.statements import receipt_narratives
from ..documents.router import DocumentRouter
from .remittances import read_applications, read_face_application
from ..model import BankLine, JournalEntry, JournalLine
from ..output_models import ArCashRow

AR_ACCOUNTS = {"43000000", "43100000"}
CUSTOMER_WORDS = {"DE", "DEL", "LA", "LAS", "LOS", "EL", "Y", "E", "THE"}
LEGAL_WORDS = CUSTOMER_WORDS | {"SA", "SL", "S", "A", "L", "LLC", "LTD", "SC"}
BANK_PREFIXES = {"TRANSFERENCIA", "ABONO", "PAGO", "TESORERIA", "DEVOLUCION"}
_INVOICE_REF = re.compile(r"\b[A-Z]{2,8}[- ]?\d{2,8}[- ]?\d{0,8}\b", re.IGNORECASE)
MAX_GROUP = 6
# Shares of the payable observed in the partial payments of the collection history (research
# 04_ar_cash). A data observation, not a policy rule: used only when nothing else explains a receipt.
PARTIAL_RATIOS = (Fraction(2, 5), Fraction(1, 2), Fraction(3, 5), Fraction(3, 4))


@dataclass(frozen=True)
class ArCashResult:
    """A delivery row with internal diagnostics that are not part of the JSONL contract."""

    row: ArCashRow
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArCashRun:
    """Results in the deterministic task order and run-level diagnostics."""

    results: tuple[ArCashResult, ...]
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Invoice:
    id: str
    company: str
    customer: str
    date: str
    due_date: str
    currency: str
    factored: bool
    payable: int = 0


@dataclass(frozen=True)
class _Candidate:
    invoice: _Invoice
    account: str
    balance: int


class _ReceivableTimeline:
    """Recorded AR balances advanced by posting date, with per-run applications projected."""

    def __init__(self, entries: Iterable[JournalEntry]) -> None:
        events: list[tuple[str, str, str, str | None, str | None, int]] = []
        self.item_metadata: defaultdict[tuple[str, str, str | None, str | None], list[tuple[str, str]]] = defaultdict(list)
        for entry in entries:
            posting_date = entry.get("posting_date")
            if not posting_date:
                continue
            for line in entry.get("lines", []):
                account = str(line.get("account", ""))
                if account not in AR_ACCOUNTS:
                    continue
                amount = int(line.get("debit") or 0) - int(line.get("credit") or 0)
                if amount:
                    events.append((posting_date, str(entry["company"]), account,
                                   line.get("partner"), line.get("assignment"), amount))
                    self.item_metadata[(str(entry["company"]), account, line.get("partner"),
                                        line.get("assignment"))].append(
                                            (posting_date, str(line.get("currency") or entry.get("currency") or "")))
        events.sort(key=lambda x: x[0])
        self.events = events
        self.cursor = 0
        self.as_of = ""
        self.balances: defaultdict[tuple[str, str, str | None, str | None], int] = defaultdict(int)
        self.projected: defaultdict[tuple[str, str, str | None, str | None], int] = defaultdict(int)

    def advance(self, through: str) -> None:
        self.as_of = through
        while self.cursor < len(self.events) and self.events[self.cursor][0] <= through:
            _, company, account, partner, assignment, amount = self.events[self.cursor]
            self.balances[(company, account, partner, assignment)] += amount
            self.cursor += 1

    def balance(self, company: str, account: str, customer: str | None,
                assignment: str | None) -> int:
        key = (company, account, customer, assignment)
        return self.balances[key] - self.projected[key]

    def apply(self, candidate: _Candidate, amount: int) -> None:
        key = (candidate.invoice.company, candidate.account, candidate.invoice.customer,
               candidate.invoice.id)
        # AR journal assignments may carry an explicit factoring prefix.
        direct_key = key
        if self.balances.get(direct_key, 0) == 0:
            direct_key = (candidate.invoice.company, candidate.account,
                          candidate.invoice.customer, f"FT {candidate.invoice.id}")
        self.projected[direct_key] += amount

    def apply_open_item(self, company: str, account: str, partner: str,
                        assignment: str, amount: int) -> None:
        self.projected[(company, account, partner, assignment)] += amount

    def referenced_candidate(self, reference: str, company: str, customer: str,
                             currency: str) -> _Candidate | None:
        """Resolve an explicit bank reference against a positive, as-of ERP open item."""
        options = []
        for assignment in (reference, f"FT {reference}"):
            key = (company, "43000000", customer, assignment)
            balance = self.balance(*key)
            metadata = [(posted, item_currency) for posted, item_currency in self.item_metadata.get(key, [])
                        if posted <= self.as_of]
            currencies = {item_currency for _, item_currency in metadata if item_currency}
            if balance <= 0 or len(currencies) > 1 or (currencies and currency not in currencies):
                continue
            invoice_date = min((posted for posted, _ in metadata), default="")
            invoice = _Invoice(reference, company, customer, invoice_date, "", currency,
                               assignment.startswith("FT "))
            options.append(_Candidate(invoice, "43000000", balance))
        return options[0] if len(options) == 1 else None

    def candidates(self, invoices: dict[str, _Invoice], company: str, customer: str,
                   through: str) -> list[_Candidate]:
        found: list[_Candidate] = []
        for invoice in invoices.values():
            if invoice.company != company or invoice.customer != customer or invoice.date > through:
                continue
            for account in sorted(AR_ACCOUNTS):
                assignments = (invoice.id, f"FT {invoice.id}")
                amounts = [self.balance(company, account, customer, assignment)
                           for assignment in assignments]
                positive = [amount for amount in amounts if amount > 0]
                if positive:
                    found.append(_Candidate(invoice, account, sum(positive)))
                    break
        return found


def _normalize(value: object) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", decomposed.upper()).split())


def _name_score(text: str, name: str) -> tuple[int, int] | None:
    """Match a customer name as a phrase, allowing bank truncation at the final token.

    The score is (complete meaningful tokens, matched characters). We require two
    complete name tokens and resolve only a unique best-scoring customer.
    """
    bank_words = [w for w in _normalize(text).split()
                  if w not in BANK_PREFIXES and w not in CUSTOMER_WORDS]
    name_words = [w for w in _normalize(name).split()
                  if w not in LEGAL_WORDS]
    if not bank_words or len(name_words) < 2:
        return None
    best: tuple[int, int] | None = None
    for start in range(len(bank_words)):
        full = 0
        matched_chars = 0
        for offset, name_word in enumerate(name_words):
            index = start + offset
            if index >= len(bank_words):
                break
            word = bank_words[index]
            if word == name_word:
                full += 1
                matched_chars += len(word)
                continue
            if name_word.startswith(word) and len(word) >= 4:
                matched_chars += len(word)
            break
        partial_is_credible = (full >= 1 and matched_chars >= 13
                               and start + full < len(bank_words)
                               and len(bank_words[start + full]) >= 4)
        if full >= 2 or partial_is_credible:
            score = (full, matched_chars)
            if best is None or score > best:
                best = score
    return best


def _identify_customer(text: str, customers: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    scored = [(score, str(row["id"])) for row in customers
              if (score := _name_score(text, str(row.get("name", "")))) is not None]
    if not scored:
        return None, "customer not identified from structured bank narrative"
    highest = max(score for score, _ in scored)
    winners = sorted({customer for score, customer in scored if score == highest})
    if len(winners) != 1:
        return None, f"ambiguous payer name: {', '.join(winners)}"
    return winners[0], None


def _remittance_sender(data: PhaseData, line: BankLine, customers: list[dict[str, Any]]
                      ) -> tuple[str | None, str | None, str | None]:
    """Use JSON notice metadata only when its sender matches this dated bank narrative.

    Sidecars identify a possible payer; they do not contain invoice allocation evidence.
    The referenced attachment is deliberately never opened.
    """
    directory = data.phase_dir / "inbox" / "ar" / "remittances"
    if not directory.is_dir():
        return None, None, None
    matches: list[tuple[tuple[int, int], str, str]] = []
    for path in sorted(directory.glob("*.json")):
        notice = data.table(path.relative_to(data.phase_dir).as_posix())
        sender = notice.get("from_")
        received_at = notice.get("received_at")
        if not isinstance(sender, str) or not isinstance(received_at, str):
            continue
        try:
            date.fromisoformat(received_at)
        except ValueError:
            continue
        if received_at != line["value_date"]:
            continue
        score = _name_score(str(line.get("text", "")), sender)
        if score is None:
            continue
        customer, issue = _identify_customer(sender, customers)
        if customer is not None:
            matches.append((score, customer, path.name))
    if not matches:
        return None, None, None
    best_score = max(score for score, _, _ in matches)
    best = [(customer, filename) for score, customer, filename in matches if score == best_score]
    customer_ids = sorted({customer for customer, _ in best})
    if len(customer_ids) != 1:
        return None, None, "remittance sender metadata is ambiguous for this bank line"
    filenames = ", ".join(sorted({filename for _, filename in best}))
    return customer_ids[0], filenames, None


def _penalty_inputs(data: PhaseData) -> list[dict[str, Any]]:
    """Combine ERP penalty records with optional structured JSON notice records."""
    rows = list(data.table("penalty_notices"))
    directory = data.phase_dir / "inbox" / "ar" / "notices"
    if not directory.is_dir():
        return rows
    known = {(row.get("invoice"), row.get("customer"), row.get("amount"), row.get("notified_on"))
             for row in rows}
    for path in sorted(directory.glob("*.json")):
        notice = data.table(path.relative_to(data.phase_dir).as_posix())
        if not isinstance(notice, dict):
            continue
        identity = (notice.get("invoice"), notice.get("customer"), notice.get("amount"),
                    notice.get("notified_on"))
        if all(value is not None for value in identity) and identity not in known:
            rows.append({key: value for key, value in zip(
                ("invoice", "customer", "amount", "notified_on"), identity)})
            known.add(identity)
    return rows


def _task_ids(data: PhaseData) -> list[str]:
    task = data.table("tasks/ar_receipts")
    if isinstance(task, dict):
        task = task.get("bank_lines", task.get("items", []))
    if not isinstance(task, list) or any(not isinstance(row, str) for row in task):
        raise ValueError("tasks/ar_receipts.json must be a list of bank_line IDs")
    if len(task) != len(set(task)):
        raise ValueError("tasks/ar_receipts.json contains duplicate bank_line IDs")
    return task


def _bank_line_index(data: PhaseData) -> tuple[dict[str, tuple[BankLine, str]], dict[str, dict[str, Any]]]:
    accounts = {str(row["id"]): row for row in data.table("bank_accounts")}
    indexed: dict[str, tuple[BankLine, str]] = {}
    for account in sorted(accounts):
        narratives = receipt_narratives(data, account, data.month)
        for line in data.bank_lines(account, data.month):
            if line["bank_line"] in indexed:
                raise ValueError(f"duplicate bank_line across accounts: {line['bank_line']}")
            enriched = cast(BankLine, dict(line))
            enriched["text"] = narratives.get(line["bank_line"], line["text"])
            indexed[line["bank_line"]] = (enriched, account)
    return indexed, accounts


def _invoice_index(data: PhaseData) -> dict[str, _Invoice]:
    result: dict[str, _Invoice] = {}
    for row in data.table("ar_invoices"):
        if row.get("kind") not in (None, "invoice"):
            continue
        invoice_id = str(row["id"])
        result[invoice_id] = _Invoice(invoice_id, str(row["company"]), str(row["customer"]),
                                      str(row["date"]), str(row.get("due_date") or "9999-12-31"),
                                      str(row.get("currency") or ""), bool(row.get("factored")),
                                      int(row.get("payable") or 0))
    return result


def _invoice_reference(text: str, invoices: dict[str, _Invoice]) -> str | None:
    normalized = _normalize(text).replace(" ", "")
    matches = [invoice_id for invoice_id in invoices
               if invoice_id.replace("-", "").upper() in normalized]
    return matches[0] if len(matches) == 1 else None


def _matured_note(notes: list[dict[str, Any]], timeline: _ReceivableTimeline,
                  company: str, customer: str, receipt_date: str, amount: int,
                  text: str) -> tuple[str, str, int] | None:
    normalized_text = _normalize(text).replace(" ", "")
    matches: list[tuple[str, str, int]] = []
    for note in notes:
        if (str(note.get("company")) != company or str(note.get("customer")) != customer
                or str(note.get("maturity", "9999-12-31")) > receipt_date):
            continue
        number = str(note.get("number", ""))
        assignments = (f"PAG{number}", number)
        item = next(((assignment, timeline.balance(company, "43100000", customer, assignment))
                     for assignment in assignments
                     if timeline.balance(company, "43100000", customer, assignment) > 0), None)
        if item is None:
            continue
        assignment, balance = item
        explicit = bool(number and number in normalized_text)
        if explicit or balance == amount:
            matches.append((number, assignment, balance))
    return matches[0] if len(matches) == 1 else None


def _eligible(candidates: list[_Candidate], receipt_date: str, *, include_near_future: bool = False) -> list[_Candidate]:
    due = [c for c in candidates if c.invoice.due_date <= receipt_date]
    if not include_near_future:
        return due
    limit = date.fromisoformat(receipt_date) + timedelta(days=7)
    return [c for c in candidates if c.invoice.due_date <= limit.isoformat()]


def _entity_key(name: object) -> str:
    return " ".join(word for word in _normalize(name).split() if word not in LEGAL_WORDS)


def _fully_open(candidate: _Candidate) -> bool:
    return bool(candidate.invoice.payable) and candidate.balance == candidate.invoice.payable


def _best_subset(candidates: list[_Candidate], amount: int) -> tuple[list[_Candidate], str] | None:
    """The exact group with the fewest invoices; among equal groups, fully open invoices before
    remnants, then the oldest (date, id). Monthly fees repeat the same amount, so a grouped
    transfer can match several groups. Bounded at 18 candidates and MAX_GROUP invoices."""
    if len(candidates) > 18:
        return None
    for size in range(2, min(MAX_GROUP, len(candidates)) + 1):
        matches = [list(group) for group in combinations(candidates, size)
                   if sum(c.balance for c in group) == amount]
        if matches:
            matches.sort(key=lambda group: (sum(not _fully_open(c) for c in group),
                                            sorted((c.invoice.date, c.invoice.id) for c in group)))
            note = ("" if len(matches) == 1 else
                    f"tie-break: {len(matches)} groups of {size} invoices match; took the oldest fully open one")
            return matches[0], note
    return None


def _ratio_partial(candidates: list[_Candidate], amount: int) -> tuple[_Candidate, Fraction] | None:
    """Oldest fully open invoice whose payable times a usual ratio, truncated to the cent, is the receipt."""
    hits = [(c.invoice.date, c.invoice.id, c, ratio) for c in candidates if _fully_open(c)
            for ratio in PARTIAL_RATIOS if amount == c.balance * ratio.numerator // ratio.denominator]
    if not hits:
        return None
    _, _, candidate, ratio = min(hits, key=lambda hit: (hit[0], hit[1]))
    return candidate, ratio


def _exact_subset_count(candidates: list[_Candidate], amount: int) -> int | None:
    """Count exact subsets up to two; None means the candidate set is too large."""
    if len(candidates) > 18:
        return None
    ways = {0: 1}
    for candidate in candidates:
        for subtotal, count in list(ways.items()):
            total = subtotal + candidate.balance
            if total <= amount:
                ways[total] = min(2, ways.get(total, 0) + count)
    return ways.get(amount, 0)


def _unique_penalty_subset(candidates: list[_Candidate], penalty_rows: list[dict[str, Any]],
                           customer: str, receipt_date: str, cash: int
                           ) -> list[tuple[_Candidate, int]] | None:
    """Find the unique set of invoices whose full balances net of notices equal cash."""
    if len(candidates) > 16:
        return None
    options: list[list[tuple[int, int]]] = []
    for candidate in candidates:
        adjustments = {0}
        adjustments.update(
            int(row["amount"]) for row in penalty_rows
            if row.get("invoice") == candidate.invoice.id
            and row.get("customer") == customer
            and str(row.get("notified_on", "9999-12-31")) <= receipt_date
            and 0 < int(row.get("amount") or 0) < candidate.balance
        )
        options.append([(candidate.balance - penalty, penalty) for penalty in sorted(adjustments)])

    # Keep two witnesses per subtotal so ambiguity is detected without exponential
    # memory growth. Each item can be omitted, applied in full, or reduced by notice.
    states: dict[int, list[tuple[tuple[int, int], ...]]] = {0: [()]}
    for index, candidate in enumerate(candidates):
        previous = [(total, tuple(paths)) for total, paths in states.items()]
        for subtotal, paths in previous:
            for net_amount, penalty in options[index]:
                total = subtotal + net_amount
                if total > cash:
                    continue
                destination = states.setdefault(total, [])
                destination.extend(path + ((index, penalty),) for path in paths)
                if len(destination) > 2:
                    del destination[2:]
    witnesses = [path for path in states.get(cash, []) if path]
    if len(witnesses) != 1 or not any(penalty for _, penalty in witnesses[0]):
        return None
    return [(candidates[index], penalty) for index, penalty in witnesses[0]]


def _line(company: str, account: str, debit: int, credit: int,
          partner: str | None = None, assignment: str | None = None) -> JournalLine:
    line: JournalLine = {"company": company, "account": account,
                         "debit": debit, "credit": credit}
    if partner is not None:
        line["partner"] = partner
    if assignment is not None:
        line["assignment"] = assignment
    return line


def _balanced(lines: list[JournalLine]) -> bool:
    return sum(int(line.get("debit", 0)) for line in lines) == sum(int(line.get("credit", 0)) for line in lines)


def _casefold_map(rows: list[dict[str, Any]], field: str = "id") -> dict[str, dict[str, Any]]:
    return {str(row[field]): row for row in rows if row.get(field) is not None}


def _special_non_customer(text: str) -> str | None:
    normalized = _normalize(text)
    if "IVA" in normalized and any(word in normalized for word in ("DEVOLUCION", "REEMBOLSO", "REFUND")):
        return "47000000"
    if "FIANZA" in normalized or "DEPOSITO" in normalized:
        return "56500000"
    if "SEGURO" in normalized or "INDEMNIZACION" in normalized:
        return "75900000"
    return None


def _as_of_balances(data: PhaseData) -> list[JournalEntry]:
    """Return recorded entries only; each task's date cursor filters them as needed."""
    return list(data.iter_journal())


def _billed(billing: Iterable[dict[str, Any]]) -> tuple[dict[str, _Invoice], list[JournalEntry]]:
    """Invoices issued by this month's AR billing delivery: they are receivables from their posting date."""
    invoices: dict[str, _Invoice] = {}
    entries: list[JournalEntry] = []
    for row in billing:
        invoice, entry = row.get("invoice") or {}, row.get("journal_entry")
        if row.get("expected") != "INVOICE" or not invoice.get("number") or not entry:
            continue
        receivable = next((line for line in entry["lines"] if line.get("account") == "43000000"), None)
        if receivable is None:
            continue
        invoices[invoice["number"]] = _Invoice(invoice["number"], str(entry["company"]), str(receivable.get("partner")),
                                               invoice["date"], invoice.get("due_date") or "9999-12-31",
                                               invoice.get("currency") or "", False, int(invoice.get("payable") or 0))
        entries.append(cast(JournalEntry, {**entry, "id": f"billing:{row['billing_item']}"}))
    return invoices, entries


def build_ar_cash(data: PhaseData, *, use_preparsed: bool = False,
                  normalized_dir: str | Path | None = None,
                  billing: Iterable[dict[str, Any]] = ()) -> ArCashRun:
    """Build one application result per receipt task using ERP/bank evidence.

    Exact unique matches are auto-applied. Ambiguous payer/invoice relationships are
    left in 555 and described in diagnostics; no approximate or amount-only customer
    assignment is made.
    """
    task_ids = _task_ids(data)
    document_router = DocumentRouter(data.phase_dir, use_preparsed=use_preparsed,
                                     normalized_dir=normalized_dir)
    bank_index, bank_accounts = _bank_line_index(data)
    missing = [line_id for line_id in task_ids if line_id not in bank_index]
    if missing:
        raise ValueError(f"task bank_line IDs missing from normalized statements: {', '.join(missing)}")

    customers = list(data.table("customers"))
    invoices = _invoice_index(data)
    billed_invoices, billed_entries = _billed(billing)
    invoices.update(billed_invoices)
    vendors = _casefold_map(list(data.table("vendors")))
    penalty_rows = _penalty_inputs(data)
    factoring_rows = list(data.table("factoring_assignments"))
    entries = _as_of_balances(data) + billed_entries
    timeline = _ReceivableTimeline(cast(Iterable[JournalEntry], entries))

    # Existing AP/open-item balances are calculated at each receipt date from the
    # recorded book, not from the end-of-month open-item snapshot.
    ap_events: list[tuple[str, str, str, str | None, str | None, int]] = []
    for entry in entries:
        posting_date = entry.get("posting_date")
        if not posting_date:
            continue
        for line in entry.get("lines", []):
            account = str(line.get("account", ""))
            if not (account.startswith("400") or account.startswith("410")):
                continue
            amount = int(line.get("debit") or 0) - int(line.get("credit") or 0)
            if amount:
                ap_events.append((posting_date, str(entry["company"]), account,
                                  line.get("partner"), line.get("assignment"), amount))
    ap_events.sort(key=lambda x: x[0])
    ap_balance: defaultdict[tuple[str, str, str | None, str | None], int] = defaultdict(int)
    ap_cursor = 0
    customers_by_tax: dict[str, list[str]] = defaultdict(list)
    customers_by_name: dict[str, list[str]] = defaultdict(list)
    for row in customers:
        if row.get("tax_id"):
            customers_by_tax[str(row["tax_id"])].append(str(row["id"]))
        if _entity_key(row.get("name", "")):
            customers_by_name[_entity_key(row["name"])].append(str(row["id"]))
    vendors_by_customer: dict[str, list[str]] = defaultdict(list)
    for vendor_id, vendor in vendors.items():
        customer_ids = customers_by_tax.get(str(vendor.get("tax_id")), [])
        if not customer_ids and _entity_key(vendor.get("name", "")):
            customer_ids = customers_by_name.get(_entity_key(vendor["name"]), [])
        for customer_id in customer_ids:
            vendors_by_customer[customer_id].append(vendor_id)

    results_by_id: dict[str, ArCashResult] = {}
    applied_receipts: defaultdict[tuple[str, int], list[str]] = defaultdict(list)
    run_diagnostics: list[str] = []
    sort_ids = sorted(task_ids, key=lambda line_id: (bank_index[line_id][0]["value_date"],
                                                     bank_index[line_id][0]["booking_date"], line_id))

    for line_id in sort_ids:
        bank_line, bank_account_id = bank_index[line_id]
        account = bank_accounts[bank_account_id]
        company = str(account["company"])
        receipt_date = str(bank_line["value_date"])
        timeline.advance(receipt_date)
        while ap_cursor < len(ap_events) and ap_events[ap_cursor][0] <= receipt_date:
            _, co, ap_account, vendor_id, assignment, amount = ap_events[ap_cursor]
            ap_balance[(co, ap_account, vendor_id, assignment)] += amount
            ap_cursor += 1

        amount = int(bank_line["amount"])
        diagnostics: list[str] = []
        net_vendor: tuple[str, str, str | None] | None = None
        if amount <= 0:
            results_by_id[line_id] = ArCashResult({"bank_line": line_id, "customer": None,
                                                    "applications": [], "residuals": [], "adjustment": []},
                                                   ("bank line is not a positive receipt",))
            continue
        currency_mismatch = str(bank_line.get("currency")) != str(account.get("currency"))
        if currency_mismatch:
            diagnostics.append("bank line currency differs from the bank-account master")

        customer, payer_issue = _identify_customer(str(bank_line.get("text", "")), customers)
        if payer_issue:
            diagnostics.append(payer_issue)
        notice_customer, notice_file, notice_issue = _remittance_sender(data, bank_line, customers)
        if notice_issue:
            diagnostics.append(notice_issue)
        if notice_file:
            if customer is not None and customer != notice_customer:
                diagnostics.append(
                    f"bank payer {customer} conflicts with remittance sender in {notice_file}; left unresolved")
                customer = None
            elif customer is None:
                customer = notice_customer
                diagnostics.append(f"payer identified from remittance metadata {notice_file}")
            else:
                diagnostics.append(f"payer corroborated by remittance metadata {notice_file}")

        apps: list[dict[str, Any]] = []
        residuals: list[dict[str, Any]] = []
        adjustments: list[JournalLine] = []
        chosen: list[_Candidate] | None = None
        ref = _invoice_reference(str(bank_line.get("text", "")), invoices)
        ledger_ref_candidate = None
        if ref is None and customer is not None:
            ledger_references = {}
            for match in _INVOICE_REF.finditer(str(bank_line.get("text", ""))):
                token = match.group(0).strip().upper()
                candidate = timeline.referenced_candidate(token, company, customer,
                                                          str(bank_line.get("currency", "")))
                if candidate is not None:
                    ledger_references[token] = candidate
            if len(ledger_references) == 1:
                ref, ledger_ref_candidate = next(iter(ledger_references.items()))
                diagnostics.append(f"explicit bank reference resolved from dated ERP open item {ref}")
            elif len(ledger_references) > 1:
                diagnostics.append("multiple explicit references have open ERP balances; left unresolved")
        if ref and ref in invoices and invoices[ref].company == company:
            referenced_customer = invoices[ref].customer
            if customer is None and notice_issue is None and not notice_file:
                customer = referenced_customer
                diagnostics.append(f"payer identified by explicit bank invoice reference {ref}")
            elif customer is not None and customer != referenced_customer:
                diagnostics.append(f"bank payer conflicts with invoice reference {ref}; left unresolved")
                results_by_id[line_id] = ArCashResult(
                    {"bank_line": line_id, "customer": None, "applications": [],
                     "residuals": [], "adjustment": []}, tuple(diagnostics))
                continue
        matured_note = (_matured_note(list(data.table("promissory_notes")), timeline, company,
                                     customer, receipt_date, amount, str(bank_line.get("text", "")))
                        if customer is not None else None)

        # A tax refund/deposit/insurance receipt is classified only when the narrative
        # names the non-customer concept and no customer was identified.
        non_customer_account = _special_non_customer(str(bank_line.get("text", ""))) if customer is None else None
        if currency_mismatch:
            results_by_id[line_id] = ArCashResult({"bank_line": line_id, "customer": customer,
                                                    "applications": [], "residuals": [], "adjustment": []},
                                                   tuple(diagnostics))
            continue
        if non_customer_account:
            residuals.append({"type": "NON_CUSTOMER", "amount": amount})
            adjustments = [_line(company, "55500000", amount, 0),
                           _line(company, non_customer_account, 0, amount)]
            diagnostics.append(f"non-customer receipt mapped from explicit narrative to {non_customer_account}")
        elif customer is None:
            results_by_id[line_id] = ArCashResult({"bank_line": line_id, "customer": None,
                                                    "applications": [], "residuals": [], "adjustment": []},
                                                   tuple(diagnostics or ["payer not resolved"]))
            continue
        elif matured_note:
            number, assignment, note_balance = matured_note
            applied = min(amount, note_balance)
            apps.append({"pagare": number, "amount": applied})
            timeline.apply_open_item(company, "43100000", customer, assignment, applied)
            adjustments = [_line(company, "55500000", applied, 0),
                           _line(company, "43100000", 0, applied, customer, f"PAG{number}")]
            if applied < amount:
                diagnostics.append("receipt exceeds matured promissory note; unsupported excess remains unapplied")
        else:
            candidates = [c for c in timeline.candidates(invoices, company, customer, receipt_date)
                          if c.invoice.currency in ("", str(bank_line.get("currency")))]
            if ledger_ref_candidate is not None:
                candidates.append(ledger_ref_candidate)
            all_candidates = candidates
            observed = None
            source_conflict = False
            if use_preparsed:
                if notice_file:
                    observed, source_diagnostics = read_applications(
                        data, document_router, notice_file, company, receipt_date,
                        amount, str(bank_line.get("currency")))
                    diagnostics.extend(source_diagnostics)
                    source_conflict = any("left unresolved" in item for item in source_diagnostics)
                face_observed, face_diagnostics = read_face_application(
                    data, document_router, company, receipt_date, amount,
                    str(bank_line.get("currency")), customer)
                diagnostics.extend(face_diagnostics)
                source_conflict = source_conflict or any("left unresolved" in item for item in face_diagnostics)
                if face_observed:
                    if observed is not None and observed != face_observed:
                        diagnostics.append("FACe and remittance applications conflict; left unresolved")
                        observed = None
                        source_conflict = True
                    else:
                        observed = face_observed
            if source_conflict:
                results_by_id[line_id] = ArCashResult(
                    {"bank_line": line_id, "customer": customer, "applications": [],
                     "residuals": [], "adjustment": []}, tuple(diagnostics))
                continue
            by_invoice = {candidate.invoice.id: candidate for candidate in candidates}
            if observed and all(reference in by_invoice and value <= by_invoice[reference].balance
                                for reference, value in observed):
                chosen = [by_invoice[reference] for reference, _ in observed]
                for reference, value in observed:
                    candidate = by_invoice[reference]
                    apps.append({"invoice": reference, "amount": value})
                    timeline.apply(candidate, value)
                    if value == candidate.balance:
                        applied_receipts[(customer, value)].append(reference)
            elif observed:
                diagnostics.append("remittance applications conflict with available receivable balances")
                results_by_id[line_id] = ArCashResult(
                    {"bank_line": line_id, "customer": customer, "applications": [],
                     "residuals": [], "adjustment": []}, tuple(diagnostics))
                continue
            if ref:
                candidates = [candidate for candidate in candidates if candidate.invoice.id == ref]
                if not candidates:
                    diagnostics.append(f"invoice reference {ref} has no positive AR balance at the receipt date")

            # Explicit invoice reference beats amount matching.
            if not apps and candidates and ref:
                candidate = candidates[0]
                applied = min(amount, candidate.balance)
                if applied > 0:
                    chosen = [candidate]
                    apps.append({"invoice": candidate.invoice.id, "amount": applied})
                    timeline.apply(candidate, applied)
                    if applied == candidate.balance:
                        applied_receipts[(customer, applied)].append(candidate.invoice.id)
                    if applied < amount:
                        diagnostics.append("receipt exceeds referenced invoice; unsupported excess remains unapplied")

            if not apps:
                due_candidates = _eligible(all_candidates, receipt_date)
                near_due = _eligible(all_candidates, receipt_date, include_near_future=True)
                penalty_solution = _unique_penalty_subset(due_candidates, penalty_rows,
                                                          customer, receipt_date, amount)
                if penalty_solution:
                    chosen = [candidate for candidate, _ in penalty_solution]
                    for candidate, penalty in penalty_solution:
                        apps.append({"invoice": candidate.invoice.id, "amount": candidate.balance})
                        if penalty:
                            residuals.append({"type": "PENALTY", "invoice": candidate.invoice.id,
                                              "amount": penalty})
                        timeline.apply(candidate, candidate.balance)
                    applied_receipts[(customer, amount)].extend(c.invoice.id for c, _ in penalty_solution)

            if not apps:
                # NETTING_AP requires a same-customer vendor with an open AP item;
                # cash + AP must exactly clear one receivable item.
                net_matches: list[tuple[_Candidate, str, str, str | None, int]] = []
                for candidate in due_candidates:
                    needed = candidate.balance - amount
                    if needed <= 0:
                        continue
                    for vendor_id in vendors_by_customer.get(customer, []):
                        vendor_master = vendors.get(vendor_id, {})
                        if company not in vendor_master.get("companies", []):
                            continue
                        ap_items = [(ap_account, assignment, abs(balance))
                                    for (co, ap_account, partner, assignment), balance in ap_balance.items()
                                    if co == company and partner == vendor_id and balance < 0]
                        for ap_account, ap_assignment, ap_amount in ap_items:
                            if needed == ap_amount:
                                net_matches.append((candidate, vendor_id, ap_account,
                                                    ap_assignment, needed))
                if len(net_matches) == 1:
                    candidate, vendor_id, ap_account, ap_assignment, net_amount = net_matches[0]
                    chosen = [candidate]
                    apps.append({"invoice": candidate.invoice.id, "amount": candidate.balance})
                    residuals.append({"type": "NETTING_AP", "invoice": candidate.invoice.id,
                                      "amount": net_amount})
                    timeline.apply(candidate, candidate.balance)
                    applied_receipts[(customer, amount)].append(candidate.invoice.id)
                    # Save the balancing payable debit for the adjustment below.
                    net_vendor = (vendor_id, ap_account, ap_assignment)
                else:
                    if net_matches:
                        diagnostics.append("multiple netting matches; left unapplied")

            # Exact single-item match, preferring due invoices; then a unique subset
            # for grouped remittances. Same-total monthly invoices remain ambiguous.
            if not apps:
                exact = [c for c in due_candidates if c.balance == amount]
                if len(exact) == 1:
                    chosen = exact
                elif not exact:
                    near_exact = [c for c in near_due if c.balance == amount]
                    if len(near_exact) == 1:
                        chosen = near_exact
                    elif len(near_exact) > 1:
                        nearest_delta = min(abs((date.fromisoformat(c.invoice.due_date) - date.fromisoformat(receipt_date)).days)
                                            for c in near_exact)
                        nearest = [c for c in near_exact if abs((date.fromisoformat(c.invoice.due_date)
                                                                 - date.fromisoformat(receipt_date)).days) == nearest_delta]
                        if len(nearest) == 1:
                            chosen = nearest
                if chosen is None and not exact:
                    grouped = _best_subset(due_candidates, amount)
                    if grouped:
                        chosen, note = grouped
                        if note:
                            diagnostics.append(note)
                if chosen:
                    apps.extend({"invoice": c.invoice.id, "amount": c.balance} for c in chosen)
                    for candidate in chosen:
                        timeline.apply(candidate, candidate.balance)
                    applied_receipts[(customer, amount)].extend(c.invoice.id for c in chosen)
                elif due_candidates and not residuals:
                    if sum(candidate.balance == amount for candidate in due_candidates) > 1:
                        diagnostics.append("multiple exact invoice matches; left unapplied")
                    elif len(due_candidates) > 1:
                        subset_count = _exact_subset_count(due_candidates, amount)
                        if subset_count == 2:
                            diagnostics.append("multiple exact invoice subsets match; left unapplied")
                        elif subset_count is None:
                            diagnostics.append("exact invoice subset search exceeded its bound; left unapplied")
                        else:
                            diagnostics.append("no unique exact/grouped invoice match; left unapplied")

            if not apps:
                # A repeated transfer matching a prior full application is evidence of
                # a duplicate only when the customer has no exact open invoice match.
                prior = applied_receipts.get((customer, amount), [])
                if prior:
                    duplicate_invoice = prior[0]
                    residuals.append({"type": "OVERPAYMENT_DUPLICATE", "invoice": duplicate_invoice,
                                      "amount": amount})
                    adjustments = [_line(company, "55500000", amount, 0),
                                   _line(company, "43800000", 0, amount, customer, duplicate_invoice)]
                    diagnostics.append(f"same customer paid the same amount again after clearing {duplicate_invoice}")

            # A receipt that is a usual share of one fully open due invoice is a partial
            # payment (policy: apply it and leave the shortfall open).
            if not apps and not residuals and customer and ref is None:
                partial = _ratio_partial(_eligible(all_candidates, receipt_date), amount)
                if partial:
                    candidate, ratio = partial
                    apps.append({"invoice": candidate.invoice.id, "amount": amount})
                    timeline.apply(candidate, amount)
                    diagnostics.append(f"partial payment by ratio {float(ratio):g}; the rest stays open")

            # If no exact mapping/cause was established, a partial payment is accepted
            # only when exactly one due invoice remains possible for this customer.
            if not apps and not residuals:
                due_candidates = _eligible(all_candidates, receipt_date)
                if len(due_candidates) == 1 and 0 < amount < due_candidates[0].balance:
                    candidate = due_candidates[0]
                    apps.append({"invoice": candidate.invoice.id, "amount": amount})
                    timeline.apply(candidate, amount)
                    diagnostics.append("partial payment applied; unknown shortfall remains open")

            # If no open receivable can explain this receipt, a specific factoring
            # assignment can establish that the customer paid a ceded invoice to Kalmora.
            if not apps and not residuals:
                factored_matches = []
                for assignment in factoring_rows:
                    invoice_id = str(assignment.get("invoice", ""))
                    invoice = invoices.get(invoice_id)
                    if (invoice is None or invoice.customer != customer or invoice.company != company
                            or assignment.get("customer") != customer
                            or str(assignment.get("date", "9999-12-31")) > receipt_date):
                        continue
                    ar_record = next((row for row in data.table("ar_invoices") if row.get("id") == invoice_id), None)
                    if ar_record and int(ar_record.get("payable") or 0) == amount:
                        factored_matches.append(invoice_id)
                if len(factored_matches) == 1:
                    invoice_id = factored_matches[0]
                    residuals.append({"type": "FACTORED_MISDIRECTED", "invoice": invoice_id,
                                      "amount": amount})
                    adjustments = [_line(company, "55500000", amount, 0),
                                   _line(company, "55300000", 0, amount, "FACTOR-BAE", invoice_id)]
                    diagnostics.append(f"payment received for factored invoice {invoice_id}")
                elif len(factored_matches) > 1:
                    diagnostics.append("multiple factored invoice matches; left unapplied")

            # Build normal application journal lines: debit 555 for cash, debit any
            # evidenced residual counterpart, and credit each invoice/open item.
            if apps and not adjustments:
                cash_applied = (sum(int(app["amount"]) for app in apps)
                                - sum(int(r["amount"]) for r in residuals
                                      if r["type"] in ("PENALTY", "NETTING_AP")))
                debit_lines: list[JournalLine] = [_line(company, "55500000", cash_applied, 0)]
                credit_lines: list[JournalLine] = []
                # Invoice application values are the AR credits. Residuals increase
                # the cleared face amount while explaining why the bank cash is lower.
                for app in apps:
                    invoice_id = str(app["invoice"])
                    app_candidate = next((c for c in (chosen or []) if c.invoice.id == invoice_id), None)
                    account_code = app_candidate.account if app_candidate else "43000000"
                    credit_lines.append(_line(company, account_code, 0, int(app["amount"]), customer, invoice_id))
                for residual in residuals:
                    if residual["type"] == "PENALTY":
                        debit_lines.append(_line(company, "70590000", int(residual["amount"]), 0))
                    elif residual["type"] == "NETTING_AP":
                        if not net_vendor:
                            diagnostics.append("netting evidence found but vendor identity unresolved")
                            continue
                        vendor_id, ap_account, ap_assignment = net_vendor
                        debit_lines.append(_line(company, ap_account, int(residual["amount"]), 0,
                                                 str(vendor_id), ap_assignment))
                adjustments = debit_lines + credit_lines

        row: ArCashRow = {"bank_line": line_id, "customer": customer,
                          "applications": cast(Any, apps), "residuals": cast(Any, residuals),
                          "adjustment": adjustments}
        if adjustments and not _balanced(adjustments):
            raise ValueError(f"unbalanced generated AR cash adjustment for {line_id}")
        results_by_id[line_id] = ArCashResult(row, tuple(diagnostics))

    ordered_results = tuple(results_by_id[line_id] for line_id in task_ids)
    return ArCashRun(ordered_results, tuple(run_diagnostics))


def to_row(result: ArCashResult) -> ArCashRow:
    """Return a fresh delivery-shaped row without internal diagnostics."""
    return cast(ArCashRow, {
        "bank_line": result.row["bank_line"],
        "customer": result.row["customer"],
        "applications": [dict(application) for application in result.row["applications"]],
        "residuals": [dict(residual) for residual in result.row["residuals"]],
        "adjustment": [dict(line) for line in result.row["adjustment"]],
    })
