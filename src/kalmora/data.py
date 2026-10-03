"""Lazy, read-only solver data access. Golden data is never a solver table."""
import json
from decimal import Decimal
from pathlib import Path, PurePosixPath


def _reject_constant(value):
    raise ValueError(f'Invalid JSON constant: {value}')


def _decode(text):
    return json.loads(text, parse_float=Decimal, parse_constant=_reject_constant)


def _input_path(path):
    path = Path(path)
    if 'golden' in path.parts or 'golden' in path.resolve().parts:
        raise ValueError('Golden data is not available to solvers')
    return path


def load_json(path: Path):
    """Read UTF-8 JSON; malformed input raises ValueError with its path."""
    path = _input_path(path)
    try:
        return _decode(path.read_text(encoding='utf-8'))
    except (ValueError, UnicodeError) as exc:
        raise ValueError(f'{path}: invalid JSON: {exc}') from exc


def read_jsonl(path: Path):
    """Yield object rows without loading the complete journal into memory."""
    path = _input_path(path)
    with path.open(encoding='utf-8') as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = _decode(line)
                if not isinstance(row, dict):
                    raise ValueError('JSONL row must be an object')
            except ValueError as exc:
                raise ValueError(f'{path}:{number}: {exc}') from exc
            yield row


class PhaseData:
    """Lazy tables and indexes for a phase directory.

    ERP names accept bare stems (vendors) or erp/vendors. Task tables use
    tasks/<stem>; inbox messages use inbox/<kind>/<document>/<stem>.
    table returns the original JSON shape or a cached list of JSONL objects.
    get uses id, doc_id, code, account, bank_line or number, then entity aliases.
    document_messages and bank_lines aggregate inbox messages and bank rows.
    Composite get IDs are tuples: open_items(company, account, partner, assignment),
    fx_rates(date, base, currency), contractor_certificates(vendor, reference),
    factoring_assignments(invoice, remittance), penalty_notices(invoice, notified_on).
    Composite identities can be queried with find; ambiguous get raises ValueError.
    iter_journal streams entries; table('journal_entries') caches on demand.
    """
    def __init__(self, phase_dir: Path):
        self.phase_dir = _input_path(phase_dir).resolve()
        self._cache = {}
        self._indexes = {}
        self.month = self.table('tasks/close')['month']

    def _path(self, name):
        relative = PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts or '\\' in name or 'golden' in relative.parts:
            raise ValueError(f'Unsafe table name: {name}')
        if len(relative.parts) == 1:
            relative = PurePosixPath('erp') / relative
        if relative.parts[0] not in {'erp', 'tasks', 'bank', 'inbox'}:
            raise ValueError(f'Unknown solver data area: {name}')
        path = self.phase_dir.joinpath(*relative.parts)
        candidates = [path] if path.suffix in {'.json', '.jsonl'} else [path.with_suffix('.jsonl'), path.with_suffix('.json')]
        for candidate in candidates:
            resolved = _input_path(candidate).resolve()
            if not resolved.is_relative_to(self.phase_dir):
                raise ValueError(f'Table escapes phase: {name}')
            if candidate.is_file():
                return candidate
        raise KeyError(name)

    def table(self, name):
        if name in {'document_messages', 'bank_lines'}:
            if name not in self._cache:
                if name == 'document_messages':
                    paths = sorted((self.phase_dir / 'inbox').glob('*/*/message.json'))
                    self._cache[name] = [load_json(self._path(p.relative_to(self.phase_dir).as_posix())) for p in paths]
                else:
                    paths = sorted((self.phase_dir / 'bank').glob('*/*.lines.jsonl'))
                    self._cache[name] = [row for p in paths for row in read_jsonl(self._path(p.relative_to(self.phase_dir).as_posix()))]
            return self._cache[name]
        path = self._path(name)
        if path not in self._cache:
            self._cache[path] = list(read_jsonl(path)) if path.suffix == '.jsonl' else load_json(path)
        return self._cache[path]

    @property
    def companies(self):
        return self.table('companies')

    @property
    def tasks(self):
        return {path.stem: self.table('tasks/' + path.stem)
                for path in sorted((self.phase_dir / 'tasks').glob('*.json'))}

    def _rows(self, table):
        value = self.table(table)
        if isinstance(value, dict):
            if table.rsplit('/', 1)[-1].removesuffix('.json') == 'tax_codes':
                value = value['tax_codes']
            return [dict(row, id=key) if isinstance(row, dict) else {'id': key, 'value': row}
                    for key, row in value.items()]
        return [row if isinstance(row, dict) else {'id': row} for row in value]

    def find(self, table, **criteria):
        """Return every row matching all exact field values."""
        return [row for row in self._rows(table)
                if all(row.get(key) == value for key, value in criteria.items())]

    def get(self, table, id):
        """Return a row by its identity; missing IDs raise KeyError."""
        path = table if table in {'document_messages', 'bank_lines'} else self._path(table)
        if path not in self._indexes:
            index = {}
            for row in self._rows(table):
                stem = table.rsplit('/', 1)[-1].split('.')[0]
                composite = {'open_items': ('company', 'account', 'partner', 'assignment'),
                             'fx_rates': ('date', 'base', 'currency'),
                             'contractor_certificates': ('vendor', 'reference'),
                             'factoring_assignments': ('invoice', 'remittance'),
                             'penalty_notices': ('invoice', 'notified_on')}
                if stem in composite:
                    identity = tuple(row.get(key) for key in composite[stem])
                else:
                    identity = next((row[key] for key in ('id', 'doc_id', 'code', 'account', 'bank_line', 'number', 'reference', 'invoice', 'vendor') if key in row), None)
                if identity is not None:
                    index.setdefault(identity, []).append(row)
            self._indexes[path] = index
        matches = self._indexes[path].get(id, [])
        if not matches:
            raise KeyError(id)
        if len(matches) != 1:
            raise ValueError(f'Ambiguous identity {id!r} in {table}; use find')
        return matches[0]

    def bank_lines(self, account, month=None):
        """Iterate parsed statement lines for a bank account and optional month."""
        if '/' in account or '\\' in account or account in {'.', '..'}:
            raise ValueError('Invalid bank account')
        if month is not None and (len(month) != 7 or not month[:4].isdigit() or month[4] != '-' or not month[5:].isdigit()):
            raise ValueError('Invalid statement month')
        for path in sorted((self.phase_dir / 'bank' / account).glob('*.lines.jsonl')):
            if month is None or path.name == f'{month}.lines.jsonl':
                safe = self._path(path.relative_to(self.phase_dir).as_posix())
                yield from read_jsonl(safe)

    def iter_journal(self):
        """Stream all journal entry objects, preserving their original lines."""
        yield from read_jsonl(self._path('journal_entries'))
