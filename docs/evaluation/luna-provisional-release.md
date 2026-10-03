# Luna provisional release — M1 LLM

Approved by the user on 2026-10-03 to let the project continue. Model: `gpt-6-luna`, reasoning `low`; extraction prompt `document-observations-v10`, schema `document-interpretation-v3`. Request timeout and output-token cap are unset. For scanned-page comparisons, `include_processing_aids=False` preserves the OCR archive while sending only original images and source blocks to the model.

The user accepts the current documentary limitations provisionally and asks to stop quality iteration. This approval unblocks backend/AP integration and subsequent work. #39 and #139 are accepted as the provisional delivery; their outstanding quality and evaluation work is transferred to [hotfix #222](https://github.com/alfonsomayoral/talky-labs-hackathon/issues/222). #133 still tracks the wider integration. The full benchmark has not passed; reports retain their actual failed/unknown states.

## Measured evidence and limitations

All figures below are real calls on the same original tuning scan, including local processing. They describe one case, not the full sample or unseen-layout performance.

| Configuration | Raw fields / rows | Seconds | Estimated USD | Review outcome |
| --- | --- | --- | --- | --- |
| Luna, OCR aid, v9 | 174 / 26 | 45.49 | 0.003973125 | I/l and accent errors; 61 exact observation reviews rejected. |
| Luna, original image without OCR hint, v10 | 174 / 26 | 44.70 | 0.003795750 | Payment-term accent corrected; I/l errors remain; 60 exact observation reviews rejected. |
| Sol comparison, original image without OCR hint, v10 | 179 / 26 | 84.83 | 0.0786350 | First-row IIa and payment-term accent corrected; full fidelity review pending. Experimental. |

Original scan: `phase_dev/inbox/ap/API005199/factura_2026-030797.pdf`, source SHA-256 `2ee5ab17fe56e481b4706420cc3e5622f0d4eaf24ae3b95ce398e588f2b3d2f8`. Render SHA-256 `808d482745af6ecc9691f2b90ffb110ebe82abd4a79ba8b8d377bc06dd5e5736`. The manually inspected numeric columns and delivery references are retained, but a misspelled shared quotation also invalidates proof for its other values. Rejected review counts therefore count observations affected by quotation fidelity, rather than asserting that every associated amount was numerically wrong.

A separate v10 Luna capture of the other eleven tuning cases finished before the stop instruction: eight completed and T03/T06/T10 failed. Estimated known cost USD0.018610250, no unknown reservation in that run. This operational capture has not completed the required full acceptance evaluation. Semantic/hybrid coverage, complete source fidelity and the frozen holdout remain pending in #222. Holdout labels have not been opened or used for tuning.

The earlier Sol request reached the former 60-second deadline; its usage remains unknown with a USD1.78 conservative reservation. Earlier Luna timeouts retain USD0.267. Reservations are not confirmed charges. The aggregate experimental budget is USD5 with necessary further extensions authorized and recorded explicitly. No new calls or quality iterations continue after this release decision.

## Follow-up boundary

Continue existing backend contracts and deterministic accounting with Luna. Preserve raw responses, original hashes, unknowns and contradictions. Keep strict evidence checks and honest evaluator results. Do not silently repair identifiers, hashes, money or quantities to conceal character errors. Original images, OCR aids and evaluator reviews retain their separate roles.

The hotfix owns literal fidelity, the remaining failed tuning cases, the period-date evaluator follow-up and the complete frozen acceptance evaluation. Golden/labels/reviews remain outside production prompts. Astra and cross-chat/agent messages remain prohibited.
