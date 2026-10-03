"""FastAPI application: translates HTTP to use-case calls and back. No logic lives here."""
import json
import shutil
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, Body, Depends, FastAPI, File, Query, Request, UploadFile
from fastapi.dependencies.utils import get_flat_dependant
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..app.container import Services
from ..app.errors import DomainError

STATUS = {
    "request.invalid": 400, "page.cursor_invalid": 400, "package.unsafe_archive": 400,
    "package.invalid_archive": 400, "package.invalid": 400,
    "phase.not_found": 404, "package.not_found": 404, "job.not_found": 404, "record.not_found": 404,
    "task.not_found": 404, "entry.not_found": 404, "document.not_found": 404, "run.not_found": 404,
    "bank_account.not_found": 404, "fx_rate.not_found": 404, "submission.not_found": 404, "route.not_found": 404,
    "file.not_found": 404,
    "phase.not_loaded": 409, "ingestion.busy": 409, "phase.conflict": 409,
    "golden.forbidden": 403, "evaluation.unavailable": 404, "evaluation.failed": 500,
    "upload.too_large": 413, "entry.invalid": 422, "submission.invalid": 422, "method.not_allowed": 405,
    "internal": 500,
}
ORIGIN_REGEX = r"https?://(localhost|127\.0\.0\.1)(:\d+)?"
COLLECTIONS = ("companies", "accounts", "cost-centers", "vendors", "customers", "projects", "tax-codes")


class ApiResponse(JSONResponse):
    """JSON that renders ``Decimal`` as a string, so rates never pass through a float."""
    media_type = "application/json"

    def render(self, content: Any) -> bytes:
        return json.dumps(content, ensure_ascii=False, allow_nan=False, separators=(",", ":"),
                          default=_default).encode("utf-8")


def _default(value: object) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def problem(request: Request, code: str, title: str, detail: str, diagnostics: list[str] | None = None,
            status: int | None = None) -> JSONResponse:
    status = status or STATUS.get(code, 400)
    body = {"type": f"https://kalmora.example/problems/{code}", "title": title, "status": status,
            "code": code, "detail": detail, "instance": request.url.path, "diagnostics": diagnostics or []}
    return JSONResponse(body, status_code=status, media_type="application/problem+json")


def strict_query(request: Request) -> None:
    """Reject query parameters the route does not declare."""
    route = request.scope.get("route")
    if route is None:
        return
    allowed = {p.alias for p in get_flat_dependant(route.dependant).query_params}
    unknown = sorted(set(request.query_params) - allowed)
    if unknown:
        raise DomainError("request.invalid", f"Unknown query parameter(s): {', '.join(unknown)}.")


class Paging:
    def __init__(self, limit: int | None = Query(None), cursor: str | None = Query(None)) -> None:
        self.limit, self.cursor = limit, cursor


def create_app(services: Services) -> FastAPI:
    api = FastAPI(title="Kalmora close API", version="1", default_response_class=ApiResponse,
                  dependencies=[Depends(strict_query)], docs_url="/v1/docs", openapi_url="/v1/openapi.json",
                  redoc_url=None)
    origins = list(services.settings.cors_origins)
    api.add_middleware(CORSMiddleware, allow_origins=origins, allow_origin_regex=None if origins else ORIGIN_REGEX,
                       allow_methods=["GET", "POST"], allow_headers=["*"])

    @api.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError) -> JSONResponse:
        return problem(request, exc.code, exc.code.replace(".", " ").replace("_", " ").capitalize(),
                       exc.detail, exc.diagnostics)

    @api.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        found = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
        return problem(request, "request.invalid", "Invalid request", "The request is malformed.", found)

    @api.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "route.not_found" if exc.status_code == 404 else "method.not_allowed" if exc.status_code == 405 else "request.invalid"
        return problem(request, code, str(exc.detail), str(exc.detail), status=exc.status_code)

    @api.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        return problem(request, "internal", "Internal error", f"{type(exc).__name__}: {exc}")

    def raw(result: Any) -> Any:
        """Raw file or ``[{path, size}]`` index, without the envelope: clients parse the files."""
        return FileResponse(result) if isinstance(result, Path) else ApiResponse(result)

    def call(function: Any, *args: Any, **kwargs: Any) -> Any:
        return function(*args, **kwargs)

    # health ---------------------------------------------------------------
    @api.get("/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # ingestion --------------------------------------------------------------
    @api.post("/v1/packages")
    async def upload_package(background: BackgroundTasks, archive: UploadFile = File(...)) -> Any:
        uploads = services.settings.data_dir / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        limit = services.settings.max_upload_bytes
        with tempfile.NamedTemporaryFile(dir=uploads, suffix=".zip", delete=False) as handle:
            temp, size = Path(handle.name), 0
            while chunk := await archive.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    handle.close()
                    temp.unlink(missing_ok=True)
                    raise DomainError("upload.too_large", f"Upload exceeds {limit // (1024 * 1024)} MB.")
                handle.write(chunk)
        try:
            envelope, created = await run_in_threadpool(services.ingest.start, temp)
        finally:
            temp.unlink(missing_ok=True)
        if created:
            background.add_task(services.ingest.run, envelope["data"]["job_id"])
        return ApiResponse(envelope, status_code=202 if created else 200, background=background)

    @api.get("/v1/packages")
    def packages(paging: Paging = Depends()) -> Any:
        return services.list_packages(paging.limit, paging.cursor)

    @api.get("/v1/packages/{package_id}")
    def package(package_id: str) -> Any:
        return services.get_package(package_id)

    @api.get("/v1/jobs/{job_id}")
    def job(job_id: str) -> Any:
        return services.get_job(job_id)

    # phases ---------------------------------------------------------------
    @api.get("/v1/phases")
    def phases() -> Any:
        return services.list_phases()

    @api.get("/v1/phases/{phase}")
    def phase(phase: str) -> Any:
        return services.get_phase(phase)

    def register_collection(name: str) -> None:
        @api.get(f"/v1/phases/{{phase}}/{name}", name=f"list_{name}")
        def listing(phase: str, company: str | None = None, q: str | None = None, type: str | None = None,
                    open_items: bool | None = None, prefix: str | None = None, paging: Paging = Depends()) -> Any:
            return services.list_records(phase, name, company=company, q=q, type=type, open_items=open_items,
                                         prefix=prefix, limit=paging.limit, cursor=paging.cursor)

        @api.get(f"/v1/phases/{{phase}}/{name}/{{record_id}}", name=f"get_{name}")
        def single(phase: str, record_id: str) -> Any:
            return services.get_record(phase, name, record_id)

    for collection in COLLECTIONS:
        register_collection(collection)

    @api.get("/v1/phases/{phase}/tasks")
    def tasks(phase: str) -> Any:
        return services.list_tasks(phase)

    @api.get("/v1/phases/{phase}/tasks/{task}")
    def task(phase: str, task: str) -> Any:
        return services.get_task(phase, task)

    @api.get("/v1/phases/{phase}/documents")
    def documents(phase: str, kind: str | None = None, paging: Paging = Depends()) -> Any:
        return services.list_documents(phase, kind=kind, limit=paging.limit, cursor=paging.cursor)

    @api.get("/v1/phases/{phase}/documents/{doc_id}")
    def document(phase: str, doc_id: str) -> Any:
        return services.get_document(phase, doc_id)

    # accounting -----------------------------------------------------------
    @api.get("/v1/phases/{phase}/journal-entries")
    def journal_entries(phase: str, company: str | None = None, account: str | None = None,
                        partner: str | None = None, doc_type: str | None = None, source: str | None = None,
                        reference: str | None = None, from_: str | None = Query(None, alias="from"),
                        to: str | None = None, include: str | None = None, paging: Paging = Depends()) -> Any:
        return services.query_journal(phase, company=company, account=account, partner=partner, doc_type=doc_type,
                                      source=source, reference=reference, date_from=from_, date_to=to,
                                      include=include, limit=paging.limit, cursor=paging.cursor)

    @api.get("/v1/phases/{phase}/journal-entries/{entry_id}")
    def journal_entry(phase: str, entry_id: str) -> Any:
        return services.get_journal_entry(phase, entry_id)

    @api.get("/v1/phases/{phase}/journal-lines")
    def journal_lines(phase: str, company: str | None = None, account: str | None = None,
                      partner: str | None = None, doc_type: str | None = None,
                      from_: str | None = Query(None, alias="from"), to: str | None = None,
                      paging: Paging = Depends()) -> Any:
        return services.query_journal_lines(phase, company=company, account=account, partner=partner,
                                            doc_type=doc_type, date_from=from_, date_to=to,
                                            limit=paging.limit, cursor=paging.cursor)

    @api.get("/v1/phases/{phase}/balances")
    def balances(phase: str, company: str | None = None, account: str | None = None,
                 account_prefix: str | None = None, nonzero: bool | None = None, paging: Paging = Depends()) -> Any:
        return services.get_balances(phase, company=company, account=account, account_prefix=account_prefix,
                                     nonzero=nonzero, limit=paging.limit, cursor=paging.cursor)

    @api.get("/v1/phases/{phase}/balances:summary")
    def balance_summary(phase: str, company: str | None = None) -> Any:
        return services.get_balance_summary(phase, company=company)

    @api.get("/v1/phases/{phase}/open-items")
    def open_items(phase: str, company: str | None = None, account: str | None = None,
                   partner: str | None = None, assignment: str | None = None, only_open: bool = True,
                   source: str | None = None, paging: Paging = Depends()) -> Any:
        return services.get_open_items(phase, company=company, account=account, partner=partner,
                                       assignment=assignment, only_open=only_open, source=source,
                                       limit=paging.limit, cursor=paging.cursor)

    # bank and fx ------------------------------------------------------------
    @api.get("/v1/phases/{phase}/bank-accounts")
    def bank_accounts(phase: str, company: str | None = None, paging: Paging = Depends()) -> Any:
        return services.list_bank_accounts(phase, company=company, limit=paging.limit, cursor=paging.cursor)

    @api.get("/v1/phases/{phase}/bank-accounts/{account}/lines")
    def bank_lines(phase: str, account: str, month: str | None = None, from_: str | None = Query(None, alias="from"),
                   to: str | None = None, min_amount: int | None = None, max_amount: int | None = None,
                   q: str | None = None, paging: Paging = Depends()) -> Any:
        return services.get_bank_lines(phase, account, month_=month, date_from=from_, date_to=to,
                                       min_amount=min_amount, max_amount=max_amount, q=q,
                                       limit=paging.limit, cursor=paging.cursor)

    @api.get("/v1/phases/{phase}/fx-rates")
    def fx_rates(phase: str, currency: str | None = None, date: str | None = None,
                 from_: str | None = Query(None, alias="from"), to: str | None = None,
                 paging: Paging = Depends()) -> Any:
        return services.get_fx_rates(phase, currency=currency, date=date, date_from=from_, date_to=to,
                                     limit=paging.limit, cursor=paging.cursor)

    # pure checks ------------------------------------------------------------
    @api.post("/v1/phases/{phase}/entries:validate")
    def validate(phase: str, body: Any = Body(...)) -> Any:
        return services.validate_entry(phase, body)

    @api.post("/v1/phases/{phase}/entries:simulate")
    def simulate(phase: str, body: Any = Body(...)) -> Any:
        return services.simulate_entry(phase, body)

    # runs, submission, evaluation -------------------------------------------
    @api.get("/v1/runs")
    def runs(paging: Paging = Depends()) -> Any:
        return services.list_runs(paging.limit, paging.cursor)

    @api.get("/v1/runs/{run_id}")
    def run(run_id: str) -> Any:
        return services.get_run(run_id)

    @api.get("/v1/runs/{run_id}/files/{path:path}")
    def run_file(run_id: str, path: str) -> Any:
        return raw(services.get_run_file(run_id, path))

    @api.get("/v1/phases/{phase}/files/{path:path}")
    def phase_file(phase: str, path: str) -> Any:
        return raw(services.get_phase_file(phase, path))

    @api.get("/v1/phases/{phase}/submission")
    def submission(phase: str) -> Any:
        return services.get_submission(phase)

    @api.get("/v1/phases/{phase}/submission:check")
    def submission_check(phase: str) -> Any:
        return services.check_submission(phase)

    @api.get("/v1/phases/{phase}/submission/{module}")
    def submission_rows(phase: str, module: str, paging: Paging = Depends()) -> Any:
        return services.list_submission_rows(phase, module, paging.limit, paging.cursor)

    @api.get("/v1/phases/{phase}/evaluation")
    def evaluation(phase: str) -> Any:
        return services.get_evaluation(phase)

    @api.get("/v1/phases/{phase}/evaluation/{module}")
    def evaluation_module(phase: str, module: str) -> Any:
        return services.get_evaluation(phase, module)

    return api
