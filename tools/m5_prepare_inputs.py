#!/usr/bin/env python3
"""Create a solver-only copy without opening reference/scorer members.

The original ZIP is hash-identified and unchanged. This preparation step is not
an AP extractor; the solver itself only uses PhaseData's existing readers.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import zipfile


def prepare(archive: Path, destination: Path) -> dict:
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("Refusing to overwrite an existing input directory")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".m5-inputs-", dir=destination.parent))
    try:
        snapshot = staging / ".original.zip"
        shutil.copyfile(archive, snapshot)
        with snapshot.open("rb") as stream:
            package_hash = hashlib.file_digest(stream, "sha256").hexdigest()
        manifest = {"schema_version": 1, "archive_sha256": package_hash,
                    "role": "solver-only", "excluded_areas": ["golden", "score.py"], "files": []}
        seen = set()
        with zipfile.ZipFile(snapshot) as source:
            if sum(member.file_size for member in source.infolist()) > 512 * 1024 * 1024:
                raise ValueError("Input package exceeds the 512 MiB preparation limit")
            for member in source.infolist():
                name = PurePosixPath(member.filename)
                if "__MACOSX" in name.parts:
                    continue
                if (name.is_absolute() or ".." in name.parts or "\\" in member.filename
                        or not name.parts or name.parts[0] != "participant"
                        or stat.S_ISLNK(member.external_attr >> 16)):
                    raise ValueError(f"Unsafe archive member: {member.filename}")
                if name.as_posix() in seen:
                    raise ValueError(f"Duplicate archive member: {name}")
                seen.add(name.as_posix())
                if "golden" in name.parts or name.name == "score.py" or member.is_dir():
                    continue  # Crucially, never source.open/read these members.
                target = staging.joinpath(*name.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open(member) as incoming, target.open("xb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing)
                with target.open("rb") as stream:
                    manifest["files"].append({"path": name.as_posix(), "size": target.stat().st_size,
                                              "sha256": hashlib.file_digest(stream, "sha256").hexdigest()})
        if not list((staging / "participant").glob("*/tasks/close.json")):
            raise ValueError("Package has no phase task inventory")
        manifest["files"].sort(key=lambda row: row["path"])
        snapshot.unlink()
        (staging / "solver-input-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        destination.mkdir()  # Reserve without replacing any concurrently created directory.
        for child in staging.iterdir():
            os.rename(child, destination / child.name)
        return manifest
    finally:
        shutil.rmtree(staging)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = prepare(args.package, args.out)
    print(json.dumps({"archive_sha256": report["archive_sha256"], "files": len(report["files"]), "out": str(args.out)}))
