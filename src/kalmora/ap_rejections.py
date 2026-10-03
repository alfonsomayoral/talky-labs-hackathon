"""Evidence-driven invoice rejection gates, in policy §2.2 order (#48).

Inputs are resolved source candidates, not extraction or guessed accounting facts.
Empty/contradictory candidate sets stay unknown. This module never posts entries.
"""
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, DecimalException

from .facts import Evidence, Fact
from .money import decimal, integer


REJECTION_CODES = (
    "MANDATORY_FIELD_MISSING", "WRONG_ADDRESSEE", "ISP_NOT_APPLIED",
    "VAT_RATE_INCORRECT", "WITHHOLDING_MISSING", "ARITHMETIC_ERROR",
    "CERTIFICATION_CUMULATIVE_BILLED", "CFDI_MISMATCH",
)
UNKNOWN = object()


@dataclass(frozen=True)
class RuleCheck:
    code: str
    violation: bool | None
    evidence: tuple[Evidence, ...] = ()
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self):
        if self.violation is not None and type(self.violation) is not bool:
            raise TypeError("rule violation must be bool or None")
        if self.violation is not None and not self.evidence:
            raise ValueError("known checks require evidence (including explicit non-applicability)")
        if any(not isinstance(item, Evidence) for item in self.evidence):
            raise TypeError("rule checks require structured evidence")


@dataclass(frozen=True)
class RuleStage:
    status: str  # CLEAR, UNKNOWN, REJECT or HOLD; internal, not an output contract
    reason: str | None
    checks: tuple[RuleCheck, ...]


def evaluate_ordered_checks(checks, codes, decision):
    """First violation wins only once all preceding gates are known clear."""
    checks, codes = tuple(checks), tuple(codes)
    if decision not in ("REJECT", "HOLD"):
        raise ValueError("decision must be REJECT or HOLD")
    if len(set(codes)) != len(codes) or len({c.code for c in checks}) != len(checks):
        raise ValueError("duplicate rule code")
    if any(c.code not in codes for c in checks):
        raise ValueError("unexpected rule code")
    by_code = {check.code: check for check in checks}
    ordered = tuple(by_code.get(code, RuleCheck(code, None, diagnostics=("MISSING_CHECK",)))
                    for code in codes)
    for check in ordered:
        if check.violation is None:
            return RuleStage("UNKNOWN", None, ordered)
        if check.violation:
            return RuleStage(decision, check.code, ordered)
    return RuleStage("CLEAR", None, ordered)


def resolve_field(fields: Mapping[str, Sequence[Fact]], name: str):
    """Resolve equal candidates, preserve contradictions and unknowns with evidence."""
    candidates = tuple(fields.get(name, ()))
    if any(not isinstance(fact, Fact) for fact in candidates):
        raise TypeError("fields require sequences of Fact")
    evidence = tuple(fact.evidence for fact in candidates)
    if not candidates:
        return UNKNOWN, evidence, (f"MISSING:{name}",)
    value = candidates[0].value
    # bool and integer equality must not silently turn malformed facts into numbers.
    if any(type(fact.value) is not type(value) or fact.value != value for fact in candidates[1:]):
        return UNKNOWN, evidence, (f"CONFLICT:{name}",)
    return value, evidence, ()


def bool_field(fields, name):
    value, evidence, diagnostics = resolve_field(fields, name)
    if value is UNKNOWN:
        return None, evidence, diagnostics
    if type(value) is not bool:
        return None, evidence, (f"INVALID_BOOLEAN:{name}",)
    return value, evidence, diagnostics


def _check(fields, code, names, calculation):
    values, evidence, diagnostics = [], [], []
    for name in names:
        value, proof, notes = resolve_field(fields, name)
        values.append(value)
        evidence.extend(proof)
        diagnostics.extend(notes)
    if diagnostics:
        return RuleCheck(code, None, tuple(evidence), tuple(diagnostics))
    try:
        violation = calculation(*values)
        if type(violation) is not bool:
            raise ValueError("calculation did not produce a boolean")
    except (TypeError, ValueError, KeyError, DecimalException):
        return RuleCheck(code, None, tuple(evidence), (f"INVALID_INPUT:{code}",))
    return RuleCheck(code, violation, tuple(evidence))


def _applicable(fields, code, flag, names, calculation):
    applies, evidence, diagnostics = bool_field(fields, flag)
    if applies is None:
        return RuleCheck(code, None, evidence, diagnostics)
    if not applies:
        return RuleCheck(code, False, evidence)
    result = _check(fields, code, names, calculation)
    return RuleCheck(code, result.violation, evidence + result.evidence, result.diagnostics)


def _amount(value):
    value = integer(value)
    if value < 0:
        raise ValueError("invoice amounts must be nonnegative")
    return value


def _nif_missing(value):
    if value is None:
        return True  # explicit observation that the field is absent
    if not isinstance(value, str):
        raise TypeError("NIF must be text or observed missing")
    return not value.strip()


def _wrong_addressee(recipient, ordering):
    if not isinstance(recipient, str) or not recipient or not isinstance(ordering, str) or not ordering:
        raise ValueError("resolved recipient and ordering company required")
    return recipient != ordering


def spanish_standard_vat_rate(activity: Fact) -> Fact:
    """Rate only for an explicitly classified Spanish ordinary taxable activity.

    Do not call for exempt/reverse-charge/foreign regimes or unknown activities.
    OTHER_STANDARD is a classification supplied by the adapter, never a fallback.
    """
    reduced = {"WASTE_COLLECTION", "WASTE_TREATMENT", "STREET_CLEANING", "WATER"}
    if activity.value not in reduced | {"OTHER_STANDARD"}:
        raise ValueError("explicit Spanish standard taxable activity required")
    return Fact(Decimal("0.10") if activity.value in reduced else Decimal("0.21"), activity.evidence)


def _vat_wrong(lines):
    if not isinstance(lines, (list, tuple)) or not lines:
        raise ValueError("explicit applicable VAT lines required")
    # Check every line, including mixed-rate invoices. Rates are fractions of one.
    wrong = False
    for line in lines:
        actual, expected = decimal(line["applied_rate"]), decimal(line["applicable_rate"])
        if not (0 <= actual <= 1 and 0 <= expected <= 1):
            raise ValueError("VAT rate must be a fraction")
        wrong = wrong or actual != expected
    return wrong


def _cumulative(billed, current, cumulative):
    billed, current, cumulative = map(_amount, (billed, current, cumulative))
    if current > cumulative:
        raise ValueError("current certification exceeds cumulative")
    return billed == cumulative and cumulative != current


CFDI_FIELDS = ("number", "date", "issuer_tax_id", "recipient_tax_id", "currency",
               "net_cents", "tax_cents", "gross_cents")


def _cfdi_mismatch(pdf, xml):
    if not isinstance(pdf, dict) or not isinstance(xml, dict):
        raise TypeError("independently extracted CFDI PDF/XML fields required")
    # A known discrepancy proves mismatch even if another field is still absent.
    mismatch = False
    incomplete = False
    for name in CFDI_FIELDS:
        if name not in pdf or name not in xml or pdf[name] is None or xml[name] is None:
            incomplete = True
            continue
        if name.endswith("_cents"):
            _amount(pdf[name])
            _amount(xml[name])
        elif not isinstance(pdf[name], str) or not isinstance(xml[name], str):
            raise TypeError("CFDI identifiers require text")
        mismatch = mismatch or pdf[name] != xml[name]
    if not mismatch and incomplete:
        raise ValueError("CFDI comparison incomplete")
    return mismatch


def rejection_checks(fields: Mapping[str, Sequence[Fact]]) -> tuple[RuleCheck, ...]:
    """Calculate policy gates from explicit source candidates (see docs/ap-decisions.md)."""
    return (
        _check(fields, REJECTION_CODES[0], ("recipient_nif",), _nif_missing),
        _check(fields, REJECTION_CODES[1], ("recipient_company", "order_company"), _wrong_addressee),
        _applicable(fields, REJECTION_CODES[2], "isp_required", ("charged_vat_cents",),
                    lambda tax: _amount(tax) > 0),
        _applicable(fields, REJECTION_CODES[3], "vat_check_applicable", ("vat_lines",), _vat_wrong),
        _applicable(fields, REJECTION_CODES[4], "withholding_required", ("withholding_cents",),
                    lambda amount: _amount(amount) == 0),
        _check(fields, REJECTION_CODES[5], ("net_cents", "tax_cents", "gross_cents"),
               lambda net, tax, gross: _amount(net) + _amount(tax) != _amount(gross)),
        _applicable(fields, REJECTION_CODES[6], "certification_applicable",
                    ("billed_net_cents", "certification_current_cents", "certification_cumulative_cents"),
                    _cumulative),
        _applicable(fields, REJECTION_CODES[7], "cfdi_applicable", ("cfdi_pdf", "cfdi_xml"), _cfdi_mismatch),
    )


def evaluate_rejections(fields: Mapping[str, Sequence[Fact]]) -> RuleStage:
    return evaluate_ordered_checks(rejection_checks(fields), REJECTION_CODES, "REJECT")
