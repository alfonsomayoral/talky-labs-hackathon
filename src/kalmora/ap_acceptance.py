"""Read-only AP delivery acceptance and provider-free transaction replay (#55).

An export receipt proves bytes/coverage. This audit additionally binds the active
masters, originals, saved facts and installed rules. Missing results or replay
remain explicit blockers; this module never fills an accounting row.
"""
from collections import Counter
from dataclasses import asdict, dataclass, is_dataclass
from decimal import Decimal
import calendar
import hashlib
import json
import os
from pathlib import Path

from .ap_output import POSTING, _pinned_ap_directory, _prepare_ap_payload, validate_ap_row
from .ap_phase_export import load_ap_task_inventory
from .ap_sources import load_prepared_ap_sources
from .ap_tax import TaxCatalog
from .ap_v0_projection import project_v0_output
from .output_models.ap import ApRow, ApLine
from .output_validation import check_structure
from .validation import validate_entry
from .ap_transaction import APTransactionRequest, APTransactionState, commit_ap_transaction
from .data import PhaseData
from .documents.contracts import fingerprint
from .money import company_local_currency

ACCEPTANCE_VERSION = "ap-acceptance-v2"


def _safe(path, root=None):
    path = Path(path)
    resolved = path.resolve()
    if "golden" in path.parts or "golden" in resolved.parts:
        raise ValueError("evaluation data is not an AP acceptance source")
    if root is not None and not resolved.is_relative_to(root):
        raise ValueError("acceptance source escapes its root")
    return resolved


def _hash(payload):
    return hashlib.sha256(payload).hexdigest()


def _read(path):
    path = _safe(path)
    with _pinned_ap_directory(path) as descriptor:
        with os.fdopen(os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptor), "rb") as stream:
            return stream.read()


def _json(payload):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON member: " + key)
            result[key] = value
        return result
    def constant(value):
        raise ValueError("nonfinite JSON value: " + value)
    return json.loads(payload, object_pairs_hook=pairs, parse_constant=constant)


def _encode(value):
    if is_dataclass(value):
        return _encode(asdict(value))
    if isinstance(value, Decimal):
        return {"decimal": str(value)}
    if isinstance(value, dict):
        return {key: _encode(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_encode(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_encode(item) for item in value)
    return value


def _state_hash(state):
    return fingerprint(_encode(state))


def _posting(row):
    return isinstance(row.get("decision"), str) and row["decision"] in POSTING


@dataclass(frozen=True)
class APReplayProof:
    """Proof returned only after executing the actual transaction factories twice.

    Rows are immutable JSON bytes; a later mutation of a caller's dict cannot
    change what was replayed. This does not prove document understanding.
    """
    rows_json: bytes
    requests_sha256: str
    initial_state_sha256: str
    final_state_sha256: str
    committed_doc_ids: tuple[str, ...]
    nonposting_doc_ids: tuple[str, ...]
    duplicate_attempts_rejected: int
    nonposting_projection: tuple[tuple[str, str, str], ...]


def replay_ap_transactions(requests, initial_state, **engine_options):
    """Execute typed resolved inputs twice from the same immutable baseline.

    No extraction, callbacks or provider clients are accepted. Non-posting
    requests must retain the identical state; committed keys must reject another
    commit before any additional consumption/event can become visible.
    """
    requests = tuple(requests)
    if not isinstance(initial_state, APTransactionState) or initial_state.rows:
        raise ValueError("replay requires an unpublished historical transaction baseline")
    if any(not isinstance(request, APTransactionRequest) for request in requests):
        raise TypeError("replay requires typed APTransactionRequest inputs")
    ids = [request.scope.invoice_id for request in requests]
    if len(ids) != len(set(ids)):
        raise ValueError("replay requests repeat a task")
    allowed = {"tax_catalog", "withholding_catalog", "rates", "context"}
    if set(engine_options) - allowed:
        raise TypeError("replay accepts only actual engine catalogues, rates and context")
    before = _state_hash(initial_state)
    request_hash = fingerprint(_encode(requests))
    def execute():
        state, committed, nonposting = initial_state, [], []
        for request in requests:
            old = state
            result = commit_ap_transaction(request, state, **engine_options)
            if result.status == "NOT_POSTING":
                if result.state is not old:
                    raise ValueError("non-posting replay changed transaction state")
                nonposting.append((request.scope.invoice_id, request.document_type, request.scope.decision))
            elif result.status == "COMMITTED":
                state = result.state
                committed.append(request)
            else:
                raise ValueError("replay transaction blocked: " + request.scope.invoice_id)
        return state, tuple(committed), tuple(nonposting)
    first, committed, nonposting = execute()
    second, _, _ = execute()
    if _state_hash(first) != _state_hash(second) or _state_hash(initial_state) != before:
        raise ValueError("replay changed baseline or produced a different ledger snapshot")
    if fingerprint(_encode(requests)) != request_hash:
        raise ValueError("replay mutated resolved factual requests")
    for request in committed:
        try:
            commit_ap_transaction(request, first, **engine_options)
        except ValueError as exc:
            if "already committed" not in str(exc):
                raise
        else:
            raise ValueError("repeated AP publication was accepted")
    if _state_hash(first) != _state_hash(second):
        raise ValueError("duplicate retry changed consumption or advance state")
    payload = _prepare_ap_payload(first.rows, expected_doc_ids=[r.scope.invoice_id for r in committed],
                                  context=engine_options.get("context"),
                                  tax_catalog=engine_options.get("tax_catalog"))
    return APReplayProof(payload, request_hash, before, _state_hash(first),
                         tuple(r.scope.invoice_id for r in committed),
                         tuple(item[0] for item in nonposting), len(committed), nonposting)


def _phase_paths(phase, doc_ids):
    paths = [phase / "tasks/ap_documents.json", phase / "tasks/close.json"]
    paths.extend(path for path in (phase / "erp").rglob("*") if path.is_file())
    for doc_id in doc_ids:
        if Path(doc_id).name != doc_id or doc_id in {".", ".."} or "\\" in doc_id:
            raise ValueError("unsafe AP task folder")
        folder = _safe(phase / "inbox/ap" / doc_id, phase)
        paths.extend(path for path in folder.rglob("*") if path.is_file())
    return tuple(sorted({_safe(path, phase) for path in paths}))


def _snapshot(root, paths):
    return {path.relative_to(root).as_posix(): _hash(_read(path)) for path in paths}


def _master_context(data):
    def index(rows, field):
        records = {}
        for row in rows:
            key = row[field]
            if key in records:
                raise ValueError("ambiguous phase master: " + str(key))
            records[key] = row
        return records
    companies = index(data.companies, "code")
    vendors = index(data.table("vendors"), "id")
    customers = index(data.table("customers"), "id")
    centers = index(data.table("cost_centers"), "id")
    projects = data.table("projects")
    wbs = index([dict(item, company=project["company"]) for project in projects
                 for item in project["wbs"]], "id")
    year, month = map(int, data.month.split("-"))
    context = dict(companies=companies, accounts=index(data.table("chart_of_accounts"), "account"),
                   partners=set(vendors) | set(customers) | set(companies) | {"FACTOR-BAE"},
                   cost_centers=centers, wbs=wbs, min_date=data.month + "-01",
                   max_date=f"{data.month}-{calendar.monthrange(year, month)[1]:02d}")
    return context, vendors, index(data.table("purchase_orders"), "id")


def _facts_audit(path, phase, inventory, inputs, watched):
    if path is None:
        return {"status": "ABSENT", "sha256": None, "diagnostics": ["SAVED_FACTS_ABSENT"]}
    path = _safe(path)
    if path.is_relative_to(phase):
        raise ValueError("saved facts must be outside original phase")
    payload = _read(path)
    watched[path] = _hash(payload)
    manifest = None
    try:
        manifest = _json(payload)
        # Freeze artifact bytes before semantic loading; the outer audit also
        # rechecks these exact bytes after row generation and validation.
        for packet in manifest["documents"]:
            for attachment in packet["attachments"]:
                artifact_path = _safe(path.parent / attachment["artifact"], path.parent)
                watched[artifact_path] = _hash(_read(artifact_path))
        # This public loader rederives normalization/classification and checks
        # original grounding, capture origin and exact task/attachment inventory.
        prepared = load_prepared_ap_sources(phase, path)
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
        config = manifest.get("configuration") if isinstance(manifest, dict) else None
        return dict(status="INCOMPATIBLE", sha256=_hash(payload),
                    configuration_sha256=fingerprint(config) if isinstance(config, dict) else None,
                    diagnostics=["PREPARED_SOURCE_INVALID:" + str(error)])
    attachments = [attachment for task in prepared.values() for attachment in task.attachments]
    artifact_paths = {stage["path"]: stage["artifact"] for packet in manifest["documents"]
                      for stage in packet["attachments"]}
    source_unknowns, invalid_unknowns = [], []
    for doc_id, task in prepared.items():
        for attachment in task.attachments:
            for index, unknown in enumerate(attachment.unknowns, 1):
                valid = (isinstance(unknown, dict) and set(unknown) == {"field", "status", "reason"}
                         and all(isinstance(unknown.get(key), str) and unknown[key].strip()
                                 for key in ("field", "status", "reason"))
                         and unknown["status"] in {"MISSING", "AMBIGUOUS", "CONTRADICTORY"})
                diagnostic = dict(doc_id=doc_id, path=attachment.path,
                                  artifact=artifact_paths[attachment.path], index=index, valid=valid)
                if valid:
                    diagnostic.update(unknown)
                else:
                    diagnostic["raw"] = unknown
                    invalid_unknowns.append(f"SOURCE_UNKNOWN_SCHEMA_INVALID:{doc_id}:{attachment.path}:{index}")
                source_unknowns.append(diagnostic)
    document_sources = {}
    for doc_id, task in prepared.items():
        unknowns = [item for item in source_unknowns if item["doc_id"] == doc_id]
        packet_diagnostics = list(prepared.diagnostics.get(doc_id, ()))
        incomplete = (any(a.facts is None or a.error is not None or a.classification is None
                          or a.classification.status != "CLASSIFIED" for a in task.attachments)
                      or bool(unknowns) or any(not item.startswith("UNLISTED_ATTACHMENT:")
                                               for item in packet_diagnostics))
        document_sources[doc_id] = dict(status="INCOMPLETE" if incomplete else "COMPLETE",
            source_mode=prepared.source_mode, unknowns=unknowns, diagnostics=packet_diagnostics,
            attachments=[dict(path=a.path, facts_present=a.facts is not None,
                error=a.error, classification=a.classification.status if a.classification else None)
                         for a in task.attachments])
    diagnostics = [doc_id + ":" + diagnostic for doc_id, values in prepared.diagnostics.items()
                   for diagnostic in values]
    return dict(status="INCOMPATIBLE" if invalid_unknowns else "COMPATIBLE", sha256=_hash(payload),
                stable_source_sha256=prepared.stable_source_sha256,
                configuration_sha256=fingerprint(manifest["configuration"]),
                source_mode=prepared.source_mode, documents=document_sources,
                accepted_attachments=sum(a.facts is not None and a.error is None for a in attachments),
                unknown_attachments=sum(a.facts is None or a.error is not None for a in attachments),
                unclassified_attachments=sum(a.classification is None or a.classification.status != "CLASSIFIED"
                                             for a in attachments),
                source_diagnostics=sorted(set(diagnostics)), source_unknowns=source_unknowns,
                unresolved_source_fields=sum(item["valid"] for item in source_unknowns),
                diagnostics=invalid_unknowns + (["FIXTURE_SOURCE_NOT_REAL_RECORDING"]
                                               if prepared.source_mode == "fixture" else []))


def _criterion(status, errors=(), **evidence):
    return dict(status=status, errors=list(errors), **evidence)


def _scope_errors(row, context, vendors, orders):
    """Check observed scopes even when another criterion has already failed."""
    errors = []
    company = row.get("company")
    if isinstance(company, str) and company not in context["companies"]:
        errors.append("unknown AP header company")
    if not _posting(row):
        return errors
    vendor, currency = row.get("vendor_id"), row.get("currency")
    if isinstance(vendor, str) and isinstance(company, str):
        master = vendors.get(vendor)
        if master is None or ("companies" in master and company not in master["companies"]):
            errors.append("vendor not enabled for posting company")
    coded_lines = row.get("lines")
    for coded in coded_lines if isinstance(coded_lines, list) else ():
        if not isinstance(coded, dict):
            continue
        for field, registry in (("account", "accounts"), ("cost_center", "cost_centers"), ("wbs", "wbs")):
            value = coded.get(field)
            if isinstance(value, str):
                records = context[registry]
                if value not in records:
                    errors.append(f"unknown coded-line {field}")
                elif isinstance(records, dict) and isinstance(records[value], dict) and records[value].get("company", company) != company:
                    errors.append(f"coded-line {field} belongs to another company")
        po = coded.get("po")
        if isinstance(po, str) and type(coded.get("po_item")) is int and all(isinstance(item, str) for item in (company, vendor, currency)):
            order = orders.get(po)
            if (order is None or (order["company"], order["vendor"], order["currency"]) !=
                    (company, vendor, currency)
                    or not any(item["item"] == coded.get("po_item") for item in order["items"])):
                errors.append("coded PO position outside company/vendor/currency scope")
    return errors


def _contract_errors(row):
    # The official optional action:null example is accepted without changing raw.
    shape = dict(row)
    if shape.get("action") is None:
        shape.pop("action", None)
    errors = [item["message"] for item in check_structure({"ap": [shape]})]
    if set(row) - ApRow.__annotations__.keys():
        errors.append("unexpected AP fields")
    for line in row.get("lines", ()) if isinstance(row.get("lines"), list) else ():
        if isinstance(line, dict) and set(line) - ApLine.__annotations__.keys():
            errors.append("unexpected coded line fields")
    return errors


def _document_audit(doc_id, candidates, facts, context, vendors, orders, catalog, replay):
    source = facts.get("documents", {}).get(doc_id)
    if facts["status"] != "COMPATIBLE":
        documentary = _criterion(facts["status"], facts.get("diagnostics", ()))
    elif source is None:
        documentary = _criterion("UNKNOWN", ["DOCUMENT_SOURCE_ABSENT"])
    else:
        documentary = _criterion(source["status"], source["diagnostics"], **{
            key: value for key, value in source.items() if key not in {"status", "diagnostics"}})
    criteria = {"documentary": documentary}
    if len(candidates) != 1:
        status = "ABSENT" if not candidates else "AMBIGUOUS"
        for key in ("contract", "strict_row_validation", "master_scope", "journal_validation",
                    "nonposting_journal", "document_currency_conservation", "transaction_replay"):
            criteria[key] = _criterion(status, ["ROW_ABSENT" if not candidates else "ROW_DUPLICATE"])
        return dict(doc_id=doc_id, criteria=criteria, accounting_status="INCONCLUSIVE")
    number, row = candidates[0]
    contract = _contract_errors(row)
    strict = list(validate_ap_row(row, context, tax_catalog=catalog))
    scopes = _scope_errors(row, context, vendors, orders)
    criteria["contract"] = _criterion("FAIL" if contract else "PASS", contract,
                                     scope="typed shape and permitted fields; domain invariants are separate")
    criteria["strict_row_validation"] = _criterion("FAIL" if strict else "PASS", strict)
    known_decision = row.get("decision") in {"POST", "POST_PAYMENT_BLOCK", "HOLD", "REJECT", "DUPLICATE", "NOT_INVOICE"} if isinstance(row.get("decision"), str) else False
    posting = _posting(row)
    scope_known = not posting or all(isinstance(row.get(key), str) and row[key] for key in ("company", "vendor_id", "currency"))
    if posting:
        scope_known = scope_known and isinstance(row.get("lines"), list) and bool(row["lines"])
        scope_known = scope_known and all(isinstance(line, dict)
            and isinstance(line.get("account"), str)
            and (line.get("po") is None or isinstance(line["po"], str) and type(line.get("po_item")) is int)
            for line in row.get("lines", ()) if isinstance(row.get("lines"), list))
    criteria["master_scope"] = _criterion("FAIL" if scopes else "PASS" if known_decision and scope_known else "UNKNOWN", scopes)
    if posting:
        journal_errors = validate_entry(row.get("journal_entry"), context)
        criteria["journal_validation"] = _criterion("FAIL" if journal_errors else "PASS", journal_errors)
        criteria["nonposting_journal"] = _criterion("NOT_APPLICABLE")
        entry = row.get("journal_entry")
        lines = entry.get("lines", ()) if isinstance(entry, dict) else ()
        missing_doc_cents = (row.get("currency") != company_local_currency(row["company"])) if isinstance(row.get("company"), str) and row["company"] in context["companies"] else False
        missing_doc_cents = missing_doc_cents and isinstance(lines, list) and any(
            isinstance(line, dict) and (line.get("account", "").startswith(("2", "4", "6")))
            and line.get("currency", row.get("currency")) == row.get("currency")
            and "amount_doc" not in line for line in lines if isinstance(line, dict) and isinstance(line.get("account"), str))
        monetary_errors = [error for error in strict if any(token in error for token in
            ("cents", "document amount", "document base", "document withholding", "document payable",
             "payable", "gross", "charged VAT", "self-assessed VAT", "currency", "coded net",
             "document net", "journal base side"))]
        observed_conflicts = [error for error in monetary_errors if any(token in error for token in
            ("must be unsigned", "zero local side", "local-currency journal document cents differ",
             "currency differs", "currency is outside"))]
        monetary_shape_known = (all(type(row.get(field)) is int for field in
            ("net", "tax", "gross", "withholding", "retention", "payable"))
            and isinstance(row.get("lines"), list) and bool(row["lines"])
            and all(isinstance(line, dict) and type(line.get("amount")) is int for line in row["lines"])
            and isinstance(lines, list) and bool(lines)
            and all(isinstance(line, dict) and type(line.get("debit")) is int
                    and type(line.get("credit")) is int for line in lines))
        currency_status = ("FAIL" if observed_conflicts else "INCONCLUSIVE" if missing_doc_cents or contract or not monetary_shape_known
                           else "FAIL" if monetary_errors else "PASS")
        criteria["document_currency_conservation"] = _criterion(currency_status,
            (["FOREIGN_DOCUMENT_CENTS_NOT_OBSERVED"] if missing_doc_cents else []) + monetary_errors,
            scope="strict document-currency correspondence; optional absent journal amount_doc is not a shape contradiction")
    elif known_decision:
        illegal = "journal_entry" in row
        criteria["journal_validation"] = _criterion("NOT_APPLICABLE")
        criteria["nonposting_journal"] = _criterion("FAIL" if illegal else "PASS", ["NONPOSTING_JOURNAL_PRESENT"] if illegal else ())
        criteria["document_currency_conservation"] = _criterion("NOT_APPLICABLE")
    else:
        for key in ("journal_validation", "nonposting_journal", "document_currency_conservation"):
            criteria[key] = _criterion("UNKNOWN", ["DECISION_UNKNOWN"])
    if replay is None:
        criteria["transaction_replay"] = _criterion("ABSENT", ["TRANSACTION_REPLAY_ABSENT"])
    elif posting:
        replayed = [_json(line) for line in replay.rows_json.splitlines() if line.strip()]
        expected = [item for item in replayed if item.get("doc_id") == doc_id]
        criteria["transaction_replay"] = _criterion("MATCH" if expected == [row] else "MISMATCH",
            scope="full posted row and transaction state proof")
    else:
        identity = (doc_id, row.get("document_type"), row.get("decision"))
        criteria["transaction_replay"] = _criterion("MATCH" if identity in replay.nonposting_projection else "MISMATCH",
            scope="identity/type/decision only; reasons/header are not replayed")
    clear = not contract and not strict and not scopes and criteria["master_scope"]["status"] == "PASS"
    return dict(doc_id=doc_id, line=number, decision=row.get("decision"), criteria=criteria,
                accounting_status="VALIDATED" if clear else "NOT_VALIDATED")


def audit_ap_delivery(*, phase_path, bundle_path, policy_path, source_manifest_path=None,
                      replay: APReplayProof | None = None, rules_root=None, project_v0=False,
                      documentary_acceptance_reference: str | None = None):
    """Audit existing RunBundle files and compatible source artifacts without writes.

    The public bundle contract is ``deliverables/ap.jsonl`` with optional manifest
    and trace. Incomplete deliveries are reported, never repaired. Static byte
    comparison alone is not reported as transaction replay or policy accuracy.
    """
    if type(project_v0) is not bool:
        raise TypeError("project_v0 must be an explicit boolean")
    if documentary_acceptance_reference is not None and (not isinstance(documentary_acceptance_reference, str)
            or not documentary_acceptance_reference.strip()):
        raise ValueError("documentary acceptance requires an explicit nonempty authorization reference")
    if replay is not None and not isinstance(replay, APReplayProof):
        raise TypeError("APReplayProof required")
    inventory = load_ap_task_inventory(phase_path)
    phase, bundle, policy = inventory.phase_path, _safe(bundle_path), _safe(policy_path)
    if bundle.is_relative_to(phase):
        raise ValueError("AP RunBundle must be outside source phase")
    rules = _safe(rules_root or Path(__file__).parent)
    paths = _phase_paths(phase, inventory.doc_ids)
    inputs = _snapshot(phase, paths)
    rule_paths = tuple(sorted(path for path in rules.rglob("*.py") if "evaluation" not in path.relative_to(rules).parts))
    rule_hashes = _snapshot(rules, rule_paths)
    watched = {policy: _hash(_read(policy))}
    delivery_format = _safe(policy.parent / "FORMATO_ENTREGA.md")
    watched[delivery_format] = _hash(_read(delivery_format))
    data = PhaseData(phase)
    context, vendors, orders = _master_context(data)
    catalog = TaxCatalog(data.table("tax_codes"))
    facts = _facts_audit(source_manifest_path, phase, inventory, inputs, watched)
    output = _safe(bundle / "deliverables/ap.jsonl", bundle)
    payload = _read(output) if output.is_file() else None
    if payload is not None:
        watched[output] = _hash(payload)
    projection = project_v0_output(payload) if project_v0 and payload is not None else None
    validation_payload = projection.projected_bytes if projection else payload
    errors, rows, line_errors, journal_totals, dimensions = [], [], [], {}, []
    row_candidates = {}
    for number, line in enumerate((validation_payload or b"").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = _json(line)
        except (ValueError, UnicodeError) as exc:
            line_errors.append(dict(line=number, errors=[str(exc)]))
            continue
        problems = list(validate_ap_row(row, context, tax_catalog=catalog))
        if isinstance(row, dict):
            rows.append(row)
            if isinstance(row.get("doc_id"), str):
                row_candidates.setdefault(row["doc_id"], []).append((number, row))
            problems.extend(_scope_errors(row, context, vendors, orders))
        if not problems:
            if row["decision"] in POSTING:
                key = row["company"] + "/" + company_local_currency(row["company"])
                totals = journal_totals.setdefault(key, dict(debit=0, credit=0))
                totals["debit"] += sum(item["debit"] for item in row["journal_entry"]["lines"])
                totals["credit"] += sum(item["credit"] for item in row["journal_entry"]["lines"])
                dimensions.append(dict(doc_id=row["doc_id"], company=row["company"],
                    document_currency=row["currency"], local_currency=company_local_currency(row["company"]),
                    coding=[{field: line.get(field) for field in
                             ("account", "cost_center", "wbs", "tax_code", "po", "po_item", "amount")}
                            for line in row["lines"]],
                    journal=[{field: line.get(field) for field in
                              ("account", "partner", "cost_center", "wbs", "debit", "credit", "currency", "amount_doc", "assignment")}
                             for line in row["journal_entry"]["lines"]]))
        problems = list(dict.fromkeys(problems))
        if problems:
            line_errors.append(dict(line=number, doc_id=row.get("doc_id") if isinstance(row, dict) else None,
                                    errors=problems))
    ids = [row.get("doc_id") for row in rows]
    valid_ids = [ident for ident in ids if isinstance(ident, str)]
    counts = Counter(valid_ids)
    expected = set(inventory.doc_ids)
    coverage = dict(expected=len(expected), rows=len(rows), missing=sorted(expected - set(valid_ids)),
                    extra=sorted(set(valid_ids) - expected), duplicate=sorted(key for key, count in counts.items() if count > 1))
    coverage["exact"] = not coverage["missing"] and not coverage["extra"] and not coverage["duplicate"] and len(rows) == len(expected)
    if projection is not None and projection.changes:
        errors.append("RAW_OUTPUT_REQUIRES_CONTRACT_PROJECTION")
    if payload is None:
        errors.append("AP_DELIVERY_ABSENT")
    if not coverage["exact"]:
        errors.append("AP_TASK_COVERAGE_INCOMPLETE")
    if line_errors:
        errors.append("AP_OUTPUT_INVALID")
    if facts["status"] != "COMPATIBLE":
        errors.extend(facts["diagnostics"])
    if facts.get("source_mode") == "fixture":
        errors.append("FIXTURE_SOURCE_NOT_REAL_RECORDING")
    if (facts.get("unknown_attachments") or facts.get("unclassified_attachments")
            or facts.get("unresolved_source_fields")):
        errors.append("SOURCE_UNDERSTANDING_INCOMPLETE")
    if any(not diagnostic.split(":", 1)[1].startswith("UNLISTED_ATTACHMENT:")
           for diagnostic in facts.get("source_diagnostics", ())):
        errors.append("SOURCE_PACKET_INCOMPLETE")
    replay_report = {"status": "ABSENT"}
    if replay is None:
        errors.append("TRANSACTION_REPLAY_ABSENT")
    elif not isinstance(replay, APReplayProof):
        raise TypeError("APReplayProof required")
    else:
        posted = [row for row in rows if _posting(row)]
        replay_rows = [_json(line) for line in replay.rows_json.splitlines()]
        agrees = sorted(posted, key=lambda row: str(row.get("doc_id"))) == sorted(replay_rows, key=lambda row: str(row.get("doc_id")))
        agrees = agrees and set(replay.nonposting_projection) == {
            (row.get("doc_id"), row.get("document_type"), row.get("decision")) for row in rows
            if not _posting(row) and all(isinstance(row.get(field), str)
                for field in ("doc_id", "document_type", "decision"))}
        if not agrees:
            errors.append("TRANSACTION_REPLAY_OUTPUT_MISMATCH")
        replay_report = dict(status="MATCH" if agrees else "MISMATCH", requests_sha256=replay.requests_sha256,
                             initial_state_sha256=replay.initial_state_sha256, final_state_sha256=replay.final_state_sha256,
                             committed_doc_ids=list(replay.committed_doc_ids),
                             nonposting_doc_ids=list(replay.nonposting_doc_ids),
                             nonposting_projection=[list(item) for item in replay.nonposting_projection],
                             duplicate_attempts_rejected=replay.duplicate_attempts_rejected,
                             provider_calls=0, repeated_state_identical=True,
                             nonposting_scope="identity/type/decision only; reasons/header require upstream decision replay")
    # Preserve optional RunBundle audit files and detect repeated recorded events.
    for relative in ("manifest.json", "run.json", "trace/events.jsonl", "trace/attention.jsonl"):
        path = _safe(bundle / relative, bundle)
        if not path.is_file():
            continue
        content = _read(path)
        watched[path] = _hash(content)
        if relative == "trace/events.jsonl":
            events = [_json(line) for line in content.splitlines() if line.strip()]
            if any(not isinstance(event, dict) or not isinstance(event.get("event_id"), str)
                   or not event["event_id"] or not isinstance(event.get("item"), str)
                   or type(event.get("seq")) is not int or event["seq"] < 0 for event in events):
                errors.append("TRACE_EVENT_INVALID")
                continue
            event_ids = [event.get("event_id") for event in events]
            sequences = [(event.get("item"), event.get("seq")) for event in events]
            if len(set(event_ids)) != len(event_ids) or len(set(sequences)) != len(sequences):
                errors.append("TRACE_EVENT_DUPLICATE")
            nonposting = {"ap:" + row["doc_id"] for row in rows if not _posting(row) and isinstance(row.get("doc_id"), str)}
            if any(event.get("kind") == "POST" and event.get("item") in nonposting for event in events):
                errors.append("TRACE_NONPOSTING_PUBLICATION")
            publications = [event["item"] for event in events if event.get("kind") == "POST" and event["item"].startswith("ap:")]
            if len(set(publications)) != len(publications):
                errors.append("TRACE_POSTING_DUPLICATE")
            if any(event["item"].startswith("ap:") and event["item"][3:] not in expected for event in events):
                errors.append("TRACE_TASK_UNKNOWN")
    documents = [_document_audit(doc_id, row_candidates.get(doc_id, ()), facts,
                  context, vendors, orders, catalog, replay) for doc_id in inventory.doc_ids]
    criteria_summary = {criterion: dict(sorted(Counter(document["criteria"][criterion]["status"]
                        for document in documents).items())) for criterion in documents[0]["criteria"]} if documents else {}
    if (_phase_paths(phase, inventory.doc_ids) != paths or _snapshot(phase, paths) != inputs
            or load_ap_task_inventory(phase) != inventory
            or tuple(sorted(path for path in rules.rglob("*.py") if "evaluation" not in path.relative_to(rules).parts)) != rule_paths
            or _snapshot(rules, rule_paths) != rule_hashes
            or any(not path.is_file() or _hash(_read(path)) != value for path, value in watched.items())
            or (payload is None and output.exists())):
        raise ValueError("AP acceptance inputs, rules, facts or output changed during audit")
    report = dict(schema_version=2, acceptance_version=ACCEPTANCE_VERSION, month=data.month,
                  phase_path=str(phase), bundle_path=str(bundle),
                  status="READY_FOR_EVALUATION" if not errors else "BLOCKED",
                  scope="COMPLETE_DELIVERY" if coverage["exact"] else "PARTIAL_DELIVERY" if rows else "SOURCE_ONLY",
                  coverage=coverage, output_errors=line_errors, blockers=sorted(set(errors)),
                  input_hashes=inputs, inputs_sha256=fingerprint(inputs),
                  task_sha256=inventory.source_sha256, rules_hashes=rule_hashes,
                  rules_sha256=fingerprint(rule_hashes), policies_sha256=watched[policy],
                  delivery_format_sha256=watched[delivery_format],
                  output_sha256=_hash(payload) if payload is not None else None,
                  artifact_hashes={str(path): value for path, value in sorted(watched.items())},
                  facts=facts, replay=replay_report, journal_totals=journal_totals,
                  projection=projection.evidence() if projection else {"version": None},
                  documentary_acceptance=dict(status="PROVISIONAL_USER_ACCEPTANCE" if documentary_acceptance_reference else "NOT_ASSUMED",
                    reference=documentary_acceptance_reference,
                    scope="documentary base only; source unknowns retained; no transaction replay or monthly acceptance inferred"),
                  documents=documents, criteria_summary=criteria_summary,
                  accounting_summary=dict(scope="contractual row validation against active masters, separate from documentary accuracy and transaction replay",
                    validated=sum(doc["accounting_status"] == "VALIDATED" for doc in documents),
                    not_validated=sum(doc["accounting_status"] == "NOT_VALIDATED" for doc in documents),
                    inconclusive=sum(doc["accounting_status"] == "INCONCLUSIVE" for doc in documents),
                    monthly_acceptance=False, delivery_ready_for_evaluation=not errors),
                  accounting_dimensions=sorted(dimensions, key=lambda row: row["doc_id"]),
                  decision_counts=dict(sorted(Counter(row.get("decision") for row in rows if isinstance(row.get("decision"), str)).items())),
                  evaluation={"performed": False, "score": None}, provider_calls=0)
    report["report_sha256"] = fingerprint(report)
    return report


def compare_ap_acceptance(previous, current, *, independent_phase=False):
    """Compare evidence identities; a September run keeps rules, never July facts.

    A self-hash detects report corruption, not a trusted signature. Compatibility
    is distinct from completeness and from golden correctness.
    """
    for report in (previous, current):
        if report.get("report_sha256") != fingerprint({k: v for k, v in report.items() if k != "report_sha256"}):
            raise ValueError("AP acceptance report hash mismatch")
    fields = ["acceptance_version", "rules_sha256", "policies_sha256", "delivery_format_sha256", "documentary_acceptance"]
    if not independent_phase:
        fields += ["month", "inputs_sha256", "output_sha256", "facts", "replay"]
    differences = []
    if previous.get("projection", {}).get("version") != current.get("projection", {}).get("version"):
        differences.append("projection.version")
    differences += [field for field in fields if previous.get(field) != current.get(field)]
    previous_config = previous.get("facts", {}).get("configuration_sha256")
    current_config = current.get("facts", {}).get("configuration_sha256")
    if previous_config != current_config:
        differences.append("facts.configuration_sha256")
    if independent_phase and (previous_config is None or current_config is None):
        differences.append("facts.configuration_absent")
    if independent_phase and previous.get("inputs_sha256") == current.get("inputs_sha256"):
        differences.append("independent_phase_inputs")
    if independent_phase and previous.get("facts", {}).get("sha256") == current.get("facts", {}).get("sha256"):
        differences.append("independent_phase_facts")
    return dict(compatible=not differences, differences=differences,
                acceptance_status=current["status"], independent_phase=independent_phase)
