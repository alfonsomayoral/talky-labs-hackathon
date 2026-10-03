---
status: proposed
---

# The assistant is a separate read-only process that reaches data only through MCP

`kalmora chat` runs apart from `kalmora serve`: it holds the model key, speaks the web app's `POST /api/chat` contract, and gets every fact by calling the API process's MCP server (`/mcp`, same memory) as a client. It has no write tool, enforced by the tool list and not by the prompt. We rejected a chat router inside the API process (the model key and a future write path would sit beside the data), calling `Services` directly (it would give the in-product agent a different tool surface from Claude Desktop and Claude Code, so the thing we evaluate would not be the thing people use), and the vendor MCP connector (it needs a publicly reachable server and is not zero-retention eligible). The cost is a second process and an MCP round trip per tool call.
