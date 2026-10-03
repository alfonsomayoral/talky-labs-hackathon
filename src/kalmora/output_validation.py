"""Shared delivery-contract validation, independent of scoring and golden data."""
from datetime import date
from functools import lru_cache
from types import UnionType
from typing import Any, Literal, NotRequired, Required, TypeAliasType, Union, get_args, get_origin, get_type_hints, is_typeddict

from .output_models import ApRow, ArBillingRow, ArCashRow, BankRecRow, CloseRow, IcRow

ROW_TYPES = {"ap": ApRow, "ar_billing": ArBillingRow, "ar_cash": ArCashRow,
             "bank_rec": BankRecRow, "ic": IcRow, "close": CloseRow}


@lru_cache
def _hints(shape: Any) -> dict[str, Any]:
    return get_type_hints(shape, include_extras=True)


def _errors(value: Any, shape: Any, path: str) -> list[str]:
    if isinstance(shape, TypeAliasType):
        errors = _errors(value, shape.__value__, path)
        if not errors and shape.__name__ == "IsoDate":
            try:
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError()
            except ValueError:
                errors.append(f"{path}: invalid YYYY-MM-DD date")
        return errors
    origin, args = get_origin(shape), get_args(shape)
    if origin in (Required, NotRequired):
        return _errors(value, args[0], path)
    if origin in (Union, UnionType):
        if any(not _errors(value, option, path) for option in args):
            return []
        return [f"{path}: value does not match the allowed types"]
    if origin is Literal:
        return [] if any(type(value) is type(option) and value == option for option in args) else [f"{path}: invalid enum {value!r}"]
    if is_typeddict(shape):
        if not isinstance(value, dict):
            return [f"{path}: expected object"]
        errors = [f"{path}.{key}: required field missing" for key in sorted(shape.__required_keys__) if key not in value]
        if shape.__name__ == "JournalEntry" and value.get("lines") == []:
            errors.append(f"{path}.lines: nonempty array required")
        for key, kind in _hints(shape).items():
            if key in value:
                errors.extend(_errors(value[key], kind, f"{path}.{key}"))
        return errors
    if origin is list:
        if not isinstance(value, list):
            return [f"{path}: expected array"]
        return [error for index, item in enumerate(value) for error in _errors(item, args[0], f"{path}[{index}]")]
    if shape in (int, str, type(None)):
        return [] if type(value) is shape else [f"{path}: expected {shape.__name__}"]
    return []


def check_structure(subs: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Return format errors without altering or coercing the submitted values."""
    diagnostics = []
    for module, rows in subs.items():
        for index, row in enumerate(rows, 1):
            path = f"{module}.jsonl:{index}"
            errors = _errors(row, ROW_TYPES[module], path)
            if not errors:
                if module == "ap":
                    if row["decision"] in ("POST", "POST_PAYMENT_BLOCK"):
                        required = ("company", "vendor_id", "invoice_number", "invoice_date", "currency", "net", "tax", "gross", "withholding", "retention", "payable", "lines", "journal_entry")
                        errors.extend(f"{path}.{key}: required for a posted document" for key in required if key not in row)
                    elif row.get("journal_entry"):
                        errors.append(f"{path}.journal_entry: only allowed for POST or POST_PAYMENT_BLOCK")
                if module == "ar_billing" and row["expected"] == "INVOICE":
                    errors.extend(f"{path}.{key}: required for INVOICE" for key in ("invoice", "journal_entry") if key not in row)
                if module == "close":
                    key = {"ACCRUAL": "vendor", "PREPAID": "invoice", "FX_REVAL": "item", "BAD_DEBT": "customer", "WIP_REVENUE": "billing_item"}[row["type"]]
                    if not row.get(key):
                        errors.append(f"{path}.{key}: required for {row['type']}")
                groups = []
                if module in ("ar_cash", "ic"):
                    groups = [row["adjustment"]]
                elif module == "bank_rec":
                    groups = [adjustment["lines"] for adjustment in row["adjustments"]]
                for lines in groups:
                    if any(not line.get("company") for line in lines):
                        errors.append(f"{path}: adjustment lines require explicit company")
            diagnostics.extend({"module": module, "entity": index, "code": "INVALID_STRUCTURE",
                                "severity": "error", "message": error} for error in errors)
    return diagnostics
