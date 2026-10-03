"""Immutable original-invoice credit limits in document cents, scoped by source."""
from collections.abc import Iterable
from dataclasses import dataclass, replace
import hashlib
import json
import re

from .money import company_local_currency, integer


@dataclass(frozen=True)
class CreditBalance:
    company: str
    vendor: str
    currency: str
    original_id: str
    original_sha256: str
    bucket: str
    capacity_doc: int
    used_doc: int


@dataclass(frozen=True)
class CreditReservation:
    original_id: str
    original_sha256: str
    bucket: str
    capacity_doc: int
    amount_doc: int


def original_credit_sha256(entry: dict) -> str:
    """Pin the exact journal snapshot, including line order and source identity."""
    payload = json.dumps(entry, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _values(record):
    for field in ("original_id", "bucket"):
        if not isinstance(getattr(record, field), str) or not getattr(record, field).strip():
            raise ValueError("credit balance requires exact original/bucket identity")
    if not isinstance(record.original_sha256, str) or not re.fullmatch("[0-9a-f]{64}", record.original_sha256):
        raise ValueError("credit balance requires original snapshot SHA-256")
    capacity = integer(record.capacity_doc, "original credit capacity")
    if capacity < 0:
        raise ValueError("original credit capacity cannot be negative")


def validate_credit_balances(balances: tuple[CreditBalance, ...]) -> None:
    if not isinstance(balances, tuple):
        raise TypeError("credit state must be an immutable tuple")
    seen, originals = set(), {}
    for balance in balances:
        if not isinstance(balance, CreditBalance):
            raise TypeError("credit state requires CreditBalance records")
        _values(balance)
        company_local_currency(balance.company)
        if (not isinstance(balance.vendor, str) or not balance.vendor.strip()
                or not isinstance(balance.currency, str) or not re.fullmatch("[A-Z]{3}", balance.currency)):
            raise ValueError("credit balance requires vendor/document currency scope")
        used = integer(balance.used_doc, "consumed original credit amount")
        if not 0 <= used <= balance.capacity_doc:
            raise ValueError("invalid cumulative original credit consumption")
        key = (balance.company, balance.original_id, balance.bucket)
        if key in seen:
            raise ValueError("duplicate original credit bucket")
        seen.add(key)
        scope = (balance.vendor, balance.currency, balance.original_sha256)
        original = (balance.company, balance.original_id)
        if original in originals and originals[original] != scope:
            raise ValueError("conflicting original credit scope/snapshot")
        originals[original] = scope


def reserve_credit(balances: tuple[CreditBalance, ...], reservations: Iterable[CreditReservation], *,
                   company: str, vendor: str, currency: str) -> tuple[CreditBalance, ...]:
    """Return tentative cumulative usage; no caller state or journal is modified."""
    validate_credit_balances(balances)
    company_local_currency(company)
    if (not isinstance(vendor, str) or not vendor.strip() or not isinstance(currency, str)
            or not re.fullmatch("[A-Z]{3}", currency)):
        raise ValueError("resolved credit vendor/document currency required")
    records = {(b.company, b.original_id, b.bucket): b for b in balances}
    originals = {(b.company, b.original_id): (b.vendor, b.currency, b.original_sha256) for b in balances}
    for request in reservations:
        if not isinstance(request, CreditReservation):
            raise TypeError("resolved credit reservation required")
        _values(request)
        amount = integer(request.amount_doc, "requested original credit amount")
        if amount < 0:
            raise ValueError("requested credit consumption cannot be negative")
        original = (company, request.original_id)
        scope = (vendor, currency, request.original_sha256)
        if original in originals and originals[original] != scope:
            raise ValueError("original credit scope/snapshot differs from committed state")
        originals[original] = scope
        key = (company, request.original_id, request.bucket)
        balance = records.get(key, CreditBalance(company, vendor, currency, request.original_id,
                              request.original_sha256, request.bucket, request.capacity_doc, 0))
        if balance.capacity_doc != request.capacity_doc:
            raise ValueError("original credit capacity differs from committed state")
        if balance.used_doc + amount > balance.capacity_doc:
            raise ValueError(f"credit exceeds remaining original {request.bucket}")
        if amount:
            records[key] = replace(balance, used_doc=balance.used_doc + amount)
    result = tuple(records[key] for key in sorted(records))
    validate_credit_balances(result)
    return result
