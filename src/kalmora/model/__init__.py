"""Backend data model: shapes of the data, no logic.

One module per type. The ``TypedDict`` classes describe the JSON dictionaries as
they arrive from the ERP, so they do not change runtime behavior. Balance and
open-item keys are ``NamedTuple`` and remain tuples.
"""
from .account import Account
from .balance_key import BalanceKey
from .bank_line import BankLine
from .company import Company
from .cost_center import CostCenter
from .cost_summary import CostSummary
from .diagnostic import Diagnostic
from .fx_rate import FxRate
from .journal_entry import JournalEntry
from .journal_line import JournalLine
from .manifest import Manifest
from .manifest_file import ManifestFile
from .manifest_phase import ManifestPhase
from .open_item import OpenItem
from .open_item_key import OpenItemKey
from .pricing import Pricing, PricingInput
from .provenance import Provenance
from .run_call import RunCall
from .run_report import RunReport
from .scalars import (AccountCode, CompanyCode, Cents, Currency, DocCents, IsoDate,
                      Milli, Month, PartnerCode)
from .trace import (AttentionItem, Evidence, ModelCall, ModelUsage, Override, RunManifest, TraceEvent,
                    TaskTiming)
from .validation_context import ValidationContext

__all__ = [
    "Account", "AccountCode", "BalanceKey", "BankLine", "Cents", "Company", "CompanyCode",
    "CostCenter", "CostSummary", "Currency", "Diagnostic", "DocCents", "FxRate", "IsoDate",
    "JournalEntry", "JournalLine", "Manifest", "ManifestFile", "ManifestPhase", "Milli",
    "Month", "OpenItem", "OpenItemKey", "PartnerCode", "Pricing", "PricingInput",
    "AttentionItem", "Evidence", "ModelCall", "ModelUsage", "Override", "RunManifest", "TaskTiming",
    "TraceEvent", "Provenance", "RunCall", "RunReport", "ValidationContext",
]
