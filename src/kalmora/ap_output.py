"""Validated AP delivery rows and atomic, complete-inventory JSONL export (#55).

Only resolved decisions and monetary inputs are accepted. Extraction, semantic
selection and accounting calculations remain in their owning modules. Evidence
and internal UNKNOWN states belong to the audit, never to the delivery contract.
"""
from collections.abc import Collection, Iterable, Mapping, Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import tempfile

from .ap_rejections import REJECTION_CODES
from .ap_holds import HOLD_CODES
from .evaluation.structure import check_structure
from .model.journal_entry import JournalEntry
from .model.validation_context import ValidationContext
from .money import company_local_currency
from .output_models.ap import ApLine, ApPayee, ApRow
from .validation import validate_entry

NOTICE_ACTIONS = {
    "PROFORMA": "NONE", "VENDOR_STATEMENT": "NONE",
    "FACTORING_NOTICE": "REGISTER_ALTERNATIVE_PAYEE",
    "TAX_GARNISHMENT_ORDER": "REGISTER_EMBARGO",
    "BANK_DETAILS_CHANGE": "UPDATE_BANK_DETAILS",
    "CONTRACTOR_TAX_CERTIFICATE": "UPDATE_CONTRACTOR_CERTIFICATE",
}
POSTING = {"POST", "POST_PAYMENT_BLOCK"}
TRANSACTIONS = {"INVOICE", "CREDIT_NOTE", "DOWN_PAYMENT_REQUEST"}


@dataclass(frozen=True)
class APHeader:
    company: str
    vendor_id: str
    invoice_number: str
    invoice_date: str
    currency: str
    net: int
    tax: int
    gross: int
    withholding: int
    retention: int
    payable: int


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def validate_ap_row(row: ApRow, context: ValidationContext | None = None) -> tuple[str, ...]:
    """Validate shape, decision invariants, dimensions and monetary conservation.

    An explicit header is in document cents, including unsigned credit-note
    amounts. Debit/credit sides carry the reversal. Local-currency cents reside
    in the journal. This check never rounds, recodes or repairs a supplied row.
    """
    if not isinstance(row, dict):
        return ("AP row must be an object",)
    if context is not None:
        if not isinstance(context, Mapping):
            return ("master context must be a mapping",)
        for registry in ("companies", "accounts", "partners", "cost_centers", "wbs"):
            if registry in context:
                records = context[registry]
                if isinstance(records, (str, bytes)) or not isinstance(records, Collection) or any(not isinstance(key, str) for key in records):
                    return (f"master context {registry} must contain reference IDs",)
        for field in ("min_date", "max_date"):
            if field in context and not isinstance(context[field], str):
                return (f"master context {field} must be an ISO date",)
    shape = check_structure({"ap": [row]})
    if shape:
        return tuple(d["message"] for d in shape)
    errors = []
    if set(row) - ApRow.__annotations__.keys():
        errors.append("unexpected AP fields")
    if not _text(row["doc_id"]):
        errors.append("nonempty doc_id required")
    decision, kind = row["decision"], row["document_type"]
    reasons = row["reasons"]
    if decision in {"REJECT", "HOLD"}:
        codes = REJECTION_CODES if decision == "REJECT" else HOLD_CODES
        if len(reasons) != 1 or reasons[0] not in codes:
            errors.append("exactly one policy reason required for REJECT/HOLD")
    elif reasons:
        errors.append("this decision does not carry a rejection/HOLD reason")
    if decision == "NOT_INVOICE":
        if kind not in NOTICE_ACTIONS or row.get("action") != NOTICE_ACTIONS.get(kind):
            errors.append("non-invoice type/action mismatch")
    elif kind not in TRANSACTIONS or row.get("action") is not None:
        errors.append("transaction type/action mismatch")
    if decision == "DUPLICATE":
        if not _text(row.get("duplicate_of")) or row["duplicate_of"] == row["doc_id"]:
            errors.append("duplicate must identify another original document")
    elif row.get("duplicate_of") is not None:
        errors.append("duplicate_of is only valid for DUPLICATE")
    block = row.get("payment_block")
    if (decision == "POST_PAYMENT_BLOCK") != (block == "CONTRACTOR_CERTIFICATE_EXPIRED"):
        errors.append("payment block and decision disagree")
    if decision not in POSTING:
        if "journal_entry" in row or row.get("lines") or row.get("payee") is not None:
            errors.append("non-posting decision cannot carry a journal, coded lines or payee")
        return tuple(errors)
    if kind in {"CREDIT_NOTE", "DOWN_PAYMENT_REQUEST"} and decision != "POST":
        errors.append("credit notes and approved foreign advances require POST")
    for field in ("company", "vendor_id", "invoice_number", "currency"):
        if not _text(row.get(field)):
            errors.append(f"resolved {field} required")
    try:
        local = company_local_currency(row["company"])
    except ValueError:
        errors.append("unsupported posting company")
        local = None
    if not re.fullmatch(r"[A-Z]{3}", row["currency"]):
        errors.append("ISO document currency required")
    for field in ("net", "tax", "gross", "withholding", "retention", "payable"):
        if row[field] < 0:
            errors.append(f"unsigned document cents required: {field}")
    if row["net"] + row["tax"] != row["gross"]:
        errors.append("gross must equal net plus charged tax")
    lines = row["lines"]
    if not lines or sum(line["amount"] for line in lines) != row["net"]:
        errors.append("coded lines must conserve document net")
    for line in lines:
        if set(line) - ApLine.__annotations__.keys():
            errors.append("unexpected coded-line fields")
        account = line["account"]
        if not re.fullmatch(r"[26]\d{7}", account) and not (kind == "DOWN_PAYMENT_REQUEST" and account == "40700000"):
            errors.append("coded line requires expense/asset or advance-request account")
        if account.startswith(("2", "6")) and bool(line.get("cost_center")) == bool(line.get("wbs")):
            errors.append("coded expense/asset requires exactly one cost object")
        if line["amount"] < 0 or not _text(line["tax_code"]):
            errors.append("coded line requires unsigned cents and resolved tax code")
        for field in ("cost_center", "wbs"):
            if line.get(field) is not None and not _text(line[field]):
                errors.append(f"coded-line {field} must be nonempty or null")
        po, item = line.get("po"), line.get("po_item")
        if (po is None) != (item is None) or (po is not None and (not _text(po) or item <= 0)):
            errors.append("PO number and positive position must be paired")
        if context:
            for field, registry in (("account", "accounts"), ("cost_center", "cost_centers"), ("wbs", "wbs")):
                value = line.get(field)
                if value is not None and registry in context:
                    records = context[registry]
                    if value not in records:
                        errors.append(f"unknown coded-line {field}")
                    elif isinstance(records, dict) and isinstance(records[value], dict) and records[value].get("company", row["company"]) != row["company"]:
                        errors.append(f"coded-line {field} belongs to another company")
    entry = row["journal_entry"]
    errors.extend(validate_entry(entry, context))
    dimensions = {(line["account"], line.get("cost_center"), line.get("wbs")) for line in lines}
    monetary_accounts = {"40000000", "41000000", "40300000", "40700000", "40000900",
                         "47200000", "47210000", "47710000", "47510000", "66800000", "76800000"}
    if any(line.get("po") is not None for line in lines):
        monetary_accounts.add("40090000")
    signed_base = 0
    for line in entry["lines"]:
        if "amount_doc" in line and line["amount_doc"] < 0:
            errors.append("journal document cents must be unsigned")
        if line.get("currency", row["currency"]) == local and "amount_doc" in line and line["amount_doc"] != max(line["debit"], line["credit"]):
            errors.append("local-currency journal document cents differ from debit/credit")
        if line["account"].startswith(("400", "410", "403", "407")) and line.get("partner") != row["vendor_id"]:
            errors.append("AP journal partner differs from header vendor")
        if line["account"].startswith(("2", "6")) and line["account"] not in {"66800000", "76800000"}:
            if (line["account"], line.get("cost_center"), line.get("wbs")) not in dimensions:
                errors.append("journal base imputation is absent from coded lines")
            signed_base += line["debit"] - line["credit"]
        elif line["account"] == "40090000":
            if "40090000" not in monetary_accounts:
                errors.append("GR/IR requires an explicitly coded PO portion")
            positions = {f"{coded['po']}/{coded['po_item']}" for coded in lines if coded.get("po") is not None}
            if line.get("assignment") is not None and line["assignment"] not in positions:
                errors.append("GR/IR assignment differs from coded PO positions")
            signed_base += line["debit"] - line["credit"]
        elif line["account"] not in monetary_accounts:
            errors.append("account is outside the AP journal components")
    if kind == "CREDIT_NOTE" and signed_base > 0 or kind == "INVOICE" and signed_base < 0:
        errors.append("journal base side contradicts invoice/credit-note type")
    if kind == "DOWN_PAYMENT_REQUEST":
        accounts = {line["account"] for line in entry["lines"]}
        advance_lines = [line for line in entry["lines"] if line["account"] == "40700000"]
        if accounts != {"40700000", "40000000"} or len(entry["lines"]) != 2 or len(advance_lines) != 1 or advance_lines[0]["credit"] or advance_lines[0]["debit"] <= 0:
            errors.append("advance request requires only Dr407 / Cr400")
        elif advance_lines[0].get("amount_doc", advance_lines[0]["debit"] if row["currency"] == local else None) != row["net"]:
            errors.append("advance request document amount differs from header")
        if row["tax"] or row["withholding"] or row["retention"]:
            errors.append("advance request cannot invent fiscal deductions or VAT")
    if entry["company"] != row["company"]:
        errors.append("journal company differs from header")
    for field, expected in (("currency", row["currency"]), ("document_date", row["invoice_date"]), ("reference", row["invoice_number"])):
        if field in entry and entry[field] != expected:
            errors.append(f"journal {field} differs from header")
    suppliers = [line for line in entry["lines"] if line["account"] in {"40000000", "41000000", "40300000"}]
    if len(suppliers) != 1 or suppliers[0].get("partner") != row["vendor_id"]:
        errors.append("exactly one scoped supplier line required")
    else:
        supplier = suppliers[0]
        doc_amount = supplier.get("amount_doc")
        if doc_amount is None and row["currency"] == local:
            doc_amount = max(supplier["debit"], supplier["credit"])
        expected_side = "debit" if kind == "CREDIT_NOTE" else "credit"
        other_side = "credit" if expected_side == "debit" else "debit"
        if supplier[other_side] or doc_amount != row["payable"]:
            errors.append("supplier side/document payable differs from header")
        if supplier.get("currency", row["currency"]) != row["currency"]:
            errors.append("supplier currency differs from header")
        for line in entry["lines"]:
            # Factory-generated non-monetary/monetary advance adjustments are
            # in local currency. Other AP base/tax/supplier legs stay in the
            # document currency; this exporter does not infer a new FX scope.
            if line.get("currency", row["currency"]) not in {row["currency"], local}:
                errors.append("journal line currency is outside invoice/local scope")
        if supplier.get("assignment") not in (None, row["invoice_number"]):
            errors.append("supplier assignment differs from invoice number")
    applied = [line for line in entry["lines"] if line["account"] == "40700000" and line["credit"]]
    if any(type(line.get("amount_doc")) is not int or line.get("currency", row["currency"]) != row["currency"] for line in applied):
        errors.append("advance applications require scoped document cents")
    else:
        advance = sum(line["amount_doc"] for line in applied)
        if row["gross"] - row["withholding"] - row["retention"] - advance != row["payable"]:
            errors.append("payable does not conserve gross less deductions and applied advances")
    return tuple(errors)


def build_ap_row(*, doc_id: str, document_type: str, decision: str,
                 reasons: Sequence[str] = (), header: APHeader | None = None,
                 lines: Sequence[ApLine] | None = None, journal_entry: JournalEntry | None = None,
                 duplicate_of: str | None = None, payee: ApPayee | None = None,
                 payment_block: str | None = None, action: str | None = None,
                 context: ValidationContext | None = None) -> ApRow:
    row = {"doc_id": doc_id, "document_type": document_type, "decision": decision,
           "reasons": list(reasons)}
    if header is not None:
        row.update(asdict(header))
    for key, value in (("lines", list(lines) if lines is not None else None), ("journal_entry", journal_entry),
                       ("duplicate_of", duplicate_of), ("payee", payee), ("payment_block", payment_block), ("action", action)):
        if value is not None:
            row[key] = deepcopy(value)
    errors = validate_ap_row(row, context)
    if errors:
        raise ValueError("; ".join(errors))
    return row


def write_ap_jsonl(path: Path, rows: Iterable[ApRow], *, expected_doc_ids: Iterable[str],
                   context: ValidationContext | None = None, overwrite: bool = False) -> None:
    """Validate the entire task inventory before writing any destination bytes.

    Sort by task ID for reproducibility. A missing, extra, duplicate, unresolved
    or invalid result fails before replacing output. The caller commits journal
    and receipt/advance states separately; serializing is not ledger posting.
    """
    expected = tuple(expected_doc_ids)
    if any(not _text(doc) for doc in expected) or len(set(expected)) != len(expected):
        raise ValueError("unique nonempty expected task IDs required")
    records = {}
    for original in rows:
        row = deepcopy(original)
        errors = validate_ap_row(row, context)
        if errors:
            raise ValueError("; ".join(errors))
        if row["doc_id"] in records:
            raise ValueError("duplicate output document")
        records[row["doc_id"]] = row
    if set(records) != set(expected):
        raise ValueError(f"AP coverage mismatch: missing={sorted(set(expected)-set(records))}, extra={sorted(set(records)-set(expected))}")
    payload = "".join(json.dumps(records[doc], ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n" for doc in sorted(records))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=".ap-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary, path)
        else:
            # Exclusive atomic creation also guards against a destination race.
            os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
