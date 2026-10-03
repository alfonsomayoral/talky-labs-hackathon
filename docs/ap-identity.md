# Exact AP identity core — #42

`IdentityCatalog.from_phase(PhaseData)` reads companies and vendors without LLM
or document parsing. `resolve` accepts independent `Fact`/`Evidence` candidates
for supplier and recipient tax identifiers, plus the expected company explicitly
resolved from the task/PO. It retains document and matched master evidence.

Case and presentation separators normalize deterministically. VAT country prefixes
are accepted only as aliases explicitly present in each master. Mexican RFCs are
never shortened; vendor names are not fuzzy-matched. Shared master tax IDs return
ambiguity. Conflicting PDF/XML facts remain conflicting rather than selecting the
one that happens to match a master. Missing and not-yet-extracted fields differ.

The result separates supplier and recipient, checks vendor affiliation if its
master supplies it, and compares recipient company with the expected PO/task
company. 1100 and UTE 1910 are distinct even when their vendors overlap. No AP
decision is emitted; #48/#49 own mandatory-field/wrong-addressee/master decisions.

Authority: POLITICAS_CONTABLES.md §§1–2.2; exact tax IDs and company affiliations
come from the supplied active-phase masters. The catalog copies mutable input
rows and affiliation lists. Production and synthetic tests never consult golden.

Pending #41: supply complete normalized evidenced document identifiers; #43: PO
company resolution; #48/#49: decision adaptation. Because document extraction and
phase-wide comparison are still pending, this core alone does not close #42.
