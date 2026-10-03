# M6 close

PRs #197 and #277 are merged in backend. The current corrective review connects
real deterministic AP/bank outputs to IC, requires positive IC coverage in M6
and preserves the policy-based treatment of open foreign credit notes.

Read [REAL_FLOW_REVIEW.md](REAL_FLOW_REVIEW.md) for current execution, commands,
remaining acceptance limits and the machine evidence. July and September both
complete the six-module workflow and replay the ten M6 accounting files exactly.
July scores 96.79% globally; September has structural validation only.

M6 and issues #171/#251 remain open for review. Four July AP recipient-company
differences and the documented source/reference discrepancies remain visible.
The deterministic v0 producer run does not accept the separate native/model AP
workflow or every accounting decision.

METHOD.md and CONTRACT.md describe the updated contracts and rules.
RESULTS.md, SCORE_INVESTIGATION.md, REVIEW.md and PR_BODY.md preserve historical
simulated execution and the already-merged delivery; their older scores/PR state
are not the current integration status.
