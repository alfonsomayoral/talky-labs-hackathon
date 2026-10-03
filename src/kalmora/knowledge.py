"""The accounting policies as the assistant cites them: a section index with stable references.

References follow the convention the web app already shows (``§2.2.3``): the heading number, then the number of
the item in a numbered list. Codes the engines emit (``PRICE_VARIANCE``, ``BANK_FEE_NOT_BOOKED``) also get a
named anchor (``§2.2:PRICE_VARIANCE``) so an explanation can cite the exact rule. Pure text processing.
"""
import hashlib
import re
from typing import Any, TypedDict

HEADING = re.compile(r"^(#{1,4})\s+(?:(\d+(?:\.\d+)*)\.?\s+)?(.+?)\s*$")
ITEM = re.compile(r"^\s{0,3}(\d+)\.\s+(.*)$")
CODE = re.compile(r"`([A-Z][A-Z0-9_]{3,})`")
REF = re.compile(r"§\s?(\d+(?:\.\d+)*)(?::([A-Z][A-Z0-9_]{3,}))?")


class Section(TypedDict):
    ref: str
    title: str
    line: int


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_policy(text: str) -> dict[str, Any]:
    """``{sha256, sections: [{ref, title, line}], anchors: [ref]}``; ``anchors`` holds every valid reference."""
    sections: list[Section] = []
    anchors: dict[str, None] = {}
    heading = ""
    item = 0
    for number, line in enumerate(text.splitlines(), 1):
        match = HEADING.match(line)
        if match:
            heading, item = match.group(2) or "", 0
            if heading:
                ref = f"§{heading}"
                sections.append({"ref": ref, "title": match.group(3), "line": number})
                anchors[ref] = None
            continue
        if not heading:
            continue
        entry = ITEM.match(line)
        if entry:
            item = int(entry.group(1))
            ref = f"§{heading}.{item}"
            sections.append({"ref": ref, "title": re.sub(r"[*`]", "", entry.group(2))[:80], "line": number})
            anchors[ref] = None
        for code in CODE.findall(line):
            anchors[f"§{heading}:{code}"] = None
            if item:
                anchors[f"§{heading}.{item}:{code}"] = None
    return {"sha256": sha256_text(text), "sections": sections, "anchors": list(anchors)}


def references(text: str) -> list[str]:
    """Every ``§`` reference written in ``text``, normalised (no space after the sign)."""
    return [f"§{m.group(1)}" + (f":{m.group(2)}" if m.group(2) else "") for m in REF.finditer(text)]
