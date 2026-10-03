"""Semantic aliases for the scalar values of the Kalmora accounting domain.

They are transparent aliases of ``int`` or ``str``: runtime behavior is unchanged,
but every signature states *which* unit or identity is expected. That matters here
because the same ``int`` can be local cents, document cents or thousandths of a
unit, and mixing them silently produces wrong books.

Money is always integer cents (policy §1): there is no float anywhere in the
accounting path, and a ``float`` or ``bool`` is rejected at the boundary.
"""

type Cents = int
"""Amount in whole cents of the company's **local currency** (EUR; MXN for company 3100).

This is the unit of ``debit``, ``credit`` and every balance. A foreign-currency
document is converted to it at the SYN-BCE rate of the invoice date, rounding line
by line; the vendor or customer line absorbs the rounding difference (policy §1).
Never ``float`` or ``bool``."""

type DocCents = int
"""Amount in whole cents of the line's **document currency** (its ``currency``).

Kept intact for traceability: it is the amount the vendor or customer actually
invoiced (e.g. USD for a US supplier) and is never recomputed from ``Cents``.
Unsigned: whether it is a debit or a credit is told by ``debit``/``credit``."""

type Milli = int
"""Quantity in thousandths of a unit (1.5 units = 1500).

Purchase-order and receipt quantities allow at most three decimals, so they are
held exactly as integers; ``quantity x unit price`` is then rounded once to cents."""

type CompanyCode = str
"""Four-digit code of a legal entity of Grupo Kalmora.

``1000`` holding, ``1100`` construction, ``1200``, ``1300``, ``1910`` (the UTE joint
venture), ``2100`` and ``3100`` (Mexico). Each company records its own entries, in
its own local currency, and balances are never mixed across companies."""

type AccountCode = str
"""Eight-digit ledger account (Spanish PGC-style chart, zero-padded).

The leading digits carry meaning: ``40x`` vendors, ``43x`` customers, ``47x`` taxes,
``55x`` current accounts/factoring, ``572`` banks, ``6xxxxxxx`` expenses,
``7xxxxxxx`` income and ``2xxxxxxx`` fixed assets. Expense, income and fixed-asset
accounts require a cost object (cost center or WBS element)."""

type PartnerCode = str
"""Business partner of a line; *which kind* depends on the account (policy §1).

* vendor id (``V100123``) on 400/410/403/407/40000900/40090000;
* customer id (``C200001``) on 430/431/436/438/43000900/43090000/49000000;
* another group company's code on the intercompany accounts 5520/5521/5522/2423/1633;
* the literal ``FACTOR-BAE`` on 55300000 (factoring)."""

type Currency = str
"""Three-letter uppercase ISO 4217 code (EUR, MXN, USD, GBP...)."""

type IsoDate = str
"""Calendar date as ``YYYY-MM-DD``.

Compared lexicographically, so it must be zero-padded and normalized."""

type Month = str
"""Close month as ``YYYY-MM``; the period a phase's close task refers to."""
