"""Preserve and inventory organizer packages without executing their contents."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import zipfile


def register_package(archive: Path, destination: Path) -> dict:
    """Extract into a new directory; refuse every existing destination.

    Inventory paths are relative to destination, including participant/. Originals,
    documentation, evaluator and golden files are retained byte for byte.
    """
    archive, destination = Path(archive), Path(destination)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Refusing existing package destination: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".package-", dir=destination.parent))
    try:
        # One immutable snapshot prevents hashes and extracted bytes disagreeing.
        snapshot = staging / ".archive.zip"
        shutil.copyfile(archive, snapshot)
        with snapshot.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        files = []
        seen = set()
        with zipfile.ZipFile(snapshot) as source:
            for member in source.infolist():
                path = PurePosixPath(member.filename)
                if "__MACOSX" in path.parts:
                    continue
                mode = member.external_attr >> 16
                if (path.is_absolute() or ".." in path.parts or "\\" in member.filename
                        or not path.parts or path.parts[0] != "participant"
                        or stat.S_ISLNK(mode)):
                    raise ValueError(f"Unsafe archive member: {member.filename}")
                key = path.as_posix()
                if key in seen:
                    raise ValueError(f"Duplicate archive member: {key}")
                seen.add(key)
                target = staging.joinpath(*path.parts)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open(member) as incoming, target.open("xb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing)
                with target.open("rb") as handle:
                    sha = hashlib.file_digest(handle, "sha256").hexdigest()
                files.append({"path": key, "size": target.stat().st_size, "sha256": sha})
        phases = []
        for close in sorted((staging / "participant").glob("*/tasks/close.json")):
            data = json.loads(close.read_text(encoding="utf-8"))
            month = data.get("month")
            if (not isinstance(month, str) or len(month) != 7 or month[4] != "-"
                    or not month[:4].isdigit() or not month[5:].isdigit()
                    or not 1 <= int(month[5:]) <= 12):
                raise ValueError(f"Invalid close month: {close}")
            phases.append({"phase": close.parent.parent.name, "month": month})
        if not phases:
            raise ValueError("Package contains no phase tasks/close.json")
        manifest = {"schema_version": 1, "archive_sha256": digest,
                    "files": sorted(files, key=lambda item: item["path"]), "phases": phases}
        snapshot.unlink()
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        # mkdir reserves the destination atomically and never replaces old data.
        destination.mkdir()
        try:
            for child in staging.iterdir():
                os.rename(child, destination / child.name)
        except BaseException:
            shutil.rmtree(destination)
            raise
        return manifest
    finally:
        shutil.rmtree(staging)
