# Energy calculation core — partial #62

`kalmora.energy` implements §3.1 of `POLITICAS_CONTABLES.md` using explicit resolved
inputs. `EnergyScope` identifies company, document currency, contract and measured
period. Every input plant carries that scope; mismatches and duplicate plant rows
fail. The adapter must validate plant ownership and membership in the contract.

`calculate_ppa` takes `PlantMeasurement.mwh_milli`, explicit `share_bp` (0–10000)
and `price_mwh_cents` (exact Decimal/integer/text). It calls M0 `line_amount` with
truncation for each plant, then sums integer cents. The per-plant convention follows
§1's per-line amounts; fractions discarded at one plant cannot raise another
plant's revenue. No binary float or implicit percentage/price is accepted.

`calculate_market` takes `PlantSettlement` rows: gross cents **before deviations
and fees**, positive deviation cost cents allocated explicitly to that plant, and
optional informational representative fee cents. Revenue equals gross minus
deviations. Representative costs remain available as excluded metadata; they are
not subtracted again because they belong to the separate AP/netting workflow.
Negative net plant revenue is preserved instead of silently capped at zero.

## Inputs not resolved here

#58 and the extraction/contract adapters must supply measured/settled periods,
approved eligibility, exact prices/shares, plant ownership and gross settlement
amounts. A source settlement already net of fees must be normalized to gross with
explicit evidence before calling the core. A negative source deviation becomes a
positive cost only in that adapter. If the source gives aggregate deviations, their
plant assignment must be resolved upstream; this core does not invent weights.

#63 adds tax and contractual deductions. #64 supplies invoice dates, revenue coding,
FX conversion where needed and full posting. #32 owns final output serialization.
These functions do not read documents, billing history, ERP or golden, decide
approval, prevent refacturation or register revenue. Synthetic tests exercise exact
arithmetic, truncation boundaries, per-plant conservation and scope isolation.
