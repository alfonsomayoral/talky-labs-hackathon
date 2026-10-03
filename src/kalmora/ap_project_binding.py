"""Exact source project reference to active ID, within one company (#140).

Observed text stays intact. Only case/whitespace name normalization is allowed;
no PO default, fuzzy match, prefix stripping or cross-company selection occurs.
"""
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .ap_document_bridge import APField
from .facts import Evidence


@dataclass(frozen=True)
class APProjectBinding:
    status: str  # RESOLVED, OMITTED, UNKNOWN
    project_id: str | None
    match_kind: str | None  # EXACT_ID or EXACT_NAME
    evidence: tuple[Evidence, ...]
    diagnostics: tuple[str, ...] = ()


def resolve_ap_project_binding(observed: APField, *, company: str | None,
                               projects: Iterable[Mapping] | None = None,
                               project_source: str = "erp/projects.jsonl") -> APProjectBinding:
    """Resolve a literal ID first, otherwise a unique exact normalized name.

    Omitted fields do not iterate/read a supplied master. The caller pins source
    hashes and loads the master only for observed references. Explicit None,
    conflicts, invalid scope/master rows and ambiguous/missing joins abstain.
    """
    if not isinstance(observed, APField):
        raise TypeError("observed project reference requires APField")
    proof = list(observed.evidence)

    def unknown(diagnostic):
        return APProjectBinding("UNKNOWN", None, None, tuple(dict.fromkeys(proof)), (diagnostic,))

    if not observed.candidates:
        return APProjectBinding("OMITTED", None, None, tuple(proof))
    if not observed.known or not isinstance(observed.value, str) or not observed.value.strip():
        return unknown("PROJECT_REFERENCE_UNKNOWN")
    if not isinstance(company, str) or not company or company.strip() != company:
        return unknown("PROJECT_COMPANY_SCOPE_UNKNOWN")
    if projects is None:
        return unknown("PROJECT_MASTER_UNAVAILABLE")
    Evidence(project_source, "inventory")
    try:
        rows = tuple(projects)
    except TypeError:
        return unknown("PROJECT_MASTER_MALFORMED")
    ids = set()
    for row in rows:
        if (not isinstance(row, Mapping)
                or any(not isinstance(row.get(key), str) or not row[key].strip()
                       for key in ("id", "company", "name"))
                or row["id"].strip() != row["id"] or row["company"].strip() != row["company"]
                or row["id"] in ids):
            return unknown("PROJECT_MASTER_MALFORMED")
        ids.add(row["id"])
    exact = [row for row in rows if row["id"] == observed.value]

    def retain(row):
        proof.extend(Evidence(project_source, f"id={row['id']}.{field}")
                     for field in ("id", "company", "name"))

    if exact:
        retain(exact[0])
        if exact[0]["company"] != company:
            return unknown("PROJECT_REFERENCE_FOREIGN_COMPANY")
        return APProjectBinding("RESOLVED", exact[0]["id"], "EXACT_ID", tuple(dict.fromkeys(proof)))
    name = " ".join(observed.value.casefold().split())
    names = [row for row in rows if " ".join(row["name"].casefold().split()) == name]
    for row in names:
        retain(row)
    matches = [row for row in names if row["company"] == company]
    if len(matches) != 1:
        return unknown("PROJECT_NAME_AMBIGUOUS" if len(matches) > 1 else
                       "PROJECT_REFERENCE_FOREIGN_COMPANY" if names else "PROJECT_REFERENCE_NOT_FOUND")
    return APProjectBinding("RESOLVED", matches[0]["id"], "EXACT_NAME", tuple(dict.fromkeys(proof)))
