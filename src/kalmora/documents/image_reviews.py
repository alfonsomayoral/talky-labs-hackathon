"""Evaluator-only manual image quote reviews; never import from capture/solver.

A review binds an observed quote/value to original and rendered identities. It
contains no expected answer and must not enter a model prompt. The evaluator must
first verify original bytes, actual rendered image identity and value/quote support.
This helper verifies the review binding, not pixels or a human reviewer's honesty.
"""
from __future__ import annotations

from pathlib import Path, PurePosixPath
import re

from kalmora.facts import _decode_value, _encode_value, atomic_json
from .contracts import fingerprint, valid_hash

STATUSES = frozenset({'VERIFIED', 'REJECTED', 'UNREVIEWED'})
_RECORD_KEYS = frozenset({'schema_version', 'key', 'identity', 'status', 'review_basis', 'reviewer', 'date'})


def _document(value):
    if not isinstance(value, str) or not value or '\\' in value or ':' in value:
        raise ValueError('Review document requires a relative original source path')
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {'..', 'golden', 'phase_test'} for part in path.parts) or path.as_posix() == '.':
        raise ValueError('Review document is outside the original development source boundary')
    canonical = path.as_posix()
    return 'phase_dev/' + canonical if canonical.startswith('inbox/') else canonical


def image_review_identity(observed, transformation_sha256):
    """Exact typed identity, with only relative document-path canonicalization.

    Quotes, values, units and field names are not normalized. Decimal precision,
    quote whitespace and literal punctuation remain part of the review identity.
    ``observed`` is the evaluator's flat field/value/evidence/source_hash record.
    """
    if not isinstance(observed, dict) or not isinstance(observed.get('evidence'), dict):
        raise ValueError('Review requires an observed field and structured evidence')
    evidence = observed['evidence']
    valid_hash(observed.get('source_sha256'))
    valid_hash(transformation_sha256)
    locator = evidence.get('field')
    match = re.fullmatch(r'image:([0-9a-f]{64})', locator) if isinstance(locator, str) else None
    if not match:
        raise ValueError('Review requires an exact image:SHA256 evidence locator')
    page = evidence.get('page')
    if type(page) is not int or page < 1:
        raise ValueError('Review requires a positive original page')
    field = observed.get('field')
    quote = evidence.get('quote')
    unit = observed.get('unit')
    if not isinstance(field, str) or not field.strip() or not isinstance(quote, str) or not quote.strip():
        raise ValueError('Review requires a field and a nonempty literal quote')
    if unit is not None and (not isinstance(unit, str) or not unit.strip()):
        raise ValueError('Review unit must be explicit text or null')
    if 'value' not in observed:
        raise ValueError('Review requires the observed typed value')
    identity = {'canonicalrelative_document': _document(evidence.get('document')),
                'source_sha256': observed['source_sha256'], 'page': page,
                'image_sha256': match.group(1), 'transformation_sha256': transformation_sha256,
                'field': field, 'value': observed['value'], 'unit': unit, 'quote': quote}
    fingerprint(identity)  # Reject unsupported values/nonfinite JSON numbers.
    return identity


def image_review_key(observed, transformation_sha256):
    """Fingerprint the exact observation identity, not OCR confidence or answers."""
    return fingerprint(image_review_identity(observed, transformation_sha256))


def validate_review(observed, transformation_sha256, registry):
    """Return VERIFIED/REJECTED only for a strict, exact original-image review.

    Missing, malformed, stale or mismatched records return UNREVIEWED. A genuine
    REJECTED review remains rejected. Confidence and OCR-based review records do
    not establish verification. Caller must separately validate actual source and
    image bytes; self-consistent records cannot prove that a reviewer was honest.
    """
    try:
        if not isinstance(registry, dict):
            return 'UNREVIEWED'
        identity = image_review_identity(observed, transformation_sha256)
        key = fingerprint(identity)
        record = registry.get(key)
        if not isinstance(record, dict) or set(record) != _RECORD_KEYS:
            return 'UNREVIEWED'
        if type(record['schema_version']) is not int or record['schema_version'] != 1:
            return 'UNREVIEWED'
        if record['key'] != key or not isinstance(record['identity'], dict):
            return 'UNREVIEWED'
        if set(record['identity']) != set(identity) or fingerprint(record['identity']) != key:
            return 'UNREVIEWED'
        if record['status'] not in STATUSES or record['review_basis'] != 'original_page_image':
            return 'UNREVIEWED'
        if any(not isinstance(record[name], str) or not record[name].strip() for name in ('reviewer', 'date')):
            return 'UNREVIEWED'
        return record['status']
    except (ValueError, TypeError, KeyError):
        return 'UNREVIEWED'


def dump_registry(path, registry):
    """Atomically persist exact typed review records, including nested Decimal."""
    if not isinstance(registry, dict):
        raise ValueError('Review registry must be a mapping')
    fingerprint(registry)
    atomic_json(path, {'schema_version': 1, 'review_value_encoding': 'typed-v1',
                       'reviews': _encode_value(registry)})


def load_registry(path):
    """Load explicit typed-v1 reviews; never silently accept an untyped format."""
    import json
    envelope = json.loads(Path(path).read_text(encoding='utf-8'))
    if (not isinstance(envelope, dict) or set(envelope) != {'schema_version', 'review_value_encoding', 'reviews'}
            or type(envelope['schema_version']) is not int or envelope['schema_version'] != 1
            or envelope['review_value_encoding'] != 'typed-v1'):
        raise ValueError('Unsupported manual image review registry format')
    registry = _decode_value(envelope['reviews'])
    if not isinstance(registry, dict):
        raise ValueError('Review registry must decode to a mapping')
    fingerprint(registry)
    return registry
