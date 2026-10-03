"""AP fiscal components from the active package catalogue (policies §1, §2.3).

Inputs are resolved facts, not extracted documents. This module neither decides
invoice eligibility nor posts base/settlement lines. Import VAT is a separate
DUA disbursement with zero expense base; never derive it from freight charges.
"""
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from .model.journal_line import JournalLine
from .money import RateTable, company_local_currency, integer, round_cents

type PostingDecision = Literal["POST", "POST_PAYMENT_BLOCK"]


@dataclass(frozen=True)
class TaxCode:
    country: str
    kind: str
    rate: int


class TaxCatalog:
    """Validated AP subset of erp/tax_codes.json; AR codes remain unavailable."""

    def __init__(self, source: Mapping[str, Any]) -> None:
        self._codes: dict[str, TaxCode] = {}
        for code, row in source["tax_codes"].items():
            if row["kind"] not in {"input", "reverse", "import", "exempt", "nondeductible"}:
                continue
            rate = integer(row["rate"], "tax rate")
            if not 0 <= rate <= 10000 or row["country"] not in {"ES", "PT", "MX"}:
                raise ValueError("invalid AP catalogue country/rate")
            if row["kind"] == "exempt" and rate != 0:
                raise ValueError("exempt code must have zero rate")
            self._codes[code] = TaxCode(row["country"], row["kind"], rate)

    def get(self, code: str, country: str) -> TaxCode:
        try:
            treatment = self._codes[code]
        except KeyError:
            raise ValueError(f"unknown or non-AP tax code: {code}") from None
        if treatment.country != country:
            raise ValueError("tax country differs from posting company country")
        return treatment


@dataclass(frozen=True)
class TaxSelection:
    code: str
    source: Literal["document", "order", "vendor"]


def select_tax_code(*, document: str | None = None, order: str | None = None,
                    vendor: str | None = None) -> TaxSelection:
    """Explicit document/PO evidence overrides the vendor default (§1).

    Contradictions must be resolved upstream; do not pass an unconfirmed code.
    An explicit but invalid code must fail, not silently fall back to a default.
    """
    for source, code in (("document", document), ("order", order), ("vendor", vendor)):
        if code is not None:
            if not isinstance(code, str) or not code:
                raise ValueError("tax code must be nonempty text")
            return TaxSelection(code, source)
    raise ValueError("missing resolved tax treatment")


@dataclass(frozen=True)
class TaxLine:
    line_id: str
    base_doc: int
    tax_code: str
    account: str | None = None
    cost_center: str | None = None
    wbs: str | None = None
    tax_doc: int | None = None
    dua_reference: str | None = None


@dataclass(frozen=True)
class TaxComponent:
    line_id: str
    tax_code: str
    base_doc: int
    base_local: int
    tax_doc: int
    tax_local: int
    gross_doc: int
    journal_lines: tuple[JournalLine, ...]


@dataclass(frozen=True)
class TaxResult:
    net_doc: int
    tax_doc: int
    gross_doc: int
    net_local: int
    tax_local: int
    components: tuple[TaxComponent, ...]


def require_posting(decision: PostingDecision) -> None:
    if decision not in {"POST", "POST_PAYMENT_BLOCK"}:
        raise ValueError("fiscal posting requires an explicit eligible decision")


def nonnegative(value: int, name: str) -> int:
    if integer(value, name) < 0:
        raise ValueError(f"{name} must be nonnegative; reverse credit notes downstream")
    return value


def local_amount(amount: int, company: str, currency: str, invoice_date: str,
                 rates: RateTable | None) -> int:
    local_currency = company_local_currency(company)
    if date.fromisoformat(invoice_date).isoformat() != invoice_date:
        raise ValueError("invoice date must use YYYY-MM-DD")
    if not isinstance(currency, str) or not currency:
        raise ValueError("document currency required")
    if currency == local_currency:
        return amount
    if rates is None:
        raise ValueError("foreign-currency fiscal lines require invoice-date FX rates")
    return rates.to_local(amount, currency, company, invoice_date)


def fiscal_line(account: str, amount_doc: int, amount_local: int, currency: str,
                code: str | None, *, credit: bool = False,
                partner: str | None = None, cost_center: str | None = None,
                wbs: str | None = None, assignment: str | None = None) -> JournalLine:
    return {"account": account, "debit": 0 if credit else amount_local,
            "credit": amount_local if credit else 0, "currency": currency,
            "amount_doc": amount_doc, "tax_code": code, "partner": partner,
            "cost_center": cost_center, "wbs": wbs, "assignment": assignment}


def calculate_ap_tax(*, company: str, country: str, currency: str,
                     invoice_date: str, decision: PostingDecision,
                     lines: Iterable[TaxLine], catalog: TaxCatalog,
                     rates: RateTable | None = None) -> TaxResult:
    """Calculate each resolved fiscal base, then convert its posting per line.

    ``tax_doc`` is the document's charged VAT (zero for reverse/exempt). If
    supplied it must match the exact catalogue calculation; invoice validation
    and its rejection precedence belong upstream. Reverse-charge ``tax_local``
    is self-assessed VAT while result.tax_doc excludes it. Fiscal grouping/base
    resolution belongs to the caller; no implicit regrouping changes rounding.
    """
    require_posting(decision)
    local_amount(0, company, currency, invoice_date, rates)
    expected_country = "MX" if company == "3100" else "PT" if company == "2100" else "ES"
    if country != expected_country:
        raise ValueError("country differs from the supported posting company's master")
    components: list[TaxComponent] = []
    seen: set[str] = set()
    for item in lines:
        if not isinstance(item.line_id, str) or not item.line_id or item.line_id in seen:
            raise ValueError("unique nonempty fiscal line id required")
        seen.add(item.line_id)
        base = nonnegative(item.base_doc, "tax base")
        treatment = catalog.get(item.tax_code, country)
        quota = round_cents(Decimal(base) * treatment.rate / 10000)
        if treatment.kind == "import":
            if (base != 0 or item.tax_doc is None or not isinstance(item.dua_reference, str)
                    or not item.dua_reference):
                raise ValueError("import VAT requires a zero-base DUA disbursement and explicit quota/reference")
            quota = nonnegative(item.tax_doc, "DUA VAT")
        charged = 0 if treatment.kind in {"reverse", "exempt"} else quota
        if item.tax_doc is not None and nonnegative(item.tax_doc, "document VAT") != charged:
            raise ValueError("document VAT differs from resolved fiscal treatment")
        base_local = local_amount(base, company, currency, invoice_date, rates)
        tax_local = local_amount(quota, company, currency, invoice_date, rates)
        postings: list[JournalLine] = []
        if quota:
            if treatment.kind == "reverse":
                postings = [fiscal_line("47210000", quota, tax_local, currency, item.tax_code),
                            fiscal_line("47710000", quota, tax_local, currency, item.tax_code, credit=True)]
            elif treatment.kind == "nondeductible":
                if (not isinstance(item.account, str) or len(item.account) != 8 or not item.account.isdigit()
                        or not item.account.startswith(("6", "2"))
                        or bool(item.cost_center) == bool(item.wbs)):
                    raise ValueError("non-deductible VAT requires expense/asset account and one resolved cost object")
                for value in (item.cost_center, item.wbs):
                    if value is not None and (not isinstance(value, str) or not value):
                        raise ValueError("invalid non-deductible VAT cost object")
                postings = [fiscal_line(item.account, quota, tax_local, currency, item.tax_code,
                                        cost_center=item.cost_center, wbs=item.wbs)]
            else:
                postings = [fiscal_line("47200000", quota, tax_local, currency, item.tax_code,
                                        assignment=item.dua_reference if treatment.kind == "import" else None)]
        components.append(TaxComponent(item.line_id, item.tax_code, base, base_local,
                                       charged, tax_local, base + charged, tuple(postings)))
    if not components:
        raise ValueError("at least one resolved fiscal line required")
    return TaxResult(sum(c.base_doc for c in components), sum(c.tax_doc for c in components),
                     sum(c.gross_doc for c in components), sum(c.base_local for c in components),
                     sum(c.tax_local for c in components), tuple(components))
