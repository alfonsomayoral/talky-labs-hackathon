"""Deterministic AP coding from explicit context and validated masters (#45).

Per-field precedence: document, confirmed PO, contextual historical records,
vendor defaults. A cost object is one indivisible CC/WBS choice. No voting,
latest-record preference, fuzzy concepts, amount matching or golden reads.
"""
from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from typing import Any

from .facts import Evidence
from .ap_allocation import OrderKey

_WITHHOLDING_COUNTRIES = {"IRPF15": "ES", "IRPF7": "ES", "IRPF19": "ES",
                         "MXISR10": "MX", "MXIVAR": "MX", "MXFLETE": "MX", "PTIRS25": "PT"}


@dataclass(frozen=True)
class CostObject:
    cost_center: str | None = None
    wbs: str | None = None


@dataclass(frozen=True)
class CodingRecord:
    company: str
    vendor: str
    currency: str
    account: str | None = None
    tax_code: str | None = None
    reconciliation_account: str | None = None
    cost_center: str | None = None
    wbs: str | None = None
    evidence: tuple[Evidence, ...] = ()
    recorded_on: str | None = None
    context: str | None = None
    withholding_codes: tuple[str, ...] | None = None  # None unknown; () explicitly none


@dataclass(frozen=True)
class CodingQuery:
    company: str
    vendor: str
    currency: str
    invoice_date: str
    project: str | None = None
    context: str | None = None


@dataclass(frozen=True)
class FieldResolution:
    field: str
    status: str  # RESOLVED, MISSING, AMBIGUOUS, INVALID
    value: str | CostObject | tuple[str, ...] | None
    candidates: tuple[str | CostObject | tuple[str, ...], ...]
    source: str | None
    evidence: tuple[Evidence, ...]
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class CodingResult:
    status: str  # RESOLVED, INCOMPLETE, AMBIGUOUS, INVALID
    record: CodingRecord | None
    fields: tuple[FieldResolution, ...]


def _day(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError("canonical ISO date required")
    return value


def _text(value):
    if not isinstance(value, str) or not value:
        raise ValueError("nonempty scope/field required")
    return value


def _context(value):
    result = " ".join(_text(value).casefold().split())
    return _text(result)


def _index(rows, identity):
    result = {}
    for row in deepcopy(tuple(rows)):
        key = _text(row[identity])
        if key in result:
            raise ValueError("duplicate master identity")
        result[key] = row
    return result


def _withholding(row):
    value = row.get("withholding")
    return (None if "withholding" not in row else () if value is None
            else tuple(value.split("+")) if isinstance(value, str) else value)


class CodingCatalog:
    """Independent master snapshot and evidence-preserving historical candidates."""

    def __init__(self, *, companies: Iterable[Mapping[str, Any]],
                 vendors: Iterable[Mapping[str, Any]], accounts: Iterable[Mapping[str, Any]],
                 cost_centers: Iterable[Mapping[str, Any]], projects: Iterable[Mapping[str, Any]],
                 tax_codes: Mapping[str, Any], history: Iterable[CodingRecord] = (),
                 orders: Iterable[Mapping[str, Any]] = ()):
        self._companies = _index(companies, "code")
        self._vendors = _index(vendors, "id")
        self._accounts = _index(accounts, "account")
        self._centers = _index(cost_centers, "id")
        self._projects = _index(projects, "id")
        self._wbs = {}
        for project_id, project in self._projects.items():
            if project["company"] not in self._companies:
                raise ValueError("project company missing from master")
            for item in project.get("wbs", ()):
                identity = _text(item["id"])
                if identity in self._wbs:
                    raise ValueError("duplicate WBS master identity")
                self._wbs[identity] = (project["company"], project_id)
        self._tax = deepcopy(tax_codes["tax_codes"])
        self._withholdings = deepcopy(tax_codes.get("withholdings", {}))
        self._orders = {}
        for order in deepcopy(tuple(orders)):
            for item in order["items"]:
                key = OrderKey(order["company"], order["vendor"], order["currency"], order["id"], item["item"])
                if key in self._orders:
                    raise ValueError("duplicate PO position")
                self._orders[key] = item
        self._history = tuple(history)
        for record in self._history:
            self._record(record)
            _day(record.recorded_on)

    @staticmethod
    def _record(record):
        if not isinstance(record, CodingRecord):
            raise TypeError("coding sources require CodingRecord")
        for value in (record.company, record.vendor, record.currency):
            _text(value)
        if not isinstance(record.evidence, tuple) or not record.evidence or any(
                not isinstance(item, Evidence) for item in record.evidence):
            raise ValueError("coding record requires immutable source evidence")
        if record.context is not None:
            _context(record.context)

    def _validate(self, field, value, query):
        if field == "withholding_codes":
            if (not isinstance(value, tuple) or any(not isinstance(code, str) for code in value)
                    or len(set(value)) != len(value)):
                return "INVALID_WITHHOLDING_CODES"
            if len(value) > 1 and set(value) != {"MXISR10", "MXIVAR"}:
                return "INCOMPATIBLE_WITHHOLDING_CODES"
            for code in value:
                if code not in self._withholdings or code not in _WITHHOLDING_COUNTRIES:
                    return "UNKNOWN_WITHHOLDING_CODE"
                if _WITHHOLDING_COUNTRIES[code] != self._companies[query.company].get("country"):
                    return "WITHHOLDING_COUNTRY_MISMATCH"
            return None
        if field == "cost_object":
            center, wbs = value.cost_center, value.wbs
            if (center is None) == (wbs is None):
                return "EXACTLY_ONE_COST_OBJECT_REQUIRED"
            if center is not None:
                if not isinstance(center, str) or center not in self._centers:
                    return "UNKNOWN_COST_CENTER"
                if self._centers[center].get("company") != query.company:
                    return "COST_CENTER_COMPANY_MISMATCH"
                if query.project is not None:
                    return "PROJECT_REQUIRES_WBS"
            else:
                if not isinstance(wbs, str) or wbs not in self._wbs:
                    return "UNKNOWN_WBS"
                owner, project = self._wbs[wbs]
                if owner != query.company:
                    return "WBS_COMPANY_MISMATCH"
                if query.project is not None and project != query.project:
                    return "WBS_PROJECT_MISMATCH"
            return None
        if not isinstance(value, str) or not value:
            return "INVALID_FIELD_TYPE"
        if field == "account":
            if (value not in self._accounts or len(value) != 8 or not value.isascii()
                    or not value.isdigit() or not value.startswith(("2", "6"))):
                return "UNKNOWN_OR_NON_EXPENSE_ASSET_ACCOUNT"
        elif field == "reconciliation_account":
            if value not in self._accounts or value not in {"40000000", "41000000", "40300000"}:
                return "UNKNOWN_OR_NON_SUPPLIER_ACCOUNT"
        else:
            row = self._tax.get(value)
            if row is None or row.get("kind") not in {"input", "reverse", "import", "exempt", "nondeductible"}:
                return "UNKNOWN_OR_NON_AP_TAX_CODE"
            if row.get("country") != self._companies[query.company].get("country"):
                return "TAX_COUNTRY_MISMATCH"
        return None

    def _field(self, name, tiers, query):
        for source, records in tiers:
            values, evidence = [], []
            for record in records:
                value = (CostObject(record.cost_center, record.wbs) if name == "cost_object"
                         and (record.cost_center is not None or record.wbs is not None)
                         else None if name == "cost_object" else getattr(record, name))
                if value is not None:
                    if value not in values:
                        values.append(value)
                    evidence.extend(record.evidence)
            if not values:
                continue
            errors = tuple(error for value in values if (error := self._validate(name, value, query)))
            if errors:
                return FieldResolution(name, "INVALID", None, tuple(values), source, tuple(evidence), errors)
            if len(values) > 1:
                return FieldResolution(name, "AMBIGUOUS", None, tuple(values), source, tuple(evidence))
            return FieldResolution(name, "RESOLVED", values[0], tuple(values), source, tuple(evidence))
        return FieldResolution(name, "MISSING", None, (), None, ())

    def resolve(self, query: CodingQuery, *, document: Iterable[CodingRecord] = (),
                order: Iterable[CodingRecord] = ()) -> CodingResult:
        """Resolve each field independently; invalid/ambiguous higher tiers never fall back."""
        for value in (query.company, query.vendor, query.currency):
            _text(value)
        _day(query.invoice_date)
        if query.company not in self._companies:
            raise ValueError("unknown company")
        if query.project is not None and (query.project not in self._projects or
                self._projects[query.project]["company"] != query.company):
            raise ValueError("unknown or foreign project")
        if query.context is not None:
            _context(query.context)
        document, order = tuple(document), tuple(order)
        for record in (*document, *order):
            self._record(record)
            if (record.company, record.vendor, record.currency) != (query.company, query.vendor, query.currency):
                raise ValueError("coding source scope differs from query")
        history = []
        if query.context is not None:
            for record in self._history:
                if ((record.company, record.vendor, record.currency) != (query.company, query.vendor, query.currency)
                        or record.recorded_on >= query.invoice_date or record.context is None
                        or _context(record.context) != _context(query.context)):
                    continue
                # Historical objects outside explicit project/company context
                # provide no evidence for this invoice's coding.
                obj = CostObject(record.cost_center, record.wbs)
                if (record.cost_center is not None or record.wbs is not None) and self._validate("cost_object", obj, query):
                    continue
                history.append(record)
        defaults = ()
        vendor = self._vendors.get(query.vendor)
        if vendor is not None:
            proof = tuple(Evidence("erp/vendors.jsonl", f"id={query.vendor}.{name}") for name in
                ("default_gl_account", "default_tax_code", "reconciliation_account",
                 "default_cost_center", "default_wbs", "withholding") if name in vendor)
            defaults = (CodingRecord(query.company, query.vendor, query.currency,
                vendor.get("default_gl_account"), vendor.get("default_tax_code"),
                vendor.get("reconciliation_account"), vendor.get("default_cost_center"),
                vendor.get("default_wbs"), proof,
                withholding_codes=_withholding(vendor)),)
        tiers = (("document", document), ("order", order), ("history", tuple(history)), ("vendor", defaults))
        fields = tuple(self._field(name, tiers, query) for name in
                       ("account", "tax_code", "reconciliation_account", "cost_object", "withholding_codes"))
        statuses = {field.status for field in fields}
        status = ("INVALID" if "INVALID" in statuses else "AMBIGUOUS" if "AMBIGUOUS" in statuses
                  else "INCOMPLETE" if "MISSING" in statuses else "RESOLVED")
        record = None
        if status == "RESOLVED":
            values = {field.field: field.value for field in fields}
            obj = values["cost_object"]
            evidence = tuple(item for field in fields for item in field.evidence)
            record = CodingRecord(query.company, query.vendor, query.currency,
                values["account"], values["tax_code"], values["reconciliation_account"],
                obj.cost_center, obj.wbs, evidence, context=query.context,
                withholding_codes=values["withholding_codes"])
        return CodingResult(status, record, fields)

    def order_record(self, key: OrderKey, *, evidence: tuple[Evidence, ...]) -> CodingRecord:
        """Read coding for a position explicitly confirmed by #43, preserving proof.

        No candidate retrieval/reference recovery occurs here. Pass the confirmed
        position and its source relationship evidence, not a guessed order key.
        """
        item = self._orders[key]
        result = CodingRecord(key.company, key.vendor, key.currency, item.get("gl_account"),
            item.get("tax_code"), item.get("reconciliation_account"), item.get("cost_center"),
            item.get("wbs"), evidence + (Evidence("erp/purchase_orders.jsonl", f"id={key.po}.item={key.item}"),),
            withholding_codes=_withholding(item))
        if not evidence:
            raise ValueError("confirmed PO relationship evidence required")
        self._record(result)
        return result

    @classmethod
    def from_phase(cls, data) -> "CodingCatalog":
        """Join recorded AP invoices to expense/asset journal lines; never read golden.

        Historical visibility starts only after issue/receipt/posting dates. Each
        concept is the source journal text, compared exactly apart from case and
        whitespace; shortened texts cannot be expanded into invented concepts.
        """
        invoices = {}
        for invoice in data.table("ap_invoices"):
            journal_id = invoice.get("journal_entry")
            if journal_id and invoice.get("decision") in {"POST", "POST_PAYMENT_BLOCK"}:
                key = (invoice["company"], journal_id)
                if key in invoices:
                    raise ValueError("ambiguous AP invoice to journal join")
                invoices[key] = invoice
        history = []
        for entry in data.iter_journal():
            invoice = invoices.get((entry["company"], entry["id"]))
            if invoice is None:
                continue
            dates = [_day(invoice[name]) for name in ("issue_date", "received_on", "posted_on")]
            dates.append(_day(entry["posting_date"]))
            reconciliation = {}
            for index, line in enumerate(entry["lines"], 1):
                if (line.get("partner") == invoice["vendor"] and
                        line["account"] in {"40000000", "41000000", "40300000"}):
                    reconciliation.setdefault(line["account"], []).append(Evidence(
                        "erp/journal_entries.jsonl", f"id={entry['id']}#line={line.get('line', index)}.account"))
            for index, line in enumerate(entry["lines"], 1):
                if not line["account"].startswith(("2", "6")):
                    continue
                if line.get("currency", invoice["currency"]) != invoice["currency"]:
                    continue
                evidence = (Evidence("erp/ap_invoices.jsonl", f"doc_id={invoice['doc_id']}"),
                            Evidence("erp/journal_entries.jsonl", f"id={entry['id']}#line={line.get('line', index)}"))
                for account in sorted(reconciliation) or (None,):
                    history.append(CodingRecord(invoice["company"], invoice["vendor"], invoice["currency"],
                        line["account"], line.get("tax_code"), account, line.get("cost_center"), line.get("wbs"),
                        evidence + tuple(reconciliation.get(account, ())), max(dates), line.get("text") or None))
        return cls(companies=data.companies, vendors=data.table("vendors"),
                   accounts=data.table("chart_of_accounts"), cost_centers=data.table("cost_centers"),
                   projects=data.table("projects"), tax_codes=data.table("tax_codes"), history=history,
                   orders=data.table("purchase_orders"))
