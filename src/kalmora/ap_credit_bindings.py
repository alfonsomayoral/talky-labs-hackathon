"""Original imputation binding, with observed groups rather than invented lines."""
from dataclasses import dataclass
from .ap_credit_sources import CreditOriginalResolution
from .ap_journal import CreditReference
from .facts import Evidence, Fact
from .ap_credit_state import original_credit_sha256


@dataclass(frozen=True)
class CreditLineBinding:
    line_id: str
    original_line: Fact | None = None
    # Optional observed assignment/tax code narrows the unique imputation.
    assignment: Fact | None = None
    tax_code: Fact | None = None


@dataclass(frozen=True)
class CreditBindingResolution:
    status: str
    references: tuple[CreditReference, ...]
    evidence: tuple[Evidence, ...]
    diagnostics: tuple[str, ...] = ()


def resolve_credit_line_bindings(*, original: CreditOriginalResolution,
                                 lines: tuple[CreditLineBinding, ...]) -> CreditBindingResolution:
    """A unique historical imputation can comprise several equivalent GL lines.

    No line is selected by ID order, amount, text similarity or proportional share.
    Without a line observation, all original base lines must have one accounting,
    cost, PO and tax signature (or documentary selectors must prove that group).
    """
    proof, diagnostics, references = list(original.evidence), [], []
    if original.status != "RESOLVED" or original.original_entry is None:
        return CreditBindingResolution("UNKNOWN", (), tuple(proof), ("ORIGINAL_UNRESOLVED",))
    entry = original.original_entry
    if original_credit_sha256(entry) != original.original_sha256:
        return CreditBindingResolution("UNKNOWN", (), tuple(proof), ("ORIGINAL_SNAPSHOT_CHANGED",))
    seen = set()
    for binding in lines:
        if not isinstance(binding, CreditLineBinding) or not binding.line_id or binding.line_id in seen:
            raise ValueError("unique credited line binding required")
        seen.add(binding.line_id)
        facts = [fact for fact in (binding.original_line, binding.assignment, binding.tax_code) if fact is not None]
        if any(not isinstance(fact, Fact) for fact in facts):
            raise TypeError("line selectors require Fact/Evidence")
        proof.extend(fact.evidence for fact in facts)
        if facts and (original.reference_evidence is None or any(fact.evidence.document != original.reference_evidence.document for fact in facts)):
            diagnostics.append(f"{binding.line_id}:ORIGINAL_SELECTOR_ASSOCIATION_UNKNOWN")
            continue
        if any(fact.value is None for fact in facts):
            diagnostics.append(f"{binding.line_id}:ORIGINAL_LINE_SELECTOR_UNKNOWN")
            continue
        candidates = [(line.get("line", index), line) for index, line in enumerate(entry["lines"], 1)
                      if (line["account"].startswith(("2", "6")) and line["account"] not in {"66800000", "76800000"}
                          or line["account"] == "40090000")
                      and (line.get("currency") or entry.get("currency")) == original.document_currency]
        if binding.original_line is not None:
            if type(binding.original_line.value) is not int:
                diagnostics.append(f"{binding.line_id}:ORIGINAL_LINE_UNKNOWN")
                continue
            candidates = [(number, line) for number, line in candidates if number == binding.original_line.value]
        for fact, field in ((binding.assignment, "assignment"), (binding.tax_code, "tax_code")):
            if fact is not None:
                candidates = [(number, line) for number, line in candidates if line.get(field) == fact.value]
        signature = lambda line: (line["account"], line.get("partner"), line.get("cost_center"), line.get("wbs"),
                                  line.get("assignment"), line.get("tax_code"), line["debit"] > line["credit"])
        if not candidates or len({signature(line) for _, line in candidates}) != 1:
            diagnostics.append(f"{binding.line_id}:ORIGINAL_IMPUTATION_AMBIGUOUS")
            continue
        numbers = tuple(sorted(number for number, _ in candidates))
        proof.extend(Evidence("erp/journal_entries.jsonl", f"company={entry['company']};id={entry['id']}.lines[{number}]")
                     for number in numbers)
        references.append(CreditReference(binding.line_id, entry, numbers[0] if len(numbers) == 1 else None,
                                           numbers if len(numbers) > 1 else (), original.original_sha256))
    if not lines:
        diagnostics.append("CREDIT_LINES_UNKNOWN")
    return CreditBindingResolution("UNKNOWN" if diagnostics else "RESOLVED", () if diagnostics else tuple(references),
                                    tuple(dict.fromkeys(proof)), tuple(diagnostics))
