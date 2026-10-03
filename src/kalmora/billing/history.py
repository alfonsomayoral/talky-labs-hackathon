"""Facts from ``erp/billing_history.jsonl``: the structured twin of the billing documents.

Each history record carries what the document of that month stated (certification chapters,
service fee and extras, decree, production, settlement). Replaying them through the engine
reproduces past invoices, which is how the rules are checked without the golden or the PDFs.
"""
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from .inputs import (BillingFacts, Chapter, CertificationFacts, ExtraService, PlantMwh, PlantSettlement,
                     PpaFacts, RevisionFacts, ServiceFacts, SettlementFacts)
from .model import BillingItem, BillingType


def item_from_history(row: Mapping[str, Any]) -> BillingItem:
    return BillingItem(row["id"], BillingType(row["type"]), row["company"], row["contract"],
                       row["customer"], row["month"])


def facts_from_history(row: Mapping[str, Any]) -> BillingFacts:
    kind = BillingType(row["type"])
    if kind is BillingType.OBRA_CERTIFICATION:
        cert = row["cert"]
        chapters = tuple(Chapter(i, line["desc"], line["amount"]) for i, line in enumerate(cert["lines"], 1))
        return CertificationFacts(cert["month"], chapters, cert["cumulative"], cert["previous"],
                                  cert["current"], bool(cert["approved"]))
    if kind is BillingType.SERVICE_MONTHLY:
        extras = tuple(ExtraService(e["order"], e["desc"], e["amount"], bool(e["approved"]))
                       for e in row["extra_services"])
        return ServiceFacts(row["month"], row["fee"], extras)
    if kind is BillingType.PRICE_REVISION:
        rev = row["revision"]
        return RevisionFacts(rev["old_fee"], rev["new_fee"], rev["effective"], rev["approved_on"],
                             tuple(rev["months"]), rev.get("decree", ""))
    if kind is BillingType.PPA:
        prod = row["production"]
        return PpaFacts(prod["period"], tuple(PlantMwh(p["plant"], p["mwh_milli"]) for p in prod["plants"]),
                        prod["share_bp"], Decimal(str(prod["price_eur_mwh"])) * 100)
    sett = row["settlement"]
    return SettlementFacts(sett["period"], tuple(PlantSettlement(p["plant"], p["amount"], p["mwh_milli"])
                                                 for p in sett["plants"]), sett["deviations"])
