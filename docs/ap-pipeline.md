# AP integration (#140)

The integration layer composes public accounting engines and keeps attachment
observations separate. Its first adapter is
`source_rejection_stage(fields, amount_sources=...)`, which applies the existing
eight rejection rules in policy order.

`fields` holds independent candidates and evidenced policy context, using the
rejection engine's field names. `amount_sources` holds the independently
normalized financial documents with explicit `net_cents`, `tax_cents` and
`gross_cents` observations. The caller identifies those documents by evidenced
classification; accompanying messages and notices are not extra invoice totals.

The adapter checks arithmetic within each source using the same domain rule.
A PDF and XML can both satisfy net + charged tax = gross while their totals
disagree. Their differing candidates remain in `fields`, and the CFDI comparison
retains the two independent views. A known arithmetic violation still wins before
CFDI mismatch. An incomplete amount view remains unknown; an earlier unresolved
identity or other policy gate prevents a later rejection from being selected.

Tests cover these boundaries with synthetic sources, different dates and IDs,
source reordering, evidenced conflicts and malformed money. No Golden or provider
is needed for these checks.

The phase runner/CLI and the full 305-task comparison remain part of #140's
acceptance. This adapter alone establishes neither extraction quality nor full
AP coverage. The next connections must preserve source evidence, derive policy
applicability from masters and document facts, and commit receipt consumption
only after a complete validated posting.
