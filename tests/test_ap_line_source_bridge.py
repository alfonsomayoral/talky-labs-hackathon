"""Financial source rows constrain posting inputs without choosing between sources."""
from dataclasses import replace
from decimal import Decimal, localcontext
import unittest

from kalmora.ap_allocation import InvoiceQuantityLine, OrderKey, OrderPortion
from kalmora.ap_document_bridge import APFactSet, APLineFacts
from kalmora.ap_holds import PriceLine, PricePortion
from kalmora.ap_line_source_bridge import APLineSourceBinding, validate_ap_line_sources
from kalmora.ap_valuation import CostAssignment, ValuationLine
from kalmora.facts import DocumentFacts, Evidence, Fact


class APLineSourceBridgeTests(unittest.TestCase):
    def setUp(self):
        self.path = "inbox/ap/OPAQUE/source.pdf"
        self.order = OrderKey("1100", "V-OTHER", "EUR", "PO-OTHER", 30)
        self.assignment = CostAssignment("1100", "62300000", "CC-OTHER")

    def source(self, rows, path=None, **headers):
        path = self.path if path is None else path
        fields = {name: [Fact(value, Evidence(path, name, 1, str(value)))] for name, value in headers.items()}
        for index, row in enumerate(rows, 1):
            for name, value in row.items():
                key = f"line.{index}.{name}"
                fields[key] = value if isinstance(value, tuple) else (
                    Fact(value, Evidence(path, key, 1, str(value))),)
        return DocumentFacts("a" * 64, "synthetic-normalized-v1", {name: list(values) for name, values in fields.items()})

    def inputs(self, *, amount=12000, quantity=1000, price=12000):
        source = self.source([dict(net_cents=amount, quantity_milli=quantity, uom="hours",
                                   unit_price_e4=price * 100)], currency="EUR")
        valued = ValuationLine("POSTING-A", amount, self.assignment, quantity)
        quantity_line = InvoiceQuantityLine("POSTING-A", quantity, "hours", (
            OrderPortion(self.order, quantity, ("R-OTHER",)),))
        price_line = PriceLine("POSTING-A", (Fact(price, Evidence(self.path, "line.1.unit_price_e4")),),
                              (PricePortion(self.order, quantity, (Fact(10000, Evidence("erp/po", "price")),)),))
        return dict(bindings=(APLineSourceBinding("POSTING-A", self.path, 1),),
            amount_sources=(source,), valuation_lines=(valued,), quantity_lines=(quantity_line,),
            price_lines=(price_line,), currency="EUR")

    def test_bound_source_quantity_price_and_net_are_clear_with_original_evidence(self):
        result = validate_ap_line_sources(**self.inputs())
        self.assertEqual(result.status, "CLEAR")
        self.assertEqual(result.diagnostics, ())
        self.assertEqual(result.source_hashes, ((self.path, "a" * 64),))
        self.assertTrue(any(e.field == "line.1.quantity_milli" for e in result.evidence))
        self.assertTrue(any(e.field == "line.1.unit_price_e4" for e in result.evidence))
        self.assertEqual(result.views[0].unit_price_cents.value, Decimal("12000.00"))

    def test_price_variance_cannot_be_evaded_by_an_unrelated_invoice_price(self):
        args = self.inputs(price=20000, amount=20000)
        false_price = replace(args["price_lines"][0], invoice_unit_price_cents=(
            Fact(10000, Evidence(self.path, "another observed number")),))
        args["price_lines"] = (false_price,)
        with self.assertRaisesRegex(ValueError, "invoice price check contradicts"):
            validate_ap_line_sources(**args)

    def test_quantity_forge_cannot_make_insufficient_receipts_look_sufficient(self):
        args = self.inputs(quantity=2000, amount=20000, price=10000)
        args["valuation_lines"] = (replace(args["valuation_lines"][0], quantity_milli=1000),)
        args["quantity_lines"] = (replace(args["quantity_lines"][0], quantity_milli=1000),)
        args["price_lines"] = (replace(args["price_lines"][0], portions=(replace(
            args["price_lines"][0].portions[0], quantity_milli=1000),)),)
        with self.assertRaisesRegex(ValueError, "posting quantity contradicts"):
            validate_ap_line_sources(**args)

    def test_direct_expense_does_not_require_quantity_unit_or_unit_price(self):
        source = self.source([dict(amount_cents=1000)])
        result = validate_ap_line_sources(bindings=(APLineSourceBinding("DIRECT", self.path, 1),),
            amount_sources=(source,), valuation_lines=(ValuationLine("DIRECT", 1000, self.assignment),))
        self.assertEqual(result.status, "CLEAR")
        self.assertEqual(result.views[0].quantity_milli.status, "UNKNOWN")
        self.assertEqual(result.views[0].uom.status, "UNKNOWN")

    def test_ordered_quantity_phase_can_run_before_amount_or_price_is_known(self):
        args = self.inputs()
        args["amount_sources"] = (self.source([dict(quantity_milli=1000, uom="hours")]),)
        args["price_lines"] = ()
        early = validate_ap_line_sources(**args, amounts_required=False)
        self.assertEqual(early.status, "CLEAR")
        money = validate_ap_line_sources(**args)
        self.assertEqual(money.status, "UNKNOWN")
        args["price_lines"] = self.inputs()["price_lines"]
        price = validate_ap_line_sources(**args, amounts_required=False)
        self.assertEqual(price.status, "UNKNOWN")
        self.assertTrue(any("UNIT_PRICE_UNKNOWN" in note for note in price.diagnostics))

    def test_known_money_contradiction_is_rejected_even_when_amount_is_not_required(self):
        args = self.inputs()
        args["valuation_lines"] = (replace(args["valuation_lines"][0], amount_doc=9999),)
        with self.assertRaisesRegex(ValueError, "valued amount contradicts"):
            validate_ap_line_sources(**args, amounts_required=False)

    def test_quantity_only_coverage_requires_complete_bindings_without_inventing_valuation(self):
        args = self.inputs()
        args["valuation_lines"], args["price_lines"] = (), ()
        args["amount_sources"] = (self.source([dict(quantity_milli=1000, uom="hours")]),)
        early = validate_ap_line_sources(**args, amounts_required=False)
        self.assertEqual(early.status, "CLEAR")
        self.assertEqual(early.views[0].net_cents.status, "UNKNOWN")
        self.assertEqual(args["valuation_lines"], ())
        with self.assertRaisesRegex(ValueError, "valued posting line"):
            validate_ap_line_sources(**args)
        self.assertEqual(validate_ap_line_sources(**dict(args, bindings=()),
            amounts_required=False).status, "UNKNOWN")
        two_rows = self.source([dict(quantity_milli=1000, uom="hours"),
                                dict(quantity_milli=1000, uom="hours")])
        missing = validate_ap_line_sources(**dict(args, amount_sources=(two_rows,)), amounts_required=False)
        self.assertEqual(missing.status, "UNKNOWN")
        self.assertIn("SOURCE_ROW_UNBOUND:" + self.path + ":2", missing.diagnostics)

    def test_quantity_only_views_preserve_quantity_uom_price_and_reference_guards(self):
        args = self.inputs()
        args["valuation_lines"] = ()
        self.assertEqual(validate_ap_line_sources(**args, amounts_required=False).status, "CLEAR")
        wrong = replace(args["quantity_lines"][0], quantity_milli=999)
        with self.assertRaisesRegex(ValueError, "quantity contradicts"):
            validate_ap_line_sources(**dict(args, quantity_lines=(wrong,)), amounts_required=False)
        wrong = replace(args["quantity_lines"][0], uom="days")
        with self.assertRaisesRegex(ValueError, "unit contradicts"):
            validate_ap_line_sources(**dict(args, quantity_lines=(wrong,)), amounts_required=False)
        wrong_price = replace(args["price_lines"][0], invoice_unit_price_cents=(
            Fact(10000, Evidence(self.path, "unrelated number")),))
        with self.assertRaisesRegex(ValueError, "price check contradicts"):
            validate_ap_line_sources(**dict(args, price_lines=(wrong_price,)), amounts_required=False)
        source = self.source([dict(quantity_milli=1000, uom="hours", unit_price_e4=1200000,
                                  po_reference="DIFFERENT-PO")])
        result = validate_ap_line_sources(**dict(args, amount_sources=(source,)), amounts_required=False)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertTrue(any(note.startswith("SOURCE_ORDER_REFERENCE_BINDING_REQUIRED") for note in result.diagnostics))

    def test_printed_po_cannot_be_ignored_before_quantity_allocation(self):
        args = self.inputs()
        args["price_lines"] = ()
        cases = (("PO-OTHER", 30, "CLEAR"),
                 ("PO-PRINTED-DIFFERENT", 30, "UNKNOWN"),
                 ("PO-OTHER", 31, "UNKNOWN"),
                 ("PO-OTHER, PO-SECOND", 30, "UNKNOWN"),
                 (None, 30, "UNKNOWN"))
        for reference, item, expected in cases:
            with self.subTest(reference=reference, item=item):
                args["amount_sources"] = (self.source([dict(quantity_milli=1000, uom="hours",
                    po_reference=reference, po_item=item)]),)
                result = validate_ap_line_sources(**args, amounts_required=False)
                self.assertEqual(result.status, expected)
                self.assertTrue(any(e.field == "line.1.po_reference" for e in result.evidence))
                if expected == "UNKNOWN":
                    self.assertTrue(any(note.startswith("SOURCE_ORDER_REFERENCE_BINDING_REQUIRED:")
                                        for note in result.diagnostics))

    def test_header_reference_applies_to_rows_and_cannot_be_erased_by_a_conflicting_row(self):
        args = self.inputs()
        row = dict(net_cents=12000, quantity_milli=1000, uom="hours", unit_price_e4=1200000)
        args["amount_sources"] = (self.source([row], po_reference="PO-OTHER", po_item=30),)
        matched = validate_ap_line_sources(**args)
        self.assertEqual(matched.status, "CLEAR")
        self.assertTrue(any(e.field == "po_reference" for e in matched.evidence))
        for changed in (dict(po_reference="PO-DIFFERENT"), dict(po_item=31),
                        dict(po_reference=None), dict(po_item=True)):
            with self.subTest(changed=changed):
                args["amount_sources"] = (self.source([{**row, **changed}],
                    po_reference="PO-OTHER", po_item=30),)
                result = validate_ap_line_sources(**args)
                self.assertEqual(result.status, "UNKNOWN")
                self.assertTrue(any(note.startswith("SOURCE_ORDER_REFERENCE_BINDING_REQUIRED:")
                                    for note in result.diagnostics))
        args["amount_sources"] = (self.source([row], po_reference="PO-OTHER", po_item=30),)
        wrong_price_order = replace(args["price_lines"][0].portions[0],
                                    order=replace(self.order, po="PO-PRICE-DIFFERENT"))
        args["price_lines"] = (replace(args["price_lines"][0], portions=(wrong_price_order,)),)
        self.assertEqual(validate_ap_line_sources(**args).status, "UNKNOWN")

    def test_direct_expense_cannot_silently_discard_an_observed_po_reference(self):
        args = self.inputs()
        args["valuation_lines"] = (replace(args["valuation_lines"][0], quantity_milli=None),)
        args["quantity_lines"], args["price_lines"] = (), ()
        for references in (dict(po_reference="PO-OTHER"), dict(po_item=30),
                           dict(po_reference=None), {}):
            with self.subTest(references=references):
                args["amount_sources"] = (self.source([dict(net_cents=12000, **references)]),)
                result = validate_ap_line_sources(**args)
                self.assertEqual(result.status, "UNKNOWN" if references else "CLEAR")
                if references:
                    self.assertTrue(any(note.startswith("SOURCE_ORDER_REFERENCE_BINDING_REQUIRED:")
                                        for note in result.diagnostics))

    def test_net_and_gross_line_amount_are_not_aliased_or_divided_into_unit_price(self):
        args = self.inputs(amount=18000, price=20000)
        args["amount_sources"] = (self.source([dict(net_cents=18000, amount_cents=20000,
            discount_cents=2000, quantity_milli=1000, uom="hours", unit_price_e4=2000000)]),)
        self.assertEqual(validate_ap_line_sources(**args).status, "CLEAR")
        before_discount = self.source([dict(amount_cents=20000, discount_cents=2000,
            quantity_milli=1000, uom="hours", unit_price_e4=2000000)])
        args["amount_sources"] = (before_discount,)
        result = validate_ap_line_sources(**args)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertIn("SOURCE_NET_BASIS_UNKNOWN_WITH_DISCOUNT", result.diagnostics)

    def test_independent_pdf_xml_rows_can_have_different_indices_and_are_not_summed(self):
        pdf = self.source([dict(net_cents=1000), dict(net_cents=2000)], currency="EUR", line_count=2)
        xml_path = "inbox/ap/OPAQUE/source.xml"
        xml = self.source([dict(net_cents=2000), dict(net_cents=1000)], xml_path, currency="EUR", line_count=2)
        bindings = (APLineSourceBinding("A", self.path, 1), APLineSourceBinding("B", self.path, 2),
                    APLineSourceBinding("A", xml_path, 2), APLineSourceBinding("B", xml_path, 1))
        result = validate_ap_line_sources(bindings=bindings, amount_sources=(pdf, xml),
            valuation_lines=(ValuationLine("A", 1000, self.assignment), ValuationLine("B", 2000, self.assignment)),
            currency="EUR")
        self.assertEqual(result.status, "CLEAR")
        self.assertEqual(len(result.views), 4)
        self.assertEqual(len(result.bindings), 4)

    def test_disagreeing_sources_return_unknown_without_choosing_a_primary(self):
        args = self.inputs()
        xml_path = "inbox/ap/OPAQUE/source.xml"
        xml = self.source([dict(net_cents=13000, quantity_milli=2000, uom="days", unit_price_e4=1300000)],
                          xml_path, currency="USD")
        args["amount_sources"] += (xml,)
        args["bindings"] += (APLineSourceBinding("POSTING-A", xml_path, 1),)
        result = validate_ap_line_sources(**args)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertTrue(any("CONFLICT" in note for note in result.diagnostics))
        self.assertEqual({view.source_path for view in result.views}, {self.path, xml_path})

    def test_missing_xml_unit_can_use_the_matching_pdf_observation_without_inventing_it(self):
        args = self.inputs()
        xml_path = "inbox/ap/OPAQUE/source.xml"
        xml = self.source([dict(net_cents=12000, quantity_milli=1000, unit_price_e4=1200000)], xml_path)
        args["amount_sources"] += (xml,)
        args["bindings"] += (APLineSourceBinding("POSTING-A", xml_path, 1),)
        result = validate_ap_line_sources(**args)
        self.assertEqual(result.status, "CLEAR")
        self.assertEqual(next(view for view in result.views if view.source_path == xml_path).uom.status, "UNKNOWN")
        self.assertTrue(all(e.document == self.path for e in result.evidence if e.field == "line.1.uom"))

    def test_every_source_and_valued_row_is_covered_once(self):
        source = self.source([dict(net_cents=1000), dict(net_cents=2000)])
        args = dict(bindings=(APLineSourceBinding("A", self.path, 1),), amount_sources=(source,),
                    valuation_lines=(ValuationLine("A", 1000, self.assignment), ValuationLine("B", 2000, self.assignment)))
        result = validate_ap_line_sources(**args)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertIn(f"SOURCE_ROW_UNBOUND:{self.path}:2", result.diagnostics)
        self.assertIn("POSTING_LINE_SOURCE_UNOBSERVED:B", result.diagnostics)
        args["bindings"] += (APLineSourceBinding("B", self.path, 1),)
        with self.assertRaisesRegex(ValueError, "cannot be reused"):
            validate_ap_line_sources(**args)
        args["bindings"] = (APLineSourceBinding("A", "inbox/ap/OPAQUE/unknown.pdf", 1),
                            APLineSourceBinding("B", "inbox/ap/OPAQUE/unknown.pdf", 1))
        with self.assertRaisesRegex(ValueError, "cannot be reused"):
            validate_ap_line_sources(**args)

    def test_two_equal_rows_of_one_source_cannot_disappear_into_one_posting_line(self):
        source = self.source([dict(net_cents=1000), dict(net_cents=1000)])
        with self.assertRaisesRegex(ValueError, "cannot merge distinct rows"):
            validate_ap_line_sources(bindings=(APLineSourceBinding("A", self.path, 1),
                APLineSourceBinding("A", self.path, 2)), amount_sources=(source,),
                valuation_lines=(ValuationLine("A", 1000, self.assignment),))

    def test_supplied_views_require_matching_values_types_and_evidence(self):
        args = self.inputs()
        accepted = validate_ap_line_sources(**args)
        self.assertEqual(validate_ap_line_sources(**args, views=accepted.views).status, "CLEAR")
        fields = dict(accepted.views[0].facts.fields)
        fields["quantity_milli"] = (Fact(1000, Evidence(self.path, "fabricated locator")),)
        fabricated = replace(accepted.views[0], facts=APFactSet(fields))
        with self.assertRaisesRegex(ValueError, "fields/evidence differ"):
            validate_ap_line_sources(**args, views=(fabricated,))
        fields = dict(accepted.views[0].facts.fields)
        fields["net_cents"] = (replace(fields["net_cents"][0], value=Decimal(12000)),)
        with self.assertRaisesRegex(ValueError, "fields/evidence differ"):
            validate_ap_line_sources(**args, views=(replace(accepted.views[0], facts=APFactSet(fields)),))
        self.assertEqual(validate_ap_line_sources(**args, views=()).status, "UNKNOWN")

    def test_wrong_currency_unit_and_source_count_are_not_silently_accepted(self):
        args = self.inputs()
        with self.assertRaisesRegex(ValueError, "posting currency contradicts"):
            validate_ap_line_sources(**dict(args, currency="USD"))
        wrong_unit = replace(args["quantity_lines"][0], uom="days")
        with self.assertRaisesRegex(ValueError, "posting unit contradicts"):
            validate_ap_line_sources(**dict(args, quantity_lines=(wrong_unit,)))
        source = args["amount_sources"][0]
        source.fields["line_count"] = [Fact(2, Evidence(self.path, "actual row count"))]
        result = validate_ap_line_sources(**args)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertIn("SOURCE_LINE_COUNT_UNKNOWN_OR_INCOMPLETE:" + self.path, result.diagnostics)

    def test_explicit_line_currency_does_not_override_an_opposed_document_currency(self):
        args = self.inputs()
        source = args["amount_sources"][0]
        source.fields["line.1.currency"] = [Fact("USD", Evidence(self.path, "line currency"))]
        result = validate_ap_line_sources(**dict(args, currency="USD"))
        self.assertEqual(result.status, "UNKNOWN")
        self.assertTrue(any("SOURCE_LINE_CURRENCY_UNKNOWN" in note for note in result.diagnostics))

    def test_empty_sources_and_unknown_fields_never_fabricate_header_rows(self):
        header_only = self.source([], net_cents=12000)
        args = self.inputs()
        args["amount_sources"] = (header_only,)
        result = validate_ap_line_sources(**args)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(result.views, ())
        unknown = DocumentFacts("b" * 64, "normalized", {})
        result = validate_ap_line_sources(**dict(args, amount_sources=(unknown,)))
        self.assertEqual(result.status, "UNKNOWN")
        self.assertTrue(any(note.startswith("SOURCE_IDENTITY_UNOBSERVED") for note in result.diagnostics))

    def test_explicit_absence_and_conflicting_price_candidates_stay_unknown(self):
        args = self.inputs()
        path = self.path
        conflicting = (Fact(1200000, Evidence(path, "price-A")), Fact(1300000, Evidence(path, "price-B")))
        args["amount_sources"] = (self.source([dict(net_cents=12000, quantity_milli=1000,
            uom="hours", unit_price_e4=conflicting)]),)
        result = validate_ap_line_sources(**args)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertTrue(any("UNIT_PRICE_UNKNOWN" in note for note in result.diagnostics))
        args["amount_sources"] = (self.source([dict(net_cents=12000, quantity_milli=None,
            uom="hours", unit_price_e4=1200000)]),)
        self.assertEqual(validate_ap_line_sources(**args).status, "UNKNOWN")

    def test_exact_price_conversion_and_caller_precision_are_preserved(self):
        args = self.inputs(amount=1, price=1)
        args["amount_sources"] = (self.source([dict(net_cents=1, quantity_milli=1000,
            uom="hours", unit_price_e4=12345)]),)
        args["price_lines"] = (replace(args["price_lines"][0], invoice_unit_price_cents=(
            Fact(Decimal("123.45"), Evidence(self.path, "actual exact price")),)),)
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(validate_ap_line_sources(**args).status, "CLEAR")


if __name__ == "__main__":
    unittest.main()
