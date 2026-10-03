"""Checks on a finished answer: grounded figures and ids, valid policy references, plain text.

The model never types a figure into a card; this guards the free text. A number is *grounded* when it appears in a
tool result of the turn (cents also as euros), in a ``calculate`` result, in the knowledge pack or in the user's message.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from ..knowledge import REF
from .tools import ITEM_ID, walk_json

_MASKS = [
    re.compile(r"\b(?:ap|ar_billing|ar_cash|bank_rec|ic|close):[^\s,;?¿!¡)\]\"']+"),   # item ids
    re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ][\d:.+Zz-]+)?"),                           # dates and timestamps
    re.compile(r"\d{4}-\d{2}\b"),                                                    # months
    re.compile(r"§\s?\d+(?:\.\d+)*(?::[A-Z][A-Z0-9_]*)?"),                           # policy references
    re.compile(r"\b[A-Za-z][A-Za-z_-]*[-_]?\d[\w.-]*\b"),                            # BL0000650, V100123, OB-1100-2514.04
    re.compile(r"\b\d{8}\b"),                                                        # account codes
]
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_IN_TEXT = re.compile(r"\d+(?:[.,]\d+)*")


def _decimal(text: str) -> Decimal | None:
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def candidates(token: str) -> set[Decimal]:
    """Every reading of a written number: ``1.234,56`` (es), ``1,234.56`` (en), ``1.234`` (thousands or decimal)."""
    out: set[Decimal] = set()
    if "." in token and "," in token:
        decimal_sep = "," if token.rfind(",") > token.rfind(".") else "."
        group = "." if decimal_sep == "," else ","
        value = _decimal(token.replace(group, "").replace(decimal_sep, "."))
        if value is not None:
            out.add(value)
    elif "." in token:
        if re.fullmatch(r"\d{1,3}(\.\d{3})+", token):
            out.add(Decimal(token.replace(".", "")))
        value = _decimal(token)
        if value is not None:
            out.add(value)
    elif "," in token:
        if re.fullmatch(r"\d{1,3}(,\d{3})+", token):
            out.add(Decimal(token.replace(",", "")))
        value = _decimal(token.replace(",", "."))
        if value is not None:
            out.add(value)
    else:
        value = _decimal(token)
        if value is not None:
            out.add(value)
    return out


def _norm(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.000001")).normalize()


def allowed_numbers(*sources: Any) -> set[Decimal]:
    """Numbers found in tool results and other trusted text. Integers also count as cents (value / 100)."""
    allowed: set[Decimal] = set()
    for source in sources:
        for scalar in walk_json(source):
            if isinstance(scalar, bool) or scalar is None:
                continue
            if isinstance(scalar, (int, float, Decimal)):
                value = abs(Decimal(str(scalar)))   # a balance of -40,00 is written "40,00 EUR a pagar"
                allowed.add(_norm(value))
                if isinstance(scalar, int):
                    allowed.add(_norm(value / 100))
            elif isinstance(scalar, str):
                for token in _IN_TEXT.findall(scalar):
                    for value in candidates(token):
                        allowed.add(_norm(value))
                        if value == value.to_integral():
                            allowed.add(_norm(value / 100))
    return allowed


def mask(text: str) -> str:
    for pattern in _MASKS:
        text = pattern.sub(" ", text)
    return text


@dataclass
class GuardResult:
    text: str
    ungrounded_numbers: list[str] = field(default_factory=list)
    ungrounded_items: list[str] = field(default_factory=list)
    removed_policy_refs: list[str] = field(default_factory=list)
    policy_refs: list[str] = field(default_factory=list)
    items: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.ungrounded_numbers or self.ungrounded_items)


SMALL = {Decimal(n) for n in range(0, 13)}


def check_numbers(text: str, allowed: set[Decimal]) -> list[str]:
    bad = []
    for token in _NUMBER.findall(mask(text)):
        options = candidates(token)
        if not options:
            continue
        if any(_norm(v) in allowed or v in SMALL for v in options):
            continue
        bad.append(token)
    return bad


def sanitize(text: str) -> str:
    """Plain text only: no Markdown links or images, URLs, HTML, code fences or emphasis markers."""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"```\w*", "", text)
    text = re.sub(r"(\*\*|__|`)", "", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)
    return re.sub(r"[ \t]+\n", "\n", re.sub(r"[ \t]{2,}", " ", text)).strip()


def strip_policy_refs(text: str, valid: set[str]) -> tuple[str, list[str], list[str]]:
    """Remove ``§`` references that are not in the index. Returns (text, removed, kept)."""
    removed: list[str] = []
    kept: list[str] = []

    def replace(match: re.Match[str]) -> str:
        ref = f"§{match.group(1)}" + (f":{match.group(2)}" if match.group(2) else "")
        if ref in valid:
            kept.append(ref)
            return match.group(0)
        removed.append(ref)
        return ""

    cleaned = REF.sub(replace, text) if removed or REF.search(text) else text
    if removed:   # no dangling "y ." / "( )" where a reference was removed
        cleaned = re.sub(r"\s+(?:y|e|o|u)\s*(?=[.;,)])", "", cleaned)
        cleaned = re.sub(r"\(\s*(?:véase|ver|cf\.?|según)?\s*\)", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\(\s*\)|\s+(?=[.;,])", lambda m: "" if m.group(0).strip() == "" or m.group(0) == "()" else m.group(0), cleaned)
    return re.sub(r"  +", " ", cleaned), removed, kept


def check_answer(text: str, *, tool_results: list[Any], tool_text: str, trusted: list[Any],
                 valid_refs: set[str], user_text: str = "") -> GuardResult:
    """Sanitise, then verify figures, item ids and policy references."""
    clean = sanitize(text)
    clean, removed, kept = strip_policy_refs(clean, valid_refs)
    allowed = allowed_numbers(*tool_results, *trusted)
    items = sorted(set(m.rstrip(".") for m in ITEM_ID.findall(clean)))
    return GuardResult(
        text=clean,
        ungrounded_numbers=check_numbers(clean, allowed),
        ungrounded_items=[i for i in items if i not in tool_text and i not in user_text],
        removed_policy_refs=removed, policy_refs=sorted(set(kept)),
        items=[i for i in items if i in tool_text])
