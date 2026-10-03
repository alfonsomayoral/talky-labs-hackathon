"""AR exact/semantic reference boundaries without provider access."""
from dataclasses import replace
import json
import unittest

from kalmora.billing.model import BillingItem, BillingType
from kalmora.billing.observations import BillingObservations
from kalmora.billing.resolution import (billing_contract_request, billing_customer_request,
                                        billing_plant_request, resolve_billing_references)
from kalmora.documents.contracts import ParsedBlock, ParsedDocument, ResolutionResult
from kalmora.facts import DocumentFacts, Evidence, Fact


class Masters:
    """Independent in-memory master rows; no filesystem or mutable source inputs."""
    def __init__(self):
        self.rows = {
            "customers": [{"id": "C1", "name": "Municipality", "tax_id": "T1", "dir3": {}},
                          {"id": "C2", "name": "Other customer"}],
            "sales_contracts": [{"id": "CT1", "company": "1300", "customer": "C1", "kind": "ppa",
                                 "name": "Energy contract", "plants": ["P1", "P2"], "tax": "R21"},
                                {"id": "CT2", "company": "1300", "customer": "C1", "kind": "ppa",
                                 "name": "Other contract", "plants": ["P3"]},
                                {"id": "CT3", "company": "1200", "customer": "C1", "kind": "ppa",
                                 "name": "Foreign company contract", "plants": ["PF"]}],
            "cost_centers": [{"id": "P1", "company": "1300", "desc": "Campollano I"},
                             {"id": "P2", "company": "1300", "desc": "Lomaseca"},
                             {"id": "P3", "company": "1300", "desc": "Other contract plant"},
                             {"id": "PF", "company": "1200", "desc": "Foreign plant"}],
        }

    def table(self, name):
        return self.rows[name]

    def find(self, name, **criteria):
        return [row for row in self.rows[name] if all(row.get(key) == value for key, value in criteria.items())]

    def get(self, name, identity):
        return next(row for row in self.rows[name] if row["id"] == identity)


class FakeResolver:
    def __init__(self, selected="P1", status="SELECTED", *, wrong_proof=False):
        self.selected, self.status, self.wrong_proof = selected, status, wrong_proof
        self.requests = []

    async def resolve(self, request):
        self.requests.append(request)
        if self.status != "SELECTED":
            return ResolutionResult(self.status, (), (), "source cannot distinguish candidates")
        candidate = next(candidate for candidate in request.candidates if candidate.id == self.selected)
        reference = request.context["reference"]
        proof = {"candidate_id": self.selected, "candidate_attribute": "name",
                 "candidate_value": candidate.attributes["name"],
                 "source_value": "Other" if self.wrong_proof else reference,
                 "block_id": "other" if self.wrong_proof else "page.1",
                 "quote": "Other" if self.wrong_proof else reference,
                 "source_sha256": request.document.source_sha256}
        return ResolutionResult("SELECTED", (self.selected,), (proof,), "printed alias identifies this plant")


class BillingResolutionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.data = Masters()
        self.item = BillingItem("B1", BillingType.PPA, "1300", "CT1", "C1", "2026-07")
        self.document = ParsedDocument("inbox/ar/billing/B1/meter.pdf", "a" * 64,
                                       "application/pdf", "fixture", (ParsedBlock("page.1",
                                       "Campollano I Lomaseca Campo Uno CT1 CT2 Energy contract MUNICIPALITY Other customer", 1),
                                       ParsedBlock("other", "Other", 2)))

    def observations(self, reference="Campollano I", **fields):
        values = {"plant.1.reference": [reference], **fields}
        facts = {field: [Fact(value, Evidence(self.document.path, "page.1", 1, str(value)))
                         for value in (entries if isinstance(entries, list) else [entries])]
                 for field, entries in values.items()}
        return BillingObservations(self.item.type, DocumentFacts(self.document.source_sha256, "fixture", facts),
                                   {"plant": 1})

    async def test_exact_references_do_not_call_resolver(self):
        resolver = FakeResolver()
        observations = self.observations(contract_reference="CT1")
        result = await resolve_billing_references(self.data, self.item, observations, self.document, resolver=resolver)
        self.assertEqual(result.diagnostics, ())
        self.assertEqual(resolver.requests, [])
        self.assertEqual(result.plant_id("plant.1.reference", "Campollano I", observations, self.document,
                                       data=self.data, item=self.item), "P1")
        self.assertTrue(all(reference.request_sha256 for reference in result.references))
        result.references[0].evidence[0]["value"] = "mutated copy"
        self.assertNotEqual(result.references[0].evidence[0]["value"], "mutated copy")
        json.dumps(result.to_dict())

    async def test_semantic_alias_is_bounded_and_source_bound(self):
        resolver = FakeResolver()
        observations = self.observations("Campo Uno")
        result = await resolve_billing_references(self.data, self.item, observations, self.document, resolver=resolver)
        self.assertEqual(result.diagnostics, ())
        request = resolver.requests[0]
        self.assertEqual({candidate.id for candidate in request.candidates}, {"P1", "P2"})
        self.assertEqual(request.context["hard_constraints"],
                         {"company": "1300", "customer": "C1", "contract": "CT1"})
        self.assertEqual(result.references[0].method, "SEMANTIC")
        self.assertEqual(result.references[0].request_sha256, request.sha256)
        self.assertEqual(result.plant_id("plant.1.reference", "Campo Uno", observations, self.document), "P1")
        self.assertEqual(observations.facts.fields["plant.1.reference"][0].value, "Campo Uno")

    async def test_single_candidate_without_exact_match_needs_source_proof(self):
        self.data.get("sales_contracts", "CT1")["plants"] = ["P1"]
        result = await resolve_billing_references(self.data, self.item, self.observations("Campo Uno"), self.document)
        self.assertEqual(result.references[0].status, "NO_MATCH")
        self.assertIsNone(result.references[0].selected_id)
        self.assertTrue(result.diagnostics)

    async def test_conflicting_observations_prevent_all_semantic_calls(self):
        resolver = FakeResolver()
        observations = self.observations("Campo Uno", **{"plant.2.reference": ["Campollano I", "Lomaseca"]})
        result = await resolve_billing_references(self.data, self.item, observations, self.document, resolver=resolver)
        self.assertEqual(result.diagnostics[0].code, "CONFLICT")
        self.assertEqual(len(result.diagnostics[0].candidates), 2)
        self.assertEqual(resolver.requests, [])

    async def test_known_wrong_contract_is_not_overridden(self):
        resolver = FakeResolver()
        observations = self.observations(contract_reference="CT2")
        result = await resolve_billing_references(self.data, self.item, observations, self.document, resolver=resolver)
        self.assertEqual(result.diagnostics[0].code, "REFERENCE_CONFLICT")
        self.assertEqual(resolver.requests, [])
        with self.assertRaises(ValueError):
            result.plant_id("plant.1.reference", "Campollano I", observations, self.document)

    async def test_known_out_of_scope_plant_never_reaches_semantics(self):
        self.document = replace(self.document, blocks=(ParsedBlock("page.1", "Foreign plant", 1),))
        resolver = FakeResolver()
        result = await resolve_billing_references(self.data, self.item, self.observations("Foreign plant"),
                                                 self.document, resolver=resolver)
        self.assertEqual(result.references[0].status, "NO_MATCH")
        self.assertEqual(resolver.requests, [])

    async def test_abstention_retains_reason_evidence_and_fingerprint(self):
        resolver = FakeResolver(status="AMBIGUOUS")
        result = await resolve_billing_references(self.data, self.item, self.observations("Campo Uno"),
                                                 self.document, resolver=resolver)
        record = result.references[0]
        self.assertEqual(record.status, "AMBIGUOUS")
        self.assertIn("cannot distinguish", record.reason)
        self.assertEqual(record.evidence[0]["quote"], "Campo Uno")
        self.assertEqual(record.request_sha256, resolver.requests[0].sha256)

    async def test_other_source_row_cannot_prove_this_reference(self):
        result = await resolve_billing_references(self.data, self.item, self.observations("Campo Uno"),
                                                 self.document, resolver=FakeResolver(wrong_proof=True))
        self.assertEqual(result.diagnostics[0].code, "INVALID_REFERENCE_INPUT")
        self.assertIn("this printed reference", result.diagnostics[0].message)

    async def test_changed_source_metadata_or_master_invalidates_binding(self):
        observations = self.observations()
        result = await resolve_billing_references(self.data, self.item, observations, self.document)
        for document, item in ((replace(self.document, parser_version="different"), self.item),
                               (self.document, replace(self.item, month="2026-08"))):
            with self.assertRaises(ValueError):
                result.plant_id("plant.1.reference", "Campollano I", observations, document,
                                data=self.data, item=item)
        self.data.get("cost_centers", "P1")["desc"] = "Changed name"
        with self.assertRaises(ValueError):
            result.plant_id("plant.1.reference", "Campollano I", observations, self.document,
                            data=self.data, item=self.item)

    async def test_raw_names_crosscheck_without_accounting_fields(self):
        observations = self.observations()
        raw = DocumentFacts(self.document.source_sha256, "raw", {
            name: [Fact(value, Evidence(self.document.path, "page.1", 1, value))]
            for name, value in {"contract_name": "Energy contract", "customer_name": "MUNICIPALITY"}.items()})
        result = await resolve_billing_references(self.data, self.item, observations, self.document, raw_facts=raw)
        self.assertEqual(result.diagnostics, ())
        self.assertEqual({reference.selected_id for reference in result.references}, {"CT1", "C1", "P1"})
        customer = billing_customer_request(self.data, self.item, self.document)
        self.assertNotIn("dir3", customer.candidates[0].attributes)
        contract = billing_contract_request(self.data, self.item, self.document)
        self.assertNotIn("tax", contract.candidates[0].attributes)
        self.assertEqual({candidate.id for candidate in contract.candidates}, {"CT1", "CT2"})

    async def test_candidate_bound_and_duplicate_plant_selection_fail_closed(self):
        with self.assertRaises(ValueError):
            billing_plant_request(self.data, self.item, self.document, field="plant.1.reference", max_candidates=1)
        result = await resolve_billing_references(self.data, self.item,
                                                 self.observations(**{"plant.2.reference": "Campollano I"}), self.document)
        self.assertEqual(result.diagnostics[0].code, "DUPLICATE_PLANT")


if __name__ == "__main__":
    unittest.main()
