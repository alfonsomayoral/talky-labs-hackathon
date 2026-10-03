"""Evaluator-only document checks. Never import this module from solver code.

Ground truth is supplied explicitly by the evaluator. This module does not call
a provider, change source files, learn normalizations from answers, or read golden.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path, PurePosixPath
import re
import unicodedata
import xml.etree.ElementTree as ET

from kalmora.facts import DocumentFacts, _decode_value, atomic_json
from .contracts import fingerprint
from .image_reviews import validate_review


FROZEN_THRESHOLDS = {
    "critical_header_money_tax_line_amount_exact_min": "0.95",
    "grounded_evidence_location_min": "1.00", "fabricated_values_or_ids_max": 0,
    "selected_candidate_precision_min": "1.00", "unique_resolvable_candidate_coverage_min": "0.80",
    "ambiguous_correct_abstention_min": "1.00", "case_required_field_completeness_min": "0.95",
    "latency_p95_seconds_max": 60, "capture_estimated_cost_usd_per_document_max": "0.10",
    "unknown_cost": "fails cost criterion",
}
ALIASES = {"document_number": "invoice_number", "recipient_tax_id": "buyer_tax_id",
           "document_type_hint": "document_type", "invoice_date": "document_date",
           "issue_date": "document_date", "net_amount": "net", "tax_amount": "tax",
           "vat_amount": "tax", "gross_amount": "gross", "due_on": "due_date",
           "certification_current": "certified_current", "certification_cumulative": "certified_cumulative",
           "certification_previous": "certified_previous_displayed"}
ALIASES.update({"cert_current": "certified_current", "cert_previous": "certified_previous_displayed",
                "cert_cumulative": "certified_cumulative", "document_currency": "currency",
                "po_reference": "purchase_order_reference"})
TYPE_PHRASES = [
    ("DEPOSIT REQUEST", "DOWN_PAYMENT_REQUEST"), ("PROFORMA", "PROFORMA"),
    ("RECTIFICATIVA", "CREDIT_NOTE"), ("NOTA DE CREDITO", "CREDIT_NOTE"),
    ("CREDIT NOTE", "CREDIT_NOTE"), ("EXTRACTO DE CUENTA", "VENDOR_STATEMENT"),
    ("RECORDATORIO DE PAGO", "VENDOR_STATEMENT"), ("CESION DE CREDITOS", "FACTORING_NOTICE"),
    ("CAMBIO DE CUENTA", "BANK_DETAILS_CHANGE"), ("CERTIFICADO DE ESTAR", "CONTRACTOR_TAX_CERTIFICATE"),
    ("EMBARGO", "TAX_GARNISHMENT_ORDER"), ("FACTURA", "INVOICE"),
    ("FATURA", "INVOICE"), ("INVOICE", "INVOICE"),
]
CRITICAL_HEADERS = {"invoice_number", "document_date", "due_date", "as_of_date", "effective_date",
                    "valid_until", "supplier_tax_id", "buyer_tax_id", "contractor_tax_id",
                    "corrects_invoice", "purchase_order_reference", "document_type"}
MONEY_FIELDS = {"net", "tax", "gross", "payable", "withholding", "withholding_displayed",
                "retention", "retention_displayed", "certified_cumulative", "certified_previous_displayed",
                "certified_current", "statement_outstanding_balance"}


def _text(value):
    return " ".join(unicodedata.normalize("NFKC", str(value)).split())


def canonical_field(field):
    field = str(field).strip()
    field = re.sub(r"_(?:cents|milli|e4)$", "", field)
    field = re.sub(r"^line\.", "lines.", field)
    field = re.sub(r"\b(lines|detail_lines|statement)\.(\d+)\.", r"\1[\2].", field)
    if "." in field:
        prefix, tail = field.rsplit(".", 1)
        return prefix + "." + ALIASES.get(tail, tail)
    return ALIASES.get(field, field)


def _type(value):
    value = _text(value).upper()
    plain = "".join(c for c in unicodedata.normalize("NFD", value) if not unicodedata.combining(c))
    for phrase, kind in TYPE_PHRASES:
        if phrase in plain:
            return kind
    return value


def _number(value, unit=None):
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError("Exact numeric values cannot be bool or binary float")
    if isinstance(value, (Decimal, int)):
        result = Decimal(value)
    elif isinstance(value, str):
        cleaned = re.sub(r"\b(EUR|USD|MXN|GBP)\b", "", value.upper()).strip()
        cleaned = cleaned.replace("−", "-").replace("$", "").replace("€", "").replace("%", "").strip()
        if cleaned.startswith("(") and cleaned.endswith(")"):
            cleaned = "-" + cleaned[1:-1]
        cleaned = cleaned.replace(" ", "").replace("\u00a0", "")
        if not re.fullmatch(r"[-+]?\d[\d.,]*", cleaned):
            raise ValueError("Not an exact source number")
        if "." in cleaned and "," in cleaned:
            decimal_separator = "." if cleaned.rfind(".") > cleaned.rfind(",") else ","
            cleaned = cleaned.replace("," if decimal_separator == "." else ".", "")
            cleaned = cleaned.replace(decimal_separator, ".")
        elif "," in cleaned:
            cleaned = cleaned.replace(",", ".")
        if cleaned.count(".") > 1:
            raise ValueError("Ambiguous numeric grouping requires normalization context")
        result = Decimal(cleaned)
    else:
        raise ValueError("Unsupported source number")
    if not result.is_finite():
        raise ValueError("Nonfinite value")
    scale = {"integer_cents": 100, "integer_milli": 1000, "integer_e4": 10000}.get(unit, 1)
    return result / scale


def _date(value, order="DMY"):
    value = _text(value)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:T.*)?", value):
        return date.fromisoformat(value[:10]).isoformat()
    match = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", value)
    if not match:
        raise ValueError("Date requires ISO or an explicit numeric DMY/MDY order")
    first, second, year = map(int, match.groups())
    if order not in {"DMY", "MDY"}:
        raise ValueError("Unknown date order")
    day, month = (first, second) if order == "DMY" else (second, first)
    return date(year, month, day).isoformat()


def normalize_value(field, value, *, unit=None, date_order="DMY"):
    """Deterministic lexical normalization; no source ID or expected answer lookup."""
    field = canonical_field(field)
    tail = field.rsplit(".", 1)[-1]
    if value is None:
        return None
    if field == "document_type":
        return _type(value)
    if tail.endswith("_date") or tail in {"valid_until"}:
        return _date(value, date_order)
    if tail.endswith("_rate"):
        result = _number(value, unit)
        if isinstance(value, str) and value.strip().endswith('%') and unit != 'integer_e4':
            result /= 100
        return result
    if (field in MONEY_FIELDS or tail in {"amount", "unit_price", "quantity", "deposit_percent"}
            or unit in {"currency_major_decimal", "source_decimal", "source_measure_decimal", "integer_cents", "integer_milli", "integer_e4", "percent"}):
        return _number(value, unit)
    if isinstance(value, str):
        return _text(value)
    return value


def _source_path(path):
    path = PurePosixPath(path)
    if path.is_absolute() or ".." in path.parts or "golden" in path.parts or "phase_test" in path.parts or "\\" in str(path):
        raise ValueError("Evidence source is outside the active original-source boundary")
    result = path.as_posix()
    return "phase_dev/" + result if result.startswith("inbox/") else result


def _xml_path(path):
    path = re.sub(r"\b[\w.-]+:", "", str(path))
    path = re.sub(r"\[(1)\]", "", path)
    return path.strip("/")


class SourceAudit:
    """Read only explicitly selected/anchored original bytes, not model text."""
    def __init__(self, root, manifest, parsed_documents=None, transformation_hashes=None, image_reviews=None):
        self.root = Path(root).resolve()
        self.allowed = {x["path"]: x for x in manifest.get("source_anchors", [])}
        self.allowed.update({a["path"]: a for c in manifest["cases"] for a in c["attachments"] + [c["message"]]})
        self._content = {}
        self.parsed_documents = parsed_documents or {}
        self.transformation_hashes = transformation_hashes or {}
        self.image_reviews = image_reviews or {}

    def source(self, document, expected_hash=None):
        document = _source_path(document)
        if document not in self.allowed:
            raise ValueError("Evidence source is not a selected original")
        path = (self.root / document).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Evidence source escapes its root")
        data = path.read_bytes()
        actual_hash = hashlib.sha256(data).hexdigest()
        if actual_hash != self.allowed[document]["sha256"] or (expected_hash and actual_hash != expected_hash):
            raise ValueError("Evidence source hash mismatch")
        return document, data

    def content(self, document):
        document, data = self.source(document)
        if document not in self._content:
            if document.endswith(".pdf"):
                try:
                    from pypdf import PdfReader
                except ImportError as error:
                    raise ValueError("Original PDF quote audit requires the documents/pypdf runtime") from error
                reader = PdfReader(BytesIO(data))
                parsed = self.parsed_documents.get(document)
                if parsed is not None:
                    if (parsed.source_sha256 != hashlib.sha256(data).hexdigest()
                            or _source_path(parsed.path) != document
                            or parsed.transformation_sha256 != self.transformation_hashes.get(document)):
                        raise ValueError('Archived parsed document source/transformation mismatch')
                    images = {(image.page, image.sha256) for image in parsed.images}
                else:
                    images = {(page_number, hashlib.sha256(image.data).hexdigest())
                              for page_number, page in enumerate(reader.pages, 1) for image in page.images}
                self._content[document] = {"pages": [p.extract_text(extraction_mode="layout") or "" for p in reader.pages],
                                           "images": images}
            elif document.endswith(".xml"):
                if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
                    raise ValueError("Unsafe XML source")
                fields = {}
                def visit(element, path):
                    if element.text and element.text.strip():
                        fields[_xml_path(path)] = element.text.strip()
                    for name, value in element.attrib.items():
                        fields[_xml_path(path + "/@" + name.rsplit("}", 1)[-1])] = value
                    counts = defaultdict(int)
                    for child in element:
                        name = child.tag.rsplit("}", 1)[-1]
                        counts[name] += 1
                        visit(child, path + "/" + name + f"[{counts[name]}]")
                xml = ET.fromstring(data)
                visit(xml, "/" + xml.tag.rsplit("}", 1)[-1])
                self._content[document] = {"fields": fields, "text": data.decode("utf-8")}
            else:
                self._content[document] = {"text": data.decode("utf-8")}
        return self._content[document]

    def proof(self, observed, label=None):
        evidence = observed["evidence"]
        try:
            document, _ = self.source(evidence["document"], observed["source_sha256"])
            content = self.content(document)
        except (ValueError, OSError, KeyError, UnicodeError, ET.ParseError) as error:
            return "unsupported", str(error)
        quote = evidence.get("quote")
        image_evidence = str(evidence.get('field', '')).startswith('image:')
        if image_evidence:
            image_hash = evidence['field'][len('image:'):]
            if (not re.fullmatch(r'[a-f0-9]{64}', image_hash)
                    or (evidence.get('page'), image_hash) not in content.get('images', set())):
                return 'unsupported', 'Image evidence identity is not an actual captured/original page image'
        if label and (label.get("state") == "absent" or label.get("unit") in {"rows", "nodes"}):
            if observed["value"] != label["value"]:
                return "unsupported", "Observed value differs from reviewed absence/structural count"
            if not evidence.get("field"):
                return "unsupported", "Structural proof requires a physical source location"
            if "pages" in content and (evidence.get("page") != label["evidence"].get("page") or type(evidence.get("page")) is not int or not 1 <= evidence["page"] <= len(content["pages"])):
                return "unsupported", "Structural proof refers to another or invalid page"
            return "grounded", "Manually reviewed absence/structural count, original hash and page"
        if "pages" in content:
            page = evidence.get("page")
            if type(page) is not int or not 1 <= page <= len(content["pages"]):
                return "unsupported", "Missing or invalid PDF page"
            text = content["pages"][page - 1]
            if image_evidence or not text.strip():
                if not image_evidence:
                    return 'unsupported', 'Image-only evidence requires an explicit image hash'
                review = validate_review(observed, self.transformation_hashes.get(document), self.image_reviews)
                if review == 'REJECTED':
                    return 'unsupported', 'Original-image review rejects this exact quotation/value'
                if review == 'VERIFIED':
                    if not _value_supported(observed, quote, label):
                        return 'unsupported', 'Reviewed quotation does not support the observed value'
                    return 'grounded', 'Independent exact original-image quotation review'
                if not label or label["evidence"].get("verification") != "manual_image_transcription":
                    return "unreviewed", "Image-only value requires manual source annotation"
                if label["evidence"].get("page") != page:
                    return "unsupported", "Image evidence points at another page"
                if not quote or not label["evidence"].get("quote"):
                    return "unsupported", "Image proof requires a manually transcribed quote"
                manual = _text(label["evidence"]["quote"])
                if _text(quote) not in manual:
                    return "unreviewed", "Additional image quote text requires independent visual review"
                if not _value_supported(observed, quote, label):
                    return "unsupported", "Image transcription does not support observed value"
                return "grounded", "Sealed manual image/page/field annotation"
            if not quote or _text(quote) not in _text(text):
                return "unsupported", "Quote is not present on the original PDF page"
            if label and label["evidence"].get("page") != page:
                return "unsupported", "Label and observation refer to different PDF pages"
            field = evidence.get("field", "")
            if not field:
                return "unsupported", "Missing physical evidence location"
        elif "fields" in content:
            field = _xml_path(evidence.get("field", ""))
            matches = [value for key, value in content["fields"].items() if key == field or key.endswith("/" + field)]
            if len(matches) != 1:
                return "unsupported", "XML node/attribute location is missing or ambiguous"
            text = matches[0]
            if quote is None or _text(quote) not in _text(text):
                return "unsupported", "Quote is not present in the stated original XML field"
            if label and "raw_node_values" not in label["evidence"]:
                expected_field = _xml_path(label["evidence"]["field"])
                if not (field == expected_field or field.endswith("/" + expected_field) or expected_field.endswith("/" + field)):
                    return "unsupported", "XML quote points at a different labelled node"
        else:
            text = content["text"]
            if not quote or _text(quote) not in _text(text) or not evidence.get("field"):
                return "unsupported", "Quote/location is not present in the original text"
        if label and label.get("state") == "absent":
            return "grounded", "Explicit absence reviewed in original"
        if _value_supported(observed, quote, label):
            return "grounded", "Observed value supported by original quote/location"
        return "unsupported", "Quoted text does not support the observed value"


def _value_supported(observed, quote, label):
    value, field = observed["value"], observed["field"]
    if field.endswith("_date") or field == "valid_until":
        for token in re.findall(r"\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{4}", str(quote)):
            try:
                if _date(value, (label or {}).get("date_order", "DMY")) == _date(token, (label or {}).get("date_order", "DMY")):
                    return True
            except ValueError:
                pass
    if field == "document_type" and _type(value) == _type(quote):
        return True
    if label:
        try:
            matches = normalize_value(field, value, unit=observed.get("unit") or label.get("unit"),
                                      date_order=label.get("date_order", "DMY")) == normalize_value(
                                          label["field"], label["value"], unit=label.get("unit"),
                                          date_order=label.get("date_order", "DMY"))
        except (ValueError, InvalidOperation, TypeError):
            matches = False
        if matches and (isinstance(value, bool) or field == "document_type" or "_date" in field or field == "valid_until"):
            anchor = label["evidence"].get("quote")
            if anchor and (_text(anchor) in _text(quote) or _text(quote) in _text(anchor)):
                return True
            nodes = label["evidence"].get("raw_node_values", {})
            if field == "document_type" and _text(quote) in {_text(x) for x in nodes.values()}:
                return True
            return False
    if value is None:
        return bool(label and label.get("state") == "absent")
    if isinstance(value, bool):
        return False  # Unreviewed semantic flags are not proven by a random quote.
    if field in MONEY_FIELDS or field.rsplit(".", 1)[-1] in {"amount", "unit_price", "quantity"} or field.endswith('_rate'):
        try:
            normalized = normalize_value(field, value, unit=observed.get("unit"))
            for token in re.findall(r"[-−+]?\d[\d.,]*(?:\s*(?:%|EUR|USD|MXN|GBP))?", str(quote)):
                try:
                    supported = normalize_value(field, token)
                    if field.endswith('_rate') and 'TaxRate' in observed['evidence'].get('field', '') and '%' not in token:
                        supported /= 100
                    if supported == normalized:
                        return True
                except (ValueError, InvalidOperation):
                    pass
        except (ValueError, InvalidOperation, TypeError):
            pass
        return False
    return _text(value) in _text(quote)


def _load(value):
    if isinstance(value, (str, Path)):
        data = Path(value).read_bytes()
        return json.loads(data), hashlib.sha256(data).hexdigest()
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return value, hashlib.sha256(data).hexdigest()


def _predictions(capture):
    if capture is None:
        return []
    if isinstance(capture, dict) and "raw_facts" in capture:
        capture = list(capture["raw_facts"]) + list(capture.get("normalized_facts", []))
    if isinstance(capture, (dict, DocumentFacts)):
        capture = [capture]
    result, seen = [], set()
    for document in capture:
        document = document.to_dict() if isinstance(document, DocumentFacts) else document
        DocumentFacts.from_dict(document)  # Validate the M0 boundary before evaluation.
        for key, facts in document["fields"].items():
            for fact in facts:
                value = _decode_value(fact["value"]) if document.get("fact_value_encoding") else fact["value"]
                evidence = dict(fact["evidence"])
                evidence["document"] = _source_path(evidence["document"])
                inferred_unit = next((unit for suffix, unit in (("_cents", "integer_cents"),
                    ("_milli", "integer_milli"), ("_e4", "integer_e4")) if key.endswith(suffix)), None)
                unit = fact.get("unit") or inferred_unit
                item = {"field": canonical_field(key), "value": value, "evidence": evidence,
                        "source_sha256": document["source_sha256"], "unit": unit}
                try:
                    equivalent_value = normalize_value(item["field"], value, unit=unit)
                except (ValueError, TypeError, InvalidOperation):
                    equivalent_value = repr(value)
                if isinstance(equivalent_value, Decimal):
                    equivalent_value = equivalent_value.normalize()
                fingerprint = (item["field"], evidence["document"], evidence.get("page"),
                               evidence.get("field"), evidence.get("quote"), repr(equivalent_value))
                if fingerprint not in seen:
                    seen.add(fingerprint)
                    result.append(item)
    return result


def _critical(label):
    if "critical" in label:
        return bool(label["critical"])
    field = canonical_field(label["field"])
    return field in CRITICAL_HEADERS or field.rsplit(".", 1)[-1] in {"amount", "unit_price", "quantity"} or label.get("unit") == "currency_major_decimal"


def _missing_abstention(capture, field, document, source_hash):
    """Compare an explicit unknown with reviewed absence; never create a fact."""
    if not isinstance(capture, dict):
        return False
    states = []
    items = capture.get('unknown_states', [])
    if not isinstance(items, (list, tuple)):
        return False
    for item in items:
        if not isinstance(item, dict):
            continue
        if not isinstance(item.get('field'), str) or not isinstance(item.get('document'), str):
            continue
        try:
            if (canonical_field(item['field']) == field and _source_path(item['document']) == document
                    and item.get('source_sha256') == source_hash):
                states.append(item)
        except (KeyError, ValueError, TypeError):
            continue
    return bool(states) and all(item.get('status') == 'MISSING' and isinstance(item.get('reason'), str)
                                and item['reason'].strip() for item in states)


def _ratio(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "rate": str(Decimal(numerator) / denominator) if denominator else None,
            "small_n": denominator < 20, "status": "measured" if denominator else "not_applicable"}


def validate_annotation_sources(manifest, annotations, source_root):
    """Return source-integrity errors without ever reading prohibited directories."""
    manifest, _ = _load(manifest)
    annotations, _ = _load(annotations)
    audit, errors = SourceAudit(source_root, manifest), []
    ids = {c["case_id"]: c for c in manifest["cases"]}
    seen = set()
    for case in annotations["cases"]:
        cid = case["case_id"]
        if cid in seen or cid not in ids or case["doc_id"] != ids[cid]["doc_id"]:
            errors.append({"case_id": cid, "code": "annotation_case_identity"})
        seen.add(cid)
        allowed = {a["path"] for a in ids.get(cid, {}).get("attachments", [])}
        slots = set()
        for label in [case["expected_document_type"]] + case["facts"]:
            ev = label["evidence"]
            slot = (canonical_field(label["field"]), ev["document"], ev.get("page"))
            if slot in slots:
                errors.append({"case_id": cid, "field": label["field"], "code": "duplicate_annotation_slot"})
            slots.add(slot)
            try:
                if ev["document"] not in allowed:
                    raise ValueError("Annotation is outside the case attachments")
                audit.source(ev["document"], ev["source_sha256"])
                content = audit.content(ev["document"])
                if "pages" in content:
                    page = ev.get("page")
                    if type(page) is not int or not 1 <= page <= len(content["pages"]):
                        raise ValueError("Label page is invalid")
                    text = content["pages"][page - 1]
                    if ev.get("quote") and text.strip() and _text(ev["quote"]) not in _text(text):
                        raise ValueError("Label quote is absent from original page")
                    if not text.strip() and ev.get("verification") != "manual_image_transcription":
                        raise ValueError("Image label lacks manual verification")
                elif "fields" in content and ev.get("quote"):
                    node = _xml_path(ev["field"])
                    values = [v for k, v in content["fields"].items() if k == node or k.endswith("/" + node)]
                    if len(values) != 1 or _text(ev["quote"]) not in _text(values[0]):
                        raise ValueError("Label XML quote/node does not match original")
            except (ValueError, OSError) as error:
                errors.append({"case_id": cid, "field": label["field"], "code": "annotation_source_integrity", "reason": str(error)})
    for check in annotations.get("semantic_candidates", []):
        ev = check["evidence"]
        try:
            _, data = audit.source(ev["document"], ev.get("source_sha256"))
            record = json.loads(data.decode().splitlines()[ev["line"] - 1])
            if record.get("id") != check["expected_candidate_id"]:
                raise ValueError("Semantic candidate ID differs from the original master row")
        except (ValueError, IndexError, OSError, KeyError) as error:
            errors.append({"case_id": check["case_id"], "code": "semantic_source_integrity", "reason": str(error)})
    return errors


def _exact_cost(value):
    """Machine-recorded prices use Decimal syntax, including scientific notation."""
    if isinstance(value, (bool, float)):
        raise ValueError('Cost requires an exact decimal value')
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError('Cost must be finite')
    return result


def _runtime(case_ids, reports, contract):
    results, issues, times, costs = {}, [], [], []
    for cid in case_ids:
        report = reports.get(cid)
        reason, cost = [], None
        if not isinstance(report, dict):
            reason.append("missing RunRecorder report")
            report = {}
        meta = report.get("input_metadata", {})
        if not isinstance(meta, dict):
            meta = {}
        source_tools = (meta.get('response_source') == 'source_tools'
                        and meta.get('transport_mode') == 'local'
                        and meta.get('source_tools_validated') is True)
        if (not source_tools and (meta.get("capture_mode") != "captured_live" or meta.get("transport_mode") != "default"
                or meta.get("response_source") != "provider_api")):
            reason.append("live default-transport provenance not established")
        calls = report.get("calls", [])
        if not isinstance(calls, list):
            calls = []
        operations = defaultdict(int)
        for call in calls:
            request = (call.get("usage") or {}).get("request") or {}
            identity = {key: request.get(key) for key in (
                "instructions_sha256", "prompt_sha256", "output_schema_sha256", "images")}
            operations[json.dumps(identity, sort_keys=True)] += 1
        if any(count > contract["budget"]["max_attempts_per_document"] for count in operations.values()):
            reason.append("attempt cap exceeded")
        if meta.get("synthetic") or meta.get("test_fixture"):
            reason.append("synthetic capture is not a live benchmark")
        if (not calls and not source_tools) or report.get("status") != "completed":
            reason.append("no completed real provider capture")
        if source_tools:
            proofs = meta.get('source_tools', [])
            if (calls or report.get('cache_hits') or meta.get('capture_mode') != 'fresh_source_tools'
                    or not isinstance(proofs, list) or not proofs
                    or any(not isinstance(proof, dict) or proof.get('fresh_processing') is not True
                           or not proof.get('adapter_name') or not proof.get('adapter_version')
                           or any(not isinstance(proof.get(key), str) or not re.fullmatch(r'[a-f0-9]{64}', proof[key])
                                  for key in ('adapter_sha256', 'config_sha256', 'source_sha256', 'transformation_sha256'))
                           for proof in proofs)):
                reason.append('fresh deterministic source processing provenance not established')
            else:
                cost = Decimal(0)
                costs.append(cost)
        estimates = []
        for call in calls:
            pricing = call.get("pricing") or {}
            try:
                if call.get("provider") != "openai" or call.get("model") != contract["candidate_model"]:
                    raise ValueError("unexpected provider/model")
                counts = [call.get("input_tokens"), call.get("output_tokens")]
                if any(type(n) is not int or n < 0 for n in counts) or sum(counts) == 0:
                    raise ValueError("unknown or zero token usage")
                if (pricing.get("currency") != "USD" or pricing.get("unit") != "per_token"
                        or not pricing.get("provenance")):
                    raise ValueError("USD pricing/unit/provenance missing")
                rates = [_exact_cost(pricing[k]) for k in ("input_rate", "output_rate")]
                if any(r < 0 for r in rates):
                    raise ValueError("negative price")
                estimate = _exact_cost(call["estimated_cost"])
                if estimate <= 0:
                    raise ValueError("zero-cost capture cannot establish paid live provenance")
                if estimate != sum((rate * count for rate, count in zip(rates, counts)), Decimal(0)):
                    raise ValueError("cost does not reproduce supplied prices and usage")
                estimates.append(estimate)
            except (ValueError, TypeError, KeyError, InvalidOperation) as error:
                reason.append(str(error))
        if calls and len(estimates) == len(calls):
            cost = sum(estimates, Decimal(0))
            costs.append(cost)
            if cost > Decimal(FROZEN_THRESHOLDS["capture_estimated_cost_usd_per_document_max"]):
                reason.append("per-document cost gate exceeded")
        elapsed = report.get("elapsed_seconds")
        if isinstance(elapsed, (int, float)) and not isinstance(elapsed, bool) and math.isfinite(elapsed) and elapsed >= 0:
            times.append(elapsed)
        else:
            reason.append("unknown document elapsed time")
        results[cid] = {"estimated_cost_usd": str(cost) if cost is not None else None,
                        "elapsed_seconds": elapsed, "live_confirmed": not reason, "violations": reason}
        if reason:
            issues.append({"case_id": cid, "code": "live_capture_gate", "reasons": reason})
    p95 = sorted(times)[math.ceil(len(times) * .95) - 1] if times else None
    if p95 is None or len(times) != len(case_ids) or p95 > FROZEN_THRESHOLDS["latency_p95_seconds_max"]:
        issues.append({"code": "latency_gate", "unknown_count": len(case_ids) - len(times)})
    budget = Decimal(contract["budget"]["smoke_plus_sample_spend_cap_usd"])
    if len(costs) != len(case_ids) or sum(costs, Decimal(0)) > budget:
        issues.append({"code": "capture_budget_gate", "unknown_count": len(case_ids) - len(costs)})
    return {"cases": results, "p95_seconds": p95, "document_denominator": len(case_ids),
            "total_estimated_usd": str(sum(costs, Decimal(0))) if len(costs) == len(case_ids) else None}, issues


def evaluate_sample(manifest, annotations, captures, *, source_root, semantic_results=None,
                    candidate_sets=None, run_reports=None, scope="holdout", output_path=None,
                    parsed_documents=None, transformation_hashes=None, image_reviews=None):
    """Produce a JSON report; ``passed`` requires correctness AND genuine live accounting.

    ``captures`` maps case aliases to M0 DocumentFacts / serialized lists or a
    {raw_facts: [...], normalized_facts: [...]} envelope. Semantic results are keyed
    by check_id (case_id fallback); candidate_sets contain the actual supplied IDs.
    No runtime reports means a useful offline correctness report, never a live pass.
    """
    manifest, manifest_hash = _load(manifest)
    annotations, annotation_hash = _load(annotations)
    contract = manifest["evaluation_contract"]
    violations = []
    if contract["thresholds"] != FROZEN_THRESHOLDS:
        violations.append({"code": "frozen_thresholds_changed"})
    expected_cases = {c["case_id"] for c in manifest["cases"] if c["split"] == scope}
    actual_cases = {c["case_id"] for c in annotations["cases"]}
    if expected_cases != actual_cases:
        violations.append({"code": "annotation_partition_mismatch"})
    if scope == "holdout" and (not annotations.get("sealed_before_live_evaluation") or annotations.get("selection_sha256") != manifest["selection_sha256"]):
        violations.append({"code": "unsealed_holdout_annotations"})
    violations.extend(validate_annotation_sources(manifest, annotations, source_root))
    audit = SourceAudit(source_root, manifest, parsed_documents, transformation_hashes, image_reviews)
    counters = defaultdict(lambda: [0, 0])
    case_results, field_counts, format_counts = {}, defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    unsupported, unknown, reviewed_predictions, correct_predictions = 0, 0, 0, 0
    critical_predictions, correct_critical_predictions = 0, 0
    for case in annotations["cases"]:
        cid = case["case_id"]
        labels = [case["expected_document_type"]] + case["facts"]
        try:
            predictions = _predictions(captures.get(cid))
        except (ValueError, TypeError, KeyError) as error:
            predictions = []
            violations.append({"case_id": cid, "code": "invalid_capture", "reason": str(error)})
        expected_slots = defaultdict(list)
        outcomes, present, exact, grounded, abstentions = [], 0, 0, 0, 0
        used = set()
        for label in labels:
            field = canonical_field(label["field"])
            doc = label["evidence"]["document"]
            expected_slots[(field, doc)].append(label)
            candidates = [(i, p) for i, p in enumerate(predictions) if p["field"] == field and p["evidence"]["document"] == doc]
            matches, proofs = [], []
            for index, predicted in candidates:
                used.add(index)
                try:
                    equals = (normalize_value(field, predicted["value"], unit=predicted.get("unit") or label.get("unit"), date_order=label.get("date_order", "DMY")) ==
                              normalize_value(field, label["value"], unit=label.get("unit"), date_order=label.get("date_order", "DMY")))
                except (ValueError, InvalidOperation, TypeError):
                    equals = False
                proof, reason = audit.proof(predicted, label)
                matches.append(equals)
                proofs.append(proof == "grounded" and equals)
            observed = bool(candidates)
            abstained = (not observed and label.get('state') == 'absent' and _missing_abstention(
                captures.get(cid), field, doc, label['evidence']['source_sha256']))
            if label.get('state') == 'absent':
                counters['reviewed_absence_abstention'][0] += abstained
                counters['reviewed_absence_abstention'][1] += 1
            correct = any(matches) or abstained
            proven = any(proofs)
            present += observed or abstained
            abstentions += abstained
            exact += correct
            grounded += proven
            counters["required_exact"][0] += correct
            counters["required_exact"][1] += 1
            if _critical(label):
                counters["critical_exact"][0] += correct
                counters["critical_exact"][1] += 1
            field_counts[field][0] += correct
            field_counts[field][1] += 1
            fmt = audit.allowed[doc].get("format", "unknown")
            format_counts[fmt][0] += correct
            format_counts[fmt][1] += 1
            outcomes.append({"field": field, "document": doc, "present": observed, "exact": correct, "grounded": proven,
                             "critical": _critical(label), "candidate_count": len(candidates),
                             "correct_missing_abstention": bool(abstained)})
        for index, predicted in enumerate(predictions):
            slot_labels = expected_slots.get((predicted["field"], predicted["evidence"]["document"]), [])
            if slot_labels:
                reviewed_predictions += 1
                equal_labels = []
                for label in slot_labels:
                    try:
                        if normalize_value(predicted["field"], predicted["value"], unit=predicted.get("unit") or label.get("unit"), date_order=label.get("date_order", "DMY")) == normalize_value(label["field"], label["value"], unit=label.get("unit"), date_order=label.get("date_order", "DMY")):
                            equal_labels.append(label)
                    except (ValueError, TypeError, InvalidOperation):
                        pass
                correct_predictions += bool(equal_labels)
                if any(_critical(x) for x in slot_labels):
                    critical_predictions += 1
                    correct_critical_predictions += bool(equal_labels)
                label = equal_labels[0] if equal_labels else slot_labels[0]
            else:
                label = None
            proof, reason = audit.proof(predicted)
            if proof == "unreviewed" or predicted["value"] is None or isinstance(predicted["value"], bool) or (label and label.get("unit") in {"rows", "nodes"}):
                proof, reason = audit.proof(predicted, label)
            counters["grounded_evidence"][0] += proof == "grounded"
            counters["grounded_evidence"][1] += 1
            if proof == "unsupported":
                unsupported += 1
                violations.append({"case_id": cid, "field": predicted["field"], "code": "unsupported_observation", "reason": reason})
            elif proof == "unreviewed":
                unknown += 1
                violations.append({"case_id": cid, "field": predicted["field"], "code": "unreviewed_observation", "reason": reason})
        case_results[cid] = {"required": len(labels), "completeness": _ratio(present, len(labels)),
                             "exact": _ratio(exact, len(labels)), "grounded": _ratio(grounded, len(labels)),
                             "returned_values": len(predictions), "fields": outcomes,
                             "correct_missing_abstentions": abstentions,
                             "unknown_states": captures.get(cid, {}).get('unknown_states', []) if isinstance(captures.get(cid), dict) else []}
        if Decimal(present) / len(labels) < Decimal(FROZEN_THRESHOLDS["case_required_field_completeness_min"]):
            violations.append({"case_id": cid, "code": "case_completeness_gate"})
    for metric, threshold in [("critical_exact", "critical_header_money_tax_line_amount_exact_min"),
                              ("grounded_evidence", "grounded_evidence_location_min")]:
        n, d = counters[metric]
        if not d or Decimal(n) / d < Decimal(FROZEN_THRESHOLDS[threshold]):
            violations.append({"code": metric + "_gate"})
    if critical_predictions and Decimal(correct_critical_predictions) / critical_predictions < Decimal(FROZEN_THRESHOLDS["critical_header_money_tax_line_amount_exact_min"]):
        violations.append({"code": "critical_prediction_precision_gate"})
    counters["critical_prediction_precision"] = [correct_critical_predictions, critical_predictions]
    semantics, semantic_issues, fabricated_ids = _semantic(annotations, semantic_results or {}, candidate_sets or {})
    violations.extend(semantic_issues)
    counters["reviewed_prediction_precision"] = [correct_predictions, reviewed_predictions]
    conflicts, preserved = [], 0
    for conflict in annotations.get("cross_attachment_conflicts", []):
        cid, field = conflict["case_id"], canonical_field(conflict["field"])
        try:
            predictions = _predictions(captures.get(cid))
            observed = {normalize_value(field, x["value"]) for x in predictions if x["field"] == field}
        except (ValueError, KeyError, TypeError, InvalidOperation):
            observed = set()
        expected = {normalize_value(field, x) for x in conflict["expected_values"]}
        capture = captures.get(cid)
        unified = capture.get("unified_values", {}).get(field) if isinstance(capture, dict) else None
        retained = expected.issubset(observed) and unified is None
        preserved += retained
        conflicts.append({"case_id": cid, "field": field, "preserved": retained, "unified_abstained": unified is None})
        if not retained:
            violations.append({"case_id": cid, "code": "conflicting_attachment_values_collapsed"})
    counters["cross_attachment_conflict_preservation"] = [preserved, len(conflicts)]
    runtime, runtime_issues = _runtime(sorted(expected_cases), run_reports or {}, contract)
    correctness_passed = not violations
    violations.extend(runtime_issues)
    report = {"schema_version": 1, "scope": scope, "passed": not violations,
              "capture_correctness_passed": correctness_passed, "live_capture_confirmed": not runtime_issues,
              "manifest_sha256": manifest_hash, "annotations_sha256": annotation_hash,
              "image_reviews_sha256": fingerprint(image_reviews or {}),
              "selection_sha256": manifest["selection_sha256"], "thresholds": FROZEN_THRESHOLDS,
              "metrics": {key: _ratio(*value) for key, value in counters.items()},
              "per_field": {key: _ratio(*value) for key, value in sorted(field_counts.items())},
              "per_format": {key: _ratio(*value) for key, value in sorted(format_counts.items())},
              "cases": case_results, "semantic": semantics, "runtime": runtime, "conflicts": conflicts,
              "fabrication_audit": {"unsupported_values_or_evidence": unsupported, "fabricated_or_out_of_set_ids": fabricated_ids,
                                    "unreviewed_values": unknown,
                                    "zero_fabrication_established": unsupported == 0 and fabricated_ids == 0 and unknown == 0},
              "violations": violations, "limits": ["Small-N rates and repeated source template families remain explicit.",
                  "Unlabelled grounded text values are source-supported, not asserted semantically correct.",
                  "Image extras need manual review; unknown is not a zero-fabrication success.",
                  "Live/default-transport metadata is a runner trust boundary, not cryptographic proof of a provider call.",
                  "Synthetic candidate guard fixtures must be evaluated separately from this real-source partition."]}
    if output_path:
        atomic_json(output_path, report)
    return report


def _semantic(annotations, results, candidate_sets):
    selected, correct, resolvable, covered, ambiguous, abstained, fabricated = 0, 0, 0, 0, 0, 0, 0
    details, issues = [], []
    for check in annotations.get("semantic_candidates", []):
        key = check.get("check_id", check["case_id"])
        result = results.get(key, {})
        ids = result.get("selected_ids", [])
        if not isinstance(ids, (list, tuple)) or any(not isinstance(i, str) for i in ids):
            ids = []
            issues.append({"check_id": key, "code": "invalid_semantic_result"})
        allowed = candidate_sets.get(key)
        if allowed is None:
            issues.append({"check_id": key, "code": "bounded_candidate_set_missing"})
        else:
            fabricated += sum(i not in set(allowed) for i in ids)
        selected += len(ids)
        unique = check.get("resolvability", "").startswith("manually_unique")
        if unique:
            resolvable += 1
            hit = ids == [check["expected_candidate_id"]] or ids == (check["expected_candidate_id"],)
            covered += hit
            correct += sum(i == check["expected_candidate_id"] for i in ids)
        else:
            ambiguous += 1
            abstained += not ids and result.get("status") in {"AMBIGUOUS", "NO_MATCH", "abstain"}
        details.append({"check_id": key, "selected_count": len(ids), "resolvability": check.get("resolvability")})
    if fabricated:
        issues.append({"code": "fabricated_candidate_ids", "count": fabricated})
    if resolvable and (not selected or Decimal(correct) / selected < Decimal(FROZEN_THRESHOLDS["selected_candidate_precision_min"])):
        issues.append({"code": "semantic_precision_gate"})
    if resolvable and Decimal(covered) / resolvable < Decimal(FROZEN_THRESHOLDS["unique_resolvable_candidate_coverage_min"]):
        issues.append({"code": "semantic_coverage_gate"})
    if ambiguous and Decimal(abstained) / ambiguous < Decimal(FROZEN_THRESHOLDS["ambiguous_correct_abstention_min"]):
        issues.append({"code": "semantic_abstention_gate"})
    return {"precision": _ratio(correct, selected), "coverage": _ratio(covered, resolvable),
            "abstention": _ratio(abstained, ambiguous), "checks": details}, issues, fabricated
