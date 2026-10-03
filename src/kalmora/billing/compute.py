"""Pure AR arithmetic (policies §1 and §3.1): taxes, guarantee, Mexican deductions, energy.

Integer cents and exact ``Decimal``; VAT is calculated on the invoice net total (the ERP
history does the same, which per-line rounding does not reproduce). No document or ERP
access: callers pass resolved values.
"""
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, localcontext

from ..model import Cents, Milli
from ..money import decimal, integer, round_cents

MX_LEVY_BP = 50
"""5 al millar: 0.5 % of the base."""


def percentage(amount: Cents, bp: int) -> Cents:
    """``amount`` x ``bp`` / 10,000 rounded half up to cents."""
    with localcontext() as ctx:
        ctx.prec = 50
        return round_cents(Decimal(integer(amount)) * integer(bp, "bp") / 10000)


@dataclass(frozen=True, slots=True)
class Amounts:
    net: Cents
    tax: Cents
    gross: Cents
    retention: Cents
    levy: Cents
    advance: Cents
    payable: Cents


def invoice_amounts(*, net: Cents, tax_rate_bp: int, retention_bp: int = 0, mx_levy: bool = False,
                    advance_bp: int = 0, advance_available: Cents = 0) -> Amounts:
    """Tax on net, guarantee on net, 5-per-mille on net, advance on gross capped by the balance."""
    if not 0 <= retention_bp <= 10000 or not 0 <= advance_bp <= 10000:
        raise ValueError("rates must be between 0 and 10000 bp")
    if advance_available < 0:
        raise ValueError("advance balance cannot be negative")
    tax = percentage(net, tax_rate_bp)
    gross = net + tax
    retention = percentage(net, retention_bp)
    levy = percentage(net, MX_LEVY_BP) if mx_levy else 0
    advance = min(percentage(gross, advance_bp), advance_available) if advance_bp else 0
    payable = gross - retention - levy - advance
    if payable < 0:
        raise ValueError("deductions exceed the invoice gross")
    return Amounts(net, tax, gross, retention, levy, advance, payable)


def ppa_net(*, mwh_milli: tuple[Milli, ...], share_bp: int, price_mwh_cents: Decimal) -> Cents:
    """Contracted energy = total measured MWh x share truncated to 0.001 MWh; x price truncated to cents."""
    if not 0 <= integer(share_bp, "share_bp") <= 10000:
        raise ValueError("share_bp must be between 0 and 10000")
    price = decimal(price_mwh_cents)
    if price < 0 or any(integer(m, "mwh_milli") < 0 for m in mwh_milli):
        raise ValueError("energy and price must be nonnegative")
    with localcontext() as ctx:
        ctx.prec = 50
        contracted = (Decimal(sum(mwh_milli)) * share_bp / 10000).to_integral_value(rounding=ROUND_DOWN)
        return round_cents(contracted / 1000 * price, truncate=True)
