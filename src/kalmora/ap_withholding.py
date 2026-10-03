"""AP tax withholdings and contractual guarantees (policies §2.3).

MXIVAR uses the catalogue's 1067 basis points, established by ERP history;
it is not calculated as two thirds of the rounded VAT quota. No AR deductions.
"""
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from .ap_tax import PostingDecision, fiscal_line, local_amount, nonnegative, require_posting
from .model.journal_line import JournalLine
from .money import RateTable, integer, round_cents

_COUNTRIES = {"IRPF15": "ES", "IRPF7": "ES", "IRPF19": "ES",
              "MXISR10": "MX", "MXIVAR": "MX", "MXFLETE": "MX", "PTIRS25": "PT"}


@dataclass(frozen=True)
class WithholdingCode:
    country: str
    rate: int
    account: str


class WithholdingCatalog:
    def __init__(self, source: Mapping[str, Any]) -> None:
        self._codes: dict[str, WithholdingCode] = {}
        for code, row in source["withholdings"].items():
            if code not in _COUNTRIES:
                raise ValueError(f"unsupported AP withholding: {code}")
            rate = integer(row["rate"], "withholding rate")
            account = row["account"]
            if (not 0 <= rate <= 10000 or not isinstance(account, str)
                    or len(account) != 8 or not account.isdigit()):
                raise ValueError("invalid withholding catalogue rate/account")
            self._codes[code] = WithholdingCode(_COUNTRIES[code], rate, account)

    def get(self, code: str, country: str) -> WithholdingCode:
        try:
            treatment = self._codes[code]
        except KeyError:
            raise ValueError(f"unknown AP withholding code: {code}") from None
        if treatment.country != country:
            raise ValueError("withholding country differs from posting company country")
        return treatment


@dataclass(frozen=True)
class WithholdingSelection:
    codes: tuple[str, ...]
    source: Literal["document", "order", "vendor"]


def _codes(codes: tuple[str, ...]) -> None:
    if not isinstance(codes, tuple):
        raise TypeError("withholding codes must be a tuple")
    if any(not isinstance(c, str) or not c for c in codes) or len(set(codes)) != len(codes):
        raise ValueError("unique nonempty withholding codes required")
    if len(codes) > 1 and set(codes) != {"MXISR10", "MXIVAR"}:
        raise ValueError("unsupported simultaneous withholdings on the same base")


def select_withholdings(*, document: tuple[str, ...] | None = None,
                        order: tuple[str, ...] | None = None,
                        vendor: str | None = None) -> WithholdingSelection:
    """Resolve confirmed document/PO treatment ahead of the vendor default.

    Vendor strings use the package's '+' notation. An empty document tuple means
    confirmed no withholding, not an omitted/undetected withholding. Mandatory
    withholding checks and WITHHOLDING_MISSING precedence remain upstream.
    """
    for source, codes in (("document", document), ("order", order)):
        if codes is not None:
            _codes(codes)
            return WithholdingSelection(codes, source)
    if vendor is not None and (not isinstance(vendor, str) or not vendor):
        raise ValueError("vendor withholding must be nonempty text or null")
    codes = tuple(vendor.split("+")) if vendor is not None else ()
    _codes(codes)
    return WithholdingSelection(codes, "vendor")


@dataclass(frozen=True)
class WithholdingBase:
    line_id: str
    base_doc: int
    codes: tuple[str, ...]


@dataclass(frozen=True)
class ContractGuarantee:
    base_doc: int
    contract_reference: str
    rate: int = 500


@dataclass(frozen=True)
class WithholdingComponent:
    kind: Literal["WITHHOLDING", "GUARANTEE"]
    line_id: str | None
    code: str | None
    base_doc: int
    amount_doc: int
    amount_local: int
    journal_line: JournalLine
    contract_reference: str | None = None


@dataclass(frozen=True)
class WithholdingResult:
    withholding_doc: int
    withholding_local: int
    retention_doc: int
    retention_local: int
    components: tuple[WithholdingComponent, ...]

    @property
    def deduction_doc(self) -> int:
        return self.withholding_doc + self.retention_doc

    @property
    def deduction_local(self) -> int:
        return self.withholding_local + self.retention_local


def calculate_ap_withholdings(*, company: str, country: str, vendor: str,
                              currency: str, invoice_date: str, invoice_number: str,
                              decision: PostingDecision, bases: Iterable[WithholdingBase],
                              catalog: WithholdingCatalog, guarantee: ContractGuarantee | None = None,
                              rates: RateTable | None = None) -> WithholdingResult:
    """Unsigned credits to deduct from supplier gross; no final journal posting.

    Bases are explicit fiscal base groups; never apply withholding to gross/VAT.
    A guarantee exists only with explicit contract evidence and uses its eligible
    base. Return no zero-amount journal lines. Reverse credit notes downstream.
    """
    require_posting(decision)
    local_amount(0, company, currency, invoice_date, rates)
    expected_country = "MX" if company == "3100" else "PT" if company == "2100" else "ES"
    if country != expected_country:
        raise ValueError("country differs from the supported posting company's master")
    for value in (vendor, invoice_number):
        if not isinstance(value, str) or not value:
            raise ValueError("resolved vendor and invoice number required")
    seen: set[str] = set()
    components: list[WithholdingComponent] = []
    for base in bases:
        if not isinstance(base.line_id, str) or not base.line_id or base.line_id in seen:
            raise ValueError("unique nonempty withholding base id required")
        seen.add(base.line_id)
        amount = nonnegative(base.base_doc, "withholding base")
        _codes(base.codes)
        for code in base.codes:
            treatment = catalog.get(code, country)
            quota = round_cents(Decimal(amount) * treatment.rate / 10000)
            if not quota:
                continue
            converted = local_amount(quota, company, currency, invoice_date, rates)
            line = fiscal_line(treatment.account, quota, converted, currency, code,
                               credit=True, partner=vendor)
            components.append(WithholdingComponent("WITHHOLDING", base.line_id, code,
                                                   amount, quota, converted, line))
    if guarantee is not None:
        amount = nonnegative(guarantee.base_doc, "guarantee base")
        if integer(guarantee.rate, "guarantee rate") != 500:
            raise ValueError("AP guarantee policy supports the contractual 5% rate")
        if not isinstance(guarantee.contract_reference, str) or not guarantee.contract_reference:
            raise ValueError("explicit guarantee contract reference required")
        quota = round_cents(Decimal(amount) * guarantee.rate / 10000)
        if quota:
            converted = local_amount(quota, company, currency, invoice_date, rates)
            line = fiscal_line("40000900", quota, converted, currency, None, credit=True,
                               partner=vendor, assignment=invoice_number)
            components.append(WithholdingComponent("GUARANTEE", None, None,
                                                   amount, quota, converted, line,
                                                   guarantee.contract_reference))
    withholding = [c for c in components if c.kind == "WITHHOLDING"]
    retention = [c for c in components if c.kind == "GUARANTEE"]
    return WithholdingResult(sum(c.amount_doc for c in withholding), sum(c.amount_local for c in withholding),
                             sum(c.amount_doc for c in retention), sum(c.amount_local for c in retention),
                             tuple(components))
