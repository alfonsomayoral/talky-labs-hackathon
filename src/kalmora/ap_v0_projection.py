"""Explicit contractual view of v0 output; original bytes remain evidence.

Only known internal metadata and absent optional header values are projected.
No domain value, reason, decision, journal or coded dimension is repaired.
"""
from dataclasses import dataclass
import hashlib
import json

PROJECTION_VERSION = "ap-v0-contract-v1"
OPTIONAL_HEADERS = frozenset({"company", "invoice_date", "currency", "net", "tax", "gross",
                              "withholding", "retention", "payable", "action"})
NONPOSTING = frozenset({"HOLD", "REJECT", "DUPLICATE", "NOT_INVOICE"})


@dataclass(frozen=True)
class APProjectionChange:
    line: int
    doc_id: str | None
    pointer: str
    reason: str
    value_json: bytes

    def evidence(self):
        return dict(line=self.line, doc_id=self.doc_id, pointer=self.pointer,
                    reason=self.reason, value=json.loads(self.value_json))


@dataclass(frozen=True)
class APV0Projection:
    original_bytes: bytes
    projected_bytes: bytes
    changes: tuple[APProjectionChange, ...]

    def evidence(self):
        return dict(version=PROJECTION_VERSION,
                    original_sha256=hashlib.sha256(self.original_bytes).hexdigest(),
                    projected_sha256=hashlib.sha256(self.projected_bytes).hexdigest(),
                    changes=[change.evidence() for change in self.changes])


def project_v0_output(payload: bytes) -> APV0Projection:
    """Return an opt-in immutable view, retaining malformed JSON for diagnosis."""
    if not isinstance(payload, bytes):
        raise TypeError("v0 projection requires immutable original bytes")
    def pairs(items):
        row = {}
        for key, value in items:
            if key in row:
                raise ValueError("duplicate JSON member")
            row[key] = value
        return row
    def constant(value):
        raise ValueError("nonfinite JSON value: " + value)
    projected, changes = [], []
    for number, line in enumerate(payload.splitlines(keepends=True), 1):
        try:
            row = json.loads(line, object_pairs_hook=pairs, parse_constant=constant)
        except (ValueError, UnicodeError):
            projected.append(line)
            continue
        if not isinstance(row, dict):
            projected.append(line)
            continue
        doc_id = row.get("doc_id") if isinstance(row.get("doc_id"), str) else None
        def remove(mapping, key, pointer, reason):
            value = mapping.pop(key)
            changes.append(APProjectionChange(number, doc_id, pointer, reason,
                json.dumps(value, ensure_ascii=False, allow_nan=False).encode()))
        if "action_data" in row:
            remove(row, "action_data", "/action_data", "V0_INTERNAL_METADATA")
        for index, coded in enumerate(row.get("lines", ()) if isinstance(row.get("lines"), list) else ()):
            if isinstance(coded, dict) and "goods_receipts" in coded:
                remove(coded, "goods_receipts", f"/lines/{index}/goods_receipts", "V0_INTERNAL_METADATA")
        # Missing posting amounts/scopes remain explicit failures. A non-posting
        # header does not require these optional fields; absent is not zero.
        if isinstance(row.get("decision"), str) and row["decision"] in NONPOSTING:
            for key in sorted(OPTIONAL_HEADERS):
                if key in row and row[key] is None:
                    remove(row, key, "/" + key, "OPTIONAL_ABSENT_VALUE")
        projected.append(json.dumps(row, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
                         + (b"\n" if line.endswith((b"\n", b"\r")) else b""))
    return APV0Projection(payload, b"".join(projected), tuple(changes))
