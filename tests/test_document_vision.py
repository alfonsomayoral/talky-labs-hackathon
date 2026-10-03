from dataclasses import replace
from io import BytesIO
import unittest

from kalmora.documents.contracts import ImageRegion, PageImage, ParsedBlock, ParsedDocument, digest
from kalmora.documents.prompts import image_manifest
from kalmora.documents.vision import PageStripConfig, add_page_strips

try:
    from PIL import Image
except ImportError:
    Image = None


@unittest.skipIf(Image is None, "documents extra required")
class PageStripTests(unittest.TestCase):
    def document(self, height=100):
        image = Image.new("RGB", (20, height))
        for y in range(height):
            for x in range(20):
                image.putpixel((x, y), (x, y % 256, (x + y) % 256))
        stream = BytesIO()
        image.save(stream, format="PNG")
        return ParsedDocument("inbox/ap/a/scan.pdf", digest(b"original"),
            "application/pdf", "test", (ParsedBlock("page.1", "", 1),),
            (PageImage(1, "image/png", stream.getvalue()),))

    def test_strips_cover_original_with_overlap_and_no_pixel_changes(self):
        original = self.document()
        result = add_page_strips(original, PageStripConfig(height=40, overlap=10))
        self.assertEqual(result.images[0], original.images[0])
        self.assertEqual([i.region.box for i in result.images[1:]],
                         [(0, 0, 20, 40), (0, 30, 20, 70), (0, 60, 20, 100)])
        self.assertEqual(result.blocks, original.blocks)
        self.assertEqual(result.source_sha256, original.source_sha256)
        self.assertNotEqual(result.transformation_sha256, original.transformation_sha256)
        self.assertEqual(ParsedDocument.from_dict(result.to_dict()), result)
        manifest = image_manifest(result)
        self.assertNotIn("region", manifest[0])
        self.assertEqual(manifest[1]["region"]["parent_sha256"], original.images[0].sha256)

    def test_tampered_crop_pixels_or_parent_coordinates_are_rejected(self):
        result = add_page_strips(self.document(), PageStripConfig(height=40, overlap=10))
        crop = result.images[1]
        wrong_box = ImageRegion(crop.region.parent_sha256, 20, 100, (0, 1, 20, 41))
        with self.assertRaisesRegex(ValueError, "pixels differ"):
            replace(result, images=(result.images[0], replace(crop, region=wrong_box)))
        with self.assertRaisesRegex(ValueError, "retained original"):
            replace(result, images=(crop,))
        payload = result.to_dict()
        payload["images"][1]["region"]["box"] = [0, 1, 20, 41]
        with self.assertRaisesRegex(ValueError, "pixels differ"):
            ParsedDocument.from_dict(payload)

    def test_resource_limits_and_double_transform_are_explicit(self):
        original = self.document()
        with self.assertRaisesRegex(ValueError, "image limit"):
            add_page_strips(original, PageStripConfig(height=40, overlap=10, max_images=2))
        with self.assertRaisesRegex(ValueError, "pixel limit"):
            add_page_strips(original, PageStripConfig(max_page_pixels=50))
        result = add_page_strips(original, PageStripConfig(height=40, overlap=10))
        with self.assertRaisesRegex(ValueError, "already contains"):
            add_page_strips(result)

    def test_legacy_source_fingerprint_and_short_images_remain_unchanged(self):
        original = self.document(height=20)
        self.assertNotIn("region", original.to_dict()["images"][0])
        self.assertEqual(ParsedDocument.from_dict(original.to_dict()), original)

    def test_strips_preserve_transparency(self):
        pixels = Image.new('RGBA', (20, 100), (10, 20, 30, 0))
        pixels.putpixel((0, 0), (255, 0, 0, 128))
        stream = BytesIO()
        pixels.save(stream, format='PNG')
        original = replace(self.document(), images=(PageImage(1, 'image/png', stream.getvalue()),))
        result = add_page_strips(original, PageStripConfig(height=40, overlap=10))
        crop = Image.open(BytesIO(result.images[1].data))
        self.assertEqual(crop.mode, 'RGBA')
        self.assertEqual(crop.getpixel((0, 0)), (255, 0, 0, 128))
        self.assertEqual(crop.getpixel((1, 1)), (10, 20, 30, 0))


if __name__ == "__main__":
    unittest.main()
