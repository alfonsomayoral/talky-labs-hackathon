"""Tentative monetary inputs from an ordinary AP source context (#140).

READY describes technical preparation, never policy eligibility. Calculators
run a disposable POST preview; the ordered coordinator owns the real decision
and repeats the factories. No journal, receipt or balance is published here.
"""
from dataclasses import dataclass, replace
from datetime import date
from hashlib import sha256

from .ap_coding import CodingCatalog, CodingQuery, CodingRecord
from .ap_document_bridge import APFactSet
from .ap_erp import APERPBaseline
from .ap_identity import IdentityCatalog
from .ap_invoice_context import APInvoiceContext
from .ap_line_source_bridge import APLineSourceBinding, _net_observation, validate_ap_line_sources
from .ap_output import APHeader
from .ap_pipeline import APInvoiceRequest
from .ap_project_binding import resolve_ap_project_binding
from .ap_rejections import bool_field
from .ap_sources import _safe_file
from .ap_tax import TaxCatalog, TaxLine, calculate_ap_tax
from .ap_transaction import APPostingInputs, APTransactionState, CodedAPLine
from .ap_valuation import CostAssignment, ValuationLine
from .ap_withholding import (
    ContractGuarantee, WithholdingBase, WithholdingCatalog, calculate_ap_withholdings,
)
from .data import PhaseData
from .facts import Evidence, Fact
from .money import RateTable, company_local_currency

POSTING_SOURCE_BRIDGE_VERSION = "ap-posting-source-bridge-v1"


@dataclass(frozen=True)
class APGuaranteePostingPlan:
    """Observed eligible contract base and literal reference; no inferred base."""
    base_doc: Fact
    contract_reference: Fact


@dataclass(frozen=True)
class APPostingPreparation:
    status: str  # READY, UNKNOWN, UNSUPPORTED; not a decision
    request: APInvoiceRequest | None
    header: APHeader | None
    posting: APPostingInputs | None
    evidence: tuple[Evidence, ...]
    diagnostics: tuple[str, ...]
    source_hashes: tuple[tuple[str, str], ...] = ()
    version: str = POSTING_SOURCE_BRIDGE_VERSION


def prepare_ap_invoice_posting(
    context: APInvoiceContext, *, data: PhaseData, baseline: APERPBaseline,
    state: APTransactionState, posting_date: Fact, coding_catalog: CodingCatalog,
    tax_catalog: TaxCatalog, withholding_catalog: WithholdingCatalog,
    rates: RateTable | None = None, bindings=None, advance_plan: Fact | None = None,
    guarantee_plan: APGuaranteePostingPlan | None = None,
) -> APPostingPreparation:
    """Prepare explicit-net, single-position rows or evidenced direct expenses.

    Multiple financial attachments need caller-supplied row equivalences. An
    explicit false ``advance_plan`` proves no application; positive applications,
    DUA and multi-position source rows remain unsupported in this increment.
    Missing facts preserve the structural request so earlier policy decisions
    can still be evaluated. Caller contract violations raise TypeError/ValueError.
    """
    if not isinstance(context, APInvoiceContext) or not isinstance(data, PhaseData):
        raise TypeError("typed AP invoice context and phase required")
    if not isinstance(baseline, APERPBaseline) or not isinstance(state, APTransactionState):
        raise TypeError("typed ERP and evolving transaction snapshots required")
    if not isinstance(posting_date, Fact):
        raise TypeError("posting date requires an observed Fact")
    if not isinstance(coding_catalog, CodingCatalog) or not isinstance(tax_catalog, TaxCatalog) or not isinstance(withholding_catalog, WithholdingCatalog):
        raise TypeError("real coding, tax and withholding catalogues required")
    if rates is not None and not isinstance(rates, RateTable):
        raise TypeError("exact source FX RateTable required")
    request, proof, notes, hashes = context.request, list(context.evidence), [], {}

    def stop(status, diagnostic):
        return APPostingPreparation(status, request, None, None,
            tuple(dict.fromkeys(proof)), tuple(dict.fromkeys((*notes, diagnostic))),
            tuple(sorted(hashes.items())))

    if request is None or context.scope is None or context.primary_source is None:
        return stop("UNSUPPORTED" if context.status == "UNSUPPORTED" else "UNKNOWN",
                    "ORDINARY_SOURCE_CONTEXT_INCOMPLETE")
    if request.observation.document_type != "INVOICE":
        return stop("UNSUPPORTED", "ORDINARY_INVOICE_ONLY")
    if (context.bridge.source_issues or context.bridge.unclassified_sources
            or any(source.diagnostics for source in context.financial_sources)):
        return stop("UNKNOWN", "FINANCIAL_SOURCE_INVENTORY_UNRESOLVED")
    if request.header is not None or request.posting is not None:
        raise ValueError("prepare from a structural request, not an existing posting plan")
    company, vendor, currency = context.scope.company, context.scope.vendor, context.scope.currency
    observation = request.observation
    if (observation.company, observation.vendor, observation.currency) != (company, vendor, currency):
        raise ValueError("source observation differs from context scope")
    if data.month != baseline.month:
        raise ValueError("phase and ERP month differ")
    try:
        posted = date.fromisoformat(posting_date.value)
        if posted.isoformat() != posting_date.value or posted.strftime("%Y-%m") != baseline.month:
            raise ValueError("posting date outside active month")
    except (TypeError, ValueError):
        return stop("UNKNOWN", "POSTING_DATE_UNKNOWN_OR_OUTSIDE_PHASE")
    proof.append(posting_date.evidence)

    # Validate every chosen path before fresh PhaseData opens the close task or
    # any master. Recheck at reads as a source may be redirected during planning.
    phase = data.phase_dir
    try:
        local = company_local_currency(company)
    except ValueError:
        return stop("UNSUPPORTED", "UNSUPPORTED_COMPANY")
    try:
        for source in baseline.sources:
            path = _safe_file(phase, source.path)
            if not path.is_file() or sha256(path.read_bytes()).hexdigest() != source.sha256:
                return stop("UNKNOWN", "ACTIVE_ERP_SNAPSHOT_CHANGED")
            hashes[source.path] = source.sha256
    except (OSError, ValueError):
        return stop("UNKNOWN", "ACTIVE_ERP_SNAPSHOT_CHANGED")
    try:
        master_paths = []
        for stem in ("tasks/close", "companies", "chart_of_accounts", "cost_centers", "projects", "tax_codes"):
            path = data._path(stem)
            relative = path.relative_to(phase).as_posix()
            _safe_file(phase, relative)
            master_paths.append(relative)
    except (KeyError, OSError, TypeError, ValueError):
        return stop("UNKNOWN", "ACTIVE_POSTING_MASTER_UNRESOLVED")
    if currency != local and rates is not None:
        try:
            _safe_file(phase, data._path("fx_rates").relative_to(phase).as_posix())
        except (KeyError, OSError, TypeError, ValueError):
            return stop("UNKNOWN", "SOURCE_FX_RATE_UNKNOWN")
    try:
        data = PhaseData(phase)
        for relative in master_paths:
            hashes[relative] = sha256(_safe_file(phase, relative).read_bytes()).hexdigest()
        active_coding = CodingCatalog.from_phase(data)
        active_tax = TaxCatalog(data.table("tax_codes"))
        active_withholding = WithholdingCatalog(data.table("tax_codes"))
    except (KeyError, OSError, TypeError, ValueError):
        return stop("UNKNOWN", "ACTIVE_POSTING_MASTER_UNRESOLVED")

    all_fields = {}
    for source in request.amount_sources:
        for name, candidates in source.fields.items():
            if not name.startswith("line."):
                all_fields.setdefault(name, []).extend(candidates)
    facts = APFactSet(all_fields)
    source_header = facts.header
    required = (source_header.invoice_number, source_header.invoice_date, source_header.currency,
                source_header.net_cents, source_header.tax_cents, source_header.gross_cents)
    for field in required:
        proof.extend(field.evidence)
        if not field.known:
            return stop("UNKNOWN", f"SOURCE_HEADER_UNKNOWN:{field.name}:{field.status}")
    if (source_header.currency.value, source_header.invoice_number.value,
            source_header.gross_cents.value) != (currency, observation.number, observation.amount_cents):
        return stop("UNKNOWN", "SOURCE_HEADER_SCOPE_OR_OBSERVATION_CONFLICT")
    invoice_date = source_header.invoice_date.value
    if request.invoice_date is None or request.invoice_date.value != invoice_date:
        return stop("UNKNOWN", "SOURCE_INVOICE_DATE_CONFLICT")
    identity = IdentityCatalog.from_phase(data).resolve(
        supplier_tax_ids=source_header.issuer_tax_id.candidates,
        recipient_tax_ids=source_header.recipient_tax_id.candidates, expected_company=company)
    proof.extend((*identity.supplier.evidence, *identity.recipient.evidence))
    if (identity.supplier.status, identity.supplier.identity, identity.recipient.status,
            identity.recipient.identity) != ("RESOLVED", vendor, "RESOLVED", company):
        return stop("UNKNOWN", "POSTING_IDENTITY_UNRESOLVED")
    company_row = data.get("companies", company)
    country = company_row.get("country")
    proof.append(Evidence("erp/companies.json", f"code={company}.country"))
    active_rates = None
    if currency != local:
        if rates is None:
            return stop("UNKNOWN", "SOURCE_FX_RATES_REQUIRED")
        try:
            path = _safe_file(phase, data._path("fx_rates").relative_to(phase).as_posix())
            hashes[path.relative_to(data.phase_dir).as_posix()] = sha256(path.read_bytes()).hexdigest()
            active_rates = RateTable(data.table("fx_rates"))
            for code in {currency, local}:
                if rates.as_of(invoice_date, code) != active_rates.as_of(invoice_date, code):
                    return stop("UNKNOWN", "ACTIVE_FX_CATALOG_MISMATCH")
                if code != "EUR":
                    row = max((r for r in data.table("fx_rates") if r["currency"] == code and r["date"] <= invoice_date), key=lambda r: r["date"])
                    proof.append(Evidence(path.relative_to(data.phase_dir).as_posix(),
                        f"date={row['date']};currency={code}.rate"))
        except (KeyError, OSError, ValueError, TypeError):
            return stop("UNKNOWN", "SOURCE_FX_RATE_UNKNOWN")
    proof.append(Evidence("participant/POLITICAS_CONTABLES.md", "1.local_currency_and_invoice_date_FX"))

    if advance_plan is None:
        return stop("UNKNOWN", "ADVANCE_APPLICATION_APPLICABILITY_UNKNOWN")
    if not isinstance(advance_plan, Fact):
        raise TypeError("advance applicability requires Fact/Evidence")
    proof.append(advance_plan.evidence)
    if advance_plan.value is True:
        return stop("UNSUPPORTED", "POSITIVE_ADVANCE_APPLICATION_NOT_IMPLEMENTED")
    if advance_plan.value is not False:
        return stop("UNKNOWN", "ADVANCE_APPLICATION_APPLICABILITY_UNKNOWN")
    observed_advance = facts.field("advance_applicable")
    proof.extend(observed_advance.evidence)
    if observed_advance.candidates and (not observed_advance.known or observed_advance.value is not False):
        return stop("UNKNOWN", "SOURCE_ADVANCE_APPLICATION_CONFLICT")
    advance_amount = facts.integer("advance_amount_cents")
    proof.extend(advance_amount.evidence)
    if advance_amount.candidates and (not advance_amount.known or advance_amount.value != 0):
        return stop("UNKNOWN", "SOURCE_ADVANCE_APPLICATION_CONFLICT")

    guarantee_fact = request.guarantee_applicable
    if not isinstance(guarantee_fact, Fact) or type(guarantee_fact.value) is not bool:
        return stop("UNKNOWN", "GUARANTEE_APPLICABILITY_UNKNOWN")
    proof.append(guarantee_fact.evidence)
    guarantee = None
    if guarantee_fact.value:
        if guarantee_plan is None:
            return stop("UNKNOWN", "GUARANTEE_CONTRACT_BASE_UNKNOWN")
        if not isinstance(guarantee_plan, APGuaranteePostingPlan) or not isinstance(guarantee_plan.base_doc, Fact) or not isinstance(guarantee_plan.contract_reference, Fact):
            raise TypeError("guarantee plan requires evidenced base/reference")
        base, reference = guarantee_plan.base_doc, guarantee_plan.contract_reference
        proof.extend((base.evidence, reference.evidence))
        if (type(base.value) is not int or not 0 <= base.value <= source_header.net_cents.value
                or not isinstance(reference.value, str) or not reference.value.strip()
                or base.evidence.document != reference.evidence.document):
            return stop("UNKNOWN", "GUARANTEE_CONTRACT_BASE_UNKNOWN")
        observed_base = facts.integer("guarantee_base_cents")
        observed_reference = facts.text("contract_reference")
        proof.extend((*observed_base.evidence, *observed_reference.evidence))
        if (not observed_base.known or not observed_reference.known
                or base not in observed_base.candidates or reference not in observed_reference.candidates):
            return stop("UNKNOWN", "GUARANTEE_PLAN_SOURCE_UNCONFIRMED")
        guarantee = ContractGuarantee(base.value, reference.value)
    elif guarantee_plan is not None:
        return stop("UNKNOWN", "GUARANTEE_PLAN_CONTRADICTS_NONAPPLICABILITY")

    if bindings is None:
        if len(context.financial_sources) != 1:
            return stop("UNKNOWN", "FINANCIAL_ROW_EQUIVALENCES_REQUIRED")
        bindings = tuple(APLineSourceBinding(line.source.line_id, line.source.source_path, line.source.index)
                         for line in context.lines)
    else:
        bindings = tuple(bindings)
    if any(not isinstance(binding, APLineSourceBinding) for binding in bindings):
        raise TypeError("financial row equivalences require APLineSourceBinding")
    source_views = {(source.source_path, row.index): (source, row)
                    for source in context.financial_sources for row in source.lines}

    def line_field(line_id, name, *, kind="any", include_header=True):
        candidates = []
        for binding in bindings:
            if binding.line_id != line_id:
                continue
            pair = source_views.get((binding.source_path, binding.index))
            if pair is not None:
                attachment, row = pair
                if include_header:
                    candidates.extend(attachment.field(name, kind=kind).candidates)
                candidates.extend(row.field(name, kind=kind).candidates)
        return APFactSet({name: candidates}).field(name, kind=kind)

    direct, direct_proof, _ = bool_field(context.hold_fields, "quantity_check_applicable")
    proof.extend(direct_proof)
    valued, taxes, deductions, coded, quantity_lines, reconciliations = [], [], [], [], [], set()
    if not context.lines:
        return stop("UNKNOWN", "SOURCE_LINE_INVENTORY_UNKNOWN")
    for line in context.lines:
        source = line.source
        amount = _net_observation(source)  # an undiscounted row amount is its net
        proof.extend(amount.evidence)
        if not amount.known or amount.value < 0:
            return stop("UNKNOWN", f"SOURCE_LINE_EXPLICIT_NET_REQUIRED:{source.line_id}")
        selected = None if line.match is None else line.match.reference.selected
        order_records = ()
        if line.match is not None and line.match.reference.status == "RESOLVED" and selected is not None:
            quantity = line.match.quantity_line
            if quantity is None or len(quantity.portions) != 1:
                return stop("UNSUPPORTED", "MULTIPART_ORDER_LINE_NOT_IMPLEMENTED")
            if quantity.portions[0].order != selected.order or selected.order not in {o.key for o in baseline.orders}:
                return stop("UNKNOWN", "CONFIRMED_ORDER_DIFFERS_FROM_ACTIVE_ERP")
            order_records = (active_coding.order_record(selected.order, evidence=selected.evidence),)
            quantity_lines.append(quantity)
        elif direct is not False:
            return stop("UNKNOWN", f"DIRECT_EXPENSE_NOT_DEMONSTRATED:{source.line_id}")
        elif selected is not None or line.match is not None and line.match.quantity_line is not None:
            return stop("UNKNOWN", "DIRECT_EXPENSE_CONTRADICTS_ORDER_MATCH")

        # Explicit document candidates do not vanish into defaults. An observed
        # None/conflict remains UNKNOWN; known overrides pass to the real coder.
        values, document_proof = {}, []
        for target, name in (("account", "account"), ("tax_code", "tax_code"),
                ("reconciliation_account", "reconciliation_account"),
                ("cost_center", "cost_center"), ("wbs", "wbs"),
                ("withholding_codes", "withholding_codes")):
            field = line_field(source.line_id, name)
            if field.candidates:
                proof.extend(field.evidence)
                if not field.known:
                    return stop("UNKNOWN", f"DOCUMENT_CODING_UNKNOWN:{source.line_id}:{name}")
                value = field.value
                if target == "withholding_codes":
                    if not isinstance(value, (tuple, list)) or any(not isinstance(code, str) for code in value):
                        return stop("UNKNOWN", "DOCUMENT_WITHHOLDING_CODES_UNKNOWN")
                    value = tuple(value)
                values[target] = value
                document_proof.extend(field.evidence)
        records = () if not values else (CodingRecord(company, vendor, currency,
            evidence=tuple(document_proof), **values),)
        project = line_field(source.line_id, "project_reference")
        description = line_field(source.line_id, "description")
        for field in (project, description):
            proof.extend(field.evidence)
            if field.candidates and not field.known:
                return stop("UNKNOWN", "DOCUMENT_CODING_CONTEXT_UNKNOWN:" + field.name)
        project_binding = resolve_ap_project_binding(project, company=company,
            projects=data.table("projects") if project.candidates else None,
            project_source=data._path("projects").relative_to(data.phase_dir).as_posix()
                if project.candidates else "erp/projects.jsonl")
        proof.extend(project_binding.evidence)
        if project_binding.status == "UNKNOWN":
            notes.extend(project_binding.diagnostics)
            return stop("UNKNOWN", "DOCUMENT_PROJECT_BINDING_UNRESOLVED")
        query = CodingQuery(company, vendor, currency, invoice_date,
                            project=project_binding.project_id,
                            context=description.value if description.known else None)
        try:
            coding = active_coding.resolve(query, document=records, order=order_records)
            supplied = coding_catalog.resolve(query, document=records, order=order_records)
        except (ValueError, KeyError):
            return stop("UNKNOWN", f"CODING_MASTER_OR_SCOPE_INVALID:{source.line_id}")
        proof.extend(e for field in coding.fields for e in field.evidence)
        if coding.status != "RESOLVED":
            return stop("UNKNOWN", f"CODING_UNRESOLVED:{source.line_id}:{coding.status}")
        if supplied.record != coding.record:
            return stop("UNKNOWN", "ACTIVE_CODING_CATALOG_MISMATCH")
        record = coding.record
        assignment = CostAssignment(company, record.account, record.cost_center, record.wbs)
        try:
            treatment = active_tax.get(record.tax_code, country)
            proof.append(Evidence(data._path("tax_codes").relative_to(data.phase_dir).as_posix(),
                                  f"tax_codes.{record.tax_code}.country_kind_rate"))
            if tax_catalog.get(record.tax_code, country) != treatment:
                return stop("UNKNOWN", "ACTIVE_TAX_CATALOG_MISMATCH")
            for code in record.withholding_codes:
                proof.append(Evidence(data._path("tax_codes").relative_to(data.phase_dir).as_posix(),
                                      f"withholdings.{code}.country_rate_account"))
                if withholding_catalog.get(code, country) != active_withholding.get(code, country):
                    return stop("UNKNOWN", "ACTIVE_WITHHOLDING_CATALOG_MISMATCH")
        except ValueError:
            return stop("UNKNOWN", "FISCAL_COUNTRY_OR_CATALOG_INVALID")
        if treatment.kind == "import":
            return stop("UNSUPPORTED", "DUA_POSTING_NOT_IMPLEMENTED")
        observed_tax = line_field(source.line_id, "tax_cents", kind="integer", include_header=False)
        proof.extend(observed_tax.evidence)
        if observed_tax.candidates and not observed_tax.known:
            return stop("UNKNOWN", f"SOURCE_LINE_TAX_UNKNOWN:{source.line_id}")
        valued.append(ValuationLine(source.line_id, amount.value, assignment,
            quantity_lines[-1].quantity_milli if selected is not None else None))
        taxes.append(TaxLine(source.line_id, amount.value, record.tax_code, record.account,
                            record.cost_center, record.wbs, observed_tax.value if observed_tax.known else None))
        deductions.append(WithholdingBase(source.line_id, amount.value, record.withholding_codes))
        output_line = dict(amount=amount.value, account=record.account, tax_code=record.tax_code)
        output_line.update({name: value for name, value in (("cost_center", record.cost_center), ("wbs", record.wbs)) if value is not None})
        if selected is not None:
            output_line.update(po=selected.order.po, po_item=selected.order.item)
        coded.append(CodedAPLine(source.line_id, output_line))
        reconciliations.add(record.reconciliation_account)
    if len(reconciliations) != 1:
        return stop("UNKNOWN", "SUPPLIER_RECONCILIATION_ACCOUNT_CONFLICT")
    try:
        linked = validate_ap_line_sources(bindings=bindings, amount_sources=request.amount_sources,
            valuation_lines=tuple(valued), quantity_lines=tuple(quantity_lines), currency=currency)
    except ValueError as error:
        return stop("UNKNOWN", "SOURCE_LINE_POSTING_CONFLICT:" + str(error))
    proof.extend(linked.evidence)
    if linked.status != "CLEAR":
        notes.extend(linked.diagnostics)
        return stop("UNKNOWN", "SOURCE_LINE_BINDING_UNRESOLVED")
    try:
        tax = calculate_ap_tax(company=company, country=country, vendor=vendor, currency=currency,
            invoice_id=observation.doc_id, invoice_date=invoice_date, decision="POST",
            lines=tuple(taxes), catalog=active_tax, rates=active_rates)
        withholding = calculate_ap_withholdings(company=company, country=country, vendor=vendor,
            currency=currency, invoice_id=observation.doc_id, invoice_date=invoice_date,
            invoice_number=source_header.invoice_number.value, decision="POST",
            bases=tuple(deductions), catalog=active_withholding, guarantee=guarantee, rates=active_rates)
    except (ValueError, TypeError) as error:
        return stop("UNKNOWN", "FISCAL_PREVIEW_UNRESOLVED:" + str(error))
    if (tax.net_doc, tax.tax_doc, tax.gross_doc) != tuple(f.value for f in (source_header.net_cents, source_header.tax_cents, source_header.gross_cents)):
        return stop("UNKNOWN", "FISCAL_PREVIEW_SOURCE_TOTAL_CONFLICT")
    for name, calculated in (("withholding_cents", withholding.withholding_doc),
                             ("retention_cents", withholding.retention_doc)):
        candidates = tuple(f for alias in ((name, "guarantee_amount_cents") if name == "retention_cents" else (name,))
                           for f in facts.fields.get(alias, ()))
        field = APFactSet({name: candidates}).integer(name)
        proof.extend(field.evidence)
        if candidates and (not field.known or field.value != calculated):
            return stop("UNKNOWN", "SOURCE_DEDUCTION_PREVIEW_CONFLICT:" + name)
    payable = tax.gross_doc - withholding.deduction_doc
    if payable < 0:
        return stop("UNKNOWN", "DEDUCTIONS_EXCEED_GROSS")
    printed_payable = source_header.payable_cents
    proof.extend(printed_payable.evidence)
    if printed_payable.candidates:
        basis = request.source_payable_basis
        if (not isinstance(basis, Fact) or not isinstance(basis.value, str)
                or basis.value not in {"BEFORE_APPLIED_ADVANCES", "AFTER_APPLIED_ADVANCES"}):
            return stop("UNKNOWN", "SOURCE_PAYABLE_BASIS_UNKNOWN")
        proof.append(basis.evidence)
        if not printed_payable.known or printed_payable.value != payable:
            return stop("UNKNOWN", "SOURCE_PAYABLE_PREVIEW_CONFLICT")
    header = APHeader(company, vendor, source_header.invoice_number.value, invoice_date, currency,
        tax.net_doc, tax.tax_doc, tax.gross_doc, withholding.withholding_doc, withholding.retention_doc, payable)
    posting = APPostingInputs(header=header, country=country, posting_date=posting_date.value,
        reconciliation_account=next(iter(reconciliations)), gr_ir_account="40090000",
        valuation_lines=tuple(valued), tax_lines=tuple(taxes), withholding_bases=tuple(deductions),
        coded_lines=tuple(coded), quantity_lines=tuple(quantity_lines), order_catalog=baseline.orders,
        receipt_catalog=baseline.receipts, order_prices=baseline.prices,
        receipt_as_of=None if request.receipt_as_of is None else request.receipt_as_of.value,
        guarantee=guarantee)
    proof.append(Evidence("participant/POLITICAS_CONTABLES.md", "2.3.AP_components_and_supplier_residual"))
    try:
        for relative, expected in hashes.items():
            if sha256(_safe_file(phase, relative).read_bytes()).hexdigest() != expected:
                return stop("UNKNOWN", "ACTIVE_MASTER_SNAPSHOT_CHANGED")
    except (OSError, ValueError):
        return stop("UNKNOWN", "ACTIVE_MASTER_SNAPSHOT_CHANGED")
    enriched = replace(request, header=header, posting=posting, line_source_bindings=bindings)
    return APPostingPreparation("READY", enriched, header, posting,
        tuple(dict.fromkeys(proof)), (), tuple(sorted(hashes.items())))
