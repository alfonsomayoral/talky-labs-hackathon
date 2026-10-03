"""Printed project names join exactly within company; omission needs no lookup."""
import unittest

from kalmora.ap_document_bridge import APFactSet
from kalmora.ap_project_binding import resolve_ap_project_binding
from kalmora.facts import Evidence, Fact


class ForbiddenInventory:
    def __iter__(self):
        raise AssertionError("omitted references must not read projects")


class APProjectBindingTests(unittest.TestCase):
    def setUp(self):
        self.proof = Evidence("inbox/ap/OPAQUE-X/invoice.pdf", "observed_project", 2, "Puente Álamo")
        self.rows = [dict(id="PROJECT-OMEGA", company="CO-X", name="Puente Álamo"),
                     dict(id="PROJECT-OTHER", company="CO-Y", name="Puente Álamo")]

    def field(self, value):
        return APFactSet({"project_reference": (Fact(value, self.proof),)}).text("project_reference")

    def resolve(self, value, **changes):
        return resolve_ap_project_binding(self.field(value), **{
            "company": "CO-X", "projects": self.rows, **changes})

    def test_literal_id_is_exact_and_never_relabels_a_foreign_id_as_a_local_name(self):
        observed = self.field("PROJECT-OMEGA")
        result = resolve_ap_project_binding(observed, company="CO-X", projects=self.rows)
        self.assertEqual((result.status, result.project_id, result.match_kind),
                         ("RESOLVED", "PROJECT-OMEGA", "EXACT_ID"))
        self.assertEqual(observed.value, "PROJECT-OMEGA")
        self.assertIn(self.proof, result.evidence)
        rows = [*self.rows, dict(id="PROJECT-NAME", company="CO-X", name="PROJECT-OTHER")]
        result = self.resolve("PROJECT-OTHER", projects=rows)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertIn("PROJECT_REFERENCE_FOREIGN_COMPANY", result.diagnostics)

    def test_name_join_normalizes_only_case_whitespace_and_retains_join_evidence(self):
        name = "  PUENTE   álamo\n"
        observed = self.field(name)
        result = resolve_ap_project_binding(observed, company="CO-X", projects=self.rows,
                                           project_source="erp/projects.json")
        self.assertEqual((result.status, result.project_id, result.match_kind),
                         ("RESOLVED", "PROJECT-OMEGA", "EXACT_NAME"))
        self.assertEqual(observed.value, name)
        self.assertIn(self.proof, result.evidence)
        self.assertTrue(any(e.document == "erp/projects.json" and e.field == "id=PROJECT-OMEGA.name"
                            for e in result.evidence))
        self.assertTrue(any(e.field == "id=PROJECT-OMEGA.id" for e in result.evidence))
        self.assertEqual(self.resolve("Puente Alamo").status, "UNKNOWN")
        self.assertEqual(self.resolve("Puente-Álamo").status, "UNKNOWN")

    def test_ambiguous_foreign_absent_and_malformed_masters_abstain(self):
        duplicate = [*self.rows, dict(id="PROJECT-SECOND", company="CO-X", name=" puente  álamo ")]
        cases = (("Puente Álamo", {"projects": duplicate}, "PROJECT_NAME_AMBIGUOUS"),
                 ("Puente Álamo", {"company": "CO-Z"}, "PROJECT_REFERENCE_FOREIGN_COMPANY"),
                 ("Unknown project", {}, "PROJECT_REFERENCE_NOT_FOUND"),
                 ("Puente Álamo", {"projects": None}, "PROJECT_MASTER_UNAVAILABLE"),
                 ("Puente Álamo", {"projects": [dict(id="P", name="Puente Álamo")]}, "PROJECT_MASTER_MALFORMED"),
                 ("Puente Álamo", {"projects": [self.rows[0], self.rows[0]]}, "PROJECT_MASTER_MALFORMED"))
        for value, changes, diagnostic in cases:
            with self.subTest(value=value, changes=changes):
                result = self.resolve(value, **changes)
                self.assertEqual((result.status, result.project_id), ("UNKNOWN", None))
                self.assertIn(diagnostic, result.diagnostics)

    def test_omission_never_iterates_master_and_explicit_unknowns_do_not_become_omitted(self):
        omitted = APFactSet({}).text("project_reference")
        result = resolve_ap_project_binding(omitted, company=None, projects=ForbiddenInventory())
        self.assertEqual((result.status, result.project_id), ("OMITTED", None))
        for value in (None, "", 12):
            with self.subTest(value=value):
                self.assertEqual(self.resolve(value).status, "UNKNOWN")
        conflicting = APFactSet({"project_reference": (Fact("Puente Álamo", self.proof),
            Fact("Another work", Evidence("inbox/ap/OPAQUE-X/invoice.xml", "project")))}).text("project_reference")
        self.assertEqual(resolve_ap_project_binding(conflicting, company="CO-X", projects=self.rows).status, "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
