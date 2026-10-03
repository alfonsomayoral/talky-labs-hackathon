from typing import NamedTuple

from .scalars import AccountCode, CompanyCode, PartnerCode


class OpenItemKey(NamedTuple):
    """Identity of an open item (*partida abierta*): the thing that gets cleared.

    An open item is an individual amount awaiting settlement on a vendor, customer or
    intercompany account, e.g. one invoice. Its identity is four-dimensional:
    ``(company, account, partner, assignment)``. Postings that share the key are
    aggregated; when they sum to zero the item is **cleared**, otherwise the residual is
    what is still owed or due.

    This is why ``assignment`` matters as much as ``partner``: paying invoice A must find
    item A, and a payment that cannot be assigned leaves a residual instead of silently
    reducing an aggregate vendor balance.

    Aggregation is over the whole loaded journal and **does not cut by date**.
    """

    company: CompanyCode
    account: AccountCode
    partner: PartnerCode | None
    """Counterparty. Source records may lack it; validation still requires a
    partner on adjustments to open-item accounts."""

    assignment: str | None
    """Source or clearing document (invoice number, ``order/position``, ``PAG<n>``)."""
