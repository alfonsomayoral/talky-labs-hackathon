from dataclasses import replace
import unittest
from kalmora.ap_advance_bindings import AdvanceApplicationFacts, AdvanceClassification, resolve_advance_applications
from kalmora.ap_journal import AdvanceBalance, AdvanceState, InvoiceLineOrder
from kalmora.ap_valuation import CostAssignment, ValuationLine
from kalmora.facts import Evidence, Fact
from kalmora.model.ap_component_scope import APComponentScope


def fact(value, field, document="invoice.xml"):
    return Fact(value, Evidence(document, field))


class AdvanceBindingTests(unittest.TestCase):
    def setUp(self):
        self.state = AdvanceState((AdvanceBalance("A", "1100", "V", "USD", "DEP", "2026-01-01", "P", 100, 80, 20, 16),))
        self.observation = AdvanceApplicationFacts(fact("I", "invoice"), fact("A", "advance"), fact(40, "amount"), fact("L", "line"), fact("P", "po"))
        self.classification = AdvanceClassification(fact("A", "advance", "contract"), fact("NON_MONETARY", "treatment", "contract"))
        self.options = dict(scope=APComponentScope("1100", "V", "USD", "I", "2026-07-31", "POST"), state=self.state,
            applications=(self.observation,), classifications=(self.classification,),
            lines=(ValuationLine("L", 50, CostAssignment("1100", "21300000", None, "W")),),
            order_bindings=(InvoiceLineOrder("L", "P", 50, "invoice:po"),))

    def test_explicit_nonmonetary_and_monetary_classifications_bind_same_advance(self):
        non = resolve_advance_applications(**self.options)
        self.assertEqual(non.status, "RESOLVED")
        self.assertEqual(non.applications[0].cost_assignment, self.options["lines"][0].assignment)
        monetary = replace(self.classification, treatment=fact("MONETARY", "treatment", "contract"))
        result = resolve_advance_applications(**{**self.options, "classifications": (monetary,)})
        self.assertIsNone(result.applications[0].cost_assignment)
        self.assertEqual(self.state.balances[0].used_doc, 20)

    def test_missing_conflicting_classification_and_statement_association_abstain(self):
        for changes in ({"classifications": ()}, {"classifications": (self.classification, replace(self.classification, treatment=fact("MONETARY", "treatment", "contract")))},
                        {"applications": (replace(self.observation, amount_doc=fact(40, "amount", "unrelated")),)},
                        {"classifications": (replace(self.classification, treatment=fact("NON_MONETARY", "treatment", "unrelated")),)}):
            result = resolve_advance_applications(**{**self.options, **changes})
            self.assertEqual((result.status, result.applications), ("UNKNOWN", ()))

    def test_scope_po_capacity_and_duplicate_applications_cannot_resolve(self):
        for observation in (replace(self.observation, invoice_id=fact("OTHER", "invoice")),
                            replace(self.observation, po_reference=fact("OTHER", "po")),
                            replace(self.observation, amount_doc=fact(51, "amount")),
                            replace(self.observation, amount_doc=fact(None, "amount"))):
            self.assertEqual(resolve_advance_applications(**{**self.options, "applications": (observation,)}).status, "UNKNOWN")
        self.assertEqual(resolve_advance_applications(**{**self.options, "applications": (self.observation, self.observation)}).status, "UNKNOWN")
