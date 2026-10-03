"""Source/identity/PO context for the ordinary-invoice coordinator (#140).

This adapter prepares facts, not accounting decisions or monetary posting inputs.
A primary attachment projects rows only; every financial attachment remains an
independent arithmetic/CFDI source. Uninterpreted companions remain visible.
"""
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from calendar import monthrange
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType

from .ap_chronology import receipt_key
from .ap_document_bridge import APDocumentBridge, APFactSet, APField, APLineFacts, APSourceView
from .ap_erp import APERPBaseline
from .ap_holds import PriceLine, PricePortion
from .ap_identity import APIdentityResult, IdentityCatalog, normalize_tax_identifier
from .ap_order_bridge import APOrderBridge, APOrderMatch
from .ap_orders import POCandidate, POQuery
from .ap_pipeline import APInvoiceRequest
from .ap_project_binding import resolve_ap_project_binding
from .ap_transaction import APTransactionState
from .data import PhaseData
from .documents.ap_sources import APTaskSources
from .facts import DocumentFacts, Evidence, Fact
from .model.ap_duplicate_record import DuplicateRecord
from .model.ap_scope import ApScope

CONTEXT_VERSION = "ap-invoice-context-v1"
_REJECTION_FLAGS = ("isp_required", "vat_check_applicable", "withholding_required",
                    "certification_applicable", "cfdi_applicable")
_HOLD_FLAGS = ("vendor_in_master", "bank_differs", "signed_change_supported", "factoring_supported",
               "similar_domain", "quantity_check_applicable", "price_check_applicable")
_BASIS = {"BEFORE_APPLIED_ADVANCES", "AFTER_APPLIED_ADVANCES"}


def _file_sha256(path):
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class _APInvoiceContextBatch:
    """Private verified read snapshot; only publish a batch after verify() succeeds."""
    data: PhaseData
    baseline: APERPBaseline
    orders: APOrderBridge
    identities: IdentityCatalog
    source_hashes: tuple[tuple[Path, str], ...]

    def verify(self):
        for path, expected in self.source_hashes:
            if (not path.resolve().is_relative_to(self.data.phase_dir)
                    or "golden" in path.resolve().parts or _file_sha256(path) != expected):
                raise ValueError("invoice-context batch sources changed during planning")


def _prepare_invoice_context_batch(data: PhaseData, baseline: APERPBaseline):
    """Build once, reuse immutable matching/history, then verify after all tasks."""
    orders = APOrderBridge.from_phase(data.phase_dir, baseline)
    data = PhaseData(data.phase_dir)
    paths = [(data.phase_dir / source.path, source.sha256) for source in baseline.sources]
    companies_path = next((data.phase_dir / "erp" / ("companies" + suffix)
        for suffix in (".jsonl", ".json")
        if (data.phase_dir / "erp" / ("companies" + suffix)).is_file()), None)
    if companies_path is None or not companies_path.resolve().is_relative_to(data.phase_dir) or "golden" in companies_path.resolve().parts:
        raise ValueError("safe active-phase companies master required")
    paths.append((companies_path, _file_sha256(companies_path)))
    projects_path = next((data.phase_dir / "erp" / ("projects" + suffix)
        for suffix in (".jsonl", ".json")
        if (data.phase_dir / "erp" / ("projects" + suffix)).is_file()), None)
    if projects_path is not None:
        if not projects_path.resolve().is_relative_to(data.phase_dir) or "golden" in projects_path.resolve().parts:
            raise ValueError("safe active-phase projects master required")
        paths.append((projects_path, _file_sha256(projects_path)))
    identities = IdentityCatalog.from_phase(data)
    data.table("purchase_orders")  # one cached read for exact reference scope
    batch = _APInvoiceContextBatch(data, baseline, orders, identities, tuple(paths))
    batch.verify()
    return batch


@dataclass(frozen=True)
class APInvoiceLineContext:
    source: APLineFacts
    query: POQuery | None
    match: APOrderMatch | None
    candidates: tuple[POCandidate, ...] = ()
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class APInvoiceContext:
    status: str  # RESOLVED (structural only), UNKNOWN, UNSUPPORTED
    bridge: APDocumentBridge
    financial_sources: tuple[APSourceView, ...]
    primary_source: APSourceView | None
    financial_facts: APFactSet
    identity: APIdentityResult
    scope: ApScope | None
    observation: DuplicateRecord | None
    received_at: Fact | None
    invoice_date: Fact | None
    expected_company: Fact | None
    lines: tuple[APInvoiceLineContext, ...]
    rejection_fields: Mapping[str, tuple[Fact, ...]]
    hold_fields: Mapping[str, tuple[Fact, ...]]
    request: APInvoiceRequest | None
    evidence: tuple[Evidence, ...]
    diagnostics: tuple[str, ...]
    order_snapshot_sha256: str
    version: str = CONTEXT_VERSION


def _combined(sources):
    fields = {}
    for source in sources:
        for name, candidates in source.facts.fields.items():
            if not name.startswith("line."):
                fields.setdefault(name, []).extend(candidates)
    return APFactSet(fields)


def _proofs(*collections):
    return tuple(dict.fromkeys(proof for collection in collections for proof in collection))


def _facts(value, evidence):
    return tuple(Fact(value, proof) for proof in evidence)


def _one(field: APField) -> Fact | None:
    return Fact(field.value, field.evidence[0]) if field.known and field.evidence else None


def _identity_candidates(field, diagnostics):
    if field.status == "INVALID":
        return None
    for fact in field.candidates:
        if fact.value is None or isinstance(fact.value, str) and not fact.value.strip():
            continue
        try:
            normalize_tax_identifier(fact.value)
        except (TypeError, ValueError):
            diagnostics.append(f"IDENTIFIER_INVALID:{field.name}")
            return None
    return field.candidates


def _master_fact(row, key, field):
    if row is None or field not in row:
        return ()
    return (Fact(row[field], Evidence("erp/vendors.jsonl", f"id={key}.{field}")),)


def _bool_candidates(candidates, name, diagnostics):
    field = APFactSet({name: candidates}).field(name)
    if not field.known or type(field.value) is not bool:
        diagnostics.append(f"CONTEXT_FLAG_UNKNOWN:{name}:{field.status}")
        return None
    return _one(field)


def _reference_scope(financial, *, data, vendor, currency, invoice_date, diagnostics):
    """Exact observed references prove ordering company only in supplier/currency/date scope."""
    if vendor is None or not currency.known or not invoice_date.known:
        return ()
    refs = []
    for source in financial:
        for facts in (source.facts, *(line.facts for line in source.lines)):
            field = facts.text("po_reference")
            if field.status in {"CONFLICT", "INVALID"}:
                diagnostics.append(f"ORDER_SCOPE_REFERENCE_UNKNOWN:{source.source_path}")
                return ()
            if field.known:
                refs.append(field)
    orders = data.table("purchase_orders")
    company_facts = []
    for reference in refs:
        matching = [row for row in orders if row["id"] == reference.value
                    and row["vendor"] == vendor and row["currency"] == currency.value
                    and row["created_on"] <= invoice_date.value]
        if not matching:
            diagnostics.append(f"ORDER_SCOPE_REFERENCE_UNCONFIRMED:{reference.value}")
            return ()
        for row in matching:
            company_facts.extend(_facts(row["company"], reference.evidence))
            company_facts.append(Fact(row["company"], Evidence("erp/purchase_orders.jsonl",
                f"id={row['id']};vendor={vendor};currency={currency.value}.company")))
    return tuple(company_facts)


def _line_field(line, primary, name, kind="text"):
    local = line.field(name, kind=kind)
    header = primary.field(name, kind=kind)
    # A contradictory printed header/line is not an instruction to choose one.
    if local.candidates and header.candidates:
        return APFactSet({name: (*local.candidates, *header.candidates)}).field(name, kind=kind)
    return local if local.candidates else header


def _receipt_references(line, primary):
    references, evidence, diagnostics = [], [], []
    for source in (primary.facts, line.facts):
        for name in source.fields:
            if (name not in {"receipt_reference", "delivery_reference"}
                    and not (name.startswith("delivery.") and name.endswith(".document_number"))):
                continue
            field = source.text(name)
            evidence.extend(field.evidence)
            if field.known:
                references.append(field.value)
            elif field.status not in {"MISSING", "UNKNOWN"}:
                diagnostics.append(f"RECEIPT_REFERENCE_UNKNOWN:{name}")
    return tuple(dict.fromkeys(references)), tuple(evidence), tuple(diagnostics)


async def resolve_ap_invoice_context(
    task: APTaskSources, *, data: PhaseData, baseline: APERPBaseline, state: APTransactionState,
    receipt_as_of: Fact | None, expected_company: Fact | None = None,
    financial_source_paths: tuple[str, ...] | None = None, resolver=None,
    _batch: _APInvoiceContextBatch | None = None,
) -> APInvoiceContext:
    """Prepare a structural request from verified prepared sources and the active ERP.

    ``financial_source_paths`` selects exactly one primary row projection when
    several invoice attachments exist. It never filters ``amount_sources``.
    The caller supplies observed cutoff/expected-company facts, not defaults.
    Duplicate/event inventories, complete fiscal applicability and monetary line
    bindings remain the phase planner's responsibility. No receipt is consumed.
    """
    if (not isinstance(task, APTaskSources) or not isinstance(data, PhaseData)
            or not isinstance(baseline, APERPBaseline) or not isinstance(state, APTransactionState)):
        raise TypeError("typed prepared task, active phase, ERP baseline and AP state required")
    if expected_company is not None and not isinstance(expected_company, Fact):
        raise TypeError("expected company requires an observed Fact")
    if receipt_as_of is not None and not isinstance(receipt_as_of, Fact):
        raise TypeError("receipt cutoff requires an observed Fact")
    if _batch is None:
        orders = APOrderBridge.from_phase(data.phase_dir, baseline)
        # Do not mix an old PhaseData cache with the verified current ERP snapshot.
        data = PhaseData(data.phase_dir)
        catalog = IdentityCatalog.from_phase(data)
    else:
        if (not isinstance(_batch, _APInvoiceContextBatch) or baseline is not _batch.baseline
                or data.phase_dir != _batch.data.phase_dir):
            raise ValueError("invoice context batch belongs to a different phase/baseline")
        orders, data, catalog = _batch.orders, _batch.data, _batch.identities
    bridge = APDocumentBridge.from_task_sources(task)
    financial = bridge.financial_sources
    fields = _combined(financial)
    diagnostics = [f"SOURCE_ROLE_UNKNOWN:{issue.source_path}:{issue.diagnostic}" for issue in bridge.source_issues]
    diagnostics.extend(f"SOURCE_ROLE_UNKNOWN:{source.source_path}:{source.classification.status}"
                       for source in bridge.unclassified_sources)
    diagnostics.extend(f"SOURCE_OBSERVATION_UNKNOWN:{source.source_path}:{note}"
                       for source in bridge.sources for note in source.diagnostics)
    financial_types = {source.classification.document_type for source in financial}
    unsupported = bool(financial_types) and "INVOICE" not in financial_types
    if unsupported or financial_types != {"INVOICE"}:
        diagnostics.append("ORDINARY_INVOICE_TYPE_UNCONFIRMED" if not unsupported
                           else "CREDIT_OR_ADVANCE_CONTEXT_NOT_IMPLEMENTED")

    primary = None
    if financial_source_paths is not None:
        if (not isinstance(financial_source_paths, tuple) or len(financial_source_paths) != 1
                or financial_source_paths[0] not in {source.source_path for source in financial}):
            raise ValueError("select exactly one existing financial attachment for row projection")
        primary = next(source for source in financial if source.source_path == financial_source_paths[0])
    elif len(financial) == 1:
        primary = financial[0]
    else:
        diagnostics.append("PRIMARY_FINANCIAL_SOURCE_SELECTION_REQUIRED")

    header = fields.header
    for field in (header.issuer_tax_id, header.recipient_tax_id, header.invoice_number,
                  header.invoice_date, header.currency, header.net_cents, header.tax_cents, header.gross_cents):
        if not field.known:
            diagnostics.append(f"FINANCIAL_FIELD_UNKNOWN:{field.name}:{field.status}")
    supplier_candidates = _identity_candidates(header.issuer_tax_id, diagnostics)
    recipient_candidates = _identity_candidates(header.recipient_tax_id, diagnostics)
    identity = catalog.resolve(supplier_tax_ids=supplier_candidates,
                               recipient_tax_ids=recipient_candidates, expected_company=None)
    referenced_companies = _reference_scope(financial, data=data, vendor=identity.supplier.identity,
        currency=header.currency, invoice_date=header.invoice_date, diagnostics=diagnostics)
    observed_company = () if expected_company is None else (expected_company,)
    company_field = APFactSet({"company": (*observed_company, *referenced_companies)}).text("company")
    company_fact = _one(company_field)
    if company_fact is not None:
        identity = catalog.resolve(supplier_tax_ids=supplier_candidates,
            recipient_tax_ids=recipient_candidates, expected_company=company_fact.value)
    else:
        diagnostics.append(f"ORDERING_COMPANY_UNKNOWN:{company_field.status}")
    company = company_fact.value if company_fact is not None else identity.recipient.identity
    scope = (ApScope(company, identity.supplier.identity, header.currency.value)
             if company and identity.supplier.identity and header.currency.known else None)
    if identity.supplier.status != "RESOLVED":
        diagnostics.append(f"SUPPLIER_IDENTITY_UNKNOWN:{identity.supplier.status}")
    if identity.recipient.status != "RESOLVED":
        diagnostics.append(f"RECIPIENT_IDENTITY_UNKNOWN:{identity.recipient.status}")

    received = None
    try:
        if task.message.received_at is None or not task.message.source_sha256:
            raise ValueError("message reception not observed")
        if receipt_key(task.message.received_at).strftime("%Y-%m") != baseline.month:
            raise ValueError("message reception differs from active month")
        received = Fact(task.message.received_at, Evidence(task.message.path, "received_at",
                                                         quote=task.message.received_at))
    except (ValueError, TypeError):
        diagnostics.append("MESSAGE_RECEPTION_UNKNOWN")
    invoice_date = _one(header.invoice_date)
    cutoff = None
    try:
        if receipt_as_of is None or not isinstance(receipt_as_of.value, str):
            raise ValueError("cutoff not observed")
        value = date.fromisoformat(receipt_as_of.value)
        year, month = map(int, baseline.month.split("-"))
        if (value.isoformat() != receipt_as_of.value or value > date(year, month, monthrange(year, month)[1])
                or received is None or value < receipt_key(received.value).date()):
            raise ValueError("cutoff outside the evidenced phase window")
        cutoff = receipt_as_of
    except (TypeError, ValueError):
        diagnostics.append("RECEIPT_CUTOFF_UNKNOWN")

    rejection = {name: tuple(fields.fields.get(name, ())) for name in _REJECTION_FLAGS}
    for target, source in (("recipient_nif", "recipient_tax_id"), ("charged_vat_cents", "tax_cents"),
            ("billed_net_cents", "net_cents"), ("net_cents", "net_cents"), ("tax_cents", "tax_cents"),
            ("gross_cents", "gross_cents"), ("withholding_cents", "withholding_cents"),
            ("certification_current_cents", "certification_current_cents"),
            ("certification_cumulative_cents", "certification_cumulative_cents"), ("vat_lines", "vat_lines")):
        rejection[target] = tuple(fields.fields.get(source, ()))
    rejection["recipient_company"] = _facts(identity.recipient.identity, identity.recipient.evidence) if identity.recipient.identity else ()
    rejection["order_company"] = (*observed_company, *referenced_companies)
    holds = {name: tuple(fields.fields.get(name, ())) for name in _HOLD_FLAGS}
    if identity.supplier.status in {"RESOLVED", "NOT_FOUND"}:
        holds["vendor_in_master"] += _facts(identity.supplier.status == "RESOLVED", identity.supplier.evidence)
    vendor = data.get("vendors", identity.supplier.identity) if identity.supplier.identity else None
    vendor_id = identity.supplier.identity
    withholding = _master_fact(vendor, vendor_id, "withholding")
    if withholding:
        if withholding[0].value is None or isinstance(withholding[0].value, str) and withholding[0].value.strip():
            rejection["withholding_required"] += tuple(Fact(f.value is not None, f.evidence) for f in withholding)
        else:
            diagnostics.append("MASTER_FACT_INVALID:withholding")
    for name in (*_REJECTION_FLAGS, *_HOLD_FLAGS):
        explicit = _master_fact(vendor, vendor_id, name)
        (rejection if name in _REJECTION_FLAGS else holds)[name] += explicit
    construction_candidates = tuple(fields.fields.get("construction_subcontractor", ())) + _master_fact(vendor, vendor_id, "construction_subcontractor")
    # Only a positively identified construction reverse-charge regime proves this
    # applicability. Other/missing codes are not evidence of non-construction.
    code = _master_fact(vendor, vendor_id, "default_tax_code")
    if code and code[0].value in {"SISP", "PAUT"}:
        works = (Fact(True, code[0].evidence),)
        construction_candidates += works
        rejection["isp_required"] += works
    construction = _bool_candidates(construction_candidates, "construction_subcontractor", diagnostics)
    guarantee_candidates = tuple(fields.fields.get("guarantee_applicable", ())) + _master_fact(vendor, vendor_id, "guarantee_applicable")
    guarantee = _master_fact(vendor, vendor_id, "guarantee_retention_bp")
    if guarantee and type(guarantee[0].value) is int and guarantee[0].value >= 0:
        guarantee_candidates += (Fact(guarantee[0].value > 0, guarantee[0].evidence),)
    guarantee_fact = _bool_candidates(guarantee_candidates, "guarantee_applicable", diagnostics)
    basis = fields.text("source_payable_basis")
    basis_fact = _one(basis) if basis.value in _BASIS else None
    if basis_fact is None:
        diagnostics.append("SOURCE_PAYABLE_BASIS_UNKNOWN")
    iban = fields.text("iban")
    holds["invoice_bank_iban"] = tuple(fields.fields.get("iban", ()))
    master_bank = vendor.get("bank") if vendor is not None else None
    if iban.known and isinstance(master_bank, dict) and isinstance(master_bank.get("iban"), str) and master_bank["iban"]:
        try:
            different = normalize_tax_identifier(iban.value) != normalize_tax_identifier(master_bank["iban"])
            holds["bank_differs"] += _facts(different, (*iban.evidence, Evidence("erp/vendors.jsonl", f"id={vendor_id}.bank.iban")))
        except (TypeError, ValueError):
            diagnostics.append("BANK_ACCOUNT_COMPARISON_UNKNOWN")

    # CFDI field views preserve independent observations; no twin is made up.
    if any(any(name.startswith("raw.xml./Comprobante") for name in s.facts.fields) for s in financial):
        rejection["cfdi_applicable"] += tuple(Fact(True, fact.evidence) for s in financial
            for name, facts_ in s.facts.fields.items() if name.startswith("raw.xml./Comprobante")
            for fact in facts_)
        names = dict(number="document_number", date="document_date", issuer_tax_id="supplier_tax_id",
                     recipient_tax_id="recipient_tax_id", currency="currency", net_cents="net_cents",
                     tax_cents="tax_cents", gross_cents="gross_cents")
        for source in financial:
            attachment = next(a for a in task.attachments if a.path == source.source_path)
            media = attachment.document.media_type if attachment.document is not None else None
            kind = "cfdi_xml" if any(name.startswith("raw.xml./Comprobante") for name in source.facts.fields) else "cfdi_pdf" if media == "application/pdf" else None
            if kind:
                view = {name: source.field(field).value if source.field(field).known else None for name, field in names.items()}
                proof = tuple(e for field in names.values() for e in source.field(field).evidence)
                rejection[kind] = (*rejection.get(kind, ()), *_facts(view, proof))

    lines, prices, quantity_evidence, project_evidence = [], [], [], []
    project_rows, project_source, project_loaded = None, "erp/projects.jsonl", False
    if primary is not None and not unsupported:
        for line in primary.lines:
            notes = []
            quantity, uom = line.quantity_milli, line.uom
            optional = {name: _line_field(line, primary, name, kind) for name, kind in (
                ("po_reference", "text"), ("po_item", "integer"), ("project_reference", "text"),
                ("material", "text"), ("description", "text"))}
            refs, ref_evidence, ref_notes = _receipt_references(line, primary)
            notes.extend(ref_notes)
            for field in (quantity, uom):
                if not field.known:
                    notes.append(f"QUERY_FIELD_UNKNOWN:{field.name}:{field.status}")
            if quantity.known and quantity.value <= 0:
                notes.append("QUERY_QUANTITY_NOT_POSITIVE")
            for name, field in optional.items():
                if field.status in {"INVALID", "CONFLICT"}:
                    notes.append(f"QUERY_FIELD_UNKNOWN:{name}:{field.status}")
            if scope is None or invoice_date is None or cutoff is None:
                notes.append("QUERY_SCOPE_DATE_OR_CUTOFF_UNKNOWN")
            observed_project = optional["project_reference"]
            if observed_project.candidates and scope is not None and not project_loaded:
                project_loaded = True
                try:
                    project_path = data._path("projects")
                    project_source = project_path.relative_to(data.phase_dir).as_posix()
                    project_rows = data.table("projects")
                except (KeyError, TypeError, ValueError):
                    project_rows = None
            project_binding = resolve_ap_project_binding(observed_project,
                company=None if scope is None else scope.company,
                projects=project_rows, project_source=project_source)
            project_evidence.extend(project_binding.evidence)
            if project_binding.status == "UNKNOWN":
                notes.extend(project_binding.diagnostics)
            query, match = None, None
            if not notes:
                evidence = _proofs(quantity.evidence, uom.evidence, ref_evidence,
                                   project_binding.evidence, *(field.evidence for field in optional.values()))
                query = POQuery(line.line_id, scope.company, scope.vendor, scope.currency,
                    quantity.value, uom.value, evidence, po_reference=optional["po_reference"].value,
                    po_item=optional["po_item"].value, receipt_references=refs,
                    project=project_binding.project_id, material=optional["material"].value,
                    description=optional["description"].value)
                attachment = next(a for a in task.attachments if a.path == primary.source_path)
                match = await orders.resolve(query, invoice_date=invoice_date.value, receipt_as_of=cutoff.value,
                    state=state.consumption, document=attachment.document, resolver=resolver)
                notes.extend(match.diagnostics)
                if match.reference.status != "RESOLVED":
                    notes.append(f"ORDER_REFERENCE_UNKNOWN:{match.reference.status}")
                if match.quantity_status == "UNKNOWN":
                    notes.append("ORDER_QUANTITY_UNKNOWN")
                if match.reference.selected is not None:
                    selected = match.reference.selected
                    quantity_evidence.extend(selected.evidence)
                    if line.unit_price_cents.known:
                        key = selected.order
                        price_proof = Evidence("erp/purchase_orders.jsonl",
                            f"company={key.company};vendor={key.vendor};currency={key.currency};id={key.po};item={key.item}.unit_price")
                        prices.append(PriceLine(line.line_id, line.unit_price_cents.candidates,
                            (PricePortion(selected.order, query.quantity_milli,
                              (Fact(selected.unit_price_cents, price_proof),)),)))
            lines.append(APInvoiceLineContext(line, query, match,
                () if match is None else match.reference.candidates, tuple(notes)))
            diagnostics.extend(f"{line.line_id}:{note}" for note in notes)
        if not primary.lines:
            diagnostics.append("PRIMARY_INVOICE_LINES_UNKNOWN")
    if any(line.match is not None and line.match.reference.status == "RESOLVED" for line in lines):
        proof = _proofs(*(line.match.reference.selected.evidence for line in lines if line.match is not None and line.match.reference.selected is not None))
        holds["quantity_check_applicable"] += _facts(True, proof)
        holds["price_check_applicable"] += _facts(True, proof)
    elif vendor is not None and vendor.get("po_required") is True:
        fact = _master_fact(vendor, vendor_id, "po_required")
        holds["quantity_check_applicable"] += _facts(True, (fact[0].evidence,))
        holds["price_check_applicable"] += _facts(True, (fact[0].evidence,))

    evidence = _proofs(*(tuple(f.evidence for candidates in source.facts.fields.values() for f in candidates) for source in financial),
        identity.supplier.evidence, identity.recipient.evidence,
        *(tuple(f.evidence for f in candidates) for candidates in (*rejection.values(), *holds.values())),
        tuple(f.evidence for f in (construction, guarantee_fact, basis_fact) if f is not None),
        quantity_evidence, project_evidence, () if received is None else (received.evidence,),
        () if cutoff is None else (cutoff.evidence,))
    observation = None
    if company and identity.supplier.identity and header.invoice_number.known and received is not None and financial_types == {"INVOICE"}:
        start, end = fields.date("period_start"), fields.date("period_end")
        observation = DuplicateRecord(task.doc_id, company, identity.supplier.identity,
            header.currency.value if header.currency.known else None, header.invoice_number.value,
            received.value, header.gross_cents.value if header.gross_cents.known else None,
            evidence, status="RECEIVED", service_period=f"{start.value}/{end.value}" if start.known and end.known else None)
    rejection, holds = MappingProxyType(rejection), MappingProxyType(holds)
    request = None
    if observation is not None:
        sources = tuple(DocumentFacts(source.source_sha256, next(a.normalized.facts.extractor_version for a in task.attachments if a.path == source.source_path),
                                      {name: list(facts_) for name, facts_ in source.facts.fields.items()}) for source in financial)
        receipt_source = next((source.path for source in baseline.sources if source.path.startswith("erp/goods_receipts.")), None)
        request = APInvoiceRequest(observation=observation, duplicate_inventory_complete=None,
            rejection_fields=rejection, amount_sources=sources, hold_fields=holds,
            construction_subcontractor=construction, invoice_date=invoice_date,
            price_lines=tuple(prices), quantity_evidence=tuple(quantity_evidence),
            receipt_inventory_complete=Fact(True, Evidence(receipt_source, "active-phase complete catalogue")) if receipt_source else None,
            receipt_as_of=cutoff, guarantee_applicable=guarantee_fact, source_payable_basis=basis_fact)
    # Optional gate facts do not decide this structural status; diagnostics carry
    # their unknowns. All accounting eligibility remains with the coordinator.
    structural_notes = [note for note in diagnostics if not note.startswith(("CONTEXT_FLAG_UNKNOWN:", "SOURCE_PAYABLE_BASIS_UNKNOWN"))]
    status = "UNSUPPORTED" if unsupported else "RESOLVED" if request is not None and not structural_notes else "UNKNOWN"
    return APInvoiceContext(status, bridge, financial, primary, fields, identity, scope, observation,
        received, invoice_date, company_fact, tuple(lines), rejection, holds, request, evidence,
        tuple(dict.fromkeys(diagnostics)), orders.snapshot_sha256)
