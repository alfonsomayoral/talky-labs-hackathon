# Explicit AP chronology (#46)

`ap_chronology.replay_events` produces an immutable simulated timeline from
`model.ap_event.ApEvent` and `model.ap_scope.ApScope`. It does not parse documents,
post entries, write ERP, or serialize the AP contract. Exact repeated events are
idempotent; conflicting identities fail. Stable ordering is scope, reception,
validity start, then event ID. Selection uses latest validity start, reception,
then ID, so input/filesystem order cannot change the evidence selected.

`invoice_state(events, scope, invoice_date, received_at, month, ...)` keeps
reception and validity separate. Certificate and factoring validity is inclusive
at both ends and uses invoice date. An open-ended assignment is valid; a
certificate with unknown expiry is unknown. Baseline ERP records have no invented
receipt time. New certificate and factoring notices must be visible by invoice
reception. An embargo must have a documented reception strictly before the
invoice; equal timestamps do not qualify and same-day date-only reception is
unknown. Verified bank-change evidence registered earlier or received anywhere
in the closing month can support its exact IBAN, including a later notice in the
same month, as policy §2.2 explicitly allows. Later months cannot.

Scope is always company, vendor and currency. An assignment restricted to an
invoice requires an explicitly matching reference; this module does not infer
prefixes or normalize identity. Zoned timestamps are ordered in UTC. The package's
naive timestamps retain their wall-clock order by using UTC as a sorting frame;
callers must not combine naive local times from different time zones.

Each observation is `True`, `False` or `None`. No event means unknown unless
`complete_kinds` explicitly declares the queried inventory complete for the
scope. `event_support_facts` returns evidence-bearing `Fact` candidates for
decision checks. False candidates additionally require source evidence for that
complete inventory; unknowns return no candidate. A declared complete inventory
does not turn incomplete dates or verification into false.

Factoring payee eligibility and bank-change support are separate observations:
`factoring_active=True` redirects payment, but `factoring_bank_supported=True`
only when the invoice IBAN exactly matches the evidenced factor IBAN. An active
factor never authorizes an unrelated invoice bank account.

`registered_events(PhaseData, scope)` reads vendor alternative payee and article
43 certificates with source evidence. Customer `factoring_assignments` are AR
data and cannot authorize an AP payee. Vendor garnishments provide `from_date`
but not a documented receipt time in the supplied ERP: this remains unknown.
Bank-history `valid_to` alone cannot prove a signed, verified bank-change letter.

Validation: `PYTHONPATH=src python3 -m unittest discover -s tests -p
'test_ap_chronology.py' -v` covers validity boundaries, reception ordering,
verified/month bank changes, unknowns, replay/no mutation and scope isolation.
Fixtures are synthetic policy variations and do not read golden data.

Limits: extraction (#41) and identity (#42) must supply explicit notice facts,
resolved scopes and inventory completeness. This foundation cannot certify all
July AP decisions or the untouched #32/#35 contracts/scorer. It intentionally
leaves source ambiguity visible rather than deriving a receipt date from an
issued or effective date.
