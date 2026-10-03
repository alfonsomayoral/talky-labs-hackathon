"""Read-only phase ERP baseline for AP integration, without Golden or FIFO.

The AP journal establishes consumption even when the processing log still says
HOLD. Invoice/log links protect recorded documents; unlinked AP postings remain
visible as incomplete identities rather than being assigned invented doc_ids.
"""
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
import re

from .ap_allocation import ConsumptionState, OrderKey, OrderLine, Receipt
from .ap_duplicates import normalize_number, registered_duplicate_records
from .ap_history import (
    HistoricalDemand, HistoricalReceipt, HistoricalReceiptSnapshot,
    reconcile_receipt_history,
)
from .ap_orders import POCatalog
from .ap_valuation import OrderPrice
from .data import PhaseData, load_json
from .facts import Evidence, Fact
from .model.ap_duplicate_record import DuplicateRecord
from .money import integer


@dataclass(frozen=True)
class ERPSource:
    path: str
    sha256: str


@dataclass(frozen=True)
class RecordedAPPosting:
    company: str
    journal_entry: str
    currency: str | None  # evidenced invoice currency; never the GL header default
    journal_currency: str
    number: str
    vendors: tuple[str, ...]
    document_ids: tuple[str, ...]
    evidence: tuple[Evidence, ...]


@dataclass(frozen=True)
class PostingGuard:
    status: str  # CLEAR, ALREADY_POSTED, UNKNOWN
    evidence: tuple[Evidence, ...] = ()
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class APERPBaseline:
    month: str
    sources: tuple[ERPSource, ...]
    orders: tuple[OrderLine, ...]
    receipts: tuple[Receipt, ...]
    prices: tuple[OrderPrice, ...]
    history: HistoricalReceiptSnapshot
    recorded_postings: tuple[RecordedAPPosting, ...]
    duplicate_records: tuple[DuplicateRecord, ...]

    def posting_guard(self, *, company: str, vendor: str, currency: str,
                      doc_id: str, number: str) -> PostingGuard:
        """Protect exact registered IDs and expose incomplete journal identities.

        This is an idempotency guard, not a replacement for duplicate policy.
        An unlinked journal reference cannot supply duplicate_of or its missing
        invoice amount. Such a match prevents a false negative, retaining UNKNOWN.
        """
        for value in (company, vendor, currency, doc_id, number):
            if not isinstance(value, str) or not value:
                raise ValueError("posting identity requires nonempty source facts")
        same_id = [p for p in self.recorded_postings
                   if p.company == company and doc_id in p.document_ids]
        if same_id:
            return PostingGuard("ALREADY_POSTED", tuple(e for p in same_id for e in p.evidence))
        matches = [p for p in self.recorded_postings
                   if not p.document_ids and p.company == company and p.currency in (None, currency)
                   and vendor in p.vendors and p.number
                   and normalize_number(p.number) == normalize_number(number)]
        if matches:
            return PostingGuard("UNKNOWN", tuple(e for p in matches for e in p.evidence),
                                ("UNLINKED_AP_JOURNAL_IDENTITY",))
        return PostingGuard("CLEAR")


_TABLES = ("purchase_orders", "goods_receipts", "ap_invoices", "ap_document_log",
           "journal_entries", "vendors")


def _source(data: PhaseData, stem: str) -> tuple[Path, ERPSource]:
    for suffix in (".jsonl", ".json"):
        path = data.phase_dir / "erp" / (stem + suffix)
        resolved = path.resolve()
        if not resolved.is_relative_to(data.phase_dir) or "golden" in resolved.parts:
            raise ValueError("ERP source escapes the active phase")
        if path.is_file():
            return path, ERPSource(path.relative_to(data.phase_dir).as_posix(),
                                   sha256(path.read_bytes()).hexdigest())
    raise ValueError(f"required ERP source is absent: {stem}")


def load_ap_erp_baseline(phase_path: str | Path, *, grir_account: str) -> APERPBaseline:
    """Build a baseline from the active phase, retaining quantity uncertainty.

    Read every AP journal, not only invoices initially labelled POST. No journal
    date is treated as a proven processing clock. Source hashes are checked again
    after reading so a concurrently modified input cannot produce a mixed state.
    Unsupported or contradictory scopes fail explicitly before any posting.
    """
    if not isinstance(grir_account, str) or not re.fullmatch(r"\d{8}", grir_account):
        raise ValueError("explicit eight-digit GR/IR account required")
    data = PhaseData(Path(phase_path))
    source_paths = {stem: _source(data, stem) for stem in _TABLES}
    close_path = data.phase_dir / "tasks" / "close.json"
    if not close_path.resolve().is_relative_to(data.phase_dir):
        raise ValueError("phase clock escapes the active phase")
    close_hash = sha256(close_path.read_bytes()).hexdigest()
    if load_json(close_path)["month"] != data.month:
        raise ValueError("phase clock changed while opening the AP baseline")
    orders, receipts = data.table("purchase_orders"), data.table("goods_receipts")
    # Reuse the catalogue's scope/date/unit validation, rather than relaxing it.
    POCatalog(orders=orders, receipts=receipts)
    order_lines, prices, price_map, position_map, proofs = [], [], {}, {}, {}
    for row in orders:
        for item in row["items"]:
            key = OrderKey(row["company"], row["vendor"], row["currency"], row["id"], item["item"])
            order_lines.append(OrderLine(key, item["uom"]))
            price = OrderPrice(key, item["unit_price"])
            prices.append(price)
            price_map[key] = price
            position = (key.company, key.po, key.item)
            if position in position_map:
                raise ValueError("PO identity has contradictory supplier/currency scope")
            position_map[position] = key
            proofs[key] = Evidence(source_paths["purchase_orders"][1].path,
                                   f"company={key.company};id={key.po};item={key.item}")
    units = {line.key: line.uom for line in order_lines}
    historical_receipts = []
    for row in receipts:
        key = position_map[(row["company"], row["po"], row["po_item"])]
        receipt = Receipt(row["id"], key, row["quantity_milli"], units[key],
                          row["posting_date"], row["type"])
        historical_receipts.append(HistoricalReceipt(receipt, integer(row["amount"]),
            price_map[key].unit_price_cents, (proofs[key],
                Evidence(source_paths["goods_receipts"][1].path,
                         f"company={key.company};id={row['id']}"))))

    links, registered, linked_currencies = {}, {}, {}
    for stem in ("ap_invoices", "ap_document_log"):
        for row in data.table(stem):
            if not row.get("journal_entry"):
                continue
            identity = (row["company"], row["doc_id"])
            journal_key = (row["company"], row["journal_entry"])
            observed = (journal_key, row["vendor"])
            if identity in registered and registered[identity] != observed:
                raise ValueError("invoice/log has contradictory posted identity")
            registered[identity] = observed
            links.setdefault(journal_key, {})[identity] = row["vendor"]
            if row.get("currency") is not None:
                currency = row["currency"]
                if identity in linked_currencies and linked_currencies[identity] != currency:
                    raise ValueError("invoice/log has contradictory posted currency")
                linked_currencies[identity] = currency

    vendor_rows = {row["id"]: row for row in data.table("vendors")}
    vendors = set(vendor_rows)
    demands, recorded, seen, invoice_keys = [], [], set(), set()
    for entry in data.iter_journal():
        identity = (entry["company"], entry["id"])
        if identity in seen:
            raise ValueError("duplicate journal identity")
        seen.add(identity)
        if entry["source"] != "AP":
            if identity in links:
                raise ValueError("registered AP document links a non-AP journal")
            continue
        journal_proof = Evidence(source_paths["journal_entries"][1].path,
                                 f"company={entry['company']};id={entry['id']}")
        document_ids = tuple(sorted(key[1] for key in links.get(identity, {})))
        linked_vendors = set(links.get(identity, {}).values())
        observed_vendors = {line.get("partner") for line in entry["lines"]
                            if line.get("partner") in vendors}
        if linked_vendors - observed_vendors:
            raise ValueError("registered AP vendor is absent from its journal")
        known_currencies = {linked_currencies[key] for key in links.get(identity, {})
                            if key in linked_currencies}
        if len(known_currencies) > 1:
            raise ValueError("registered AP documents have contradictory invoice currencies")
        # Historical journal headers are local currency; 407 applications can
        # also be in local currency. Neither overwrites the invoice's currency.
        supplier_currencies = {line["currency"] for line in entry["lines"]
            if line.get("partner") in vendors and line["account"] in {
                vendor_rows[line["partner"]].get("reconciliation_account"),
                "40000000", "41000000", "40300000", "40000900"}}
        if known_currencies and supplier_currencies and not known_currencies <= supplier_currencies:
            raise ValueError("registered AP currency differs from its supplier line")
        available_currencies = known_currencies or supplier_currencies or {
            line["currency"] for line in entry["lines"]}
        document_currency = next(iter(available_currencies)) if len(available_currencies) == 1 else None
        recorded.append(RecordedAPPosting(entry["company"], entry["id"], document_currency, entry["currency"],
            entry.get("reference", ""), tuple(sorted(observed_vendors)), document_ids, (journal_proof,)))
        for key, vendor in links.get(identity, {}).items():
            if document_currency is None:
                raise ValueError("registered AP document currency is unresolved")
            invoice_keys.add((key[0], vendor, document_currency, key[1]))
        for index, line in enumerate(entry["lines"], 1):
            if line["account"] != grir_account:
                continue
            assignment = line.get("assignment")
            match = re.fullmatch(r"(.+)/([1-9]\d*)", assignment or "")
            if match is None:
                raise ValueError("AP GR/IR line lacks an explicit PO/item assignment")
            position = (entry["company"], match[1], int(match[2]))
            if position not in position_map:
                raise ValueError("AP GR/IR line refers to an unknown PO position")
            key = position_map[position]
            if line.get("partner") != key.vendor or line.get("currency") != key.currency:
                raise ValueError("AP GR/IR supplier/document currency conflicts with its PO")
            debit, credit = integer(line["debit"]), integer(line["credit"])
            if debit < 0 or credit < 0 or (debit and credit):
                raise ValueError("invalid historical AP GR/IR side")
            amount = integer(line["amount_doc"])
            if amount < 0 or (not debit and not credit and amount):
                raise ValueError("invalid historical AP document amount")
            demands.append(HistoricalDemand(key, -amount if credit else amount,
                (proofs[key], journal_proof,
                 Evidence(journal_proof.document, journal_proof.field + f";line={index}"))))
    if set(links) - seen:
        raise ValueError("registered AP document links an absent journal")
    complete = Fact(True, Evidence(source_paths["journal_entries"][1].path,
                                  f"complete_AP_scan;GRIR_account={grir_account};lines={len(demands)}"))
    history = reconcile_receipt_history(tuple(historical_receipts), tuple(demands),
                                        inventory_complete=complete)
    history = replace(history, consumption=ConsumptionState(
        history.consumption.usages, tuple(sorted(invoice_keys))))
    duplicate_records = registered_duplicate_records(data)
    # Replace generic table locators with the actual file paths in this manifest.
    duplicate_records = tuple(replace(row, evidence=tuple(
        Evidence(source_paths[e.document.rsplit('/', 1)[-1]][1].path,
                 f"company={row.company};doc_id={row.doc_id}") for e in row.evidence))
        for row in duplicate_records)
    for path, source in source_paths.values():
        if sha256(path.read_bytes()).hexdigest() != source.sha256:
            raise ValueError("ERP source changed while building the AP baseline")
    if sha256(close_path.read_bytes()).hexdigest() != close_hash:
        raise ValueError("phase clock changed while building the AP baseline")
    sources = tuple(source for _, source in source_paths.values()) + (
        ERPSource("tasks/close.json", close_hash),)
    return APERPBaseline(data.month, sources, tuple(order_lines),
        tuple(r.receipt for r in historical_receipts), tuple(prices), history,
        tuple(recorded), duplicate_records)
