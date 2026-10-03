"""Shapes returned by the use cases. Domain rows reuse ``kalmora.model``."""
from typing import Any, Literal, NotRequired, TypedDict

SCHEMA_VERSION = 1


class SourceRef(TypedDict):
    path: str
    sha256: str


class Meta(TypedDict, total=False):
    schema_version: int
    phase: str
    month: str
    package_id: str
    sources: list[SourceRef]


class Envelope(TypedDict):
    data: Any
    meta: Meta


class Page(TypedDict):
    items: list[Any]
    total: int
    next_cursor: str | None
    truncated: bool


class LoadCounts(TypedDict):
    companies: int
    journal_entries: int
    balance_accounts: int
    open_item_keys: int
    document_messages: int
    bank_lines: int


class LoadIssue(TypedDict):
    code: str
    severity: Literal["info", "warning"]
    detail: str
    ref: NotRequired[str]


class LoadReport(TypedDict):
    phase: str
    counts: LoadCounts
    issues: list[LoadIssue]


class PhaseSummary(TypedDict):
    phase: str
    month: str
    package_id: str
    status: Literal["loaded", "loading", "failed"]
    has_golden: bool
    counts: LoadCounts
    tasks: list[str]
    load_report: NotRequired[LoadReport]


class PackageRecord(TypedDict):
    package_id: str
    registered_at: str
    file_count: int
    phases: list[dict[str, str]]
    files: NotRequired[list[dict[str, Any]]]


class JobPhase(TypedDict):
    phase: str
    month: str
    status: Literal["pending", "loading", "loaded", "failed"]


class Job(TypedDict):
    job_id: str
    package_id: str
    status: Literal["received", "extracted", "inventoried", "loaded", "failed"]
    started_at: str
    ended_at: str | None
    phases: list[JobPhase]
    error: dict[str, str] | None
    load_reports: list[LoadReport]
