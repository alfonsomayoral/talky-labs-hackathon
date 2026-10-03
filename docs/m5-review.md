# M5 implementation review and release gates

Refs #18, #19, #88, #89, #90, #91, #92, #93, #94.
This is a local implementation/self-review, **not a GitHub PR approval or a completed milestone**.

## Source and integration scope

The supplied snapshot represents backend commit
`a603691d3c5c992c92d7dbda73cfb7326a38bb15` and Git tree
`045837aa9244afc68cb8543f0bfbbbf0a6827911`. The independent local baseline has
exactly that tree; its local commit identity is different. No existing shared file
is changed by the M5 patch.

Backend was checked again at
`292bd0b7bac5b5c7e337452a77f9b4c0e75acd81` (tree
`0d4758ad60b5c88c7f3509dc50bde9f98bdc0d9b`). The comparison from the supplied
snapshot contained no M5 path collisions. It includes typed models, AP allocation
and valuation, and the shared evaluator. The **complete latest backend was not
materialized or tested** in this environment. The full local suite uses the
exact original snapshot plus M5; the actual latest shared IC evaluator is tested
separately using five unchanged files whose Git blob hashes match GitHub.
Before remote integration, apply the patch to fresh backend and run that branch's
full suite and Python 3.12 CI. No claim of passing remote CI is made here.

## Review findings fixed before first reference evaluation

The implementation and independent synthetic tests were developed without reading
reference files. Review corrected local-only FX entries misidentified as duplicate
invoices, wrong-partner numeric interest being treated as absent, carried prior
accruals being missed, and possible repeat corrections already owned by another
engine. Ledger ownership is still enforced by the shared Ledger.

A whole-journal replay initially timed out because repeated full-book copies
amplified work. An index of **producer additions only** now avoids those copies;
it is not a replacement ledger. The 36,743-entry real-input test and replay pass.

## Serializer revision after the first reference evaluation

The first solver freeze and evaluation are retained in delivery evidence. After
that evaluation, current backend's independently fetched `IcRow` contract was
reviewed: it uses shared `JournalLine`, whose source dimensions must survive.
A **serialization-only** revision copies existing assignment/tax/currency/document
amount fields, with synthetic preservation and no-fabrication tests. It changes no
cause detection, amounts, responsible companies, allocations, FX or posting rules.
The later freeze explicitly records this chronology; it does not imply that no
reference had previously been viewed. No rule or parameter was inferred from the
reference to repair the amount-sign disagreement.

## Remaining defects and external dependencies

1. **Amount sign is an unresolved implementation assumption, not a bank/AP blocker.**
   The wrong-partner finding currently reports an absolute magnitude and the
   Finding model disallows negative amounts. The reference expects a negative
   signed amount for the real wrong-partner case. Neither the common output
   example nor policy §6 specifies a general cause-specific sign convention.
   The current shared IcRow permits integer cents; it does not justify the local
   positivity assumption. Obtain an authoritative sign definition and implement
   independently derived cases before accepting #92/#94. Do not silently learn a
   cause-specific sign rule or inject an amount from the reference.
2. **AP #55:** no real complete receipt inventory or owned AP posting delivery was
   supplied. A held/rejected invoice can still have been received. Therefore a
   missing posting alone cannot certify nonreceipt. #90 is implemented and tested
   with explicit coverage, but the real reference's transit row is absent; it was
   not injected to improve the score. Tests with synthetic AP entries are labeled
   synthetic, not claimed as real integration.
3. **Banks #73/#75:** original ERP and actual statement show a missing pool sweep.
   The actual bank-owned correction for statement line BL0005652 is not supplied.
   The IC row remains visible with no adjustment and a named dependency. A synthetic
   correctly owned bank delivery is tested, but it does not certify completion.
4. **Remote write:** branch creation was denied with HTTP 403, `Resource not
   accessible by integration`. No branch, PR, review, remote commit, squash merge
   or issue update was created. Main was not written. Review text and maintainer
   commands are deliverables, not evidence of those remote actions occurring.

#32 is closed by deprecation and #35 is integrated/closed in the latest check.
The actual #35 IC comparator has now been consumed, so it is **not** listed as an
absent external dependency. Other engines and their assigned issues were not owned
or changed by M5.

## Validation actually executed

Python 3.13.5 in this environment (repository minimum >=3.12). The final local
full-suite run executed **104 tests, all passing, no skips**, with both real-phase
and original-ZIP opt-ins enabled. This includes source conservation/replay, the
recorded trial balance and the 435 original reference adjustment groups. Reference
validation belongs to the separate evaluation phase, never the solver.

M5's tests exercise date boundaries/leap years, both interest sides, contract rate
changes, exact FX, duplicate VAT/cost reversal, master-backed aliases, company
separation, allocation conflicts, carried accruals, actual-vs-pending pooling,
ownership replay, forbidden reference paths and source-dimension serialization.
The evaluator's independent tests perturb sign, responsible, pair, line company,
cost objects and assignment, and reject malformed or duplicated output.

The original scorer and actual shared `compare_ic` agree: **0.8533**, four of five
reference rows detected. Financial correction lines match, but the wrong-partner
amount sign fails and the real transit row is absent. Those failures remain
visible despite passing unit tests. M5 acceptance is not proven.

Local install, compileall, doctor, full unit tests and `git diff --check` are
recorded in delivery logs. The patch is checked on a fresh copy of the source
snapshot. Remote PR review, current-backend full suite and remote CI remain gates.

## Issue disposition

All seven issues and both epics remain open remotely. No closing keywords are
used in the patch's commit/PR text. #88/#89/#91 have working local implementations
and real ERP evidence, but remote deposit/current branch validation and the
required inter-engine handoffs are not demonstrated. #90 awaits real AP; #92 has
the amount-sign defect; #93 awaits real bank ownership; #94 must expose and resolve
those failures. Closing GitHub is a consequence of proving acceptance, not a
substitute for it.
