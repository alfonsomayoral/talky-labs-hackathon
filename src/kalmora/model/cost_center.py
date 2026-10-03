from typing import TypedDict

from .scalars import CompanyCode


class CostCenter(TypedDict):
    """Cost center (``erp/cost_centers.jsonl``): an organizational unit that absorbs
    overhead and service costs or revenue (management, finance, IT...).

    Belongs to a single company. It is the alternative to a construction WBS element:
    a line carries one or the other, never both (policy §1) — jobs charge to the WBS
    element, structure and services to the cost center.
    """

    id: str
    company: CompanyCode
    """Owning company; a line of another company cannot use it."""

    desc: str
