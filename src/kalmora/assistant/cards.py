"""``present``: build the web app's cards on the server from a stored tool result, so no figure is typed by the model."""
from __future__ import annotations

from typing import Any

from .tools import ITEM_ID

TASKS = ("ap", "ar_billing", "ar_cash", "bank_rec", "ic", "close")
FORMATS = ("text", "mono", "number", "percent", "money")
MAX_ROWS = 15


class PresentError(Exception):
    """Returned to the model as a tool error so it can correct the call."""


def _pointer(document: Any, path: str) -> Any:
    node = document
    for part in [p for p in path.split("/") if p != ""]:
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            raise PresentError(f"select.path '{path}' does not exist in the result (stopped at '{part}').")
    return node


def _field(row: Any, name: str) -> Any:
    node = row
    for part in name.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            raise PresentError(f"field '{name}' is not in the rows. Available: {', '.join(map(str, row)) if isinstance(row, dict) else 'none'}.")
    return node


def _money(cents: Any, currency: str | None) -> dict[str, Any]:
    if isinstance(cents, bool) or not isinstance(cents, int):
        raise PresentError("a money column needs an integer number of cents.")
    if not currency:
        raise PresentError("a money column needs a currency: add select.currency or currency_field.")
    return {"kind": "money", "amounts": [{"cents": cents, "currency": currency}]}


def _cell(row: dict[str, Any], column: dict[str, Any], currency: str | None) -> dict[str, Any]:
    fmt = column.get("format", "text")
    if fmt not in FORMATS:
        raise PresentError(f"format must be one of: {', '.join(FORMATS)}.")
    value = _field(row, column["field"])
    if fmt == "money":
        cur = row.get(column["currency_field"]) if column.get("currency_field") else column.get("currency")
        return _money(value, cur or currency)
    if fmt == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise PresentError(f"column '{column['field']}' is not a number.")
        return {"kind": "number", "value": value}
    if fmt == "percent":
        return {"kind": "percent", "value": value}
    return {"kind": "mono" if fmt == "mono" else "text", "text": "—" if value is None else str(value)}


def build_card(args: dict[str, Any], results: dict[str, Any]) -> dict[str, Any]:
    """Validate ``present`` arguments and copy values out of ``results[source_call]``."""
    kind = args.get("type")
    title = args.get("title")
    if kind == "process":
        if args.get("task") not in TASKS:
            raise PresentError(f"task must be one of: {', '.join(TASKS)}.")
        return {"type": "process", "task": args["task"]}
    source = args.get("source_call")
    if source not in results:
        raise PresentError(f"source_call '{source}' is not a tool call of this turn. Use the 'id' of an earlier result.")
    select = args.get("select") or {}
    node = _pointer(results[source], select.get("path", "/result"))
    currency = select.get("currency")
    columns = select.get("columns") or []
    card: dict[str, Any]
    if kind == "metric":
        if not isinstance(node, dict):
            raise PresentError("a metric card needs select.path to point to one object.")
        if not columns:
            raise PresentError("a metric card needs select.columns: [{label, field, format}].")
        metrics = []
        for column in columns:
            cell = _cell(node, column, currency)
            value = {"kind": "number", "value": cell["value"]} if cell["kind"] == "number" else \
                    {"kind": "percent", "value": cell["value"]} if cell["kind"] == "percent" else \
                    {"kind": "money", "cents": cell["amounts"][0]["cents"], "currency": cell["amounts"][0]["currency"]} if cell["kind"] == "money" else \
                    {"kind": "text", "text": cell["text"]}
            metrics.append({"label": str(column.get("label", column["field"])), "value": value})
        card = {"type": "metric", "metrics": metrics}
    elif kind in ("table", "items"):
        if not isinstance(node, list) or not node:
            raise PresentError(f"a {kind} card needs select.path to point to a non-empty list.")
        total = len(node)
        rows = node[: min(int(select.get("limit", MAX_ROWS)), MAX_ROWS)]
        if kind == "table":
            if not columns:
                raise PresentError("a table card needs select.columns: [{label, field, format}].")
            card = {"type": "table",
                    "columns": [{"label": str(c.get("label", c["field"])),
                                 "align": "right" if c.get("format") in ("money", "number", "percent") else "left"} for c in columns],
                    "rows": [[_cell(r, c, currency) for c in columns] for r in rows]}
        else:
            item_field = select.get("item_field", "item")
            items = []
            for r in rows:
                item = _field(r, item_field)
                if not isinstance(item, str) or not ITEM_ID.fullmatch(item):
                    raise PresentError(f"'{item}' is not an item id (<task>:<key>).")
                entry: dict[str, Any] = {"item": item}
                if select.get("title_field"):
                    entry["title"] = str(_field(r, select["title_field"]))
                if select.get("amount_field"):
                    entry["amount"] = _field(r, select["amount_field"])
                    entry["currency"] = (r.get(select["currency_field"]) if select.get("currency_field") else currency)
                if select.get("priority_field"):
                    entry["priority"] = _field(r, select["priority_field"])
                items.append(entry)
            card = {"type": "items", "items": items, "total": total}
    elif kind == "reasoning":
        row = node
        if not isinstance(row, dict) or "item" not in row:
            raise PresentError("a reasoning card needs select.path to point to a get_run_item result (it has 'item').")
        steps = [{"key": e.get("event_id"), "kind": e.get("kind"), "result": e.get("result", "INFO"),
                  "title": e.get("summary") or e.get("step") or "", "evidence": e.get("evidence") or [],
                  "model": e.get("model"), "confidence": e.get("confidence"), "ts": e.get("ts")}
                 for e in row.get("events") or []]
        facts = []
        for column in columns:
            cell = _cell(row.get("row") or {}, column, currency)
            label = str(column.get("label", column["field"]))
            facts.append({"label": label, "cents": cell["amounts"][0]["cents"], "currency": cell["amounts"][0]["currency"]}
                         if cell["kind"] == "money" else {"label": label, "mono": cell["text"]} if cell["kind"] == "mono"
                         else {"label": label, "text": str(cell.get("text", cell.get("value")))})
        card = {"type": "reasoning", "item": row["item"], "headline": str(args.get("headline", "")), "facts": facts, "steps": steps}
    else:
        raise PresentError("type must be one of: metric, table, items, reasoning, process.")
    if title and kind != "reasoning":
        card["title"] = str(title)
    return card
