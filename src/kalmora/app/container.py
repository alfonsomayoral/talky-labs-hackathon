"""Composition root for the application layer: wires use cases to concrete ports."""
from dataclasses import dataclass
from pathlib import Path

from ..infra.files import FilePackageStore, FileRunStore, FileSubmissionStore
from ..infra.memory import InMemoryJobStore, InMemoryPhaseRepository
from .ports import EvaluationGateway
from .usecases import accounting, banking, catalog, entries, files, ingestion, runs


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path("outputs/data")
    run_dir: Path = Path("outputs/runs")
    submissions_dir: Path = Path("outputs/submissions")
    max_upload_bytes: int = 256 * 1024 * 1024
    cors_origins: tuple[str, ...] = ()


class NoEvaluator:
    """Structure checks are not available either without the evaluator package wired in."""
    enabled = False

    def check_structure(self, rows_by_module):  # type: ignore[no-untyped-def]
        from .errors import DomainError
        raise DomainError("evaluation.unavailable", "No evaluation gateway is configured.")

    def evaluate(self, phase, phase_dir, submission_dir):  # type: ignore[no-untyped-def]
        from .errors import DomainError
        raise DomainError("evaluation.unavailable", "The evaluator is not enabled in this process.")


class Services:
    """Every use case, built once. Adapters (HTTP, MCP, CLI) only call these."""

    def __init__(self, settings: Settings, gateway: EvaluationGateway | None = None) -> None:
        self.settings = settings
        repo = InMemoryPhaseRepository()
        packages = FilePackageStore(settings.data_dir / "packages")
        jobs = InMemoryJobStore()
        run_store = FileRunStore(settings.run_dir)
        submissions = FileSubmissionStore(settings.submissions_dir)
        gateway = gateway or NoEvaluator()
        self.repo = repo
        self.ingest = ingestion.IngestPackage(packages, jobs, repo)
        self.get_job = ingestion.GetJob(jobs)
        self.list_packages = ingestion.ListPackages(packages)
        self.get_package = ingestion.GetPackage(packages)
        self.list_phases = catalog.ListPhases(repo)
        self.get_phase = catalog.GetPhase(repo)
        self.list_records = catalog.ListRecords(repo)
        self.get_record = catalog.GetRecord(repo)
        self.list_tasks = catalog.ListTasks(repo)
        self.get_task = catalog.GetTask(repo)
        self.list_documents = catalog.ListDocuments(repo)
        self.get_document = catalog.GetDocument(repo)
        self.query_journal = accounting.QueryJournalEntries(repo)
        self.get_journal_entry = accounting.GetJournalEntry(repo)
        self.query_journal_lines = accounting.QueryJournalLines(repo)
        self.get_balances = accounting.GetBalances(repo)
        self.get_balance_summary = accounting.GetBalanceSummary(repo)
        self.get_open_items = accounting.GetOpenItems(repo)
        self.list_bank_accounts = banking.ListBankAccounts(repo)
        self.get_bank_lines = banking.GetBankLines(repo)
        self.get_fx_rates = banking.GetFxRates(repo)
        self.validate_entry = entries.ValidateEntry(repo)
        self.simulate_entry = entries.SimulateEntry(repo)
        self.list_runs = runs.ListRuns(run_store)
        self.get_run = runs.GetRun(run_store)
        self.get_run_file = files.GetRunFile(run_store)
        self.get_phase_file = files.GetPhaseFile(repo)
        self.get_submission = runs.GetSubmission(repo, submissions)
        self.list_submission_rows = runs.ListSubmissionRows(repo, submissions)
        self.check_submission = runs.CheckSubmission(repo, submissions, gateway)
        self.get_evaluation = runs.GetEvaluation(repo, submissions, gateway)
