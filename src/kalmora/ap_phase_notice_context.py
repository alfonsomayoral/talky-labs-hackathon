"""Evidence-bearing, scope-specific notice inventory for the phase planner (#140).

Prepared sources are loaded and authenticated upstream. This adapter reads only
active ERP/task catalogues; source errors and unresolved scope never prove absence.
"""
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, replace
from hashlib import sha256
from types import MappingProxyType

from .ap_chronology import KINDS, registered_events, replay_events, validate_scope
from .ap_document_bridge import APDocumentBridge, APFactSet
from .ap_identity import IdentityCatalog
from .ap_notice_bridge import resolve_ap_notice
from .ap_payment import apply_notice
from .ap_phase_export import load_ap_task_inventory
from .ap_sources import APPreparedSources, _safe_file
from .data import PhaseData
from .documents.ap_sources import APTaskSources
from .facts import DocumentFacts, Evidence, Fact
from .model.ap_notice_resolution import NoticeResolution
from .model.ap_scope import ApScope
from .model.ap_timeline_state import ApTimelineState

PHASE_NOTICE_CONTEXT_VERSION = "ap-phase-notice-context-v1"
_CERTIFICATE = "CONTRACTOR_TAX_CERTIFICATE"
_POLICY = "participant/POLITICAS_CONTABLES.md"


def _proof(items):
    return tuple(sorted(set(items), key=lambda e: (e.document, e.field, e.page or 0,
        e.quote is not None, e.quote or "")))


def _candidates(fields, *names):
    return tuple(f for name in names for alias in (name, "raw." + name)
                 for f in fields.get(alias, ()))


@dataclass(frozen=True)
class PhaseNoticeResult:
    source_path: str
    document_type: str
    resolution: NoticeResolution


@dataclass(frozen=True)
class PhaseNoticeContext:
    timeline: ApTimelineState
    unknown_event_kinds: tuple[str, ...]
    incomplete_sources: tuple[str, ...]
    event_inventory_evidence: Mapping[str, tuple[Evidence, ...]]
    notice_results: tuple[PhaseNoticeResult, ...]
    evidence: tuple[Evidence, ...]
    diagnostics: tuple[str, ...]
    bank_event_fields: Mapping[tuple[ApScope, str], Mapping[str, tuple[Fact, ...]]]
    source_hashes: tuple[tuple[str, str], ...]
    version: str = PHASE_NOTICE_CONTEXT_VERSION


class _RegisteredView:
    """Missing certificate catalogue is unknown, while known vendor events survive."""
    def __init__(self, data, certificates):
        self.data, self.certificates = data, certificates

    def get(self, table, key):
        return self.data.get(table, key)

    def find(self, table, **criteria):
        if table != "contractor_certificates":
            raise ValueError("unsupported registered notice source")
        return [row for row in self.certificates
                if all(row.get(key) == value for key, value in criteria.items())]


def _scope_binding(fields, kind, catalog, data, requested):
    """Return MATCH/FOREIGN/UNKNOWN and proof; never use sender or certificate issuer."""
    proof, notes, ids = [], [], {}
    roles = (("vendor", ("vendor", "vendor_id"),
        ("certificate_tax_id", "certificate_subject_tax_id", "subject_tax_id", "holder_tax_id")
        if kind == _CERTIFICATE else ("supplier_tax_id", "vendor_tax_id")),
        ("company", ("company", "company_code"), ("recipient_tax_id",)))
    for role, direct_names, tax_names in roles:
        direct = APFactSet({role: _candidates(fields, *direct_names)}).text(role)
        taxes = _candidates(fields, *tax_names)
        proof.extend(direct.evidence)
        values = []
        if direct.candidates:
            if not direct.known:
                notes.append(f"NOTICE_SCOPE_UNKNOWN:{role}:{direct.status}")
            else:
                try:
                    data.get("vendors" if role == "vendor" else "companies", direct.value)
                    values.append(direct.value)
                    proof.append(Evidence("erp/vendors" if role == "vendor" else "erp/companies",
                                          f"exact-id={direct.value}"))
                except (KeyError, ValueError):
                    notes.append(f"NOTICE_SCOPE_UNKNOWN:{role}:NOT_FOUND")
        if taxes:
            proof.extend(f.evidence for f in taxes)
            try:
                identity = catalog.resolve(supplier_tax_ids=taxes if role == "vendor" else (),
                    recipient_tax_ids=taxes if role == "company" else (), expected_company=None)
                match = identity.supplier if role == "vendor" else identity.recipient
                proof.extend(match.evidence)
                if match.status == "RESOLVED":
                    values.append(match.identity)
                else:
                    notes.append(f"NOTICE_SCOPE_UNKNOWN:{role}:{match.status}")
            except (ValueError, TypeError):
                notes.append(f"NOTICE_SCOPE_UNKNOWN:{role}:INVALID_TAX_ID")
        if len(set(values)) > 1:
            notes.append(f"NOTICE_SCOPE_UNKNOWN:{role}:CONFLICT")
        ids[role] = values[0] if values and len(set(values)) == 1 else None
    currency = APFactSet({"currency": _candidates(fields, "currency", "document_currency")}).field(
        "currency", kind="currency")
    proof.extend(currency.evidence)
    if currency.candidates and not currency.known:
        notes.append(f"NOTICE_SCOPE_UNKNOWN:currency:{currency.status}")
    # Contradictory scope is never discarded just because one component is foreign.
    if notes:
        return "UNKNOWN", _proof(proof), tuple(notes)
    for role in ("vendor", "company"):
        if ids[role] is not None and ids[role] != getattr(requested, role):
            return "FOREIGN", _proof(proof), (f"NOTICE_SCOPE_FOREIGN:{role}:{ids[role]}",)
    if currency.known and currency.value != requested.currency:
        return "FOREIGN", _proof(proof), (f"NOTICE_SCOPE_FOREIGN:currency:{currency.value}",)
    if ids["vendor"] is None:
        return "UNKNOWN", _proof(proof), ("NOTICE_SCOPE_UNKNOWN:vendor",)
    if kind == _CERTIFICATE:
        # §2.2.4 makes tax status a property of the identified contractor, not a
        # monetary obligation. Only explicit affiliations allow company projection.
        vendor = data.get("vendors", ids["vendor"])
        affiliations = vendor.get("companies")
        if (not isinstance(affiliations, (list, tuple))
                or requested.company not in affiliations):
            return "UNKNOWN", _proof(proof), ("CERTIFICATE_COMPANY_AFFILIATION_UNKNOWN",)
        proof.extend((Evidence("erp/vendors", f"id={requested.vendor}.companies"),
            Evidence(_POLICY, "§2.2.4 contractor tax status is independent of invoice currency")))
        return "MATCH", _proof(proof), ()
    if ids["company"] is None or not currency.known:
        return "UNKNOWN", _proof(proof), ("NOTICE_SCOPE_UNKNOWN:company_or_currency",)
    return "MATCH", _proof(proof), ()


def resolve_phase_notice_context(prepared: APPreparedSources, *, data: PhaseData,
                                 scope: ApScope) -> PhaseNoticeContext:
    """Resolve only proven notice scopes; retain an evidenced negative inventory.

    The verified prepared loader is a prerequisite. Exact canonical task coverage,
    classified sources and the corresponding ERP catalogue are all required for
    a negative claim. Optional master-key omission is not explicit absence.
    """
    if not isinstance(prepared, APPreparedSources) or not isinstance(data, PhaseData):
        raise TypeError("verified APPreparedSources and active PhaseData required")
    validate_scope(scope)
    _safe_file(data.phase_dir, "tasks/close.json")
    data = PhaseData(data.phase_dir)  # do not reuse stale caller master caches
    inventory = load_ap_task_inventory(data.phase_dir)
    paths, proofs, diagnostics, incomplete, uncertain = {}, [], [], set(), set()

    def table(name, *, required=True):
        try:
            candidate = data._path(name)
            path = _safe_file(data.phase_dir, candidate.relative_to(data.phase_dir).as_posix())
            digest = sha256(path.read_bytes()).hexdigest()
            paths[path.relative_to(data.phase_dir).as_posix()] = (path, digest)
            value = data.table(name)
            proofs.append(Evidence(path.relative_to(data.phase_dir).as_posix(), "sha256=" + digest))
            return value
        except KeyError:
            if required:
                raise
            return None

    table("tasks/close")
    table("tasks/ap_documents")
    table("vendors")
    table("companies")
    certificates = table("contractor_certificates", required=False)
    if certificates is not None and not isinstance(certificates, list):
        raise ValueError("contractor certificate catalogue requires rows")
    if certificates is not None and any(not isinstance(row, dict) or any(
            not isinstance(row.get(name), str) or not row[name].strip()
            for name in ("vendor", "reference", "issued_on", "valid_until")) for row in certificates):
        uncertain.add(_CERTIFICATE)
        diagnostics.append("REGISTERED_CERTIFICATE_ROWS_UNKNOWN")
    vendor = data.get("vendors", scope.vendor)
    data.get("companies", scope.company)
    catalog = IdentityCatalog.from_phase(data)
    base_proof = _proof((*proofs, Evidence(inventory.source, "sha256=" + inventory.source_sha256),
        Evidence("prepared-ap-sources", "stable-source-sha256=" + prepared.stable_source_sha256)))
    if set(prepared) != set(inventory.doc_ids):
        incomplete.add(inventory.source)
        diagnostics.append("NOTICE_TASK_INVENTORY_INCOMPLETE")
    completeness = {}
    if certificates is not None:
        completeness[_CERTIFICATE] = base_proof
    else:
        diagnostics.append("REGISTERED_CERTIFICATE_INVENTORY_UNKNOWN")
    if "alternative_payee" in vendor:
        completeness["FACTORING_NOTICE"] = (*base_proof,
            Evidence("erp/vendors", f"id={scope.vendor}.alternative_payee"))
    if "garnishments" in vendor and isinstance(vendor["garnishments"], (list, tuple)):
        completeness["TAX_GARNISHMENT_ORDER"] = (*base_proof,
            Evidence("erp/vendors", f"id={scope.vendor}.garnishments"))
    # bank_history contains accounts, not signature/certificate/registration facts.
    # It cannot prove the absence of registered signed bank-change letters.
    diagnostics.append("REGISTERED_BANK_NOTICE_INVENTORY_UNKNOWN")
    timeline = ApTimelineState()
    try:
        baseline_scope = ApScope(scope.company, scope.vendor, vendor["currency"])
        raw = registered_events(_RegisteredView(data,
            tuple(row for row in (certificates or ()) if isinstance(row, dict))), baseline_scope)
        events = []
        for event in raw.events:
            if event.kind == "FACTORING_NOTICE":
                payee = vendor["alternative_payee"]
                # The core ERP converter does not carry optional restrictions.
                # Restore the literal master fields before querying chronology.
                extra = tuple(Evidence("erp/vendors", f"id={scope.vendor}.alternative_payee.{name}")
                    for name in ("invoice_number", "valid_until") if name in payee)
                event = replace(event, invoice_number=payee.get("invoice_number"),
                    valid_until=payee.get("valid_until"), evidence=_proof((*event.evidence, *extra)))
            elif event.kind == "TAX_GARNISHMENT_ORDER":
                # Match the exact ERP reference rather than inventing a clock.
                matches = [r for r in vendor["garnishments"]
                           if event.event_id == r["ref"]]
                if len(matches) != 1:
                    raise ValueError("registered garnishment reference must be exact and unique")
                row = matches[0]
                event = replace(event, valid_until=row.get("valid_until"),
                    invoice_number=row.get("invoice_number"), evidence=_proof((*event.evidence,
                        *(Evidence("erp/vendors", f"id={scope.vendor}.garnishments.{row['ref']}.{name}")
                          for name in ("valid_until", "invoice_number") if name in row))))
            if event.kind == _CERTIFICATE:
                event = replace(event, scope=scope, evidence=_proof((*event.evidence, *base_proof,
                    Evidence(_POLICY, "§2.2.4 contractor tax status is independent of invoice currency"))))
            elif event.scope != scope:
                diagnostics.append(f"REGISTERED_NOTICE_CURRENCY_UNKNOWN:{event.event_id}")
                uncertain.add(event.kind)
                continue
            else:
                event = replace(event, evidence=_proof((*event.evidence, *base_proof)))
            events.append(event)
        timeline = replay_events(events)
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        uncertain.update(KINDS[:3])
        diagnostics.append("REGISTERED_NOTICE_CONTEXT_UNKNOWN:" + str(error))
    notice_results, bank_fields = [], {}
    for doc_id in sorted(prepared):
        task = prepared[doc_id]
        if not isinstance(task, APTaskSources) or task.doc_id != doc_id:
            raise ValueError("prepared task identity must be exact and typed")
        operational = tuple(prepared.diagnostics.get(doc_id, ()))
        if any(not note.startswith("UNLISTED_ATTACHMENT:") for note in operational):
            incomplete.add(task.message.path)
            diagnostics.extend(f"{doc_id}:{note}" for note in operational)
        if not task.attachments:
            incomplete.add(task.message.path)
            diagnostics.append(f"{doc_id}:NOTICE_SOURCE_INVENTORY_UNKNOWN")
        bridge = APDocumentBridge.from_task_sources(task)
        for issue in bridge.source_issues:
            incomplete.add(issue.source_path)
            diagnostics.append(f"{issue.source_path}:SOURCE_INCOMPLETE:{issue.diagnostic}")
            proofs.append(Evidence(issue.source_path, issue.diagnostic))
        for source in sorted(bridge.sources, key=lambda s: s.source_path):
            fields = source.facts.fields
            proofs.extend(f.evidence for values in fields.values() for f in values)
            classification = source.classification
            proofs.extend(f.evidence for f in classification.evidence)
            if classification.status != "CLASSIFIED":
                incomplete.add(source.source_path)
                diagnostics.append(f"{source.source_path}:NOTICE_TYPE_UNKNOWN")
                continue
            kind = classification.document_type
            if kind in {"PROFORMA", "VENDOR_STATEMENT"}:
                result = replace(apply_notice(kind, state=timeline), evidence=_proof(
                    f.evidence for values in fields.values() for f in values))
                notice_results.append(PhaseNoticeResult(source.source_path, kind, result))
                continue
            if kind not in KINDS:
                continue  # The explicit nine-type classification proves no operative notice.
            status, binding_proof, notes = _scope_binding(fields, kind, catalog, data, scope)
            proofs.extend(binding_proof)
            diagnostics.extend(f"{source.source_path}:{note}" for note in notes)
            if status == "FOREIGN":
                continue
            if status != "MATCH":
                incomplete.add(source.source_path)
                notice_results.append(PhaseNoticeResult(source.source_path, kind,
                    NoticeResolution("UNKNOWN", None, timeline, _proof((*binding_proof,
                        *(f.evidence for values in fields.values() for f in values))), notes)))
                continue
            if source.diagnostics or source.extraction_unknowns:
                uncertain.add(kind)
                diagnostics.append(f"{source.source_path}:NOTICE_OBSERVATIONS_UNKNOWN")
            message = task.message
            metadata = None
            try:
                metadata = DocumentFacts(message.source_sha256, "phase-notice-message-v1", {
                    "doc_id": [Fact(doc_id, Evidence(message.path, "doc_id"))],
                    "received_at": [Fact(message.received_at, Evidence(message.path, "received_at"))]})
            except ValueError:
                uncertain.add(kind)
                diagnostics.append(f"{source.source_path}:NOTICE_MESSAGE_SOURCE_UNKNOWN")
            if metadata is None or source.diagnostics or source.extraction_unknowns:
                result = NoticeResolution("UNKNOWN", None, timeline, _proof((*binding_proof,
                    *(f.evidence for values in fields.values() for f in values))),
                    ("NOTICE_FACTS_UNKNOWN",))
            else:
                result = resolve_ap_notice(kind, fields=fields, company=scope.company,
                    vendor=scope.vendor, currency=scope.currency, metadata=metadata, state=timeline)
            if result.decision == "UNKNOWN":
                uncertain.add(kind)
            # Scope proofs are adapter evidence, not fabricated attachment observations.
            original_ids = {(e.scope, e.event_id) for e in timeline.events}
            events = tuple(replace(e, evidence=_proof((*e.evidence, *binding_proof)))
                if (e.scope, e.event_id) not in original_ids else e for e in result.state.events)
            timeline = replay_events(events)
            result = replace(result, state=timeline, evidence=_proof((*result.evidence, *binding_proof)))
            proofs.extend(result.evidence)
            notice_results.append(PhaseNoticeResult(source.source_path, kind, result))
            diagnostics.extend(f"{source.source_path}:{note}" for note in result.diagnostics)
            if kind == "BANK_DETAILS_CHANGE" and result.decision != "UNKNOWN":
                for event in timeline.events:
                    if (event.scope, event.event_id) not in original_ids:
                        bank_fields[event.scope, event.event_id] = MappingProxyType({
                            name: tuple(deepcopy(values)) for name, values in fields.items()})
    if incomplete:
        uncertain.update(KINDS)
    for kind in uncertain:
        completeness.pop(kind, None)
    if incomplete:
        completeness.clear()
    # Include the full inspected source evidence in surviving inventory claims.
    proof = _proof((*proofs, *base_proof))
    completeness = {kind: _proof((*items, *proof)) for kind, items in completeness.items()}
    if load_ap_task_inventory(data.phase_dir) != inventory or any(
            sha256(_safe_file(data.phase_dir, name).read_bytes()).hexdigest() != digest
            for name, (_, digest) in paths.items()):
        raise ValueError("notice context sources changed during planning")
    return PhaseNoticeContext(timeline, tuple(sorted(uncertain)), tuple(sorted(incomplete)),
        MappingProxyType(dict(sorted(completeness.items()))), tuple(notice_results), proof,
        tuple(sorted(set(diagnostics))), MappingProxyType(bank_fields),
        tuple(sorted((name, digest) for name, (_, digest) in paths.items())))
