"""Saved sources → real AP policies → complete phase export, without a provider.

Unresolved tasks remain audit results. They never become guessed AP decisions.
Each invocation reconstructs its simulation from the active ERP receipt history.
"""
from collections import Counter
from dataclasses import dataclass, replace
import json
from pathlib import Path
from time import perf_counter_ns

from .ap_chronology import receipt_key
from .ap_coding import CodingCatalog
from .ap_document_bridge import APFactSet, DOCUMENT_BRIDGE_VERSION
from .ap_erp import load_ap_erp_baseline
from .ap_invoice_context import CONTEXT_VERSION, _prepare_invoice_context_batch, resolve_ap_invoice_context
from .ap_line_source_bridge import APLineSourceBinding, LINE_SOURCE_BRIDGE_VERSION
from .ap_output import build_ap_row
from .ap_phase_export import load_ap_task_inventory
from .ap_phase_notice_context import PHASE_NOTICE_CONTEXT_VERSION, resolve_phase_notice_context
from .ap_pipeline import APQuantityCheckInputs, evaluate_ap_invoice
from .ap_posting_source_bridge import (
    APGuaranteePostingPlan, POSTING_SOURCE_BRIDGE_VERSION, prepare_ap_invoice_posting,
)
from .ap_source_plan import _context_audit, _json
from .ap_sources import _read_prepared_source_bytes, _safe_file, load_prepared_ap_sources
from .ap_tax import TaxCatalog
from .ap_transaction import APTransactionState
from .ap_withholding import WithholdingCatalog
from .data import PhaseData
from .documents.contracts import digest, fingerprint
from .facts import Evidence, Fact
from .model.ap_scope import ApScope
from .money import RateTable

PHASE_RUNNER_VERSION = "ap-phase-runner-v1"
_PASSIVE_NOTICES = {"PROFORMA", "VENDOR_STATEMENT"}
_OPERATIONAL_NOTICES = {"CONTRACTOR_TAX_CERTIFICATE", "FACTORING_NOTICE",
                        "TAX_GARNISHMENT_ORDER", "BANK_DETAILS_CHANGE"}


@dataclass(frozen=True)
class APPhaseRun:
    report: dict
    rows: tuple[dict, ...]
    state: APTransactionState
    tax_catalog: TaxCatalog | None

    @property
    def complete(self):
        return self.report["run"]["complete"]


def _one(field):
    return Fact(field.value, field.evidence[0]) if field.known and field.evidence else None


def _quantity_request(context, baseline):
    """Quantity controls need no invented net, tax, coding or advance inputs."""
    request = context.request
    if request is None or len(context.financial_sources) != 1 or not context.lines:
        return request
    matches = tuple(line.match for line in context.lines)
    if any(match is None or match.reference.status != "RESOLVED"
           or match.quantity_line is None for match in matches):
        return request
    if request.receipt_as_of is None:
        return request
    quantity = APQuantityCheckInputs(
        quantity_lines=tuple(match.quantity_line for match in matches),
        order_catalog=baseline.orders, receipt_catalog=baseline.receipts,
        order_prices=baseline.prices, receipt_as_of=request.receipt_as_of.value)
    bindings = tuple(APLineSourceBinding(line.source.line_id, line.source.source_path,
                                        line.source.index) for line in context.lines)
    return replace(request, quantity_inputs=quantity, line_source_bindings=bindings)


def _explicit_notice_scopes(source, data, identities):
    """A standalone notice needs its own exact scope, never an email/default."""
    fields = source.facts.fields
    def candidates(*names):
        return tuple(f for name in names for alias in (name, "raw." + name)
                     for f in fields.get(alias, ()))
    certificate = source.classification.document_type == "CONTRACTOR_TAX_CERTIFICATE"
    taxes = {"vendor": candidates(*(("certificate_tax_id", "certificate_subject_tax_id", "subject_tax_id", "holder_tax_id")
        if certificate else ("supplier_tax_id", "vendor_tax_id"))),
        "company": candidates("recipient_tax_id")}
    try:
        identity = identities.resolve(supplier_tax_ids=taxes["vendor"],
            recipient_tax_ids=taxes["company"], expected_company=None)
    except (TypeError, ValueError):
        return ()
    values = {}
    for name, aliases, match in (("company", ("company", "company_code"), identity.recipient),
                                ("vendor", ("vendor", "vendor_id"), identity.supplier)):
        observed = APFactSet({name: candidates(*aliases)}).text(name)
        if observed.candidates and not observed.known or taxes[name] and match.status != "RESOLVED":
            return ()
        ids = {value for value in (observed.value if observed.known else None, match.identity) if value is not None}
        if len(ids) > 1:
            return ()
        values[name] = next(iter(ids)) if ids else None
    currency = APFactSet({"currency": candidates("currency", "document_currency")}).field("currency", kind="currency")
    if currency.candidates and not currency.known or values["vendor"] is None:
        return ()
    try:
        vendor = data.get("vendors", values["vendor"])
        companies = (values["company"],) if values["company"] is not None else (
            tuple(vendor.get("companies", ())) if certificate else ())
        # Contractor tax status is independent of invoice currency (§2.2.4).
        # This is a notice projection, never a financial-currency default.
        projected = currency.value if currency.known else vendor.get("currency") if certificate else None
        if projected is None:
            return ()
        for company in companies:
            data.get("companies", company)
        return tuple(ApScope(company, values["vendor"], projected) for company in companies)
    except (KeyError, ValueError):
        return ()


async def run_ap_phase(phase_path, manifest_path, *, receipt_as_of: Fact | None = None,
                       posting_date: Fact | None = None) -> APPhaseRun:
    """Evaluate every canonical task and return a reviewable, replayable result.

    No files are exported here. The CLI uses the existing complete-inventory
    exporter only when all tasks have real decisions. Ordinary single-position
    invoices and strict notices are supported; positive advance applications,
    credit dispatch, multipart monetary rows and DUA remain explicit limitations.
    """
    started = perf_counter_ns()
    if any(value is not None and not isinstance(value, Fact)
           for value in (receipt_as_of, posting_date)):
        raise TypeError("execution dates require explicit Fact/Evidence")
    phase = Path(phase_path).resolve()
    _safe_file(phase, "tasks/close.json")
    data = PhaseData(phase)
    inventory = load_ap_task_inventory(phase)
    path = Path(manifest_path).absolute()
    code_root = Path(__file__).parent
    code_names = ("ap_phase_runner", "ap_pipeline", "ap_invoice_context", "ap_order_bridge",
        "ap_posting_source_bridge", "ap_line_source_bridge", "ap_document_bridge", "ap_project_binding",
        "ap_phase_notice_context", "ap_notice_bridge", "ap_sources", "ap_erp", "ap_transaction",
        "ap_tax", "ap_withholding", "ap_valuation", "ap_journal", "ap_output", "ap_phase_export")
    code_hashes = {name + ".py": digest((code_root / (name + ".py")).read_bytes()) for name in code_names}
    prepared = load_prepared_ap_sources(phase, path)
    manifest_bytes = _read_prepared_source_bytes(path, phase)
    manifest_sha = digest(manifest_bytes)
    manifest = json.loads(manifest_bytes)
    if (set(prepared) != set(inventory.doc_ids)
            or manifest["stable_source_sha256"] != prepared.stable_source_sha256):
        raise ValueError("verified sources differ from the exact active task inventory")
    baseline = load_ap_erp_baseline(phase, grir_account="40090000")
    batch = _prepare_invoice_context_batch(data, baseline)
    data = batch.data
    pins = {p.relative_to(phase).as_posix(): expected for p, expected in batch.source_hashes}
    def table(stem, *, optional=False):
        try:
            candidate = data._path(stem)
        except KeyError:
            if optional:
                return None
            raise
        actual = _safe_file(phase, candidate.relative_to(phase).as_posix())
        pins[candidate.relative_to(phase).as_posix()] = digest(actual.read_bytes())
        return data.table(stem)
    # Pin all supplemental sources before constructing any cached catalogue.
    tax_source = table("tax_codes", optional=True)
    tax_catalog = None if tax_source is None else TaxCatalog(tax_source)
    withholding_catalog = None if tax_source is None else WithholdingCatalog(tax_source)
    coding = None
    coding_notes = []
    try:
        for stem in ("chart_of_accounts", "cost_centers", "projects"):
            table(stem)
        coding = CodingCatalog.from_phase(data)
    except (KeyError, ValueError, TypeError) as error:
        coding_notes.append("POSTING_CATALOGUE_UNRESOLVED:" + type(error).__name__)
    rates_source = table("fx_rates", optional=True)
    rates = None if rates_source is None else RateTable(rates_source)
    table("contractor_certificates", optional=True)
    state = APTransactionState(consumption=baseline.history.consumption)
    contexts = {}
    for doc_id in inventory.doc_ids:
        contexts[doc_id] = await resolve_ap_invoice_context(prepared[doc_id], data=data,
            baseline=baseline, state=state, receipt_as_of=receipt_as_of, _batch=batch)
    def duplicate_inventory(current):
        # Future messages and explicitly different financial types cannot be a
        # prior ordinary invoice. Unknown clocks/companions remain potential.
        complete = True
        for doc_id, other in contexts.items():
            try:
                if receipt_key(prepared[doc_id].message.received_at) > receipt_key(current.received_at):
                    continue
            except (TypeError, ValueError):
                pass
            bridge = other.bridge
            if (prepared.diagnostics[doc_id] or bridge.source_issues or bridge.unclassified_sources):
                complete = False
                continue
            if any(source.classification.document_type == "INVOICE" for source in other.financial_sources):
                complete = complete and other.observation is not None
        return Fact(complete, Evidence("prepared-ap-sources",
            "ordinary-invoice-inventory-through=" + current.received_at + ";stable-sha256=" + prepared.stable_source_sha256))
    observations = {doc_id: context.observation for doc_id, context in contexts.items()
                    if context.observation is not None}
    notice_cache = {}
    def notices(scope):
        if scope not in notice_cache:
            notice_cache[scope] = resolve_phase_notice_context(prepared, data=data, scope=scope)
        return notice_cache[scope]
    def reception_key(doc_id):
        try:
            return (0, receipt_key(prepared[doc_id].message.received_at), doc_id)
        except (ValueError, TypeError):
            return (1, None, doc_id)
    audits, rows = {}, {}
    for doc_id in sorted(inventory.doc_ids, key=reception_key):
        context = contexts[doc_id]
        bridge = context.bridge
        classification = bridge.classification
        kind = classification.document_type if classification.status == "CLASSIFIED" else None
        proof = list(context.evidence)
        notes = list(prepared.diagnostics[doc_id])
        result, preparation, row, stages = None, None, None, ()
        status = "UNKNOWN"
        if kind in _PASSIVE_NOTICES and not (bridge.source_issues or bridge.unclassified_sources
                or any(s.diagnostics or s.extraction_unknowns for s in bridge.sources)):
            row = build_ap_row(doc_id=doc_id, document_type=kind, decision="NOT_INVOICE", action="NONE")
            status = "DECIDED"
        elif kind in _OPERATIONAL_NOTICES:
            scopes = set(c.scope for c in contexts.values() if c.scope is not None)
            scopes.update(scope for source in bridge.sources
                for scope in _explicit_notice_scopes(source, data, batch.identities))
            resolved = [entry.resolution for scope in sorted(scopes, key=lambda s: (s.company, s.vendor, s.currency))
                for entry in notices(scope).notice_results
                if entry.source_path in {source.source_path for source in bridge.sources}
                and entry.document_type == kind]
            proof.extend(e for item in resolved for e in item.evidence)
            notes.extend(note for item in resolved for note in item.diagnostics)
            if (resolved and all(item.decision == "NOT_INVOICE" for item in resolved)
                    and len({item.action for item in resolved}) == 1 and not notes
                    and not bridge.source_issues and not bridge.unclassified_sources):
                row = build_ap_row(doc_id=doc_id, document_type=kind, decision="NOT_INVOICE", action=resolved[0].action)
                status = "DECIDED"
            else:
                notes.append("NOTICE_ACTION_OR_SCOPE_UNRESOLVED")
        elif context.request is not None:
            request = _quantity_request(context, baseline)
            if (posting_date is not None and coding is not None
                    and tax_catalog is not None and withholding_catalog is not None):
                advance = context.advance_applicable
                base = _one(context.financial_facts.integer("guarantee_base_cents"))
                reference = _one(context.financial_facts.text("contract_reference"))
                guarantee = APGuaranteePostingPlan(base, reference) if base is not None and reference is not None else None
                preparation = prepare_ap_invoice_posting(context, data=data, baseline=baseline,
                    state=state, posting_date=posting_date, coding_catalog=coding,
                    tax_catalog=tax_catalog, withholding_catalog=withholding_catalog,
                    rates=rates, advance_plan=advance, guarantee_plan=guarantee)
                proof.extend(preparation.evidence)
                notes.extend(preparation.diagnostics)
                if preparation.request is not None:
                    request = replace(preparation.request, quantity_inputs=request.quantity_inputs,
                        line_source_bindings=preparation.request.line_source_bindings or request.line_source_bindings)
            else:
                notes.extend(coding_notes)
                if posting_date is None:
                    notes.append("POSTING_DATE_NOT_SUPPLIED")
                if tax_catalog is None:
                    notes.append("FISCAL_CATALOGUE_NOT_SUPPLIED")
            request = replace(request, duplicate_inventory_complete=duplicate_inventory(request.observation))
            if context.scope is not None:
                event_context = notices(context.scope)
                request = replace(request, timeline=event_context.timeline,
                    bank_event_fields=event_context.bank_event_fields,
                    uncertain_event_kinds=event_context.unknown_event_kinds,
                    incomplete_event_sources=event_context.incomplete_sources,
                    event_inventory_evidence=event_context.event_inventory_evidence)
            published = {(o.company, o.doc_id) for o in state.observations}
            history = tuple(observation for observation in observations.values()
                            if (observation.company, observation.doc_id) not in published)
            result = evaluate_ap_invoice(request, state, baseline=baseline, history=history,
                tax_catalog=tax_catalog, withholding_catalog=withholding_catalog, rates=rates)
            state = result.state
            row, status, stages = result.row, result.status, result.stages
            proof.extend(result.evidence)
            notes.extend(result.diagnostics)
            if result.observation is not None:
                observations[doc_id] = result.observation
        else:
            status = "UNSUPPORTED" if context.status == "UNSUPPORTED" else "UNKNOWN"
            notes.extend(context.diagnostics)
        if row is not None:
            rows[doc_id] = row
        audits[doc_id] = dict(task_key=doc_id, status=status, decision=None if row is None else row["decision"],
            row=row, stages=[list(stage) for stage in stages], evidence=_json(tuple(dict.fromkeys(proof))),
            diagnostics=list(dict.fromkeys(notes)), context=_context_audit(context),
            monetary_preparation=None if preparation is None else dict(status=preparation.status,
                header=_json(preparation.header), source_hashes=dict(preparation.source_hashes),
                diagnostics=list(preparation.diagnostics)),
            source_attachments=[dict(path=a.path, source_sha256=None if a.document is None else a.document.source_sha256)
                                for a in prepared[doc_id].attachments])
    # No result escapes if originals, tasks, masters or saved facts changed.
    batch.verify()
    for relative, expected in pins.items():
        if digest(_safe_file(phase, relative).read_bytes()) != expected:
            raise ValueError("active AP phase source changed during execution")
    checked = load_prepared_ap_sources(phase, path)
    if (digest(_read_prepared_source_bytes(path, phase)) != manifest_sha or load_ap_task_inventory(phase) != inventory
            or checked.stable_source_sha256 != prepared.stable_source_sha256):
        raise ValueError("prepared AP inventory changed during execution")
    if any(digest((code_root / name).read_bytes()) != expected for name, expected in code_hashes.items()):
        raise ValueError("AP implementation changed during execution")
    statuses = Counter(item["status"] for item in audits.values())
    decisions = Counter(row["decision"] for row in rows.values())
    complete = set(rows) == set(inventory.doc_ids)
    stable = dict(schema_version=1, phase_runner_version=PHASE_RUNNER_VERSION,
        run=dict(accounting_run=True, complete=complete, exportsAP=False,
            initial_state="ACTIVE_ERP_RECEIPT_BASELINE", advances_opening_status="NOT_LOADED",
            credits_opening_status="NOT_LOADED", documentary_quality="NOT_EVALUATED"),
        versions=dict(invoice_context=CONTEXT_VERSION, document_bridge=DOCUMENT_BRIDGE_VERSION,
            line_source_bridge=LINE_SOURCE_BRIDGE_VERSION,
            posting_bridge=POSTING_SOURCE_BRIDGE_VERSION, notice_context=PHASE_NOTICE_CONTEXT_VERSION),
        implementation_sha256s=code_hashes,
        source_manifest=dict(mode=prepared.source_mode, stable_source_sha256=prepared.stable_source_sha256,
            month=manifest["month"], task_sha256=inventory.source_sha256,
            configuration_sha256=fingerprint(manifest["configuration"])),
        active_erp=dict(month=baseline.month, source_hashes=dict(sorted(pins.items()))),
        execution_facts=dict(receipt_cutoff=_json(receipt_as_of), posting_date=_json(posting_date)),
        task_keys=list(inventory.doc_ids), processing_order=list(audits),
        summary=dict(task_count=len(inventory.doc_ids), decided_count=len(rows),
            unresolved_count=len(inventory.doc_ids)-len(rows), statuses=dict(sorted(statuses.items())),
            decisions=dict(sorted(decisions.items()))),
        simulated_posting_state=dict(published_task_keys=[row["doc_id"] for row in state.rows],
            receipt_usage_count=len(state.consumption.usages), historical_receipt_usage_count=len(baseline.history.consumption.usages)),
        limitations=["CREDIT_DISPATCH_NOT_IMPLEMENTED", "POSITIVE_ADVANCE_APPLICATION_NOT_IMPLEMENTED",
            "MULTIPART_MONETARY_LINES_NOT_IMPLEMENTED", "DUA_POSTING_NOT_IMPLEMENTED",
            "MULTIPLE_FINANCIAL_ROW_EQUIVALENCES_REQUIRED"],
        tasks=[audits[doc_id] for doc_id in inventory.doc_ids])
    report = dict(**stable, stable_run_sha256=fingerprint(stable), execution=dict(
        phase_path=str(phase), manifest_path=str(path), manifest_sha256=manifest_sha,
        elapsed_ms=(perf_counter_ns()-started)//1_000_000, new_provider_calls=0, new_provider_cost_usd="0"))
    return APPhaseRun(report, tuple(rows[doc_id] for doc_id in inventory.doc_ids if doc_id in rows), state, tax_catalog)
