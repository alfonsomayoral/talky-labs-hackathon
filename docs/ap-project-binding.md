# Observed project reference binding

`resolve_ap_project_binding(observed: APField, *, company, projects=None,
project_source="erp/projects.jsonl")` returns `APProjectBinding` with `status`,
`project_id`, `match_kind`, `evidence` and `diagnostics`.

An exact active project ID in the invoice's company resolves as `EXACT_ID`.
Otherwise a project name resolves as `EXACT_NAME` only when case/whitespace
normalization produces exactly one match in that company. A literal foreign ID
cannot fall through to a same-text name. No accent, punctuation, prefix, fuzzy or
PO default matching occurs. Ambiguous, foreign, missing, malformed or conflicting
facts return `UNKNOWN`. An omitted field returns `OMITTED` without iterating the
master; explicit unknown is distinct from omission.

Invoice evidence and the matched ERP project ID/name/company evidence accompany
the result. The source `APField` is preserved: a printed work name remains a name,
while `POQuery.project` and `CodingQuery.project` receive the resolved active ID.
Raw text remains in the independent source view and its evidence; normalization
can already have stripped edge whitespace before this helper runs.

The context builder loads projects only for an observed reference. Its batch
snapshot pins an available projects table before planning and verifies its hash
afterwards without parsing it for omitted references. An observed reference with
no available master remains `UNKNOWN`. Monetary preparation also checks active
catalog ownership and source agreement; a successful project join alone grants
no posting or PO match.
