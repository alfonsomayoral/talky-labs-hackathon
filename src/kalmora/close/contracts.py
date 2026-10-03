"""Versioned M1–M5 handoffs; no producer implementation or document extraction.

Both real producers and the development fixture builder must emit this exact
contract. Hashes bind facts and coverage to a phase, not to a particular adapter.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from ..data import load_json
from ..facts import DocumentFacts
from .rules import month_bounds

SCHEMA = "kalmora.close.dependencies/v1"
PRODUCERS = ("ap", "ar_billing", "bank_rec", "ar_cash", "ic")


def encoded(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
                       default=lambda x: str(x) if isinstance(x, Decimal) else _unsupported(x)) + "\n").encode()


def _unsupported(value: Any) -> Any:
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def digest(value: Any) -> str:
    return sha256(encoded(value)).hexdigest()


def file_hash(path: Path) -> str:
    h = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _hash(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def seal(bundle: dict) -> dict:
    """Seal the complete payload, including coverage, evidence and financial facts."""
    result = dict(bundle)
    result.pop("payload_sha256", None)
    result["payload_sha256"] = digest(result)
    return result


@dataclass(frozen=True)
class Handoff:
    """Validated handoff snapshot. Caller receives a private deep JSON copy."""

    payload: dict

    @classmethod
    def from_dict(cls, value: dict, *, require_complete: bool = True) -> Handoff:
        value = json.loads(encoded(value))
        require(value.get("schema") == SCHEMA, "unsupported close dependency schema")
        month = value.get("month", "")
        _, closing = month_bounds(month)
        require(value.get("closing_date") == closing.isoformat(), "handoff closing date mismatch")
        require(bool(value.get("phase")), "handoff phase missing")
        expected = dict(value)
        actual_hash = expected.pop("payload_sha256", None)
        require(actual_hash == digest(expected), "handoff payload hash mismatch")
        require(isinstance(value.get("sources"), dict) and bool(value["sources"]), "source manifest missing")
        for path, hashed in value["sources"].items():
            parts = Path(path).parts
            require(not Path(path).is_absolute() and ".." not in parts and "golden" not in parts,
                    "source must be a relative non-golden phase input")
            require(_hash(hashed), "invalid source SHA-256")
        dependencies = value.get("dependencies", [])
        require(len(dependencies) == len(PRODUCERS), "all five dependencies are required")
        require({d.get("producer") for d in dependencies} == set(PRODUCERS), "dependency names mismatch")
        owners: dict[tuple[str, str], str] = {}
        for dependency in dependencies:
            producer = dependency["producer"]
            require(dependency.get("month") == month and dependency.get("phase") == value["phase"],
                    f"{producer}: cross-phase dependency")
            require(dependency.get("provenance") in {"real", "golden_fixture"}, f"{producer}: provenance missing")
            require(_hash(dependency.get("source_sha256")), f"{producer}: source hash missing")
            require(isinstance(dependency.get("coverage"), dict), f"{producer}: coverage missing")
            coverage = dependency["coverage"]
            if producer == "ic" and dependency["provenance"] == "real":
                require(coverage.get("mode") == "reconciled_pairs" and _hash(coverage.get("audit_sha256"))
                        and _hash(coverage.get("upstream_sha256")),
                        "real IC requires a phase-bound audit of every configured pair")
            expected_ids, observed_ids = coverage.get("expected", []), coverage.get("observed", [])
            require(len(set(observed_ids)) == len(observed_ids), f"{producer}: duplicated coverage IDs")
            require(set(observed_ids).issubset(expected_ids), f"{producer}: unknown coverage IDs")
            if require_complete:
                require(dependency.get("complete") is True and set(expected_ids) == set(observed_ids),
                        f"{producer}: incomplete handoff")
            for event in dependency.get("postings", []):
                owner = (event.get("event_id"), event.get("stage"))
                require(all(isinstance(x, str) and x for x in owner), "event/stage ownership missing")
                require(bool(event.get("business_key")), "semantic business key missing")
                require(bool(event.get("evidence")), "posting source evidence missing")
                sig = digest(event["journal_entry"])
                require(owner not in owners, f"duplicate dependency ownership {owner}")
                owners[owner] = sig
                posting = event["journal_entry"]
                require(posting.get("posting_date", "") <= closing.isoformat(), "future dependency posting")
                require(posting.get("posting_date", "")[:7] == month, "dependency outside close phase")
        facts = value.get("facts", {})
        require(isinstance(facts, dict), "facts must be an object")
        for name in ("accruals", "prepaids", "pending_certifications", "fx_positions"):
            require(isinstance(facts.get(name), list), f"missing facts collection: {name}")
            for fact in facts[name]:
                require(bool(fact.get("evidence")), f"{name}: original evidence required")
        for fact in facts.get("document_facts", []):
            DocumentFacts.from_dict(fact)
        return cls(value)

    @classmethod
    def load(cls, path: Path, phase_dir: Path, *, require_complete: bool = True,
             verify_documents: bool = True) -> Handoff:
        result = cls.from_dict(load_json(path), require_complete=require_complete)
        require(result.payload["phase"] == phase_dir.name, "phase directory name mismatch")
        root = phase_dir.resolve()
        for relative, expected in result.payload["sources"].items():
            if not verify_documents and Path(relative).parts[0] not in {"erp", "tasks"}:
                continue  # Replay relies on sealed observed facts, not document re-extraction.
            path = (root / relative).resolve()
            require(path.is_relative_to(root) and "golden" not in path.parts, "source escapes phase")
            require(file_hash(path) == expected, f"source changed: {relative}")
        return result

    @property
    def simulated(self) -> bool:
        return any(d["provenance"] == "golden_fixture" for d in self.payload["dependencies"])

    @property
    def complete(self) -> bool:
        return all(d["complete"] and set(d["coverage"]["expected"]) == set(d["coverage"]["observed"])
                   for d in self.payload["dependencies"])
