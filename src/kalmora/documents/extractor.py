"""Typed source-grounded extraction and bounded semantic selection, not accounting."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from functools import lru_cache
import hashlib
import re
from typing import Any

from kalmora.facts import DocumentFacts, Evidence, Fact
from kalmora.llm.client import ImageInput, LLMError, sanitize
from .contracts import ParsedDocument, ResolutionRequest, ResolutionResult, fingerprint
from .prompts import (EXTRACTION_INSTRUCTIONS, EXTRACTION_PROMPT_VERSION,
                      RESOLUTION_INSTRUCTIONS, RESOLUTION_PROMPT_VERSION, SCHEMA_VERSION, prompt_text)

HEADER_FIELDS = frozenset("""supplier_tax_id recipient_tax_id customer_tax_id supplier_name
recipient_name customer_name document_number invoice_number document_date invoice_date
due_date currency document_currency currency_symbol document_type_hint net tax gross
payable withholding retention retention_rate tax_rate tax_code_hint iban bank_name
po_reference purchase_order_reference receipt_reference delivery_reference
contract_reference project_reference original_invoice_reference credit_note_reference
period_start period_end service_period_start service_period_end certification_number
certification_date certification_current certification_previous certification_cumulative
certification_amount current_amount previous_amount cumulative_amount advance_amount
advance_rate guarantee_amount guarantee_rate factoring_reference factor_name factor_tax_id
factoring_effective_date notice_date notice_type_hint bank_details_effective_date
certificate_type_hint certificate_tax_id certificate_valid_from certificate_valid_until
certificate_expiry_date contractor_certificate_valid_until embargo_reference
embargo_amount embargo_date payment_terms line_count statement_row_count detail_line_count
as_of_date certificate_social_security_valid_until certificate_tax_valid_until
deposit_percent cfdi_type fiscal_validity old_iban new_iban""".split())
LINE_FIELDS = frozenset("""quantity uom unit_price amount net tax taxable_base tax_rate description material
po_reference purchase_order_reference po_item delivery_reference receipt_reference
discount discount_rate retention retention_rate withholding currency tax_code_hint
period_start period_end certification_current certification_previous certification_cumulative""".split())
RAW_STRING_FIELDS = frozenset("""net tax gross payable withholding retention retention_rate
tax_rate document_date invoice_date due_date period_start period_end service_period_start
service_period_end certification_date certification_current certification_previous
certification_cumulative certification_amount current_amount previous_amount cumulative_amount
advance_amount advance_rate guarantee_amount guarantee_rate factoring_effective_date
notice_date bank_details_effective_date certificate_valid_from certificate_valid_until
certificate_expiry_date contractor_certificate_valid_until embargo_amount embargo_date
quantity unit_price amount taxable_base discount discount_rate as_of_date deposit_percent
certificate_social_security_valid_until certificate_tax_valid_until fiscal_validity old_iban new_iban cfdi_type""".split())
FORBIDDEN_PARTS = frozenset("""decision action account journal_entry debit credit approved
approval receipt_confirmed receipt_status quantity_allocation allocation posting tolerance
payment_block payment_action reason_code""".split())
ABSENCE_MARKER = re.compile(r"\b(?:sin|ausente|ningun[ao]?|no\s+(?:indicado|indicada|consta|disponible|aplica)|not\s+(?:provided|available|applicable)|absent|none)\b", re.I)
ABSENCE_ALIASES = {
    "iban": ("iban", "cuenta bancaria"), "net": ("net", "neto", "subtotal", "base"),
    "tax": ("tax", "iva", "impuesto", "taxamount"), "gross": ("gross", "total"),
    "withholding": ("withholding", "retención", "retencion"),
    "retention": ("retention", "garantía", "garantia", "retención", "retencion"),
    "currency": ("currency", "moneda", "divisa"), "document_currency": ("currency", "moneda", "divisa"),
    "supplier_tax_id": ("supplier tax id", "nif proveedor", "rfc emisor"),
    "recipient_tax_id": ("recipient tax id", "nif destinatario", "nif receptor", "rfc receptor"),
}


DERIVED_COUNTS = {"line_count": "line", "statement_row_count": "statement", "detail_line_count": "detail_lines"}
STATEMENT_FIELDS = frozenset("invoice_reference status date due_date amount currency description".split())
DETAIL_FIELDS = LINE_FIELDS


def _raw_name_allowed(name: str) -> bool:
    # Literal source labels can retain Unicode, spaces, case and XML hierarchy.
    if not name or len(name) > 160 or any(not char.isprintable() for char in name):
        return False
    # Final punctuation belongs to a printed label, not an empty hierarchy node.
    parts = name.rstrip('.').split('.')
    return len(parts) <= 8 and all(part.strip() and part == part.strip()
                                  and part.casefold().replace(' ', '_') not in FORBIDDEN_PARTS
                                  for part in parts)


def _field_allowed(name: str) -> bool:
    if name in HEADER_FIELDS or re.fullmatch(r"certificate_[a-z][a-z0-9_]*_valid_until", name):
        return True
    match = re.fullmatch(r"(line|statement|detail_lines)\.([1-9]\d*)\.(.+)", name)
    if match:
        namespace, _, leaf = match.groups()
        allowed = {"line": LINE_FIELDS, "statement": STATEMENT_FIELDS, "detail_lines": DETAIL_FIELDS}[namespace]
        return leaf in allowed or (leaf.startswith('raw.') and _raw_name_allowed(leaf[4:]))
    return name.startswith('raw.') and _raw_name_allowed(name[4:])


@lru_cache(maxsize=1)
def output_models():
    """Build strict optional Pydantic DTOs only when interpretation is requested."""
    from pydantic import BaseModel, ConfigDict, Field
    from typing import Literal

    class ObservationValue(BaseModel):
        model_config = ConfigDict(strict=True, extra="forbid")
        field: str
        value: str | int | bool | None
        kind: Literal["OBSERVED", "EXPLICIT_ABSENCE"]

    class Observation(ObservationValue):
        block_id: str
        quote: str
        image_page: int | None
        image_sha256: str | None

    class ObservationGroup(BaseModel):
        model_config = ConfigDict(strict=True, extra="forbid")
        values: list[ObservationValue]
        block_id: str
        quote: str
        image_page: int | None
        image_sha256: str | None

    class Unknown(BaseModel):
        model_config = ConfigDict(strict=True, extra="forbid")
        field: str
        status: Literal["MISSING", "AMBIGUOUS", "CONTRADICTORY"]
        reason: str

    class ExtractionOutput(BaseModel):
        model_config = ConfigDict(strict=True, extra="forbid")
        observations: list[Observation]
        unknowns: list[Unknown]
        groups: list[ObservationGroup] = Field(default_factory=list)

        def iter_observations(self):
            yield from self.observations
            for group in self.groups:
                proof = group.model_dump(exclude={'values'})
                for value in group.values:
                    yield Observation(**value.model_dump(), **proof)

    class SelectionProof(BaseModel):
        model_config = ConfigDict(strict=True, extra="forbid")
        candidate_id: str
        candidate_attribute: str
        candidate_value: str | int | bool | None
        source_value: str | int | bool
        block_id: str
        quote: str
        image_page: int | None
        image_sha256: str | None

    class ResolutionOutput(BaseModel):
        model_config = ConfigDict(strict=True, extra="forbid")
        status: Literal["SELECTED", "AMBIGUOUS", "NO_MATCH"]
        selected_ids: list[str]
        evidence: list[SelectionProof]
        reason: str

    # Local forward references are resolved here rather than at module import.
    ObservationGroup.model_rebuild(_types_namespace={"ObservationValue": ObservationValue})
    ExtractionOutput.model_rebuild(_types_namespace={"Observation": Observation, "Unknown": Unknown,
                                                   "ObservationGroup": ObservationGroup})
    ResolutionOutput.model_rebuild(_types_namespace={"SelectionProof": SelectionProof})
    return ExtractionOutput, ResolutionOutput


class DocumentInterpretationError(ValueError):
    def __init__(self, category: str, document: ParsedDocument, detail: str) -> None:
        super().__init__(f"{document.path}: {category}: {detail}")
        self.category = category
        self.source_sha256 = document.source_sha256
        self.path = document.path
        self.raw_response: dict[str, Any] = {}
        self.request_metadata: dict[str, Any] = {}


@dataclass(frozen=True)
class ExtractionArtifact:
    facts: DocumentFacts
    raw_response: dict[str, Any]
    request_metadata: dict[str, Any]
    unknowns: tuple[dict[str, Any], ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"facts": self.facts.to_dict(), "raw_response": sanitize(self.raw_response),
                "request_metadata": sanitize(self.request_metadata),
                "unknowns": list(self.unknowns), "provenance": self.provenance}


@dataclass(frozen=True)
class ResolutionArtifact:
    result: ResolutionResult
    raw_response: dict[str, Any]
    request_metadata: dict[str, Any]
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"result": self.result.to_dict(),
                "raw_response": sanitize(self.raw_response),
                "request_metadata": sanitize(self.request_metadata), "provenance": self.provenance}


def _normal(value: str) -> str:
    return " ".join(value.split())


def _value_in_quote(value: Any, quote: str) -> bool:
    quote = _normal(quote)
    if isinstance(value, str):
        literal = _normal(value)
        if not literal:
            return False
        left = r"(?<!\w)" if literal[0].isalnum() else ""
        right = r"(?!\w)" if literal[-1].isalnum() else ""
        return bool(re.search(left + re.escape(literal) + right, quote))
    if type(value) is bool:
        alternatives = ("true", "yes", "sí") if value else ("false", "no")
        return any(re.search(r"(?<!\w)" + token + r"(?!\w)", quote, re.I) for token in alternatives)
    if type(value) is int:
        return bool(re.search(r"(?<![\w.,])" + re.escape(str(value)) + r"(?![\w.,])", quote))
    return False


def _ground(document: ParsedDocument, value: Any, observation: Any, *, explicit_absence=False) -> tuple[Evidence, dict[str, Any] | None]:
    block = next((block for block in document.blocks if block.id == observation.block_id), None)
    if block is None:
        raise DocumentInterpretationError("grounding", document, "nonexistent block")
    is_image = observation.image_page is not None or observation.image_sha256 is not None
    review = None
    if is_image:
        image = next((image for image in document.images if image.page == observation.image_page
                      and image.sha256 == observation.image_sha256), None)
        if image is None or block.page != image.page:
            raise DocumentInterpretationError("grounding", document, "image page/hash differs from source block")
        if not _normal(observation.quote):
            raise DocumentInterpretationError("grounding", document, "image proof requires transcribed quote")
        locator = "image:" + image.sha256
        review = {"block_id": block.id, "page": image.page, "image_sha256": image.sha256,
                  "quote": observation.quote}
    else:
        empty_xml = (explicit_absence and document.media_type == "application/xml"
                     and block.source_field is not None and block.text == "" and observation.quote == "")
        if not empty_xml and (not _normal(observation.quote) or _normal(observation.quote) not in _normal(block.text)):
            raise DocumentInterpretationError("grounding", document, "quote not found in source block")
        locator = block.source_field or block.id
    if explicit_absence:
        if value is not None:
            raise DocumentInterpretationError("absence", document, "explicit absence must have null value")
        if not (not is_image and document.media_type == "application/xml" and block.text == ""
                and block.source_field is not None and observation.quote == "") and not ABSENCE_MARKER.search(observation.quote):
            raise DocumentInterpretationError("absence", document, "no source-backed absence statement")
        if observation.quote:
            leaf = observation.field.rsplit(".", 1)[-1]
            aliases = ABSENCE_ALIASES.get(leaf, (leaf.replace("_", " "),))
            if not any(alias.casefold() in _normal(observation.quote).casefold() for alias in aliases):
                raise DocumentInterpretationError("absence", document, "absence statement does not identify the field")
    elif value is None or not _value_in_quote(value, observation.quote):
        raise DocumentInterpretationError("grounding", document, "value not supported by quoted text")
    return Evidence(document.path, locator, block.page, observation.quote), review


def _prompt(document: ParsedDocument, extras: dict[str, Any]) -> str:
    return prompt_text(document, extras)


def _provenance(document: ParsedDocument, instructions: str, prompt_version: str, schema: Any) -> dict[str, Any]:
    return {"source_sha256": document.source_sha256, "parser_version": document.parser_version,
            "transformation_sha256": document.transformation_sha256,
            "prompt_version": prompt_version, "instruction_content_sha256": hashlib.sha256(instructions.encode()).hexdigest(),
            "schema_version": SCHEMA_VERSION, "schema_sha256": fingerprint(schema.model_json_schema())}


async def _complete(client: Any, schema: Any, instructions: str, prompt: str,
                    document: ParsedDocument, provenance: dict[str, Any]) -> Any:
    try:
        return await client.complete(schema, instructions, prompt,
                                     images=tuple(ImageInput(image.data, image.media_type) for image in document.images))
    except LLMError as error:
        # Keep the operational category while making the failed source/stage auditable.
        error.path = document.path
        error.source_sha256 = document.source_sha256
        error.raw_response = error.raw
        error.request_metadata = {**getattr(error, "request_metadata", {}), **provenance}
        raise


def _recording_identity(client: Any, instructions: str, prompt_version: str,
                        schema: Any, parameters: dict[str, Any], provider: str) -> dict[str, Any]:
    config = client.config
    settings = {name: getattr(config, name) for name in (
        "reasoning_effort", "max_input_tokens", "max_output_tokens",
        "image_token_reserve", "max_image_bytes")}
    if hasattr(config, "model_output_capacity_tokens"):
        settings["model_output_capacity_tokens"] = config.model_output_capacity_tokens
    if hasattr(config, "image_detail"):
        settings["image_detail"] = config.image_detail
    identity = {"provider": provider, "model": config.model,
                "prompt_version": prompt_version,
                "prompt_sha256": hashlib.sha256(instructions.encode()).hexdigest(),
                "schema_version": SCHEMA_VERSION,
                "schema_sha256": fingerprint(schema.model_json_schema()),
                "parameters": {**settings, **parameters}}
    identity["extractor_version"] = f"{prompt_version}:{fingerprint(identity)}"
    return identity


def _candidate_value_matches(value: Any, proof: Any) -> bool:
    if isinstance(value, Decimal) and isinstance(proof, str):
        try:
            observed = Decimal(proof)
        except InvalidOperation:
            return False
        return observed.is_finite() and value.is_finite() and observed == value
    return fingerprint(value) == fingerprint(proof)


def _provider_name(client: Any) -> str:
    provider = client.provider
    if provider is None or type(provider).__name__ == "OpenAIResponsesProvider":
        return "openai"
    return f"injected:{type(provider).__module__}.{type(provider).__qualname__}"


class LLMDocumentExtractor:
    def __init__(self, client: Any) -> None:
        self.client = client

    def recording_identity(self, *, provider: str | None = None) -> dict[str, Any]:
        schema, _ = output_models()
        extras = {"canonical_fields": sorted(HEADER_FIELDS - DERIVED_COUNTS.keys()),
                  "line_fields": sorted(LINE_FIELDS), "statement_fields": sorted(STATEMENT_FIELDS),
                  "detail_fields": sorted(DETAIL_FIELDS), "raw_extension": "raw.<literal_field_name>"}
        return _recording_identity(self.client, EXTRACTION_INSTRUCTIONS,
                                   EXTRACTION_PROMPT_VERSION, schema, {"prompt_extras": extras},
                                   provider or _provider_name(self.client))

    @property
    def version(self) -> str:
        """Configuration identity available before any document/provider call."""
        return self.recording_identity()["extractor_version"]

    async def extract(self, document: ParsedDocument) -> DocumentFacts:
        return (await self.extract_with_response(document)).facts

    async def extract_with_response(self, document: ParsedDocument) -> ExtractionArtifact:
        schema, _ = output_models()
        identity = self.recording_identity()
        provenance = _provenance(document, EXTRACTION_INSTRUCTIONS, EXTRACTION_PROMPT_VERSION, schema)
        provenance.update(provider=identity["provider"], model=identity["model"],
                          extractor_version=identity["extractor_version"])
        completion = await _complete(self.client, schema, EXTRACTION_INSTRUCTIONS,
                                               _prompt(document, {"canonical_fields": sorted(HEADER_FIELDS - DERIVED_COUNTS.keys()),
                                                                  "line_fields": sorted(LINE_FIELDS), "statement_fields": sorted(STATEMENT_FIELDS),
                  "detail_fields": sorted(DETAIL_FIELDS),
                                                                  "raw_extension": "raw.<literal_field_name>"}),
                                     document, provenance)
        output = completion.output
        fields: dict[str, list[Fact]] = {}
        reviews = []
        try:
            # Legacy injected flat DTOs remain supported. Groups require the
            # typed output model so every expanded value passes its strict DTO.
            if hasattr(output, 'iter_observations'):
                observations = output.iter_observations()
            elif not getattr(output, 'groups', []):
                observations = output.observations
            else:
                raise DocumentInterpretationError('schema', document, 'grouped output requires the typed DTO')
            for observation in observations:
                name = observation.field
                if not _field_allowed(name) or name in DERIVED_COUNTS:
                    raise DocumentInterpretationError("field", document, "unsupported or accounting-owned field")
                leaf = name.rsplit(".", 1)[-1]
                if observation.kind == "OBSERVED" and (leaf in RAW_STRING_FIELDS or leaf.endswith("_valid_until") or ".raw." in name or name.startswith("raw.")) and not isinstance(observation.value, str):
                    raise DocumentInterpretationError("field", document, "amount/quantity/date must preserve original text")
                evidence, review = _ground(document, observation.value, observation,
                                          explicit_absence=observation.kind == "EXPLICIT_ABSENCE")
                fields.setdefault(name, []).append(Fact(observation.value, evidence))
                if review:
                    reviews.append({"field": name, **review})
            unknowns = tuple(unknown.model_dump() for unknown in completion.output.unknowns)
            for unknown in unknowns:
                if not unknown["reason"].strip():
                    raise DocumentInterpretationError("unknown", document, "unknown state requires a reason")
                if not _field_allowed(unknown["field"]) or unknown["field"] in DERIVED_COUNTS:
                    raise DocumentInterpretationError("field", document, "unsupported unknown field")
                if unknown["status"] == "MISSING" and unknown["field"] in fields:
                    raise DocumentInterpretationError("unknown", document, "missing field has an observation")
                if unknown["status"] == "CONTRADICTORY" and len({fingerprint(fact.value) for fact in fields.get(unknown["field"], [])}) < 2:
                    raise DocumentInterpretationError("unknown", document, "contradiction requires distinct observed values")
            for count_name, namespace in DERIVED_COUNTS.items():
                prefix = namespace + '.'
                line_ids = sorted({int(name.split('.')[1]) for name in fields if name.startswith(prefix)})
                if not line_ids:
                    continue
                if line_ids != list(range(1, len(line_ids) + 1)):
                    raise DocumentInterpretationError("lines", document, "row IDs must be contiguous and one-based")
                source_fact = next(fact for name, facts in fields.items() if name.startswith(prefix) for fact in facts)
                fields[count_name] = [Fact(len(line_ids), Evidence(document.path, source_fact.evidence.field, source_fact.evidence.page,
                                                                  source_fact.evidence.quote))]
                provenance.setdefault("derived_fields", {})[count_name] = {
                    "method": "count_unique_contiguous_line_ids", "line_ids": line_ids,
                    "source_fields": sorted({fact.evidence.field for name, facts in fields.items()
                                             if name.startswith(prefix) for fact in facts})}

        except DocumentInterpretationError as error:
            error.raw_response = completion.raw_response
            error.request_metadata = {**completion.request_metadata, **provenance}
            raise
        provenance["image_quote_review"] = reviews
        facts = DocumentFacts(document.source_sha256, identity["extractor_version"], fields)
        return ExtractionArtifact(facts, completion.raw_response, {**completion.request_metadata, **provenance}, unknowns, provenance)


class LLMSemanticResolver:
    def __init__(self, client: Any, *, max_selections: int = 1, max_candidates: int = 100) -> None:
        if type(max_selections) is not int or max_selections < 1 or type(max_candidates) is not int or max_candidates < 1:
            raise ValueError("selection/candidate limits must be positive integers")
        self.client = client
        self.max_selections = max_selections
        self.max_candidates = max_candidates

    def recording_identity(self, *, provider: str | None = None) -> dict[str, Any]:
        _, schema = output_models()
        return _recording_identity(self.client, RESOLUTION_INSTRUCTIONS,
                                   RESOLUTION_PROMPT_VERSION, schema,
                                   {"max_selections": self.max_selections, "max_candidates": self.max_candidates},
                                   provider or _provider_name(self.client))

    @property
    def version(self) -> str:
        return self.recording_identity()["extractor_version"]

    async def resolve(self, request: ResolutionRequest) -> ResolutionResult:
        return (await self.resolve_with_response(request)).result

    async def resolve_with_response(self, request: ResolutionRequest) -> ResolutionArtifact:
        document = request.document
        candidates = {candidate.id: candidate for candidate in request.candidates}
        if len(candidates) > self.max_candidates:
            raise DocumentInterpretationError("candidate_limit", document, "candidate set exceeds configured bound")
        constraints = request.context.get("hard_constraints", {})
        excluded = request.context.get("excluded_ids", [])
        if not isinstance(constraints, dict) or any(not isinstance(key, str) for key in constraints):
            raise DocumentInterpretationError("context", document, "hard constraints require attribute-value mapping")
        if not isinstance(excluded, (tuple, list)) or any(not isinstance(item, str) or item not in candidates for item in excluded):
            raise DocumentInterpretationError("context", document, "excluded IDs must belong to supplied candidates")
        _, schema = output_models()
        identity = self.recording_identity()
        provenance = _provenance(document, RESOLUTION_INSTRUCTIONS, RESOLUTION_PROMPT_VERSION, schema)
        provenance.update(provider=identity["provider"], model=identity["model"],
                          extractor_version=identity["extractor_version"])
        provenance.update(resolution_request_sha256=request.sha256, max_selections=self.max_selections,
                          max_candidates=self.max_candidates)
        completion = await _complete(self.client, schema, RESOLUTION_INSTRUCTIONS,
                                               _prompt(document, {"candidates": [{"id": candidate.id, "attributes": candidate.attributes}
                                                                                 for candidate in request.candidates],
                                                                  "context": request.context, "max_selections": self.max_selections}),
                                     document, provenance)
        output = completion.output
        try:
            if not output.reason.strip():
                raise DocumentInterpretationError("selection", document, "selection/abstention requires a reason")
            selected = output.selected_ids
            if (output.status == "SELECTED") != bool(selected) or len(set(selected)) != len(selected):
                raise DocumentInterpretationError("selection", document, "selection/abstention or duplicate IDs invalid")
            if len(selected) > self.max_selections:
                raise DocumentInterpretationError("selection", document, "selection exceeds configured bound; no quantity splits")
            for candidate_id in selected:
                if candidate_id not in candidates or candidate_id in excluded:
                    raise DocumentInterpretationError("selection", document, "selected ID is outside allowed set")
                candidate = candidates[candidate_id]
                if any(key not in candidate.attributes or fingerprint(candidate.attributes[key]) != fingerprint(value)
                       for key, value in constraints.items()):
                    raise DocumentInterpretationError("constraint", document, "selected candidate violates hard constraint")
            evidence = []
            proved = set()
            for proof in output.evidence:
                if proof.candidate_id not in selected:
                    raise DocumentInterpretationError("selection", document, "proof refers to unselected candidate")
                candidate = candidates[proof.candidate_id]
                if (proof.candidate_attribute not in candidate.attributes or
                        not _candidate_value_matches(candidate.attributes[proof.candidate_attribute], proof.candidate_value)):
                    raise DocumentInterpretationError("grounding", document, "candidate proof differs from provided attributes")
                if proof.candidate_attribute in FORBIDDEN_PARTS:
                    raise DocumentInterpretationError("selection", document, "accounting-owned candidate proof")
                _, review = _ground(document, proof.source_value, proof)
                evidence.append({**proof.model_dump(), "source_sha256": document.source_sha256,
                                 "quote_verification": "PAGE_HASH_ONLY" if review else "TEXT_MATCH"})
                proved.add(proof.candidate_id)
            if proved != set(selected):
                raise DocumentInterpretationError("grounding", document, "every selected ID requires source proof")
            result = ResolutionResult(output.status, tuple(selected), tuple(evidence), output.reason)
        except DocumentInterpretationError as error:
            error.raw_response = completion.raw_response
            error.request_metadata = {**completion.request_metadata, **provenance}
            raise
        return ResolutionArtifact(result, completion.raw_response, {**completion.request_metadata, **provenance}, provenance)
