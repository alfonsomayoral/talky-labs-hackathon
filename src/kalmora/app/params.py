"""Validation of query parameters shared by every adapter."""
import re
from datetime import date

from .errors import DomainError


def iso_date(name: str, value: str | None) -> str | None:
    if value is None:
        return None
    try:
        if date.fromisoformat(value).isoformat() == value:
            return value
    except ValueError:
        pass
    raise DomainError("request.invalid", f"{name} must be a YYYY-MM-DD date.")


def month(name: str, value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) == 7 and value[4] == "-" and value[:4].isdigit() and value[5:].isdigit() \
            and 1 <= int(value[5:]) <= 12:
        return value
    raise DomainError("request.invalid", f"{name} must be YYYY-MM.")


def one_of(name: str, value: str | None, allowed: tuple[str, ...]) -> str | None:
    if value is not None and value not in allowed:
        raise DomainError("request.invalid", f"{name} must be one of: {', '.join(allowed)}.")
    return value


def compact(**filters: object) -> dict[str, object]:
    """Keep only the filters that were supplied."""
    return {key: value for key, value in filters.items() if value is not None}


_PHASE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def valid_phase_name(name: str) -> bool:
    """Phase names come from a folder inside an uploaded ZIP and end up in URLs and in the close
    command's arguments, so they must be plain: no leading dash, separators or spaces."""
    return bool(_PHASE_NAME.match(name)) and name not in {".", ".."}
