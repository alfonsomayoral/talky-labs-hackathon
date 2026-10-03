"""Composition of evidenced AP stages; accounting rules remain in their engines."""
from collections.abc import Mapping, Sequence

from .ap_rejections import (
    REJECTION_CODES, RuleCheck, RuleStage, evaluate_ordered_checks, rejection_checks,
)
from .facts import DocumentFacts, Fact

_AMOUNT_FIELDS = ("net_cents", "tax_cents", "gross_cents")
_ARITHMETIC_CODE = "ARITHMETIC_ERROR"


def source_rejection_stage(
    fields: Mapping[str, Sequence[Fact]], *, amount_sources: Sequence[DocumentFacts],
) -> RuleStage:
    """Apply rejection precedence while checking arithmetic within each source.

    ``fields`` contains the observed candidates and evidenced policy context used
    by the rejection engine. ``amount_sources`` are the independently normalized
    financial attachments, preserving their integer-cent observations and proof.
    Do not include a message or notice merely because it accompanies an invoice.

    Different totals across PDF/XML do not make either source arithmetically
    invalid. Keep those conflicting candidates for the comparison gate, and
    check net + charged tax = gross separately using the existing arithmetic
    rule. Missing amounts remain unknown; no candidate is selected or filled.
    """
    checks = list(rejection_checks(fields))
    arithmetic = []
    diagnostics = []
    for source in amount_sources:
        if not isinstance(source, DocumentFacts):
            raise TypeError("arithmetic sources require normalized DocumentFacts")
        source_fields = {name: source.fields.get(name, ()) for name in _AMOUNT_FIELDS}
        check = next(c for c in rejection_checks(source_fields) if c.code == _ARITHMETIC_CODE)
        arithmetic.append(check)
        diagnostics.extend(f"{source.source_sha256}:{note}" for note in check.diagnostics)
    violation = (True if any(c.violation is True for c in arithmetic) else
                 False if arithmetic and all(c.violation is False for c in arithmetic) else None)
    evidence = tuple(item for check in arithmetic for item in check.evidence)
    if not arithmetic:
        diagnostics.append("MISSING_ARITHMETIC_SOURCES")
    replacement = RuleCheck(_ARITHMETIC_CODE, violation, evidence, tuple(diagnostics))
    checks = tuple(replacement if c.code == _ARITHMETIC_CODE else c for c in checks)
    return evaluate_ordered_checks(checks, REJECTION_CODES, "REJECT")
