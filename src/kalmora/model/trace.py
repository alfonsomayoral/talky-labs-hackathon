"""Shapes of a run bundle beyond the six deliverables (the web app's ``CONTRACT.md`` section 1).

``runs/<run_id>/manifest.json``, ``trace/events.jsonl`` and ``trace/attention.jsonl`` are produced
by whatever closes the month; ``overrides.jsonl`` is written by people reviewing it. Types only.
"""
from typing import Literal, NotRequired, Required, TypedDict

EventKind = Literal["EXTRACT", "CHECK", "MATCH", "CLASSIFY", "ESTIMATE", "DECIDE", "POST", "MODEL_CALL"]
EventResult = Literal["PASS", "FAIL", "INFO"]
EvidenceKind = Literal["doc", "erp", "bank", "journal", "precedent"]
AttentionKind = Literal["FRAUD_SIGNAL", "MATERIAL_UNEXPLAINED", "AGENT_DOUBT", "ESTIMATE", "CROSS_TASK",
                        "POLICY_EXCEPTION", "MASTER_DATA", "DATA_QUALITY"]
Priority = Literal["P0", "P1", "P2", "P3"]
TASKS = ("ap", "ar_billing", "ar_cash", "bank_rec", "ic", "close")


class Evidence(TypedDict, total=False):
    """Where a step looked. Which fields apply depends on ``kind``:
    ``doc`` path + locator, ``erp`` file + key + field, ``bank`` account + bank_line,
    ``journal`` ref (``<entry id>#<line>``), ``precedent`` text."""

    kind: Required[EvidenceKind]
    path: str
    locator: str
    file: str
    key: str
    field: str
    account: str
    bank_line: str
    ref: str
    text: str


class ModelCall(TypedDict, total=False):
    provider: str
    name: str
    question: str
    answer: str
    probabilities: dict[str, float]
    input_tokens: int
    output_tokens: int
    cost_usd: float


class TraceEvent(TypedDict, total=False):
    """One step an engine took on one item. Append-only."""

    event_id: Required[str]
    item: Required[str]
    """``<task>:<key>``: ``ap:<doc_id>``, ``ar_billing:<billing_item>``, ``ar_cash:<bank_line>``,
    ``bank_rec:<account>/<line>``, ``ic:<co1>-<co2>/<cause>``, ``close:<type>/<company>/<key>``."""
    seq: Required[int]
    ts: Required[str]
    kind: Required[EventKind]
    step: str
    result: EventResult
    policy_ref: str | None
    summary: str
    evidence: list[Evidence]
    model: ModelCall | None
    confidence: float | None
    """Probability that the final decision of the item is right (0-1); set on ``DECIDE`` events."""
    duration_ms: int


class Recommendation(TypedDict, total=False):
    decision: str
    reasons: list[str]


class AttentionItem(TypedDict, total=False):
    """What the engine hands to a person."""

    attention_id: Required[str]
    item: Required[str]
    kind: Required[AttentionKind]
    priority: Required[Priority]
    title: str
    impact: int
    """Cents, local currency."""
    affects_tb: bool
    policy_ref: str | None
    recommendation: Recommendation
    alternatives: list[dict[str, object]]
    suggested_action: str


class Override(TypedDict, total=False):
    """A human correction. Identifies the attention item or the item it corrects."""

    attention_id: str
    item: str
    decision: Required[str]
    note: str
    user: str
    ts: Required[str]


class TaskTiming(TypedDict, total=False):
    started_at: str
    finished_at: str


class ModelUsage(TypedDict, total=False):
    provider: str
    name: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


class RunManifest(TypedDict, total=False):
    run_id: Required[str]
    dataset: str
    """Phase name the run closed."""
    month: str
    status: Literal["running", "completed", "failed"]
    exit_code: int
    started_at: str
    finished_at: str
    runtime_s: float
    models: list[ModelUsage]
    cost_usd_total: float
    agent_version: str
    policies_sha256: str
    tasks: dict[str, TaskTiming]
    human_overrides: int
    deliverables: NotRequired[dict[str, dict[str, object]]]
    """Added by the closer: ``{module: {present, rows}}``."""
    error: NotRequired[str]
