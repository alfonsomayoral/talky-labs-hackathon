"""Composition root for the application layer: wires use cases to concrete ports."""
from dataclasses import dataclass
from pathlib import Path

from ..infra.closer import CommandCloser
from ..infra.checker import StructureChecker
from ..infra.files import FilePackageStore, FileRunStore, FileSubmissionStore
from ..infra.landing import DuckDbLandingCatalog
from ..infra.memory import InMemoryJobStore, InMemoryPhaseRepository
from .ports import EvaluationGateway
from .usecases import accounting, banking, bundles, catalog, entries, files, ingestion, landing, runs


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path("outputs/data")
    run_dir: Path = Path("outputs/runs")
    submissions_dir: Path = Path("outputs/submissions")
    max_upload_bytes: int = 256 * 1024 * 1024
    cors_origins: tuple[str, ...] = ()
    serve_golden: bool = False
    close_command: tuple[str, ...] = ()


class NoEvaluator:
    """Scoring is off unless the composition root wires the evaluator gateway in."""
    enabled = False

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
        run_deliverables = FileSubmissionStore(settings.run_dir, "deliverables")
        checker = StructureChecker()
        self.landing_catalog = DuckDbLandingCatalog(settings.data_dir / "landing")
        gateway = gateway or NoEvaluator()
        self.evaluation_enabled = gateway.enabled
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
        self.get_run = runs.GetRun(run_store, run_deliverables)
        closer = CommandCloser(settings.close_command, settings.run_dir) if settings.close_command else None
        self.closer = closer
        self.start_run = runs.StartRun(repo, closer)
        self.get_run_file = files.GetRunFile(run_store)
        self.get_phase_file = files.GetPhaseFile(repo, settings.serve_golden)
        self.get_submission = runs.GetSubmission(repo, submissions)
        self.list_submission_rows = runs.ListSubmissionRows(repo, submissions)
        self.check_submission = runs.CheckSubmission(repo, submissions, checker)
        self.get_evaluation = runs.GetEvaluation(repo, submissions, gateway)
        self.list_attachments = catalog.ListAttachments(repo)
        self.get_policies = catalog.GetPolicies(repo)
        self.summarize_run = bundles.SummarizeRun(run_store, run_deliverables)
        self.calculate = bundles.Calculate()
        self.get_landing = landing.GetLanding(repo, self.landing_catalog)
        self.query_landing = landing.QueryLanding(repo, self.landing_catalog)
        self.get_run_submission = bundles.GetRunSubmission(run_store, run_deliverables)
        self.list_run_submission_rows = bundles.ListRunSubmissionRows(run_store, run_deliverables)
        self.check_run_submission = bundles.CheckRunSubmission(run_store, run_deliverables, checker)
        self.get_run_evaluation = bundles.GetRunEvaluation(run_store, repo, run_deliverables, gateway)
        self.list_run_events = bundles.ListRunEvents(run_store)
        self.list_run_attention = bundles.ListRunAttention(run_store)
        self.get_run_item = bundles.GetRunItem(run_store, run_deliverables)
        self.add_override = bundles.AddOverride(run_store)
        self.list_overrides = bundles.ListOverrides(run_store)

    def recover_runs(self) -> int:
        """Close runs a previous server left ``running``. Returns how many."""
        return self.closer.recover() if self.closer is not None else 0

    def close(self) -> None:
        self.landing_catalog.close()
