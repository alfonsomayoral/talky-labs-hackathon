# AR billing (M2): design record

Working record for milestone M2 ("Facturación / `ar_billing.jsonl`", issues #56–#65, epics #9–#11). Questions are written before they are researched; decisions are appended under each question. Status: **design in progress, no product code touched.**

Goal (from the brief): analyse the problem and the data model we have, and propose a solution that **ends with a list of concrete model instances held in memory** (one billing result per `billing_item`), before any JSONL serialization.

## Known facts (observed, not decided)

Sources: `participant/POLITICAS_CONTABLES.md` §3.1, `FORMATO_ENTREGA.md`, `score.py`, `phase_dev/{tasks,inbox/ar/billing,erp}`, `knowledge/reference/ar-data-model.html`, `src/kalmora/`, branches `codex/62-energy-core` and `codex/63-billing-deductions`. No golden was read.

- **26 billing items** in July: 14 `OBRA_CERTIFICATION`, 8 `SERVICE_MONTHLY`, 2 `PRICE_REVISION`, 1 `PPA`, 1 `MARKET_SETTLEMENT`. Each folder has `item.json` (type, company, contract, customer, month) and one `documento.pdf`.
- The PDFs are **text PDFs** (extractable without OCR), generated from templates in three languages (ES/PT/MX layouts).
- `score.py` per item: `expected` must match, else 0; INVOICE items score `0.6 × head + 0.4 × journal-entry match`. `head` checks `tax_code` and `due_date` (**exact**) plus `net`, `tax`, `retention`, `payable` (±1 cent) and the three DIR3 codes when the client is public. Invoice `date`, `gross`, `lines` and `deductions` are not scored directly; journal lines are matched by account, partner, cost object and amount (±2).
- The project has `dependencies = []` (standard library only); `pdfplumber` and `pypdf` are installed locally but are not declared.
- `src/kalmora/model/` has typed shapes for ERP data (`JournalEntry`, `JournalLine`, `OpenItem`, ...) but **nothing for the AR billing deliverable** (no item, invoice, line, deduction or FACe type). `facts.py` already provides `DocumentFacts`/`Fact`/`Evidence` with a hash-keyed cache.
- Branch `codex/63-billing-deductions` covers taxes, guarantee and Mexican deductions from resolved bases; branch `codex/62-energy-core` covers PPA and market arithmetic from resolved inputs. Neither reads documents, decides eligibility, builds invoices or journal entries.
- Observed in `phase_dev` (history, documents):
  - the July certification of `CV-OB-1100-2511` states "anterior" = the last **invoiced** cumulative (June's certification #10 was `approved: false` and never invoiced), so its current amount catches up June;
  - `CV-OB-2100-2503` is stamped "PENDIENTE DE APROBACIÓN / No facturar";
  - energy and revision invoices are dated in the following month on a recurring pattern (see Q5), and the market deviation cost is booked as one line on `CC-1300-ADM`, not split by plant;
  - Mexican history: payable = gross − 5‰ levy − advance amortization; VAT matches rounding on the invoice total, not per line (96 of 266 multi-line history invoices differ by one cent under per-line rounding).

## Questions

### Q1. What is the concrete output model, and where does it live?

*Why it matters:* the stated end state is "a list of model instances in memory"; there is no AR billing type in `kalmora.model`, and the existing model is made of `TypedDict` shapes for ERP rows.
*Owner:* @danielorlando97. *Acceptance:* every field of the `ar_billing.jsonl` contract is reachable from one root instance per billing item; instances are immutable or validated; serialization is a separate, mechanical step.

### Q2. What are the pipeline stages and where is the line between facts and decisions?

*Why it matters:* determinism depends on isolating the only non-deterministic parts (document reading) from pure decision and arithmetic.
*Acceptance:* each stage has a typed input and output; every stage after fact extraction is a pure function of resolved facts, masters and history.

### Q3. How are the PDF documents read, with which tooling, and how are layout traps handled?

*Why it matters:* the project has no declared dependencies; the six layouts mix number formats (`8.652,582` and `2,737.647`), languages, and an overlapped stamp in service reports (`CONFOCRoMnfEorme`).
*Acceptance:* one reproducible reader per layout that emits `DocumentFacts` with evidence; contradictory candidates are kept; no OCR or model call needed for the July set.

### Q4. How is "bill or skip" decided for each type?

*Why it matters:* `expected` is a gate worth 100 % of an item; a wrong skip or invoice zeroes it.
*Acceptance:* a closed rule per type, using approval, conformity, history and contract dates; the catch-up case (2511) and the pending case (2503) are decided from evidence; double billing is impossible.

### Q5. How are invoice date and due date derived per type?

*Why it matters:* `due_date` is scored exactly, and only the certification rule is stated in the policy.
*Acceptance:* a rule per type reproducing the historical dates, including weekends and national holidays, with the evidence.

### Q6. What invoice lines, accounts and cost objects does each type produce?

*Why it matters:* journal lines are matched by account, partner, cost object and amount.
*Acceptance:* per type, line granularity (chapter, month, plant), income account, WBS or cost center, tax code on each line, taken from masters and history.

### Q7. Which tax, guarantee and Mexican deduction rules apply, and how is the advance balance obtained?

*Why it matters:* `tax`, `retention` and `payable` are scored, and the advance amortization depends on an exhaustible balance carried across invoices.
*Acceptance:* every rule reproduces the history without per-case patches; the advance balance is derived from the ERP and the processing order is fixed.

### Q8. Do the M2-07 and M2-08 branch assumptions agree with the data?

*Why it matters:* both cores were built on assumptions (per-plant deviations, per-line VAT) before the data was checked.
*Acceptance:* each assumption is confirmed or replaced by an observed rule, and the affected API is listed.

### Q9. How is the journal entry built?

*Why it matters:* it is 40 % of an INVOICE item's score and must balance and follow policy §3.1 with correct partner, assignment and cost object.
*Acceptance:* a pure builder from the invoice instance; balanced by construction; the ±2 cent rounding difference lands on a defined line.

### Q10. How are invoice numbers, identity and idempotency handled?

*Why it matters:* the journal `assignment` carries the invoice number and AR cash later applies receipts to it; the ledger refuses a repeated `(event_id, stage)`.
*Acceptance:* a deterministic numbering rule consistent with the history series, and a provenance per generated entry.

### Q11. How is the result validated and traced without the golden?

*Why it matters:* the golden is evaluation-only and the September phase has none.
*Acceptance:* invariants checked in memory (balance, sums, tax identities, policy rules) plus evidence per field; the comparator is used only in evaluation.

### Q12. What does July not exercise that September may, and does the model cover it?

*Why it matters:* the test phase is different data; extraordinary services, pending conformity, private-works guarantee, exhausted advances, revisions with several effective months and new customers can appear.
*Acceptance:* each variant is either handled by a rule or produces an explicit, typed "unresolved" result instead of a guess.

### Q13. Module boundaries, integration with the existing branches and the delivery of the in-memory list.

*Why it matters:* two partial branches, M0 contracts (`facts`, `ledger`, `validation`, `money`) and #32 (output serialization) must fit together.
*Acceptance:* module list, dependency direction, which branches are merged, and the single public entry point returning the in-memory list.

## Findings from research (facts, each reproducible from `phase_dev` without the golden)

| # | Finding | Evidence | Consequence |
|---|---|---|---|
| F1 | PPA = `trunc₃(Σ MWh of all plants × share)` MWh, then × price, truncated to cents; one invoice line on the contract's **first plant** cost center. | 20/20 history invoices match; per-plant truncation (branch `62`) matches 3/20. | `calculate_ppa` must change. |
| F2 | Market net = Σ plant gross − **one aggregate deviation** line (Dr 70530000, `CC-1300-ADM`); plant lines on each plant's cost center; the representative's fee is billed apart. | 20/20 history; July PDF gives only an aggregate "coste de desvíos". | Branch `62` per-plant deviation allocation is not needed; replace by one aggregate deviation. |
| F3 | VAT is computed on the invoice **net total**; the journal has one `47700000` line. | 266 multi-line history invoices: per-line rounding differs on 96. | Branch `63` per-line VAT must change. |
| F4 | Guarantee = contract `retention_bp` × net (RISP/PT 500, public R21 0), 5‰ levy = 50 bp × net, advance amortization = 30 % × gross capped by the advance balance; payable = gross − guarantee − levy − amortization. | 254/254 obra history invoices; MX example matches to the cent. | Branch `63` formulas stand. |
| F5 | The advance balance equals −(`open_items` 43800000 per customer) and equals ANT gross − Σ ADV_AMORT in history. | 3,979,528,476 and 12,200,090,833 in both. July does not hit the cap (30 % of gross is 861,281,621 and 1,605,162,804). | Use the ERP open item, cross-checked with history. |
| F6 | Certification amount in the document = cumulative − **last invoiced** cumulative, not the last numbered certification. | `CV-OB-1100-2511`: June cert #10 `approved: false`; July "anterior" = June-1 cumulative. | Eligibility keys on invoiced history, not on certification numbers. |
| F7 | Dates: cert and service = last day of the certified month; revision = day 4 of the decree's approval month (12/12 history); PPA = day 3 and market = day 6 of the month after the period, moved to the next Spanish national business day (40/40 history); due = date + `terms_days`. | Dec 6 2024/2025 and Jan 6 2025/2026 roll on holidays; Apr 3 2026 (Good Friday) rolls. | A national-holiday calendar per year is required; July/September 2026 need none beyond weekends. |
| F8 | The service report's "CONFOCRoMnfEorme" is a **stamp over a status cell** (blue Helvetica-Bold `CONFORME` at y≈131 over black `Conforme` at y≈128), not a conflict. | Character-level inspection with `pdfplumber`. | Read by character attributes, not by flattened text. |
| F9 | Number formats differ per document: ES (`8.652,582`), US (`2,737.647`), PPA price `41.50`. | July PDFs. | Per-layout number parser; never a generic one. |
| F10 | Public clients carry `dir3` in `customers.jsonl`; FACe goes on every public ES invoice. | `customers.kind == "public"`, 18 of 25 invoices. | Copy from master. |

## Decisions

### Q1. Output model: immutable dataclasses in `kalmora.model`, one root per item. **Decided.**

Alternatives: (a) `TypedDict` straight to JSONL, like the ERP shapes; (b) frozen dataclasses with `__post_init__` validation; (c) Pydantic. Evidence: current guidance for internal domain models is frozen, slotted dataclasses validated in `__post_init__` (zero dependencies), with `TypedDict` reserved for values that must stay `dict`; the project has `dependencies = []`; `facts.py` already uses frozen dataclasses with validation. Decision: (b). The delivery rows (`dict`) and the ledger entry (`JournalEntry` `TypedDict`) are produced from these instances in a later mechanical step (#32), so `JournalEntry` stays the existing shape.

Types (all `frozen=True, slots=True`; money is integer local cents; dates are `IsoDate`):

- `BillingItem(id, type: BillingType, company, customer, contract, month, documents)`; `BillingType` ∈ OBRA_CERTIFICATION, SERVICE_MONTHLY, PRICE_REVISION, PPA, MARKET_SETTLEMENT.
- `InvoiceLine(description, amount, account, tax_code, wbs | None, cost_center | None)`: exactly one cost object; `amount` may be negative.
- `Deduction(code: MX5MILL | ADV_AMORT, amount, account)`.
- `Face(oficina_contable, organo_gestor, unidad_tramitadora)`.
- `Invoice(number, date, due_date, tax_code, net, tax, gross, retention, deductions, payable, currency, lines, face | None)`; invariants: Σ lines = net, gross = net + tax, payable = gross − retention − Σ deductions.
- `BillingDecision` ∈ INVOICE, SKIP_PENDING_APPROVAL (the delivery `expected`).
- `BillingResult(item, decision, invoice | None, journal_entry | None, evidence: tuple[Evidence, ...], diagnostics: tuple[Diagnostic, ...])`: **the instance the pipeline ends with**. `invoice`/`journal_entry` are present iff `decision == INVOICE`; a balanced `JournalEntry` with `provenance(event_id=item.id, stage="ar_billing")`.

The pipeline's return value is `list[BillingResult]` in `tasks/ar_billing_items.json` order.

### Q2. Pipeline: one impure edge, everything else pure. **Decided.**

`read → resolve → decide → compute → assemble → validate`.

1. **read** (impure edge, cached): `documento.pdf` → `DocumentFacts` (existing type, hash-keyed cache). The only non-deterministic or slow stage.
2. **resolve**: `DocumentFacts` + item + masters (contract, customer, project WBS, cost centers) + history → one typed input per kind (`CertificationInput`, `ServiceReportInput`, `RevisionDecreeInput`, `ProductionReportInput`, `SettlementReportInput`). Cross-checks against history live here; conflicts become diagnostics, never silent picks.
3. **decide**: eligibility (Q4).
4. **compute**: base lines → amounts (taxes, guarantee, Mexican deductions, energy), all in integer cents.
5. **assemble**: `Invoice`, then `JournalEntry` from the invoice.
6. **validate**: invariants (Q11).

Properties: re-running with the same bytes, masters and history yields the same list; processing order is fixed (Q7).

### Q3. Reading: character-level, per-layout parsers, `pdfplumber` as an optional extra. **Decided.**

Alternatives: stdlib-only content-stream parsing (fragile); `pypdf` text (no position or colour, so the stamp overlap cannot be separated); `pdfplumber` (character positions, fonts, colours; already installed). The July set needs no OCR. Decision: `pdfplumber` declared in an optional dependency group for extraction only; core model, rules and arithmetic stay stdlib. One small parser per layout (certification ES/MX/PT, service report, decree, production report, settlement) with its own number format (F9), emitting `Fact`s with page and quote. A layout the parser does not recognise yields a diagnostic, not a guess. Known risk: layouts for September are unseen; parsers must key on labels, not on positions.

### Q4. Billing decision rules. **Decided.**

- **Certification:** INVOICE iff the document is stamped approved (`CONFORME`) **and** the stated current amount equals cumulative − previous **and** previous equals the last invoiced cumulative for the contract (F6). `PENDIENTE DE APROBACIÓN` or `No facturar` → `SKIP_PENDING_APPROVAL`. A certification already invoiced (same cumulative) is never invoiced again.
- **Service monthly:** canon of the month is always billable; extraordinary services only with `Conforme`; pending ones are omitted, not skipped (the item still INVOICEs for the canon).
- **Price revision:** INVOICE iff the decree is approved; one line per month from the effective date up to the month before the approval, each (new − old) canon; months already revised in history are not repeated.
- **PPA / market:** INVOICE; the period is item month − 1; a period already invoiced in history is rejected as a diagnostic.
- Anything outside these rules → diagnostic, no record (Q12).

### Q5. Dates (F7). **Decided.** Rules above; business-day roll uses a per-year Spanish national-holiday table (2026: Jan 1, Jan 6, Apr 3, May 1, Aug 15, Oct 12, Nov 1, Dec 8, Dec 25; source: BOE resolution of 17 Oct 2025, searched). Resulting July dates: PPA 2026-07-03 (due 07-23), market 2026-07-06 (due 07-06), revisions 2026-07-04, certs and canon 2026-07-31. September 2026: PPA 09-03, market 09-07 (6th is a Sunday). Evidence quality: inferred from 40/40 and 12/12 history cases; the policy states only the certification rule.

### Q6. Lines, accounts and cost objects. **Decided.**

| Type | Account | Line granularity | Cost object |
|---|---|---|---|
| Certification | 70510000 | one per chapter of the document | WBS from the project master (chapter n → `<project>.0n`) |
| Service monthly | 70500000 | one canon line (+ extraordinary lines) | cost center of the contract (`CC-<contract-company>-<code>`, from history) |
| Price revision | 70520000 | one per month, positive | contract cost center |
| PPA | 70530000 | one line "MWh × price" | first plant's cost center of the contract |
| Market | 70530000 | one per plant, plus one deviation line (Dr) | plant cost center; deviation on `CC-1300-ADM` |

### Q7. Taxes, guarantee, Mexican deductions, advance. **Decided.** F3, F4, F5. Contract terms (`tax`, `retention_bp`, `mx5mill`, `advance_bp`) come from `sales_contracts`; nothing is inferred when absent. Invoices are processed ordered by (date, contract, item id), per-contract advance state updated only after the whole invoice is built.

### Q8. Branch assumptions vs data. **Decided.** `codex/62`: replace per-plant truncation with total-energy truncation (F1) and per-plant deviations with one aggregate (F2). `codex/63`: VAT on net total (F3); everything else is confirmed (F4). Both stay pure cores; the new types in Q1 replace their input dataclasses where they overlap.

### Q9. Journal entry. **Decided.** From the `Invoice`, in this order: Dr 43000000 payable (partner = customer, assignment = invoice number); Dr 43000900 guarantee (customer); Dr 63100000 levy; Dr 43800000 amortization (customer); Cr income lines; Cr 47700000 total VAT when VAT > 0 (absent for RISP/PRAUT); the deviation line is a Dr on 70530000. The ±2 cent rounding difference goes on the customer line (policy §1). Verified shape against history entries `EN26-00012` and `EST-2026-00011`.

### Q10. Numbering and identity. **Decided.** Number = series of the last history invoice for that company and contract family, next sequence in (date, contract, item id) order. Not scored (`score.py` ignores it), so it is deterministic best effort; identity of the result is `item.id` and the entry carries `Provenance(item.id, "ar_billing")`. Open risk: AR cash (a later module) addresses invoices by number, so numbering must match the ERP series.

### Q11. Validation without the golden. **Decided.** In-memory checks per result: invoice invariants (Q1), journal balanced and one cost object per income line, journal totals equal invoice amounts, `due_date = date + terms_days`, facts conflicts empty, certification identity (Σ chapters = current = cumulative − previous). The golden is used only through the comparator (ADR 0001).

### Q12. Variants July does not exercise. **Decided.** The model carries them; rules reject what is unproven. Covered: extraordinary services (conformity), exhausted advance (cap), guarantee on private works (contract `retention_bp`), several-month revisions. Not decided here: foreign-currency invoices, credit notes, a certification with negative lines. Policy: a `BillingResult` is **not** emitted for an item the pipeline cannot resolve; a `Diagnostic` is returned instead, because a guessed invoice can score 0 where an unresolved one is reviewable.

### Q13. Modules and integration. **Decided.** New modules under `src/kalmora/billing/`: `layouts.py` (read), `resolve.py`, `decide.py`, `compute.py` (energy + deductions, merging branches `62`/`63`), `assemble.py` (invoice + journal), `run.py` (public entry `build_ar_billing(phase) -> list[BillingResult]`). Dependency direction: `run → assemble → compute/decide → resolve → layouts`; `model` has no imports from `billing`. Serialization (#32) and the comparator stay outside. Existing M0 contracts reused: `facts`, `money`, `validation`, `ledger`.

## Worked instances (illustrative; amounts computed by hand from the July documents, to be confirmed by the implementation)

`BILL-PPA-1300-01-202606`: Σ MWh 14,435.715 × 70 % = 10,105.0005 → 10,105.000 MWh; × 41.50 = 41,935,750 cents; VAT 8,806,508 (half-up of .5); gross 50,742,258; date 2026-07-03, due 2026-07-23; one line 70530000 on `CC-1300-PSF1`; no face.

`BILL-MKT-1300-01-202606`: plants 19,778,133 + 12,915,001 + 29,215,455 = 61,908,589; deviation −1,460,336; net 60,448,253; VAT 12,694,133; gross 73,142,386; date and due 2026-07-06; four lines (three plants Cr, one deviation Dr on `CC-1300-ADM`).

`BILL-CV-OB-2100-2503-202607`: `SKIP_PENDING_APPROVAL`; no invoice, no entry.

## Open risks and blockers

- **No blocker.** Nothing here needs a non-inferable product, legal or financial decision.
- R1: PPA/market invoice dates and the revision date rule are inferred from history (F7); `due_date` is scored exactly, so an error costs 1/6 of the head per affected item.
- R2: September layouts are unseen; the parsers can fail loudly but cannot be proven.
- R3: Unresolved items produce no record (Q12); that scores 0 for the item. Alternative left open to the user: emit a best-effort INVOICE with diagnostics.
- R4: Invoice numbering must match the ERP series for the later AR cash module.
- R5: `pdfplumber` becomes an extraction-time dependency.

## Proposed implementation scope (awaiting approval)

1. Typed model (Q1) in `kalmora.model` plus re-exports.
2. Merge `codex/62` and `codex/63` into `billing/compute.py` with the F1–F3 corrections.
3. `billing/layouts.py` parsers for the five document families, with number-format handling and stamp separation.
4. `resolve`, `decide`, `assemble` and `run` with the rules in Q4–Q10.
5. In-memory validation (Q11) and a reproducible check recomputing the 254 obra, 20 PPA and 20 market history invoices from their inputs.

## Implementation and evidence (engine, PDF reading excluded)

Preparatory AR observation boundary (#56): see [ar-observations.md](ar-observations.md)
for the versioned normalized contract, deterministic adapter and development
sample. Automatic AR extraction/capture and final integration remain pending.

Status: engine implemented in `src/kalmora/billing/`; document reading is owned by another team member and enters through `inputs.py` (one typed facts object per item). Approved scope changes against the plan above:

**Note on Q3 (reading).** The reader is not part of this change. The team's ADR 0002 (document LLM boundary) selects `pypdf` and typed model interpretation for document reading, which supersedes the `pdfplumber` choice recorded in Q3 and risk R5 above. The engine only depends on the facts contract in `billing/inputs.py`.

- **Module layout** (replaces Q13): `model.py` (typed results), `inputs.py` (facts contract with the reader), `calendar.py`, `compute.py` (VAT on net total, guarantee, Mexican deductions, PPA), `engine.py` (resolve, decide, assemble, validate; `build_ar_billing`, `load_items`), `journal.py` (entry and delivery row, `to_row`), `history.py` (facts from `billing_history`). Types live in `kalmora.billing.model`, not in `kalmora.model`; delivery rows reuse `kalmora.output_models.ArBillingRow`.
- **Return value:** `BillingRun(results, unresolved)`. `results` is the in-memory list of `BillingResult` (input order); items that cannot be decided are `Unresolved` with reasons and emit no record (Q12).
- **Certification previous amount (refines Q4/F6):** the document's "anterior" must equal the cumulative of the last *approved* certification in `billing_history`, not the sum of invoices, because the ERP history starts in 2024-10 and earlier invoices are missing for contracts that began before. With no earlier certification the item is resolved with a note (not verifiable).
- **Advance balance (refines F5):** computed from `ar_invoices` before the invoice date (advance gross minus `ADV_AMORT` already taken), minus what the same run already consumed; equals the ERP open item 43800000.
- **Replay mode:** `strict_duplicates=False` ignores invoices on or after the item's date, so past months can be recomputed.

Evidence (reproducible, no golden, no PDFs): replaying all 487 `billing_history` records through the engine gives 487 results and 0 unresolved. The 474 invoices (certifications, services, revisions, PPA, market, Mexican deductions) match the registered invoice on date, `tax_code`, `due_date`, `tax`, `retention`, `payable`, FACe presence and **every journal line** (account, partner, cost object, debit, credit); the 13 `approved: false` certifications produce `SKIP_PENDING_APPROVAL`. Running the July items with facts read from the PDFs by a throwaway script gives 26 results and 0 unresolved: 25 invoices and `SKIP_PENDING_APPROVAL` for `CV-OB-2100-2503`; PPA net 41,935,750 (date 2026-07-03), market net 60,448,253 (date 2026-07-06), `CV-OB-1100-2511` catch-up net 223,107,590, Mexican amortizations 861,281,621 and 1,605,162,804 (cap not binding). `mypy` is clean on the package. No test files were added (repository instruction); the replay and July scripts live outside the repository.

Known limits: invoice numbers continue the ERP series but are best effort and unscored; a revision that does not raise the fee, credit notes, foreign-currency invoices and extraordinary services in September are not decided; the dates of energy and revision invoices follow the history pattern (Q5), not a stated policy; July's facts were not produced by the real reader.
