"""Resolved document facts the billing engine consumes (the contract with document reading).

The reader (PDF/XML) must deliver one of these per billing item, with exact integers:
money in local cents, energy in thousandths of MWh, dates as ``YYYY-MM-DD``. Anything
the document does not state stays out; the engine takes prices, terms and ownership from
the ERP masters and cross-checks the document against them.
"""
from dataclasses import dataclass
from decimal import Decimal

from ..model import Cents, IsoDate, Milli, Month
from ..facts import Evidence


@dataclass(frozen=True, slots=True)
class Chapter:
    number: int
    """1-based chapter, mapped to ``<project>.0<number>``."""
    description: str
    amount: Cents


@dataclass(frozen=True, slots=True)
class CertificationFacts:
    month: Month
    chapters: tuple[Chapter, ...]
    cumulative: Cents
    previous: Cents
    current: Cents
    approved: bool
    """True only for an explicit approval stamp; pending or ``No facturar`` is False."""
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, slots=True)
class ExtraService:
    order: str
    description: str
    amount: Cents
    approved: bool
    """Municipal technician's conformity."""


@dataclass(frozen=True, slots=True)
class ServiceFacts:
    month: Month
    canon: Cents
    extras: tuple[ExtraService, ...] = ()
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, slots=True)
class RevisionFacts:
    old_fee: Cents
    new_fee: Cents
    effective: IsoDate
    approved_on: IsoDate
    months: tuple[Month, ...]
    """Months billable by the decree, as listed in it."""
    decree: str = ""
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, slots=True)
class PlantMwh:
    plant: str
    """Cost-center id of the plant (resolve from the printed name via the cost-center master)."""
    mwh_milli: Milli


@dataclass(frozen=True, slots=True)
class PpaFacts:
    period: Month
    plants: tuple[PlantMwh, ...]
    share_bp: int
    price_mwh_cents: Decimal
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, slots=True)
class PlantSettlement:
    plant: str
    amount: Cents
    """Energy settlement of the plant before deviations; representative fees are not included."""
    mwh_milli: Milli | None = None


@dataclass(frozen=True, slots=True)
class SettlementFacts:
    period: Month
    plants: tuple[PlantSettlement, ...]
    deviations: Cents
    """Signed as in the report: a deviation cost is negative."""
    evidence: tuple[Evidence, ...] = ()


type BillingFacts = CertificationFacts | ServiceFacts | RevisionFacts | PpaFacts | SettlementFacts
