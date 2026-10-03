"""Deterministic energy billing calculations from resolved inputs (#62).

POLITICAS_CONTABLES.md §3.1: truncate PPA per plant to cents; market revenue
is plant settlement less deviations. Representative fees belong to AP/netting,
and must not reduce this revenue a second time. All amounts are document cents.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .money import decimal, integer, line_amount


@dataclass(frozen=True)
class EnergyScope:
    company: str
    currency: str
    contract: str
    period: str  # measured/settled period YYYY-MM, not invoice month


@dataclass(frozen=True)
class PlantMeasurement:
    scope: EnergyScope
    plant: str
    mwh_milli: int


@dataclass(frozen=True)
class PlantSettlement:
    scope: EnergyScope
    plant: str
    gross_cents: int  # before deviations AND representative fees
    deviation_cost_cents: int
    representative_fee_cents: int = 0  # informational, excluded from revenue


@dataclass(frozen=True)
class EnergyLine:
    plant: str
    amount_cents: int
    gross_cents: int
    deviation_cost_cents: int = 0
    excluded_representative_fee_cents: int = 0


@dataclass(frozen=True)
class EnergyResult:
    scope: EnergyScope
    kind: str
    lines: tuple[EnergyLine, ...]
    net_cents: int


def _nonnegative(value, name):
    if integer(value, name) < 0:
        raise ValueError(f"{name} must be nonnegative")


def _plants(scope, rows):
    for value in (scope.company, scope.currency, scope.contract):
        if not isinstance(value, str) or not value:
            raise ValueError("nonempty scope references required")
    if date.fromisoformat(scope.period + "-01").strftime("%Y-%m") != scope.period:
        raise ValueError("period must be YYYY-MM")
    rows = tuple(rows)
    if not rows:
        raise ValueError("at least one resolved plant required")
    seen = set()
    for row in rows:
        if row.scope != scope:
            raise ValueError("plant input belongs to another company/currency/contract/period")
        if not isinstance(row.plant, str) or not row.plant or row.plant in seen:
            raise ValueError("unique nonempty plant required")
        seen.add(row.plant)
    return sorted(rows, key=lambda row: row.plant)


def calculate_ppa(*, scope, measurements, share_bp, price_mwh_cents):
    """Measured MWh × explicit contract share × fixed cents/MWh, truncated.

    Truncate each plant's amount independently, then sum; zero production/share
    is supported. No floats, negative measurements or unresolved plant ownership.
    """
    if not 0 <= integer(share_bp, "share_bp") <= 10000:
        raise ValueError("share_bp must be between 0 and 10000")
    price = decimal(price_mwh_cents)
    if price < 0:
        raise ValueError("PPA price must be nonnegative")
    lines = []
    for measurement in _plants(scope, measurements):
        _nonnegative(measurement.mwh_milli, "mwh_milli")
        amount = line_amount(measurement.mwh_milli, price,
                             share=Decimal(share_bp).scaleb(-4), truncate=True)
        lines.append(EnergyLine(measurement.plant, amount, amount))
    return EnergyResult(scope, "PPA", tuple(lines), sum(line.amount_cents for line in lines))


def calculate_market(*, scope, settlements):
    """Plant gross settlement minus explicit plant deviation costs.

    Gross must be normalized BEFORE fees/deviations. Negative source deviations
    must be resolved to positive costs by the adapter. Aggregate deviations need
    an explicit plant allocation upstream; this core invents no apportionment.
    Fees reported separately remain informational and are never subtracted here.
    """
    lines = []
    for settlement in _plants(scope, settlements):
        for name in ("gross_cents", "deviation_cost_cents", "representative_fee_cents"):
            _nonnegative(getattr(settlement, name), name)
        lines.append(EnergyLine(settlement.plant,
                                settlement.gross_cents - settlement.deviation_cost_cents,
                                settlement.gross_cents, settlement.deviation_cost_cents,
                                settlement.representative_fee_cents))
    return EnergyResult(scope, "MARKET", tuple(lines), sum(line.amount_cents for line in lines))
