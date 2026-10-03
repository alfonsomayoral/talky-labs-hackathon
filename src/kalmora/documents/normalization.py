"""Deterministic source normalization. No currency, locale or posting inference."""
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re

from kalmora.facts import DocumentFacts, Fact

NORMALIZATION_VERSION = "document-normalization-v3"
ALIASES = {
    "buyer_tax_id": "recipient_tax_id", "customer_tax_id": "recipient_tax_id",
    "vendor_tax_id": "supplier_tax_id", "seller_tax_id": "supplier_tax_id",
    "invoice_number": "document_number", "invoice_date": "document_date",
    "document_currency": "currency", "purchase_order_reference": "po_reference",
    "cert_current": "certification_current", "certified_current": "certification_current",
    "cert_previous": "certification_previous", "certified_previous": "certification_previous",
    "cert_cumulative": "certification_cumulative", "certified_cumulative": "certification_cumulative",
    "coverage_start": "period_start", "coverage_end": "period_end",
    "certificate_issued_on": "certificate_issue_date",
}
# A line unit is the literal unit used by APLineFacts and PO queries. It is
# not a global alias, nor a translation of an XML unit catalogue code.
LINE_ALIASES = {"unit": "uom"}
DATE_FIELDS = frozenset({"period_start", "period_end", "issued_on"})
MONEY = frozenset({"net", "tax", "gross", "payable", "amount", "retention",
    "withholding", "discount", "taxable_base", "advance_amount", "guarantee_amount", "embargo_amount",
    "certification_current", "certification_previous", "certification_cumulative",
    "certification_amount", "current_amount", "previous_amount", "cumulative_amount"})


@dataclass(frozen=True)
class NormalizationDiagnostic:
    code: str
    field: str
    message: str
    evidence: tuple[Fact, ...] = ()


@dataclass(frozen=True)
class NormalizedDocument:
    raw: DocumentFacts
    facts: DocumentFacts
    diagnostics: tuple[NormalizationDiagnostic, ...]
    conflicts: dict[str, tuple[Fact, ...]]
    version: str = NORMALIZATION_VERSION


def _number(value: object, fact: Fact) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError("Float and boolean numeric values are forbidden")
    if isinstance(value, (int, Decimal)):
        result = Decimal(value)
    elif isinstance(value, str):
        text = value.strip().replace("−", "-")
        negative = text.startswith("(") and text.endswith(")")
        if negative:
            text = text[1:-1].strip()
        text = re.sub(r"^(?:EUR|USD|MXN|GBP|[€$£])\s*|\s*(?:EUR|USD|MXN|GBP|[€$£])$", "", text, flags=re.I)
        xml = fact.evidence.document.lower().endswith(".xml") and fact.evidence.field.startswith("/")
        if xml:
            if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", text):
                raise ValueError("XML decimal must use dot notation without grouping")
        else:
            text = text.replace("\u00a0", " ").replace("\u202f", " ")
            if " " in text:
                if not re.fullmatch(r"[+-]?\d{1,3}(?: \d{3})+(?:[.,]\d+)?", text):
                    raise ValueError("Invalid numeric grouping")
                text = text.replace(" ", "")
            if "," in text and "." in text:
                decimal_sep = "," if text.rfind(",") > text.rfind(".") else "."
                grouping = "." if decimal_sep == "," else ","
                integral, fraction = text.rsplit(decimal_sep, 1)
                if not re.fullmatch(r"[+-]?\d{1,3}(?:" + re.escape(grouping) + r"\d{3})+", integral):
                    raise ValueError("Invalid numeric grouping")
                text = integral.replace(grouping, "") + "." + fraction
            elif "," in text or "." in text:
                separator = "," if "," in text else "."
                parts = text.split(separator)
                if len(parts) > 2:
                    if not re.fullmatch(r"[+-]?\d{1,3}(?:" + re.escape(separator) + r"\d{3})+", text):
                        raise ValueError("Invalid numeric grouping")
                    text = "".join(parts)
                else:
                    if len(parts[1]) == 3 and parts[0].lstrip("+-") != "0":
                        raise ValueError("Ambiguous decimal/grouping separator")
                    text = text.replace(separator, ".")
            if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", text):
                raise ValueError("Invalid decimal value")
        result = Decimal(text)
        if negative:
            if result < 0:
                raise ValueError("Contradictory negative notation")
            result = result.copy_negate()
    else:
        raise ValueError("Expected decimal string or exact number")
    if not result.is_finite():
        raise ValueError("Nonfinite numeric value")
    return result


# Spanish and Portuguese month names, as written in "30 de junio de 2026".
_MONTHS = {name: number for number, names in enumerate((
    ("enero", "janeiro"), ("febrero", "fevereiro"), ("marzo", "março"), ("abril",),
    ("mayo", "maio"), ("junio", "junho"), ("julio", "julho"), ("agosto",),
    ("septiembre", "setiembre", "setembro"), ("octubre", "outubro"),
    ("noviembre", "novembro"), ("diciembre", "dezembro")), start=1) for name in names}


def _date(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Expected source date string")
    text = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return date.fromisoformat(text).isoformat()
    if re.match(r"^\d{4}-\d{2}-\d{2}T", text):
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    if re.fullmatch(r"\d{4}/\d{2}/\d{2}", text):
        return date.fromisoformat(text.replace("/", "-")).isoformat()
    named = re.fullmatch(r"(\d{1,2}) de ([a-zç]+) de (\d{4})", text.casefold())
    if named and named.group(2) in _MONTHS:
        return date(int(named.group(3)), _MONTHS[named.group(2)], int(named.group(1))).isoformat()
    match = re.fullmatch(r"(\d{1,2})([/.\-])(\d{1,2})\2(\d{4})", text)
    if not match:
        raise ValueError("Unsupported date format")
    first, second, year = map(int, (match[1], match[3], match[4]))
    if first <= 12 and second <= 12 and first != second:
        raise ValueError("Ambiguous day/month order")
    day, month = (second, first) if second > 12 else (first, second)
    return date(year, month, day).isoformat()


def _canonical(key: str) -> str:
    if key.startswith("raw.") or ".raw." in key:
        return key
    match = re.fullmatch(r"(?:line\.(\d+)|lines\.(\d+)|lines\[(\d+)\])\.(.+)", key)
    if match:
        index = int(next(item for item in match.groups()[:3] if item is not None))
        if index < 1:
            raise ValueError("Flat line indices must be one based")
        leaf = LINE_ALIASES.get(match[4], ALIASES.get(match[4], match[4]))
        return f"line.{index}.{leaf}"
    return ALIASES.get(key, key)


def _convert(key: str, fact: Fact) -> tuple[str, object, bool]:
    if key.startswith("raw.") or ".raw." in key:
        if _contains_float(fact.value):
            raise ValueError("Float facts are forbidden")
        return key, deepcopy(fact.value), False
    leaf = key.rsplit(".", 1)[-1]
    value = fact.value
    suffix = "_cents" if leaf in MONEY else "_milli" if leaf == "quantity" else "_e4" if leaf == "unit_price" or leaf.endswith("_rate") else ""
    target = key + suffix
    if value is None:
        return target, None, False
    if leaf.endswith(("_cents", "_milli", "_e4")):
        if type(value) is not int:
            raise ValueError("Normalized units require integer values")
        return key, value, False
    if suffix:
        percent = isinstance(value, str) and value.strip().endswith("%")
        if percent and not leaf.endswith("_rate"):
            raise ValueError("Percent notation requires a rate field")
        numeric = _number(value.strip()[:-1] if percent else value, fact)
        if leaf.endswith("_rate"):
            if percent or "TaxRate" in fact.evidence.field:
                numeric = _decimal_shift(numeric, -2)
            elif numeric.copy_abs() > 1:
                raise ValueError("Rate unit requires explicit percent notation")
        exponent = 2 if suffix == "_cents" else 3 if suffix == "_milli" else 4
        scaled = _decimal_shift(numeric, exponent)
        integral = scaled.to_integral_value(rounding=ROUND_HALF_UP)
        rounded = scaled != integral
        if rounded and suffix != "_cents":
            raise ValueError("Precision exceeds normalized units")
        return target, int(integral), rounded
    if leaf.endswith(("_date", "valid_from", "valid_until")) or leaf in DATE_FIELDS:
        return key, _date(value), False
    if leaf == "currency":
        if not isinstance(value, str):
            raise ValueError("Currency requires literal code")
        currency = value.strip().upper()
        currency = {"€": "EUR", "EURO": "EUR", "EUROS": "EUR", "£": "GBP"}.get(currency, currency)
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise ValueError("Ambiguous or invalid currency; symbols cannot establish country")
        return key, currency, False
    if _contains_float(value):
        raise ValueError("Float facts are forbidden")
    if leaf.endswith(("_tax_id", "iban")):
        if not isinstance(value, str):
            raise ValueError("Identity requires source string")
        return key, re.sub(r"[\s.\-]", "", value).upper(), False
    return key, value.strip() if isinstance(value, str) else deepcopy(value), False


def _decimal_shift(value: Decimal, exponent: int) -> Decimal:
    """Scale exact source units without rounding in the caller's Decimal context."""
    source = value.as_tuple()
    return Decimal((source.sign, source.digits, source.exponent + exponent))


def _contains_float(value: object) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(_contains_float(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_float(item) for item in value)
    return False


def normalize_document_facts(document: DocumentFacts) -> NormalizedDocument:
    """Normalize a single attachment; retain every conflicting candidate and its proof."""
    raw = deepcopy(document)
    suffix = "/" + NORMALIZATION_VERSION
    version = document.extractor_version
    if not version.endswith(suffix):
        version += suffix
    output = DocumentFacts(document.source_sha256, version, {})
    diagnostics = []
    sources = {fact.evidence.document for candidates in document.fields.values() for fact in candidates}
    if len(sources) > 1:
        diagnostics.append(NormalizationDiagnostic("MIXED_SOURCE", "", "Normalize attachments independently"))
        return NormalizedDocument(raw, output, tuple(diagnostics), {})
    expanded = []
    for key, candidates in document.fields.items():
        for fact in candidates:
            if key == "lines" and isinstance(fact.value, list):
                for index, line in enumerate(fact.value, 1):
                    if not isinstance(line, dict) or any(not isinstance(name, str) for name in line):
                        diagnostics.append(NormalizationDiagnostic("INVALID_LINE", f"line.{index}", "Expected line dictionary", (fact,)))
                        continue
                    expanded.extend((f"line.{index}.{name}", Fact(value, fact.evidence)) for name, value in line.items())
            else:
                expanded.append((key, fact))
    for key, fact in expanded:
        try:
            canonical = _canonical(key)
            target, value, rounded = _convert(canonical, fact)
        except (ValueError, InvalidOperation) as error:
            diagnostics.append(NormalizationDiagnostic("INVALID_OR_AMBIGUOUS", key, str(error), (fact,)))
            continue
        output.fields.setdefault(target, []).append(Fact(value, fact.evidence))
        if rounded:
            diagnostics.append(NormalizationDiagnostic("ROUNDED_HALF_UP", target, "Source amount rounded to cents", (fact,)))
    conflicts = {}
    for key, candidates in output.fields.items():
        values = {repr((type(fact.value).__name__, fact.value)) for fact in candidates}
        if len(values) > 1:
            conflicts[key] = tuple(candidates)
            diagnostics.append(NormalizationDiagnostic("CONFLICT", key, "Source candidates disagree; no candidate selected", tuple(candidates)))
    # Field order changes when facts are saved and reloaded; the diagnostics must not.
    diagnostics.sort(key=lambda d: (d.field, d.code, d.message))
    return NormalizedDocument(raw, output, tuple(diagnostics), conflicts)
