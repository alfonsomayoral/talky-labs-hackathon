from typing import TypedDict

from .scalars import CompanyCode, Currency


class Company(TypedDict):
    """Legal entity of Grupo Kalmora (``erp/companies.json``).

    Each company keeps its own books: its entries, local currency and balances. The
    group has seven entities (the holding, the construction company, the UTE joint
    venture and the Mexican subsidiary among them), so anything intercompany must be
    seen from both sides and has to eliminate on consolidation (policy §6).
    """

    code: CompanyCode
    name: str
    short: str

    country: str
    """Two-letter ISO country. Drives tax treatment (Spain, Portugal and Mexico each have
    their own VAT/withholding regimes in the policies)."""

    currency: Currency
    """Local (functional) currency, in which the books are kept: EUR, except MXN for 3100."""

    role: str
    """Function in the group (``holding``, ``construction``...)."""

    city: str
    street: str
    postal_code: str
    tax_id: str
    """Tax identification number. A missing recipient tax id on a vendor invoice is a
    ``MANDATORY_FIELD_MISSING`` rejection."""

    vat_id: str

    partners: object | None
    """Other partners of the entity (relevant to a joint venture). ``null`` in the July data;
    no semantics are confirmed."""
