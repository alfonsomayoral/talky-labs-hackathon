"""Bounded local PDF rendering/OCR, never authoritative source blocks."""
from __future__ import annotations
from dataclasses import dataclass, asdict, replace
from io import BytesIO
import math
import os
from pathlib import Path
import re
import subprocess
import shutil
import tempfile
import time
from .contracts import ParsedDocument, PageImage, digest, fingerprint, source_path
from kalmora.facts import atomic_json

class PDFVisionError(ValueError):
    def __init__(self, category, detail=''):
        self.category = category
        super().__init__(category + (': ' + detail if detail else ''))

@dataclass(frozen=True)
class PDFVisionConfig:
    dpi: int = 300
    psm: int = 4
    language: str = 'eng'
    max_source_bytes: int = 20 * 1024 * 1024
    max_pages: int = 64
    max_pixels_per_page: int = 12_000_000
    max_total_pixels: int = 256_000_000
    max_image_bytes: int = 10_000_000
    max_total_image_bytes: int = 64_000_000
    max_ocr_bytes: int = 2_000_000
    timeout_seconds: float = 30
    renderer: str | None = None
    tesseract: str | None = None
    force_render_all_pages: bool = False
    ocr_enabled: bool = True
    def __post_init__(self):
        for name, program in [('renderer', 'pdftoppm'), ('tesseract', 'tesseract')]:
            configured = getattr(self, name)
            if configured is not None and (not isinstance(configured, str) or not configured):
                raise ValueError('tool path must be a nonempty string or None')
            object.__setattr__(self, name, shutil.which(configured or program) or configured or program)
        for name in ('dpi', 'psm', 'max_source_bytes', 'max_pages', 'max_pixels_per_page', 'max_total_pixels', 'max_image_bytes', 'max_total_image_bytes', 'max_ocr_bytes'):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError('positive integer processing limits required')
        if self.psm > 13 or not re.fullmatch(r'[a-zA-Z0-9_+-]+', self.language):
            raise ValueError('invalid OCR segmentation/language')
        if self.psm in (0, 2):
            raise ValueError('OCR segmentation must produce text')
        if any(type(getattr(self, name)) is not bool for name in ('force_render_all_pages', 'ocr_enabled')):
            raise ValueError('render/OCR switches must be boolean')
        if isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float)) or not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError('positive finite timeout required')

def _atomic_bytes(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(data); handle.flush(); os.fsync(handle.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)

class PDFVisionProcessor:
    def __init__(self, phase_root: Path, config: PDFVisionConfig | None = None):
        self.root = Path(phase_root).resolve()
        if 'golden' in self.root.parts:
            raise PDFVisionError('source_path')
        self.config = config or PDFVisionConfig()

    def _run(self, argv, directory, watched=()):
        """Bound generated outputs while running; never invoke a shell."""
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            try:
                process = subprocess.Popen(argv, cwd=directory, stdout=stdout, stderr=stderr,
                                           shell=False, env={**os.environ, 'OMP_THREAD_LIMIT': '1'})
            except OSError as error:
                raise PDFVisionError('missing_tool', str(argv[0])) from error
            started = time.monotonic()
            try:
                while True:
                    if time.monotonic() - started > self.config.timeout_seconds:
                        raise PDFVisionError('timeout')
                    if any(os.fstat(file.fileno()).st_size > self.config.max_ocr_bytes for file in (stdout, stderr)):
                        raise PDFVisionError('output_limit')
                    if any(path.exists() and path.stat().st_size > limit for path, limit in watched):
                        raise PDFVisionError('output_limit')
                    if process.poll() is not None:
                        break
                    time.sleep(.025)
                if process.returncode:
                    raise PDFVisionError('tool_failed', str(argv[0]))
                stdout.seek(0); stderr.seek(0)
                return (stdout.read(self.config.max_ocr_bytes) + stderr.read(self.config.max_ocr_bytes)).decode('utf-8', errors='replace')
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()

    def process(self, document: ParsedDocument, artifact_dir: Path | None = None) -> ParsedDocument:
        if (getattr(document, 'processing_aids', ())
                or any(marker in document.parser_version for marker in ('/pdf-vision-v1:', '/pdf-vision-v2:'))):
            raise PDFVisionError('already_processed')
        if document.media_type != 'application/pdf':
            raise PDFVisionError('not_pdf')
        source_path(document.path)
        if not document.path.startswith('inbox/'):
            raise PDFVisionError('source_path')
        source = (self.root / document.path).resolve()
        if not source.is_relative_to(self.root) or 'golden' in source.parts or not source.is_file():
            raise PDFVisionError('source_path')
        if source.stat().st_size > self.config.max_source_bytes:
            raise PDFVisionError('source_limit')
        original = source.read_bytes()
        if len(original) > self.config.max_source_bytes:
            raise PDFVisionError('source_limit')
        if digest(original) != document.source_sha256:
            raise PDFVisionError('source_hash')
        destination = Path(artifact_dir).resolve() if artifact_dir is not None else None
        if destination is not None and (destination.is_relative_to(self.root) or 'golden' in destination.parts):
            raise PDFVisionError('artifact_path')
        try:
            from pypdf import PdfReader
            reader = PdfReader(BytesIO(original), strict=True)
            if reader.is_encrypted:
                raise PDFVisionError('encrypted_pdf')
            if not reader.pages or len(reader.pages) > self.config.max_pages:
                raise PDFVisionError('page_limit')
            selected = sorted({int(match.group(1)) for warning in document.warnings
                               if (match := re.fullmatch(r'page\.(\d+):vision_required', warning))})
            if self.config.force_render_all_pages:
                selected = list(range(1, len(reader.pages) + 1))
            if any(page < 1 or page > len(reader.pages) for page in selected):
                raise PDFVisionError('page_locator')
            if any(number not in {block.page for block in document.blocks} for number in selected):
                raise PDFVisionError('page_locator')
            if not selected:
                return document
            total_pixels = 0
            for number in selected:
                page = reader.pages[number - 1]
                unit = float(page.get('/UserUnit', 1))
                dimensions = [float(page.mediabox.width), float(page.mediabox.height)]
                if not math.isfinite(unit) or unit <= 0 or any(not math.isfinite(value) or value <= 0 for value in dimensions):
                    raise PDFVisionError('pixel_limit')
                width, height = (math.ceil(value * unit * self.config.dpi / 72) for value in dimensions)
                if width * height > self.config.max_pixels_per_page:
                    raise PDFVisionError('pixel_limit')
                total_pixels += width * height
            if total_pixels > self.config.max_total_pixels:
                raise PDFVisionError('total_pixel_limit')
        except PDFVisionError:
            raise
        except ImportError as error:
            raise PDFVisionError('missing_documents_extra') from error
        except Exception as error:
            raise PDFVisionError('invalid_pdf') from error
        from .contracts import ProcessingAid
        aids = list(getattr(document, 'processing_aids', ()))
        images = [image for image in document.images if image.page not in selected]
        with tempfile.TemporaryDirectory(prefix='kalmora-pdf-') as scratch:
            directory = Path(scratch)
            copy = directory / 'original.pdf'; copy.write_bytes(original)
            tools = {}
            tool_list = [('renderer', self.config.renderer, '-v')]
            if self.config.ocr_enabled:
                tool_list.append(('ocr', self.config.tesseract, '--version'))
            for name, binary, argument in tool_list:
                path = Path(shutil.which(binary) or binary).resolve()
                if not path.is_file():
                    raise PDFVisionError('missing_tool', binary)
                tools[name] = {'binary_sha256': digest(path.read_bytes()), 'version': self._run([binary, argument], directory).splitlines()[0]}
            trained = {}
            if self.config.ocr_enabled:
                languages = self._run([self.config.tesseract, '--list-langs'], directory)
                match = re.search(r'"([^"]+)"', languages)
                for language in self.config.language.split('+'):
                    if language not in languages.splitlines()[1:]:
                        raise PDFVisionError('missing_language', language)
                    path = Path(match.group(1)) / (language + '.traineddata') if match else None
                    trained[language] = digest(path.read_bytes()) if path is not None and path.is_file() else None
            total_image_bytes = total_rendered_pixels = 0
            for number in selected:
                prefix = directory / f'page-{number}'
                png = prefix.with_suffix('.png'); txt = prefix.with_suffix('.txt'); tsv = prefix.with_suffix('.tsv')
                self._run([self.config.renderer, '-f', str(number), '-l', str(number), '-r', str(self.config.dpi),
                           '-singlefile', '-png', str(copy), str(prefix)], directory,
                          [(png, min(self.config.max_image_bytes, self.config.max_total_image_bytes - total_image_bytes))])
                if not png.is_file():
                    raise PDFVisionError('missing_tool_output')
                if png.stat().st_size > min(self.config.max_image_bytes, self.config.max_total_image_bytes - total_image_bytes):
                    raise PDFVisionError('output_limit')
                image = png.read_bytes()
                total_image_bytes += len(image)
                # Verify the actual renderer output, not only the PDF geometry.
                from PIL import Image
                try:
                    with Image.open(BytesIO(image)) as rendered:
                        width, height = rendered.size
                        if rendered.format != 'PNG' or width * height > self.config.max_pixels_per_page:
                            raise PDFVisionError('pixel_limit')
                        total_rendered_pixels += width * height
                        if total_rendered_pixels > self.config.max_total_pixels:
                            raise PDFVisionError('total_pixel_limit')
                        rendered.verify()
                except PDFVisionError:
                    raise
                except Exception as error:
                    raise PDFVisionError('invalid_render') from error
                text, table = b'', b''
                if self.config.ocr_enabled:
                    self._run([self.config.tesseract, str(png), str(prefix), '-l', self.config.language,
                               '--psm', str(self.config.psm), 'txt', 'tsv'], directory,
                              [(txt, self.config.max_ocr_bytes), (tsv, self.config.max_ocr_bytes)])
                    if not txt.is_file() or not tsv.is_file():
                        raise PDFVisionError('missing_tool_output')
                    if any(path.stat().st_size > self.config.max_ocr_bytes for path in (txt, tsv)):
                        raise PDFVisionError('output_limit')
                    text, table = txt.read_bytes(), tsv.read_bytes()
                try:
                    decoded = text.decode('utf-8')
                except UnicodeDecodeError as error:
                    raise PDFVisionError('invalid_ocr_text') from error
                provenance = {'kind': 'unverified_ocr' if self.config.ocr_enabled else 'page_render',
                              'authoritative': False, 'source_sha256': document.source_sha256,
                              'source_path': document.path, 'page': number, 'tools': tools, 'config': asdict(self.config),
                              'image_sha256': digest(image), 'text_sha256': digest(text), 'tsv_sha256': digest(table),
                              'traineddata_sha256': trained, 'fidelity': 'original_image_review_required',
                              'image_width': width, 'image_height': height, 'render_scope': 'full_media_box'}
                images.append(PageImage(number, 'image/png', image))
                aids.append(ProcessingAid(number, decoded, provenance))
                if destination is not None:
                    page_dir = (destination / document.source_sha256 / f'page-{number}').resolve()
                    if not page_dir.is_relative_to(destination) or page_dir.is_relative_to(self.root):
                        raise PDFVisionError('artifact_path')
                    if any((page_dir / name).is_symlink() for name in ('render.png', 'ocr.txt', 'ocr.tsv', 'metadata.json')):
                        raise PDFVisionError('artifact_path')
                    _atomic_bytes(page_dir / 'render.png', image)
                    if self.config.ocr_enabled:
                        _atomic_bytes(page_dir / 'ocr.txt', text); _atomic_bytes(page_dir / 'ocr.tsv', table)
                    atomic_json(page_dir / 'metadata.json', provenance)
        identity = fingerprint({'config': asdict(self.config), 'aids': [aid.provenance for aid in aids]})
        return replace(document, images=tuple(sorted(images, key=lambda image: image.page)), processing_aids=tuple(aids),
                       warnings=tuple(dict.fromkeys((*document.warnings,
                           'unverified_ocr:original_image_review_required' if self.config.ocr_enabled
                           else 'page_render:original_image_review_required'))),
                       parser_version=document.parser_version + '/pdf-vision-v2:' + identity)
