import hashlib
import threading
from datetime import datetime, timezone
from pathlib import Path
from zipfile import BadZipFile

from ..errors import DomainError
from ..paging import paginate
from ..params import valid_phase_name
from ..ports import JobStore, PackageStore, PhaseRepository
from ..types import Envelope
from . import plain_envelope


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


class IngestPackage:
    """Register an organizer ZIP (``start``) and load its phases (``run``).

    Extraction is synchronous so a bad archive fails the request immediately; loading is the
    slow part and runs as a job. One ingestion at a time.
    """

    def __init__(self, packages: PackageStore, jobs: JobStore, repo: PhaseRepository) -> None:
        self._packages, self._jobs, self._repo = packages, jobs, repo
        self._lock = threading.Lock()

    def _loaded(self, package_id: str) -> bool:
        phases = self._packages.manifest(package_id)["phases"]
        for item in phases:
            try:
                if self._repo.phase(item["phase"])["package_id"] != package_id:
                    return False
            except DomainError:
                return False
        return True

    def start(self, archive: Path) -> tuple[Envelope, bool]:
        """Return the response and whether a new job was created (False = already registered)."""
        package_id = sha256_file(archive)
        with self._lock:
            busy = self._jobs.active()
            if busy is not None:
                raise DomainError("ingestion.busy", f"Job {busy['job_id']} is still running.")
            existing = self._packages.get(package_id)
            if existing is not None and self._loaded(package_id):
                previous = self._jobs.latest_for(package_id)
                return plain_envelope({"package_id": package_id, "already_registered": True,
                                       "job_id": previous["job_id"] if previous else None,
                                       "status": previous["status"] if previous else "loaded"}), False
            job = self._jobs.create(package_id)
            try:
                if existing is None:
                    try:
                        manifest = self._packages.register(archive, package_id)
                    except BadZipFile as exc:
                        raise DomainError("package.invalid_archive", str(exc)) from None
                    except FileExistsError as exc:
                        raise DomainError("package.invalid_archive", str(exc)) from None
                    except ValueError as exc:
                        unsafe = "Unsafe" in str(exc) or "Duplicate" in str(exc)
                        raise DomainError("package.unsafe_archive" if unsafe else "package.invalid", str(exc)) from None
                else:
                    manifest = self._packages.manifest(package_id)
                bad = [p["phase"] for p in manifest["phases"] if not valid_phase_name(p["phase"])]
                if bad:
                    raise DomainError("package.invalid", f"Phase folder name(s) not allowed: {', '.join(bad)}. "
                                      "Use letters, digits, '_', '.' or '-', not starting with '-' or '.'.")
                self._jobs.update(job["job_id"], status="extracted")
                phases = [{"phase": p["phase"], "month": p["month"], "status": "pending"} for p in manifest["phases"]]
                self._jobs.update(job["job_id"], status="inventoried", phases=phases)
            except DomainError as exc:
                self._jobs.update(job["job_id"], status="failed", ended_at=_now(),
                                  error={"code": exc.code, "detail": exc.detail})
                raise
        return plain_envelope({"package_id": package_id, "job_id": job["job_id"],
                               "status": "inventoried", "already_registered": False}), True

    def run(self, job_id: str) -> None:
        """Load every phase of the job's package; never raises, failures land in the job."""
        job = self._jobs.get(job_id)
        package_id = job["package_id"]
        manifest, root = self._packages.manifest(package_id), self._packages.root(package_id)
        phases, reports = [dict(p) for p in job["phases"]], []
        try:
            for item in phases:
                item["status"] = "loading"
                self._repo.mark(item["phase"], package_id, "loading")
                self._jobs.update(job_id, phases=[dict(p) for p in phases])
                try:
                    reports.append(self._repo.load_phase(package_id, root / "participant" / item["phase"], manifest))
                except BaseException:
                    item["status"] = "failed"
                    self._repo.mark(item["phase"], package_id, "failed")
                    raise
                item["status"] = "loaded"
                self._repo.mark(item["phase"], package_id, "loaded")
            self._jobs.update(job_id, status="loaded", ended_at=_now(), phases=phases, load_reports=reports)
        except DomainError as exc:
            self._jobs.update(job_id, status="failed", ended_at=_now(), phases=phases,
                              error={"code": exc.code, "detail": exc.detail})
        except Exception as exc:  # noqa: BLE001 - the job records any loading failure
            self._jobs.update(job_id, status="failed", ended_at=_now(), phases=phases,
                              error={"code": "load.failed", "detail": f"{type(exc).__name__}: {exc}"})

    def restore(self) -> int:
        """Reload every package already on disk (memory is a cache). Returns packages restored."""
        count = 0
        for record in self._packages.list():
            package_id = record["package_id"]
            job = self._jobs.create(package_id)
            phases = [{"phase": p["phase"], "month": p["month"], "status": "pending"} for p in record["phases"]]
            self._jobs.update(job["job_id"], status="inventoried", phases=phases)
            self.run(job["job_id"])
            count += 1
        return count


class GetJob:
    def __init__(self, jobs: JobStore) -> None:
        self._jobs = jobs

    def __call__(self, job_id: str) -> Envelope:
        return plain_envelope(self._jobs.get(job_id))


class ListPackages:
    def __init__(self, packages: PackageStore) -> None:
        self._packages = packages

    def __call__(self, limit: int | None, cursor: str | None) -> Envelope:
        records = sorted(self._packages.list(), key=lambda r: r["registered_at"], reverse=True)
        return plain_envelope(paginate(records, limit, cursor, "packages"))


class GetPackage:
    def __init__(self, packages: PackageStore) -> None:
        self._packages = packages

    def __call__(self, package_id: str) -> Envelope:
        record = self._packages.get(package_id)
        if record is None:
            raise DomainError("package.not_found", f"No package '{package_id}'.")
        return plain_envelope({**record, "files": list(self._packages.manifest(package_id)["files"])})
