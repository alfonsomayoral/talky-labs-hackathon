---
status: proposed
---

# One service layer over a repository port, behind an HTTP API and an MCP server

Ingestion (upload of the organizer ZIP, load, normalization) and queries share one transport-free `kalmora.service`, which talks only to a `PhaseRepository` port. The first implementation is in memory (`PhaseData` + `Ledger`) and the extracted package stays on disk, so memory is a rebuildable cache; a DuckDB repository can replace it without changing the API. `kalmora.api` (FastAPI, OpenAPI generated from the existing `TypedDict` models) and `kalmora.mcp` (official SDK, stdio by default) are thin adapters, shipped as an optional extra so the core package stays dependency-free.

Ingestion is the only write and packages are immutable; everything else is read-only, because the single irreversible submission is produced only by the engines. Upload is HTTP only. The solver-side process never imports `kalmora.evaluation`; evaluator resources exist only when started with an explicit evaluator directory (see ADR 0001). We rejected a hand-written stdlib HTTP server (its contract would drift from the models) and an immediate DuckDB store (new dependency before parsing exists).
