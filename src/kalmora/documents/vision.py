"""Bounded overlapping page strips: original pixels, never OCR reconstruction."""
from __future__ import annotations

from dataclasses import dataclass, replace
from io import BytesIO

from .contracts import ImageRegion, PageImage, ParsedDocument


@dataclass(frozen=True)
class PageStripConfig:
    height: int = 1500
    overlap: int = 150
    max_images: int = 12
    max_page_pixels: int = 12_000_000

    def __post_init__(self):
        if any(type(v) is not int or v < 1 for v in
               (self.height, self.max_images, self.max_page_pixels)):
            raise ValueError("strip limits must be positive integers")
        if type(self.overlap) is not int or not 0 <= self.overlap < self.height:
            raise ValueError("strip overlap must be smaller than height")


def _open(data, limit):
    from PIL import Image
    image = Image.open(BytesIO(data))
    if image.width * image.height > limit:
        raise ValueError("page pixel limit exceeded")
    image.load()
    # Retain alpha so transparent source pixels cannot become visible crop text.
    return image.convert("RGBA") if image.mode in {"RGBA", "LA"} or 'transparency' in image.info else image.convert("RGB")


def validate_regions(images):
    """Prove retained crop bytes equal the declared original pixel rectangle."""
    parents = {(i.page, i.sha256): i for i in images if i.region is None}
    decoded = {}
    for image in images:
        region = image.region
        if region is None:
            continue
        key = (image.page, region.parent_sha256)
        if key not in parents:
            raise ValueError("crop parent missing")
        if key not in decoded:
            decoded[key] = _open(parents[key].data, 12_000_000)
        parent = decoded[key]
        if parent.size != (region.parent_width, region.parent_height):
            raise ValueError("crop parent dimensions differ")
        crop = _open(image.data, 12_000_000)
        expected = parent.crop(region.box)
        if crop.size != expected.size or crop.tobytes() != expected.tobytes():
            raise ValueError("crop pixels differ from original rectangle")


def add_page_strips(document: ParsedDocument, config: PageStripConfig | None = None):
    """Retain full pages and add unscaled, overlapping full-width crops.

    Overlap avoids cutting rows at boundaries. The extractor sees all inputs in
    one call and must deduplicate overlapping rows, retaining global row order.
    This transformation cannot improve missing pixels or certify transcription.
    """
    config = config or PageStripConfig()
    if any(image.region is not None for image in document.images):
        raise ValueError("document already contains page strips")
    images = list(document.images)
    for image in document.images:
        parent = _open(image.data, config.max_page_pixels)
        if parent.height <= config.height:
            continue
        top = 0
        while top < parent.height:
            bottom = min(top + config.height, parent.height)
            if len(images) >= config.max_images:
                raise ValueError("strip image limit exceeded")
            box = (0, top, parent.width, bottom)
            stream = BytesIO()
            parent.crop(box).save(stream, format="PNG")
            images.append(PageImage(image.page, "image/png", stream.getvalue(),
                          ImageRegion(image.sha256, parent.width, parent.height, box)))
            if bottom == parent.height:
                break
            top = bottom - config.overlap
    return replace(document, images=tuple(images),
                   parser_version=document.parser_version + "/page-strips-v1",
                   warnings=(*document.warnings, "visual_strips:overlap_requires_row_deduplication"))
