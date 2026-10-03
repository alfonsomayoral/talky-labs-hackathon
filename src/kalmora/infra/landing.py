"""``LandingCatalog`` over the DuckDB ``LandingStore`` (optional ``landing`` extra).

``LandingStore`` is single-writer and owner-thread-bound, so every call runs on one dedicated thread
that owns all the stores. A phase's database is built on first use (parsing the bank statements,
inbox items and documents) and verified against the source hashes on later opens.
"""
import threading
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from ..app.errors import DomainError

TABLES = ["source_file", "parse_issue", "task_item", "bank_statement", "bank_line",
          "inbound_item", "document", "document_line"]


class DuckDbLandingCatalog:
    def __init__(self, directory: Path) -> None:
        self._directory = Path(directory)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="landing")
        self._stores: dict[tuple[str, str], Any] = {}
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        try:
            import duckdb  # noqa: F401
            return True
        except ImportError:
            return False

    def tables(self) -> list[str]:
        return list(TABLES)

    def _on_worker(self, function: Callable[[], Any]) -> Any:
        if not self.available:
            raise DomainError("landing.unavailable", "Install the extra: pip install 'kalmora-close[landing]'.")
        try:
            return self._executor.submit(function).result()
        except DomainError:
            raise
        except (RuntimeError, ValueError, KeyError) as exc:
            raise DomainError("landing.failed", f"{type(exc).__name__}: {exc}") from None

    def _store(self, package_id: str, phase: str, phase_dir: Path) -> Any:
        key = (package_id, phase)
        if key not in self._stores:
            from ..landing import LandingStore
            store = LandingStore(self._directory / package_id[:16] / f"{phase}.duckdb")
            try:
                store.import_phase(phase_dir)
            except BaseException:
                store.close()
                raise
            self._stores[key] = store
        return self._stores[key]

    def counts(self, package_id: str, phase: str, phase_dir: Path) -> dict[str, int]:
        return self._on_worker(lambda: self._store(package_id, phase, phase_dir).counts())

    def rows(self, package_id: str, phase: str, phase_dir: Path, table: str,
             criteria: Mapping[str, Any]) -> list[dict[str, Any]]:
        if table not in TABLES:
            raise DomainError("landing.table_not_found", f"Unknown landing table '{table}'. Available: {', '.join(TABLES)}.")

        def query() -> list[dict[str, Any]]:
            store = self._store(package_id, phase, phase_dir)
            try:
                return store.rows(table, **criteria)
            except ValueError as exc:
                if "Unknown query column" in str(exc):
                    raise DomainError("request.invalid", f"Unknown column for {table}.") from None
                raise
            except Exception as exc:  # DuckDB type conversion on a mistyped filter
                numeric = {k: int(v) if isinstance(v, str) and v.lstrip("-").isdigit() else v for k, v in criteria.items()}
                if numeric != dict(criteria):
                    return store.rows(table, **numeric)
                raise DomainError("request.invalid", f"Invalid filter value for {table}: {exc}") from None

        return self._on_worker(query)

    def close(self) -> None:
        def shut() -> None:
            for store in self._stores.values():
                store.close()
            self._stores.clear()
        if self._stores:
            self._executor.submit(shut).result()
        self._executor.shutdown(wait=True)
