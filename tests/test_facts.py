import hashlib
from decimal import Decimal
import tempfile
import unittest
from kalmora.facts import DocumentFacts, Evidence, Fact, FactsCache


class FactsTests(unittest.TestCase):
    def test_nested_decimal_and_reserved_tag_roundtrip(self):
        source = b"decimal source"
        value = {"rate": Decimal("1.234500"), "nested": [Decimal("0.000000000000000000001"),
                 {"type": "decimal", "value": "1.2345"}, {"type": "list", "items": []}],
                 "raw_text": "1.234500"}
        facts = DocumentFacts(hashlib.sha256(source).hexdigest(), "v1",
                              {"rate": [Fact(value, Evidence("a.xml", "rate"))]})
        with tempfile.TemporaryDirectory() as directory:
            cache = FactsCache(directory)
            cache.store(source, facts)
            restored = cache.load(source, "v1")
            self.assertEqual(restored, facts)
            restored_value = restored.fields["rate"][0].value
            self.assertIsInstance(restored_value["rate"], Decimal)
            self.assertEqual(restored_value["rate"].as_tuple(), value["rate"].as_tuple())
            self.assertIsInstance(restored_value["nested"][1], dict)
            self.assertIsInstance(restored_value["raw_text"], str)

    def test_roundtrip_conflicts_and_invalidation(self):
        source = b"original"
        facts = DocumentFacts(hashlib.sha256(source).hexdigest(), "v1", {"gross": [
            Fact(100, Evidence("a.pdf", "gross", 1)), Fact(110, Evidence("a.xml", "Total"))]})
        with tempfile.TemporaryDirectory() as directory:
            cache = FactsCache(directory)
            cache.store(source, facts, {"locale": "es"})
            self.assertEqual(cache.load(source, "v1", {"locale": "es"}), facts)
            self.assertIsNone(cache.load(b"changed", "v1", {"locale": "es"}))
            self.assertIsNone(cache.load(source, "v2", {"locale": "es"}))
            self.assertIsNone(cache.load(source, "v1", {"locale": "pt"}))
            with self.assertRaises(ValueError):
                cache.store(b"wrong", facts)

    def test_evidence_requires_location(self):
        with self.assertRaises(ValueError):
            Evidence("", "total")
        with self.assertRaises(ValueError):
            Evidence("a", "total", 0)
