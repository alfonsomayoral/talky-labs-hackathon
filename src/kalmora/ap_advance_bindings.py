"""Bind explicitly associated advance application/classification facts to state."""
from dataclasses import dataclass
from .ap_journal import AdvanceApplication, AdvanceState, InvoiceLineOrder
from .ap_valuation import ValuationLine
from .facts import Evidence, Fact
from .model.ap_component_scope import APComponentScope


@dataclass(frozen=True)
class AdvanceClassification:
    advance_id: Fact
    treatment: Fact


@dataclass(frozen=True)
class AdvanceApplicationFacts:
    invoice_id: Fact
    advance_id: Fact
    amount_doc: Fact
    line_id: Fact
    po_reference: Fact


@dataclass(frozen=True)
class AdvanceBindingResolution:
    status: str
    applications: tuple[AdvanceApplication, ...]
    evidence: tuple[Evidence, ...]
    diagnostics: tuple[str, ...] = ()


def resolve_advance_applications(*, scope: APComponentScope, state: AdvanceState,
                                 applications: tuple[AdvanceApplicationFacts, ...],
                                 classifications: tuple[AdvanceClassification, ...],
                                 lines: tuple[ValuationLine, ...],
                                 order_bindings: tuple[InvoiceLineOrder, ...]) -> AdvanceBindingResolution:
    """No classification from country, amount, PO existence or account is inferred.

    Each application statement binds invoice, advance, line, PO and document
    cents in one source document. Each classification separately binds the exact
    advance and treatment in one source. Monetary applications carry no cost
    reassignment; non-monetary applications preserve the bound line assignment.
    Journal construction remains responsible for carry cents and final balances.
    """
    proof, diagnostics, resolved = [], [], []
    observed = {}
    for classification in classifications:
        facts = (classification.advance_id, classification.treatment)
        if not all(isinstance(fact, Fact) for fact in facts):
            raise TypeError("advance classification requires Fact/Evidence")
        proof.extend(fact.evidence for fact in facts)
        if facts[0].evidence.document != facts[1].evidence.document:
            diagnostics.append("ADVANCE_CLASSIFICATION_ASSOCIATION_UNKNOWN")
            continue
        if not isinstance(facts[0].value, str) or facts[1].value not in ("MONETARY", "NON_MONETARY"):
            diagnostics.append("ADVANCE_CLASSIFICATION_UNKNOWN")
            continue
        observed.setdefault(facts[0].value, set()).add(facts[1].value)
    balances = {(balance.company, balance.advance_id): balance for balance in state.balances}
    coding = {line.line_id: line.assignment for line in lines}
    if len(balances) != len(state.balances) or len(coding) != len(lines):
        raise ValueError("unique advance and invoice line identities required")
    bindings = {(binding.line_id, binding.po): binding.base_doc for binding in order_bindings}
    if len(bindings) != len(order_bindings):
        raise ValueError("unique invoice line/PO bindings required")
    portions, usage, seen = {}, {}, set()
    for observation in applications:
        facts = (observation.invoice_id, observation.advance_id, observation.amount_doc,
                 observation.line_id, observation.po_reference)
        if not all(isinstance(fact, Fact) for fact in facts):
            raise TypeError("advance application requires Fact/Evidence")
        proof.extend(fact.evidence for fact in facts)
        values = tuple(fact.value for fact in facts)
        if len({fact.evidence.document for fact in facts}) != 1:
            diagnostics.append("ADVANCE_APPLICATION_ASSOCIATION_UNKNOWN")
            continue
        invoice, advance, amount, line_id, po = values
        if (not all(isinstance(value, str) and value for value in (invoice, advance, line_id, po))
                or type(amount) is not int or amount <= 0):
            diagnostics.append("ADVANCE_APPLICATION_FACTS_UNKNOWN")
            continue
        balance = balances.get((scope.company, advance))
        if (invoice != scope.invoice_id or balance is None or (balance.vendor, balance.currency, balance.po) !=
                (scope.vendor, scope.currency, po) or balance.original_date > scope.invoice_date
                or line_id not in coding or coding[line_id].company != scope.company):
            diagnostics.append("ADVANCE_APPLICATION_SCOPE_CONFLICT")
            continue
        key, portion = (advance, line_id), (line_id, po)
        if key in seen or portion not in bindings:
            diagnostics.append("ADVANCE_APPLICATION_BINDING_UNKNOWN")
            continue
        seen.add(key)
        usage[advance] = usage.get(advance, 0) + amount
        portions[portion] = portions.get(portion, 0) + amount
        if usage[advance] > balance.amount_doc - balance.used_doc or portions[portion] > bindings[portion]:
            diagnostics.append("ADVANCE_APPLICATION_CAPACITY_EXCEEDED")
            continue
        treatments = observed.get(advance, set())
        if len(treatments) != 1:
            diagnostics.append("ADVANCE_CLASSIFICATION_UNKNOWN_OR_CONFLICT")
            continue
        treatment = next(iter(treatments))
        reference = next(item.treatment.evidence for item in classifications
                         if item.advance_id.value == advance and item.treatment.value == treatment)
        resolved.append(AdvanceApplication(advance, amount, treatment,
                         reference.document + ":" + reference.field,
                         coding[line_id] if treatment == "NON_MONETARY" else None, line_id))
    return AdvanceBindingResolution("UNKNOWN" if diagnostics else "RESOLVED",
                () if diagnostics else tuple(resolved), tuple(dict.fromkeys(proof)), tuple(dict.fromkeys(diagnostics)))
