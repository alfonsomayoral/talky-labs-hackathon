"""MCP server over the application use cases.

Read-only on purpose: no tool uploads a package, starts a run or records an override, so an agent can
inspect the books, the inbox and the runs but cannot change them. Tool output is the same
``{data, meta}`` envelope as the HTTP API. Lists are capped at 100 rows per call.
"""
import json
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from ..app.container import Services
from ..app.errors import DomainError

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
DEFAULT_LIMIT, MAX_LIMIT = 25, 100


def _limit(limit: int | None) -> int:
    return min(max(limit or DEFAULT_LIMIT, 1), MAX_LIMIT)


def create_server(services: Services, *, stateless: bool = False) -> FastMCP:
    """``stateless=True`` is for serving over HTTP (no protocol session; JSON responses)."""
    server = FastMCP("kalmora", stateless_http=stateless, json_response=stateless, instructions=(
        "Read-only access to the Kalmora month-end close: the loaded phases (ERP, bank, inbox), the books "
        "(journal, balances, open items) and the runs that closed a month. Amounts are integer cents in the "
        "company's local currency. Every list is paginated: pass next_cursor back as cursor. Prefer get_balances "
        "and get_open_items over paging the journal to answer a total."))

    def phase_of(phase: str | None) -> str:
        if phase:
            return phase
        loaded = [p["phase"] for p in services.list_phases()["data"]]
        if len(loaded) == 1:
            return loaded[0]
        raise ToolError(json.dumps({"code": "request.invalid", "detail":
                                    "phase is required: " + (", ".join(loaded) if loaded else "no phase is loaded yet")}))

    def run(function: Callable[..., Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return function(*args, **kwargs)  # type: ignore[no-any-return]
        except DomainError as exc:
            raise ToolError(json.dumps({"code": exc.code, "detail": exc.detail, "diagnostics": exc.diagnostics})) from None

    def tool(function: Callable[..., Any]) -> Callable[..., Any]:
        return server.tool(annotations=READ_ONLY)(function)

    # catalogue --------------------------------------------------------------
    @tool
    def list_phases() -> dict[str, Any]:
        """Loaded phases with month, record counts and whether a golden exists."""
        return run(services.list_phases)

    @tool
    def get_phase(phase: str | None = None) -> dict[str, Any]:
        """One phase with its load report (consistency findings of the loaded data)."""
        return run(services.get_phase, phase_of(phase))

    @tool
    def get_policies(phase: str | None = None) -> dict[str, Any]:
        """The accounting policies of the package the phase came with (Spanish, verbatim), their sha256 and an index
        of section references (§2.2.3, §4:BANK_FEE_NOT_BOOKED) that answers may cite."""
        return run(services.get_policies, phase_of(phase))

    @tool
    def calculate(op: str, values: list[int], rounding: str = "half_up") -> dict[str, Any]:
        """Exact integer arithmetic. op: sum, difference (first minus second), percent_bp ([part, whole] in basis points),
        apply_rate_bp ([amount, basis_points]), count. Use it instead of computing money yourself."""
        return run(services.calculate, op, values, rounding)

    @tool
    def list_records(table: str, phase: str | None = None, company: str | None = None, q: str | None = None,
                     prefix: str | None = None, limit: int | None = None, cursor: str | None = None) -> dict[str, Any]:
        """Master data. table: companies, accounts, cost-centers, vendors, customers, projects, tax-codes.
        company filters cost-centers, vendors, customers and projects; q is a name substring; prefix filters accounts."""
        return run(services.list_records, phase_of(phase), table, company=company, q=q, prefix=prefix,
                   limit=_limit(limit), cursor=cursor)

    @tool
    def get_record(table: str, record_id: str, phase: str | None = None) -> dict[str, Any]:
        """One master record by id (company code, account, vendor id, customer id, project id, tax code)."""
        return run(services.get_record, phase_of(phase), table, record_id)

    @tool
    def get_task(task: str, phase: str | None = None) -> dict[str, Any]:
        """Work queue of the phase: ap_documents, ar_billing_items, ar_receipts, bank_accounts, intercompany or close."""
        return run(services.get_task, phase_of(phase), task)

    @tool
    def list_documents(phase: str | None = None, kind: str | None = None, limit: int | None = None,
                       cursor: str | None = None) -> dict[str, Any]:
        """Inbox messages (kind ap or ar) with channel, received time and attachment names."""
        return run(services.list_documents, phase_of(phase), kind=kind, limit=_limit(limit), cursor=cursor)

    @tool
    def get_document(doc_id: str, phase: str | None = None) -> dict[str, Any]:
        """One inbox message, plus its attachment files with sizes and sha256."""
        phase = phase_of(phase)
        message = run(services.get_document, phase, doc_id)
        message["data"] = {**message["data"], "attachment_files": run(services.list_attachments, phase, doc_id)["data"]["attachments"]}
        return message

    @tool
    def landing_rows(table: str, filters: dict[str, str] | None = None, phase: str | None = None,
                     limit: int | None = None, cursor: str | None = None) -> dict[str, Any]:
        """Normalized landing tables: source_file, parse_issue, task_item, bank_statement, bank_line, inbound_item,
        document, document_line. filters are equality on the table's columns. First use builds the phase's database."""
        return run(services.query_landing, phase_of(phase), table, filters or {}, _limit(limit), cursor)

    # accounting -------------------------------------------------------------
    @tool
    def query_journal(phase: str | None = None, company: str | None = None, account: str | None = None,
                      partner: str | None = None, doc_type: str | None = None, source: str | None = None,
                      reference: str | None = None, date_from: str | None = None, date_to: str | None = None,
                      header_only: bool = True, limit: int | None = None, cursor: str | None = None) -> dict[str, Any]:
        """Journal entries (YYYY-MM-DD dates). header_only omits the lines; set it false to see them."""
        return run(services.query_journal, phase_of(phase), company=company, account=account, partner=partner,
                   doc_type=doc_type, source=source, reference=reference, date_from=date_from, date_to=date_to,
                   include="header" if header_only else "lines", limit=_limit(limit), cursor=cursor)

    @tool
    def get_journal_entry(entry_id: str, phase: str | None = None) -> dict[str, Any]:
        """One journal entry with its lines and book_line references."""
        return run(services.get_journal_entry, phase_of(phase), entry_id)

    @tool
    def get_balances(phase: str | None = None, company: str | None = None, account: str | None = None,
                     account_prefix: str | None = None, nonzero: bool | None = None, limit: int | None = None,
                     cursor: str | None = None) -> dict[str, Any]:
        """Balance (debit minus credit, in cents) of ONE account or a group of accounts, per company: use account for one account or
        account_prefix (e.g. 572) for a group. This is the tool for 'what is the balance of account X'."""
        return run(services.get_balances, phase_of(phase), company=company, account=account,
                   account_prefix=account_prefix, nonzero=nonzero, limit=_limit(limit), cursor=cursor)

    @tool
    def get_balance_summary(phase: str | None = None, company: str | None = None) -> dict[str, Any]:
        """Total debit, credit and net of ALL the entries of a company, to check the books are balanced (net is always 0). It is NOT the
        balance of an account: for an account use get_balances."""
        return run(services.get_balance_summary, phase_of(phase), company=company)

    @tool
    def get_open_items(phase: str | None = None, company: str | None = None, account: str | None = None,
                       partner: str | None = None, assignment: str | None = None, only_open: bool = True,
                       source: str | None = None, limit: int | None = None, cursor: str | None = None) -> dict[str, Any]:
        """Open items per (company, account, partner, assignment). source: ledger (computed) or master (ERP snapshot)."""
        return run(services.get_open_items, phase_of(phase), company=company, account=account, partner=partner,
                   assignment=assignment, only_open=only_open, source=source, limit=_limit(limit), cursor=cursor)

    @tool
    def list_bank_accounts(phase: str | None = None, company: str | None = None) -> dict[str, Any]:
        """Bank accounts with their ledger account and the months of statements available."""
        return run(services.list_bank_accounts, phase_of(phase), company=company, limit=MAX_LIMIT)

    @tool
    def get_bank_lines(account: str, phase: str | None = None, month: str | None = None, date_from: str | None = None,
                       date_to: str | None = None, min_amount: int | None = None, max_amount: int | None = None,
                       q: str | None = None, limit: int | None = None, cursor: str | None = None) -> dict[str, Any]:
        """Statement lines of a bank account. amount is signed cents: positive money in, negative out."""
        return run(services.get_bank_lines, phase_of(phase), account, month_=month, date_from=date_from,
                   date_to=date_to, min_amount=min_amount, max_amount=max_amount, q=q, limit=_limit(limit), cursor=cursor)

    @tool
    def get_fx_rate(currency: str, date: str, phase: str | None = None) -> dict[str, Any]:
        """Units of currency per 1 EUR on a date (the latest rate on or before it)."""
        return run(services.get_fx_rates, phase_of(phase), currency=currency, date=date, limit=1)

    @tool
    def validate_entry(entry: dict[str, Any], phase: str | None = None, with_masters: bool = True) -> dict[str, Any]:
        """Check a candidate journal entry against the accounting rules and the phase's master data. Stores nothing."""
        return run(services.validate_entry, phase_of(phase), {"entry": entry, "with_masters": with_masters})

    @tool
    def simulate_entry(entry: dict[str, Any], event_id: str, stage: str, phase: str | None = None) -> dict[str, Any]:
        """Show how a journal entry would change balances and open items. Works on a copy; nothing is stored."""
        return run(services.simulate_entry, phase_of(phase), {"entry": entry, "provenance": {"event_id": event_id, "stage": stage}})

    # ingestion, runs and bundles --------------------------------------------
    @tool
    def list_packages(limit: int | None = None, cursor: str | None = None) -> dict[str, Any]:
        """Registered organizer packages."""
        return run(services.list_packages, _limit(limit), cursor)

    @tool
    def get_job(job_id: str) -> dict[str, Any]:
        """Status of a package load, with its load reports."""
        return run(services.get_job, job_id)

    @tool
    def list_runs(limit: int | None = None, cursor: str | None = None) -> dict[str, Any]:
        """Runs, newest first, with status, month, phase (dataset) and whether they have files."""
        return run(services.list_runs, _limit(limit), cursor)

    @tool
    def get_run(run_id: str) -> dict[str, Any]:
        """A run's manifest or report, with a summary of its deliverables."""
        return run(services.get_run, run_id)

    @tool
    def get_run_deliverables(run_id: str, module: str | None = None, limit: int | None = None,
                             cursor: str | None = None) -> dict[str, Any]:
        """Without module: which of the six delivery files the run wrote and how many rows each has (use this for 'what was delivered').
        With module (ap, ar_billing, ar_cash, bank_rec, ic, close): the rows of that file."""
        if module is None:
            return run(services.get_run_submission, run_id)
        return run(services.list_run_submission_rows, run_id, module, _limit(limit), cursor)

    @tool
    def check_run_deliverables(run_id: str) -> dict[str, Any]:
        """Structure problems in a run's delivery files, row by row."""
        return run(services.check_run_submission, run_id)

    @tool
    def summarize_run(run_id: str) -> dict[str, Any]:
        """Counts and totals over a run's delivered files and trace: rows per task, AP decisions and reasons, bank
        categories, intragroup causes, close types, attention by priority. Totals are per company, never mixed.
        Prefer this to paging deliverable rows."""
        return run(services.summarize_run, run_id)

    @tool
    def list_run_events(run_id: str, item: str | None = None, kind: str | None = None, result: str | None = None,
                        step: str | None = None, limit: int | None = None, cursor: str | None = None) -> dict[str, Any]:
        """Steps the run took. item is '<task>:<key>', e.g. ap:API004151. kind: EXTRACT CHECK MATCH CLASSIFY ESTIMATE DECIDE POST MODEL_CALL."""
        return run(services.list_run_events, run_id, item=item, kind=kind, result=result, step=step,
                   limit=_limit(limit), cursor=cursor)

    @tool
    def list_run_attention(run_id: str, item: str | None = None, kind: str | None = None, priority: str | None = None,
                           limit: int | None = None, cursor: str | None = None) -> dict[str, Any]:
        """What the run handed to a person, most urgent first (P0 to P3). Call it without filters first; priority only narrows the list."""
        return run(services.list_run_attention, run_id, item=item, kind=kind, priority=priority,
                   limit=_limit(limit), cursor=cursor)

    @tool
    def get_run_item(run_id: str, item: str) -> dict[str, Any]:
        """Everything a run knows about one item: its delivered row, trace events, attention items and overrides."""
        return run(services.get_run_item, run_id, item)

    @tool
    def list_overrides(run_id: str, limit: int | None = None, cursor: str | None = None) -> dict[str, Any]:
        """Human corrections recorded on a run."""
        return run(services.list_overrides, run_id, _limit(limit), cursor)

    if services.evaluation_enabled:
        @tool
        def get_run_evaluation(run_id: str, module: str | None = None) -> dict[str, Any]:
            """Score a run against the golden (development phases only)."""
            return run(services.get_run_evaluation, run_id, module)

    return server
