import base64
import hashlib
import json
from collections.abc import Sequence
from typing import Any

from .errors import DomainError
from .types import Page

DEFAULT_LIMIT = 100
MAX_LIMIT = 1000


def fingerprint(*parts: object) -> str:
    """Identify a query so a cursor can only be replayed against the same query."""
    raw = json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _decode(cursor: str, expected: str) -> int:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        offset, token = int(payload["o"]), payload["q"]
    except (ValueError, KeyError, TypeError):
        raise DomainError("page.cursor_invalid", "Malformed cursor.") from None
    if token != expected or offset < 0:
        raise DomainError("page.cursor_invalid", "Cursor does not belong to this query.")
    return offset


def paginate(items: Sequence[Any], limit: int | None, cursor: str | None, query: str,
             *, default: int = DEFAULT_LIMIT, maximum: int = MAX_LIMIT) -> Page:
    if limit is None:
        limit = default
    if not 1 <= limit <= maximum:
        raise DomainError("request.invalid", f"limit must be between 1 and {maximum}.")
    offset = _decode(cursor, query) if cursor else 0
    end = offset + limit
    following = None
    if end < len(items):
        following = base64.urlsafe_b64encode(json.dumps({"o": end, "q": query}).encode()).decode()
    return {"items": list(items[offset:end]), "total": len(items),
            "next_cursor": following, "truncated": following is not None}
