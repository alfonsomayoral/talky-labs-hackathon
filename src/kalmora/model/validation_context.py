from collections.abc import Collection, Mapping
from typing import TypedDict

from .scalars import IsoDate


class ValidationContext(TypedDict, total=False):
    """Master data that turns on the *existence* checks of ``validate_entry``.

    Structural rules (balance, formats, partner kind, cost-object exclusivity) need no
    context. Whether an account, partner or cost center actually *exists* is only
    knowable against the phase's masters, so each check activates only when its key is
    supplied: omit ``accounts`` and an invented account number passes silently.

    Each value may be a set of ids or an ``id -> record`` mapping; use the mapping form
    when records carry their owning company.
    """

    companies: Collection[str]
    accounts: Collection[str]
    partners: Collection[str]
    """Valid partner ids across vendors, customers, group companies and ``FACTOR-BAE``."""

    cost_centers: Collection[str] | Mapping[str, Mapping[str, object]]
    """If a mapping and the record has ``company``, the cost center must belong to the
    entry's company."""

    wbs: Collection[str] | Mapping[str, Mapping[str, object]]
    """Construction WBS elements; same rules as ``cost_centers``."""

    min_date: IsoDate
    """Earliest allowed ``posting_date`` (inclusive): the start of the close window."""

    max_date: IsoDate
    """Latest allowed ``posting_date`` (inclusive): the end of the close month."""
