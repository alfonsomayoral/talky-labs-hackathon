"""Policy, handoff, projection and rerun tests independent of any participant targets."""
import copy
from datetime import date, timedelta
from pathlib import Path
import sys
import unittest

from kalmora.close.contracts import Handoff, SCHEMA, digest, seal
from kalmora.close.engine import CloseEngine
from kalmora.close.projection import project
from kalmora.close.rules import (entry, estimate_daily, fx_difference, impairment_bp, line,
                                month_bounds, prepaid_remaining, uncovered_ranges)
from kalmora.money import RateTable
from kalmora.validation import validate_entry

D = date(2026, 7, 31)
EV = [{"document": "erp/source.json", "field": "observed", "page": None, "quote": "test evidence"}]


def facts(**kwargs):
    return {"accruals": [], "prepaids": [], "pending_certifications": [], "fx_positions": [],
            "ageing_evidence": EV, **kwargs}


def handoff(f=None, postings=(), *, real=False):
    value = {"schema": SCHEMA, "phase": "test_phase", "month": "2026-07", "closing_date": D.isoformat(),
             "sources": {"erp/source.json": "0" * 64}, "facts": f or facts(), "dependencies": []}
    for name in ("ap", "ar_billing", "bank_rec", "ar_cash", "ic"):
        value["dependencies"].append({"producer": name, "phase": "test_phase", "month": "2026-07",
            "provenance": "real" if real else "golden_fixture", "source_sha256": "1" * 64,
            "complete": True, "coverage": {"expected": [], "observed": []},
            "postings": list(postings) if name == "ap" else []})
    if real:
        for dependency in value["dependencies"]:
            if dependency["producer"] == "ic":
                dependency["coverage"].update(mode="reconciled_pairs",
                                              audit_sha256="2" * 64, upstream_sha256="3" * 64)
    return Handoff.from_dict(seal(value))


def journal(lines, *, company="1000", reference="source", when="2026-06-30", source="OPENING", id="original"):
    return {"id": id, "company": company, "reference": reference, "posting_date": when,
            "document_date": when, "source": source, "currency": "MXN" if company == "3100" else "EUR", "lines": lines}


def l(account, amount, company="1000", **kw):
    return line(account, amount, company=company, **kw)


def posting(j, key="source-event", stage="ap.post", event_id="adapter-id"):
    return {"event_id": event_id, "business_key": key, "stage": stage, "journal_entry": j, "evidence": EV}


def engine(es=(), f=None, h=None, customers=(), invoices=(), rates=()):
    return CloseEngine(es, h or handoff(f), RateTable(rates), list(customers), list(invoices))


def prepaid(start="2026-07-01", end="2026-09-30", total=100):
    return {"company": "1000", "invoice": "test-invoice", "start": start, "end": end, "total_local": total,
            "components": [{"account": "62500000", "amount": total, "cost_center": "CC-1000-FIN", "wbs": None}],
            "evidence": EV}


def service(**kw):
    return {"series_id": "service-test", "service_id": "one", "company": "1000", "vendor": "V-test",
            "evidence": EV, "received_coverage": [], "components": [{"account": "62800000", "cost_center": "CC-1000-ADM",
            "samples": [{"amount": 3000, "start": "2026-06-01", "end": "2026-06-30"}]}], **kw}


class PolicyTests(unittest.TestCase):
    def test_month_last_day_leap(self):
        self.assertEqual(month_bounds("2024-02")[1], date(2024, 2, 29))

    def test_bad_month(self):
        with self.assertRaises(ValueError): month_bounds("2026-7")

    def test_monthly_residual(self):
        self.assertEqual(prepaid_remaining(100, date(2026, 6, 1), date(2026, 8, 31), D), 34)
        self.assertEqual(prepaid_remaining(100, date(2026, 6, 1), date(2026, 8, 31), date(2026, 8, 31)), 0)

    def test_prepaid_before_coverage(self):
        self.assertEqual(prepaid_remaining(100, date(2026, 9, 1), date(2026, 12, 31), D), 100)

    def test_prepaid_invalid_input(self):
        for total in (-1, 1.0, True):
            with self.assertRaises((ValueError, TypeError)): prepaid_remaining(total, D, D, D)

    def test_coverage_union(self):
        self.assertEqual(uncovered_ranges(date(2026, 7, 1), D, [(date(2026, 6, 1), date(2026, 7, 10)),
            (date(2026, 7, 5), date(2026, 7, 20))]), [(date(2026, 7, 21), D)])

    def test_daily_mean(self):
        amount, audit = estimate_daily([(300, date(2026, 6, 1), date(2026, 6, 30)),
            (600, date(2026, 6, 1), date(2026, 6, 30)), (3000, date(2026, 6, 1), date(2026, 6, 30))], 5)
        self.assertEqual(amount, 217)
        self.assertEqual(audit["low"], 50)

    def test_no_history_no_estimate(self):
        with self.assertRaises(ValueError): estimate_daily([], 10)

    def test_fx_asset_liability(self):
        rates = RateTable([{"date": "2026-07-30", "currency": "USD", "rate": "2"}])
        self.assertEqual(fx_difference(1000, 400, "USD", "1000", D, rates), (100, 100))
        self.assertEqual(fx_difference(-1000, -400, "USD", "1000", D, rates), (100, -100))

    def test_fx_no_local_or_invented_principal(self):
        for args in [(100, 100, "EUR"), (0, 100, "USD"), (-100, 100, "USD")]:
            with self.assertRaises(ValueError): fx_difference(*args, "1000", D, RateTable([]))

    def test_fx_cross_mxn(self):
        rates = RateTable([{"date": "2026-07-30", "currency": "USD", "rate": "2"},
                           {"date": "2026-07-30", "currency": "MXN", "rate": "20"}])
        self.assertEqual(fx_difference(1000, 9500, "USD", "3100", D, rates), (500, 500))

    def test_strict_ageing_boundaries(self):
        for days, bp in [(180, 0), (181, 5000), (365, 5000), (366, 10000)]:
            with self.subTest(days=days): self.assertEqual(impairment_bp("private", D-timedelta(days=days), D), bp)

    def test_public_group_excluded(self):
        for kind in ("public", "group"):
            self.assertEqual(impairment_bp(kind, None, D, D, guarantee=True), 0)

    def test_insolvency_guarantees(self):
        self.assertEqual(impairment_bp("community", None, D, D, guarantee=True), 10000)
        self.assertEqual(impairment_bp("community", None, D, D+timedelta(days=1), guarantee=True), 0)

    def test_ordinary_guarantees_not_aged(self):
        self.assertEqual(impairment_bp("private", D-timedelta(days=400), D, guarantee=True), 0)

    def test_month_end_entries_only(self):
        with self.assertRaises(ValueError): entry("1000", date(2026, 7, 1), "x", "M6", [l("48000000", 10), l("10000000", -10)])

    def test_cost_object_exclusive(self):
        with self.assertRaises(ValueError): l("62500000", 10, cost_center="one", wbs="other")


class ContractTests(unittest.TestCase):
    def test_complete_real_replacement(self):
        self.assertTrue(handoff().simulated)
        self.assertFalse(handoff(real=True).simulated)
        unaudited = copy.deepcopy(handoff(real=True).payload)
        unaudited["dependencies"][-1]["coverage"].pop("audit_sha256")
        with self.assertRaisesRegex(ValueError, "real IC requires"):
            Handoff.from_dict(seal(unaudited))

    def test_tampered_payload(self):
        h = copy.deepcopy(handoff().payload); h["month"] = "2026-08"
        with self.assertRaises(ValueError): Handoff.from_dict(h)

    def test_missing_dependency(self):
        h = copy.deepcopy(handoff().payload); h["dependencies"].pop()
        with self.assertRaises(ValueError): Handoff.from_dict(seal(h))

    def test_missing_coverage(self):
        h = copy.deepcopy(handoff().payload); h["dependencies"][0]["coverage"]["expected"] = ["invoice"]
        with self.assertRaises(ValueError): Handoff.from_dict(seal(h))

    def test_noncomplete_declared(self):
        h = copy.deepcopy(handoff().payload); h["dependencies"][0]["complete"] = False
        with self.assertRaises(ValueError): Handoff.from_dict(seal(h))

    def test_golden_path_not_source(self):
        h = copy.deepcopy(handoff().payload); h["sources"] = {"golden/close.jsonl": "1" * 64}
        with self.assertRaises(ValueError): Handoff.from_dict(seal(h))

    def test_duplicate_owner(self):
        j = journal([l("48000000", 10), l("10000000", -10)], when="2026-07-01")
        with self.assertRaises(ValueError): handoff(postings=[posting(j), posting(j)])

    def test_cross_phase_posting(self):
        j = journal([l("48000000", 10), l("10000000", -10)], when="2026-08-01")
        with self.assertRaises(ValueError): handoff(postings=[posting(j)])


class ProjectionTests(unittest.TestCase):
    def test_original_immutable_and_once(self):
        original = journal([l("48000000", 10), l("10000000", -10)])
        addition = journal([l("48000000", 5), l("10000000", -5)], when="2026-07-01", id="new", reference="new")
        snapshot = copy.deepcopy(original)
        h = handoff(postings=[posting(addition)])
        result = project([original], h)
        self.assertEqual(original, snapshot)
        self.assertEqual(len(result.recorded.entries), 1)
        self.assertEqual(len(result.pre_close.entries), 2)
        second = project(result.pre_close.entries, h)
        self.assertEqual(len(second.pre_close.entries), 2)

    def test_changed_adapter_id_same_business_not_reposted(self):
        j = journal([l("48000000", 5), l("10000000", -5)], when="2026-07-01")
        first = project([], handoff(postings=[posting(j)]))
        second = project(first.pre_close.entries, handoff(postings=[posting(j, event_id="real-id")], real=True))
        self.assertEqual(len(second.pre_close.entries), 1)

    def test_conflicting_replacement_fails(self):
        j = journal([l("48000000", 5), l("10000000", -5)], when="2026-07-01")
        first = project([], handoff(postings=[posting(j)]))
        changed = journal([l("48000000", 6), l("10000000", -6)], when="2026-07-01")
        with self.assertRaises(ValueError): project(first.pre_close.entries, handoff(postings=[posting(changed)]))

    def test_recorded_alias_no_duplicate(self):
        j = journal([l("48000000", 5), l("10000000", -5)], when="2026-07-01")
        p = dict(posting(j), recorded_ids=[j["id"]])
        self.assertEqual(len(project([j], handoff(postings=[p])).pre_close.entries), 1)

    def test_future_erp_not_posted(self):
        j = journal([l("48000000", 5), l("10000000", -5)], when="2026-08-01")
        self.assertEqual(len(project([j], handoff()).pre_close.entries), 0)


class EngineTests(unittest.TestCase):
    def test_accrual_cost_and_partner(self):
        r = engine(f=facts(accruals=[service()])).run()
        self.assertEqual(r.rows[0]["amount"], 3100)
        self.assertEqual(r.rows[0]["journal_entry"]["lines"][-1]["partner"], "V-test")

    def test_po_grir_and_ic_excluded(self):
        for kwargs in ({"po_required": True}, {"gr_ir_recognized": True}):
            self.assertFalse(engine(f=facts(accruals=[service(**kwargs)])).run().rows)
        self.assertFalse(engine(f=facts(accruals=[service()], ic_owned_services=["one"])).run().rows)

    def test_received_hold_covers_service(self):
        s = service(received_coverage=[{"start": "2026-07-01", "end": "2026-07-31", "decision": "HOLD"}])
        self.assertFalse(engine(f=facts(accruals=[s])).run().rows)

    def test_prior_unreceived_interval_carried(self):
        s = service(window_start="2026-06-16")
        self.assertEqual(engine(f=facts(accruals=[s])).run().rows[0]["amount"], 4600)

    def test_historical_reversal_not_new_output(self):
        before = journal([l("62800000", 100, cost_center="CC-1000-ADM"), l("40090000", -100, partner="V-test")],
                         reference="ACCR-old", source="CLOSE_ACCRUAL")
        reverse = journal([l("62800000", -100, cost_center="CC-1000-ADM"), l("40090000", 100, partner="V-test")],
                          reference="ACCR-old", source="CLOSE_ACCRUAL_REVERSAL", when="2026-07-01", id="reverse")
        r = engine([before, reverse], facts(accruals=[service(historical_references=["ACCR-old"])])).run()
        self.assertEqual(r.rows[0]["amount"], 3100)
        self.assertTrue(all(x["journal_entry"]["posting_date"] == D.isoformat() for x in r.rows))

    def test_unreversed_accrual_subtracted(self):
        before = journal([l("62800000", 100, cost_center="CC-1000-ADM"), l("40090000", -100, partner="V-test")],
                         reference="ACCR-old", source="CLOSE_ACCRUAL")
        r = engine([before], facts(accruals=[service(historical_references=["ACCR-old"])])).run()
        self.assertEqual(r.rows[0]["amount"], 3000)

    def test_prepaid_new_deferral(self):
        r = engine(f=facts(prepaids=[prepaid()])).run()
        self.assertEqual(r.rows[0]["amount"], 67)

    def test_prepaid_consumption(self):
        before = journal([l("48000000", 67), l("10000000", -67)], reference="PREP-test-invoice")
        r = engine([before], facts(prepaids=[prepaid(start="2026-06-01", end="2026-08-31")])).run()
        self.assertEqual(r.rows[0]["amount"], -33)
        self.assertEqual(r.rows[0]["journal_entry"]["lines"][0]["credit"], 33)

    def test_prepaid_final_residual(self):
        before = journal([l("48000000", 34), l("10000000", -34)], reference="PREP-test-invoice")
        r = engine([before], facts(prepaids=[prepaid(start="2026-05-01", end="2026-07-31")])).run()
        self.assertEqual(r.rows[0]["amount"], -34)

    def test_wip_current_not_cumulative(self):
        cert = {"billing_item": "pending", "company": "1000", "customer": "C-test", "project": "OB-test",
                "billing_status": "SKIP_PENDING_APPROVAL", "evidence": EV,
                "certification": {"month": "2026-07", "cumulative": 1000, "previous": 900, "current": 100,
                    "approved": False, "chapters": [{"number": 1, "description": "one", "amount": 35},
                                                     {"number": 2, "description": "two", "amount": 65}]}}
        r = engine(f=facts(pending_certifications=[cert])).run()
        self.assertEqual(r.rows[0]["amount"], 100)
        self.assertEqual(r.rows[0]["journal_entry"]["lines"][1]["wbs"], "OB-test.01")
        cert["certification"]["approved"] = True
        with self.assertRaises(ValueError): engine(f=facts(pending_certifications=[cert])).run()

    def test_fx_after_dependency_adjustment(self):
        before = journal([l("55200000", -21000, "3100", partner="1000", assignment="loan"),
                          l("57200001", 21000, "3100")], company="3100")
        change = journal([l("55200000", -2000, "3100", partner="1000", assignment="loan"),
                          l("66210000", 2000, "3100")], company="3100", when="2026-07-31", id="adj", reference="adj")
        f = facts(fx_positions=[{"company": "3100", "account": "55200000", "partner": "1000", "assignment": "loan",
                  "item": "GL:55200000", "currency": "EUR", "document_signed": -1100, "evidence": EV}])
        r = engine([before], h=handoff(f, [posting(change)]), rates=[{"currency": "MXN", "date": "2026-07-31", "rate": "22"}]).run()
        self.assertEqual(r.rows[0]["amount"], 1200)
        self.assertEqual(r.rows[0]["journal_entry"]["lines"][0]["credit"], 1200)
        self.assertEqual(r.rows[0]["journal_entry"]["lines"][0]["amount_doc"], 0)

    def test_bad_debt_net_of_prior_and_reversal(self):
        cust = [{"id": "C-test", "kind": "private"}]
        inv = [{"id": "invoice", "company": "1000", "due_date": "2025-12-31"}]
        j = journal([l("43000000", 100, partner="C-test", assignment="invoice"), l("49000000", -70, partner="C-test"),
                     l("10000000", -30)])
        r = engine([j], customers=cust, invoices=inv).run()
        self.assertEqual(r.rows[0]["amount"], -20)
        self.assertEqual(r.rows[0]["journal_entry"]["lines"][0]["account"], "79400000")

    def test_legacy_half_cent_impairment(self):
        j = journal([l("43000000", 101, partner="C-test", assignment="invoice"), l("10000000", -101)])
        r = engine([j], customers=[{"id": "C-test", "kind": "community"}],
                   invoices=[{"id": "invoice", "company": "1000", "due_date": "2025-12-31"}]).run()
        self.assertEqual(r.rows[0]["amount"], 50)

    def test_missing_due_not_release(self):
        j = journal([l("43000000", 100, partner="C-test", assignment="unknown"), l("49000000", -50, partner="C-test"), l("10000000", -50)])
        r = engine([j], customers=[{"id": "C-test", "kind": "private"}]).run()
        self.assertFalse(r.rows)
        self.assertFalse(r.complete)

    def test_doubtful_month_once_invoice_grain(self):
        customer = {"id": "C-test", "kind": "private", "insolvency": {"declared_on": "2026-07-15"}}
        j = journal([l("43000000", 100, partner="C-test", assignment="one"),
                     l("43000000", 200, partner="C-test", assignment="two"), l("10000000", -300)])
        r = engine([j], customers=[customer]).run()
        row = next(x for x in r.rows if x["type"] == "DOUBTFUL_RECLASS")
        self.assertEqual(len(row["journal_entry"]["lines"]), 4)
        self.assertEqual(row["amount"], 300)
        self.assertFalse(engine(r.final.entries, customers=[customer]).run().rows)
        customer["insolvency"]["declared_on"] = "2026-06-15"
        self.assertFalse(any(x["type"] == "DOUBTFUL_RECLASS" for x in engine([j], customers=[customer]).run().rows))

    def test_rerun_byte_determinism_and_no_duplicate_close(self):
        f = facts(accruals=[service()], prepaids=[prepaid()])
        first = engine(f=f).run()
        self.assertEqual(digest(first.rows), digest(engine(f=f).run().rows))
        self.assertFalse(engine(first.final.entries, f=f).run().rows)
        self.assertTrue(all(not validate_entry(r["journal_entry"]) for r in first.rows))

    def test_solver_not_import_evaluation_or_fixture(self):
        import kalmora.close.engine as module
        source = Path(module.__file__).read_text()
        self.assertNotIn("import m6_fixture", source)
        self.assertNotIn("import kalmora.evaluation", source)
        self.assertNotIn("open(", source)


if __name__ == "__main__":
    unittest.main()
