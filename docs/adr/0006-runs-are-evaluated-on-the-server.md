---
status: proposed
---

# A run's deliverables are checked and scored on the server

The web app used to score a run in the browser, which needed `--serve-golden` to ship the golden over HTTP. `GET /v1/runs/{id}/submission:check` and `/evaluation` now validate and score a run's `deliverables/` through the existing gateway, so the golden stays on the evaluator side (ADR 0001) and `--serve-golden` can be removed once the app uses them. The structure check moved to the solver side (`output_validation`, no golden), so it works without `--evaluator`. We kept the raw file endpoints because the app parses bundles itself, and we did not make the MCP server able to start runs or write overrides: an agent reads, people decide.
