import hashlib
import tempfile
import unittest
from kalmora.facts import DocumentFacts, Evidence, Fact, FactsCache


class FactsTests(unittest.TestCase):
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
