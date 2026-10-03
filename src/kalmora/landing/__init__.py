"""Versioned document landing with a single writer and exact ERP adapters."""
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
import hashlib
from importlib.resources import files
import json
import os
from pathlib import Path, PurePosixPath
import threading
from typing import Any, Iterator

from ..data import PhaseData, load_json, read_jsonl
from ..facts import DocumentFacts
from .bank import bank_csv, camt, n43, xml_root

SCHEMA_VERSION = '1'
TABLES = ('source_file', 'parse_issue', 'task_item', 'bank_statement', 'bank_line',
          'inbound_item', 'document', 'document_line')


def _json(value: Any) -> str:
    """Write finite decimals as exact JSON numeric literals, never via float."""
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError('Nonfinite JSON decimal')
        return str(value)
    if isinstance(value, float):
        raise ValueError('Floating-point JSON is forbidden in landing')
    if isinstance(value, dict):
        return '{' + ','.join(json.dumps(key) + ':' + _json(child) for key, child in value.items()) + '}'
    if isinstance(value, (list, tuple)):
        return '[' + ','.join(_json(child) for child in value) + ']'
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _exact(value: Any) -> None:
    if isinstance(value, float):
        raise ValueError('Landing rejects floating-point facts')
    if isinstance(value, Decimal) and not value.is_finite():
        raise ValueError('Landing rejects nonfinite decimals')
    if isinstance(value, dict):
        for child in value.values():
            _exact(child)
    if isinstance(value, (list, tuple)):
        for child in value:
            _exact(child)


def _relative(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if (not path.parts or path.is_absolute() or '..' in path.parts or '\\' in name
            or 'golden' in path.parts or '__MACOSX' in path.parts
            or path.parts[0] not in {'erp', 'tasks', 'inbox', 'bank'}):
        raise ValueError('Path is outside solver source areas')
    return path


class LandingStore:
    """One DuckDB per phase. Extraction workers send facts to this owner thread.

    No arbitrary SQL is exposed; rows(), table(), get() and find() form the
    bounded query interface. Money projections require explicit integer units.
    """
    def __init__(self, path: str | Path) -> None:
        try:
            import duckdb
        except ImportError as exc:
            raise RuntimeError('Install kalmora-close[landing] to use LandingStore') from exc
        self.path = Path(path).resolve()
        if 'golden' in self.path.parts:
            raise ValueError('Landing database cannot be stored in golden')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._owner = (os.getpid(), threading.get_ident())
        self._lock = (self.path.parent / (self.path.name + '.writer.lock')).open('a+b')
        self._connection: Any = None
        try:
            import fcntl
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (ImportError, BlockingIOError) as exc:
            self._lock.close()
            raise RuntimeError('Landing requires an exclusive POSIX writer lock') from exc
        try:
            self._connection = duckdb.connect(str(self.path), config={'enable_external_access': False})
            existing = self._connection.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()
            if not existing:
                with self._transaction():
                    self._connection.execute(files(__package__).joinpath('schema.sql').read_text())
                    self._connection.execute('INSERT INTO landing_meta VALUES (?,?)', ['schema_version', SCHEMA_VERSION])
            if self._meta('schema_version') != SCHEMA_VERSION:
                raise ValueError('Unsupported landing schema version; rebuild in a new database')
        except BaseException:
            self.close()
            raise

    def _check_owner(self) -> None:
        if (os.getpid(), threading.get_ident()) != self._owner:
            raise RuntimeError('Only the writer process and its owner thread may use LandingStore')
        if self._connection is None:
            raise RuntimeError('LandingStore is closed')

    def __enter__(self) -> 'LandingStore':
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def close(self) -> None:
        if (os.getpid(), threading.get_ident()) != self._owner:
            raise RuntimeError('Only the owner may close LandingStore')
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        self._lock.close()

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self._check_owner()
        self._connection.execute('BEGIN TRANSACTION')
        try:
            yield
            self._connection.execute('COMMIT')
        except BaseException:
            self._connection.execute('ROLLBACK')
            raise

    def _meta(self, key: str) -> str | None:
        row = self._connection.execute('SELECT value FROM landing_meta WHERE key=?', [key]).fetchone()
        return row[0] if row else None

    def _insert(self, table: str, values: dict[str, Any]) -> None:
        columns = ','.join('"' + key + '"' for key in values)
        self._connection.execute(f'INSERT INTO {table} ({columns}) VALUES ({",".join("?" for _ in values)})', list(values.values()))

    def _issue(self, file_id: int, code: str, message: str, locator: str | None = None,
               severity: str = 'WARN') -> None:
        issue_id = self._connection.execute('SELECT coalesce(max(issue_id),0)+1 FROM parse_issue').fetchone()[0]
        self._insert('parse_issue', {'issue_id': issue_id, 'file_id': file_id,
                                   'locator': locator, 'severity': severity, 'code': code, 'message': message})

    def rows(self, table: str, **criteria: Any) -> list[dict[str, Any]]:
        """Query only one of the eight landing tables using parameterized equality."""
        self._check_owner()
        _exact(criteria)
        if table not in TABLES:
            raise KeyError(table)
        columns = {row[1] for row in self._connection.execute(f'PRAGMA table_info({table})').fetchall()}
        if not set(criteria) <= columns:
            raise ValueError('Unknown query column')
        where = ' AND '.join('"' + key + '" IS NOT DISTINCT FROM ?' for key in criteria)
        result = self._connection.execute(f'SELECT * FROM {table}' + (' WHERE ' + where if where else ''), list(criteria.values()))
        names = [col[0] for col in result.description]
        return [dict(zip(names, row, strict=True)) for row in result.fetchall()]

    def counts(self) -> dict[str, int]:
        self._check_owner()
        return {table: self._connection.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in TABLES}

    def _source_path(self, root: Path, relative: str) -> Path:
        path = root.joinpath(*_relative(relative).parts)
        resolved = path.resolve()
        if not resolved.is_relative_to(root) or 'golden' in resolved.parts or path.is_symlink():
            raise ValueError('Symlink or path escaping the phase')
        return path

    def _catalog(self, root: Path) -> list[dict[str, Any]]:
        catalog = []
        for path in sorted(root.rglob('*')):
            relative = path.relative_to(root)
            if relative.parts[0] not in {'erp', 'tasks', 'bank', 'inbox'} or any(part in {'golden', '__MACOSX'} for part in relative.parts):
                continue
            if path.name in {'score.py', 'scorer.py'}:
                continue
            if path.is_symlink():
                raise ValueError(f'Symlink source is forbidden: {relative}')
            if not path.is_file():
                continue
            safe = self._source_path(root, relative.as_posix())
            read_error = None
            try:
                payload = safe.read_bytes()
            except OSError as exc:
                payload, read_error = b'', str(exc)
            try:
                size = safe.stat().st_size
            except OSError:
                size = None
            family = {'erp': 'ERP', 'bank': 'BANK', 'tasks': 'TASKS'}.get(relative.parts[0], 'INBOX_AP')
            if relative.parts[:3] == ('inbox', 'ar', 'billing'):
                family = 'INBOX_AR_BILLING'
            elif relative.parts[:3] == ('inbox', 'ar', 'remittances'):
                family = 'INBOX_AR_REMITTANCE'
            elif relative.parts[:2] == ('inbox', 'ar'):
                family = 'INBOX_AR_NOTICE'
            fmt = {'.json': 'JSON', '.jsonl': 'JSONL', '.n43': 'N43', '.pdf': 'PDF'}.get(path.suffix, 'OTHER')
            if path.suffix == '.csv':
                fmt = 'CSV_BANK_MX' if family == 'BANK' else 'CSV_FACE'
            if path.suffix == '.xml':
                fmt = 'CAMT053' if family == 'BANK' else ('CFDI_XML' if b'www.sat.gob.mx/cfd' in payload else 'FACTURAE_XML')
            catalog.append({'file_id': len(catalog)+1, 'phase': root.name, 'rel_path': relative.as_posix(),
                            'family': family, 'format': fmt, 'encoding': 'latin-1' if fmt == 'N43' else ('utf-8' if fmt != 'PDF' else None),
                            'sha256': hashlib.sha256(payload).hexdigest() if read_error is None else None, 'size_bytes': size,
                            'parser': 'landing@1', 'status': 'FAILED' if read_error else 'SKIPPED',
                            'error': read_error, 'loaded_at': datetime.now()})
        return catalog

    def import_phase(self, phase_path: str | Path) -> dict[str, int]:
        """Import unchanged originals atomically; repeat loads verify all hashes.

        Source changes require a new database. Per-source parse errors are saved
        without discarding valid neighboring files; structural SQL errors rollback.
        """
        self._check_owner()
        root = Path(phase_path).resolve()
        if not root.is_dir() or 'golden' in root.parts:
            raise ValueError('Invalid solver phase directory')
        if self.path.is_relative_to(root):
            raise ValueError('Landing output must be outside source phase')
        catalog = self._catalog(root)
        if self._meta('phase_root') is not None:
            if any(row['sha256'] is None for row in catalog) or any(row['sha256'] is None for row in self.rows('source_file')):
                raise ValueError('Cannot verify unreadable originals; resolve reading failure and rebuild')
            old = {(row['rel_path'], row['sha256']) for row in self.rows('source_file')}
            new = {(row['rel_path'], row['sha256']) for row in catalog}
            if self._meta('phase_root') != str(root) or self._meta('phase') != root.name or old != new:
                raise ValueError('Phase or source bytes changed; rebuild in a new database')
            return self.counts()
        by_path = {row['rel_path']: row for row in catalog}
        parsed = {}
        with self._transaction():
            for row in catalog:
                self._insert('source_file', row)
                if row['error'] is not None:
                    self._issue(row['file_id'], 'READ_ERROR', row['error'], severity='ERROR')
                    continue
                path = self._source_path(root, row['rel_path'])
                try:
                    if row['format'] == 'JSON':
                        parsed[row['rel_path']] = load_json(path)
                    elif row['format'] == 'JSONL':
                        parsed[row['rel_path']] = list(read_jsonl(path))
                    elif row['format'] in {'CFDI_XML', 'FACTURAE_XML'}:
                        xml_root(path.read_bytes())
                        continue
                    else:
                        continue
                    self._connection.execute("UPDATE source_file SET status='PARSED' WHERE file_id=?", [row['file_id']])
                except (ValueError, OSError) as exc:
                    self._failed(row, exc)
            self._load_inbound(root, by_path, parsed)
            self._load_banks(root, by_path, parsed)
            self._load_tasks(by_path, parsed)
            for key, value in [('phase_root', str(root)), ('phase', root.name)]:
                self._connection.execute('INSERT INTO landing_meta VALUES (?,?)', [key, value])
        return self.counts()

    def _failed(self, row: dict[str, Any], error: Exception) -> None:
        self._connection.execute("UPDATE source_file SET status='FAILED',error=? WHERE file_id=?", [str(error), row['file_id']])
        self._issue(row['file_id'], 'PARSE_ERROR', str(error), severity='ERROR')

    def _load_inbound(self, root: Path, catalog: dict[str, Any], parsed: dict[str, Any]) -> None:
        for relative, row in catalog.items():
            if not row['family'].startswith('INBOX'):
                continue
            path = PurePosixPath(relative)
            value = parsed.get(relative)
            kind = None
            if path.name == 'message.json' and row['family'] == 'INBOX_AP':
                kind = 'AP_MESSAGE'
            elif path.name == 'item.json' and row['family'] == 'INBOX_AR_BILLING':
                kind = 'AR_BILLING_ITEM'
            elif row['family'] == 'INBOX_AR_REMITTANCE' and path.suffix == '.json':
                kind = 'REMITTANCE_ADVICE'
            elif row['family'] == 'INBOX_AR_NOTICE' and path.suffix == '.json':
                kind = 'AR_NOTICE'
            elif row['format'] == 'CSV_FACE':
                kind, value = 'FACE_EXPORT', {}
            if kind is None or value is None:
                continue
            try:
                if not isinstance(value, dict):
                    raise ValueError('Inbound metadata must be a JSON object')
                item_id = (value.get('doc_id') or value.get('billing_item') or value.get('item_id')
                           or value.get('notice_id') or path.stem.removeprefix('aviso_pago_'))
                if not isinstance(item_id, str):
                    raise ValueError('Inbound identity must be text')
                declared = value.get('attachments', value.get('documents', [value['file']] if 'file' in value else []))
                if kind == 'FACE_EXPORT':
                    declared = [path.name]
                if not isinstance(declared, list) or any(not isinstance(name, str) for name in declared):
                    raise ValueError('Declared attachments must be a list of names')
                if len(set(declared)) != len(declared):
                    raise ValueError('Duplicate declared attachment')
                if self.rows('inbound_item', item_id=item_id):
                    raise ValueError('Duplicate inbound identity from different source files')
                received = value.get('received_at')
                if received is not None:
                    datetime.fromisoformat(received)
                attachments = []
                for seq, name in enumerate(declared, 1):
                    candidate = (path.parent / name).as_posix()
                    self._source_path(root, candidate)
                    attachments.append((seq, name, catalog.get(candidate)))
                if any(source is not None and self.rows('document', file_id=source['file_id']) for _, _, source in attachments):
                    raise ValueError('One source file cannot belong to multiple inbound items')
                sender = value.get('from', value.get('uploaded_by'))
                self._insert('inbound_item', {'item_id': item_id, 'kind': kind, 'received_at': received,
                    'channel': value.get('channel'), 'sender_addr': sender,
                    'sender_domain': sender.rsplit('@', 1)[-1] if isinstance(sender, str) and '@' in sender else None,
                    'subject': value.get('subject'), 'body': value.get('body'), 'billing_type': value.get('type'),
                    'company': value.get('company'), 'contract': value.get('contract'), 'customer': value.get('customer'),
                    'month': value.get('month'), 'payer_name': value.get('from_'), 'declared_files': declared,
                    'extra': _json(value), 'file_id': row['file_id']})
                for seq, name, source in attachments:
                    if source is None:
                        self._issue(row['file_id'], 'ATTACHMENT_MISSING', f'Declared attachment missing: {name}')
                        continue
                    self._insert('document', {'document_id': source['file_id'], 'file_id': source['file_id'],
                        'item_id': item_id, 'attachment_seq': seq, 'filename': name,
                        'filename_prefix': PurePosixPath(name).stem.split('_', 1)[0], 'method': 'UNEXTRACTED'})
            except (ValueError, OSError, TypeError) as exc:
                self._failed(row, exc)

    def _load_banks(self, root: Path, catalog: dict[str, Any], parsed: dict[str, Any]) -> None:
        for relative, row in catalog.items():
            if row['format'] not in {'N43', 'CAMT053', 'CSV_BANK_MX'}:
                continue
            if row['error'] is not None:
                continue
            path = PurePosixPath(relative)
            period = path.name.split('.', 1)[0]
            twin = catalog.get((path.parent / (period + '.lines.jsonl')).as_posix())
            try:
                if twin is None or twin['rel_path'] not in parsed:
                    raise ValueError('Missing or malformed bank JSONL twin')
                payload = self._source_path(root, relative).read_bytes()
                statement, lines = {'N43': n43, 'CAMT053': camt, 'CSV_BANK_MX': bank_csv}[row['format']](payload)
                if not isinstance(statement.get('currency'), str) or not statement['currency']:
                    raise ValueError('Statement currency is missing')
                for original in lines:
                    datetime.strptime(original['booking_date'], '%Y-%m-%d')
                    if original.get('value_date') is not None:
                        datetime.strptime(original['value_date'], '%Y-%m-%d')
                    if not isinstance(original.get('currency'), str) or not original['currency']:
                        raise ValueError('Bank line currency is missing')
                twins = parsed[twin['rel_path']]
                twin_ok = len(lines) == len(twins) and all(
                    original['amount_cents'] == mirror['amount'] and original['currency'] == mirror['currency']
                    and original['booking_date'] == mirror['booking_date']
                    and (not original.get('bank_line') or original['bank_line'] == mirror['bank_line'])
                    for original, mirror in zip(lines, twins))
                if any(type(mirror.get('amount')) is not int or not isinstance(mirror.get('bank_line'), str) for mirror in twins):
                    raise ValueError('Bank twin identities/amounts have invalid types')
                ids = [mirror['bank_line'] for mirror in twins]
                if len(set(ids)) != len(ids) or any(self.rows('bank_line', bank_line=identity) for identity in ids):
                    raise ValueError('Bank line IDs must be unique across the phase')
                chain_ok = statement.pop('chain_ok', True) and statement['opening_cents'] + sum(line['amount_cents'] for line in lines) == statement['closing_cents']
                if not twin_ok:
                    self._issue(row['file_id'], 'TWIN_MISMATCH', 'Original and JSONL twin differ; no fabricated line identities')
                if not chain_ok:
                    self._issue(row['file_id'], 'BALANCE_CHAIN_BROKEN', 'Opening plus movements does not equal closing')
                # Do not attach a mismatched JSONL ID to an unrelated original row.
                if not twin_ok:
                    self._connection.execute("UPDATE source_file SET status='PARTIAL' WHERE file_id=?", [row['file_id']])
                    continue
                self._insert('bank_statement', dict(statement, statement_id=row['file_id'], bank_account=path.parent.name,
                    period=period, format=row['format'], chain_ok=chain_ok, twin_ok=twin_ok,
                    file_id=row['file_id'], twin_file_id=twin['file_id']))
                for seq, (original, mirror) in enumerate(zip(lines, twins, strict=True), 1):
                    original['extra'] = _json(original['extra'])
                    original.update(bank_line=mirror['bank_line'], statement_id=row['file_id'], seq=seq,
                                    text_twin=mirror.get('text'))
                    self._insert('bank_line', original)
                self._connection.execute("UPDATE source_file SET status=? WHERE file_id=?", ['PARSED' if chain_ok else 'PARTIAL', row['file_id']])
            except (ValueError, OSError, KeyError, StopIteration, TypeError) as exc:
                self._failed(row, exc)

    def _load_tasks(self, catalog: dict[str, Any], parsed: dict[str, Any]) -> None:
        for relative, row in catalog.items():
            if row['family'] != 'TASKS' or relative not in parsed:
                continue
            stem, value = PurePosixPath(relative).stem, parsed[relative]
            try:
                if stem == 'close':
                    if not isinstance(value, dict) or not isinstance(value.get('steps'), list) or not isinstance(value.get('month'), str):
                        raise ValueError('Close task requires a month and a list of steps')
                    task_rows = [('close_step', i, step, value['month']) for i, step in enumerate(value['steps'], 1)]
                elif stem == 'intercompany':
                    if (not isinstance(value, dict) or not isinstance(value.get('pairs'), list)
                            or not isinstance(value.get('accounts'), list)
                            or any(not isinstance(pair, list) or len(pair) != 2 for pair in value['pairs'])):
                        raise ValueError('Intercompany task requires two-company pairs and accounts')
                    task_rows = [('intercompany_pair', i, pair[0], pair[1]) for i, pair in enumerate(value['pairs'], 1)]
                    task_rows += [('intercompany_account', i, account, None) for i, account in enumerate(value['accounts'], 1)]
                elif stem in {'ap_documents', 'ar_billing_items', 'ar_receipts', 'bank_accounts'}:
                    if not isinstance(value, list):
                        raise ValueError('Task keys must be a JSON list')
                    task_rows = [(stem, i, key, None) for i, key in enumerate(value, 1)]
                else:
                    raise ValueError('Unknown task shape')
                if any(not isinstance(key1, str) or (key2 is not None and not isinstance(key2, str)) for _, _, key1, key2 in task_rows):
                    raise ValueError('Task identities must be text')
                for task, seq, key1, key2 in task_rows:
                    self._insert('task_item', {'task': task, 'seq': seq, 'key1': key1, 'key2': key2, 'file_id': row['file_id']})
                    if task in {'ap_documents', 'ar_billing_items', 'ar_receipts'}:
                        table, col = ('bank_line', 'bank_line') if task == 'ar_receipts' else ('inbound_item', 'item_id')
                        if not self.rows(table, **{col: key1}):
                            self._issue(row['file_id'], 'TASK_REFERENCE_MISSING', f'{task} references missing {key1}')
                    elif task == 'bank_accounts':
                        accounts = parsed.get('erp/bank_accounts.jsonl', [])
                        if not any(account.get('id') == key1 for account in accounts):
                            self._issue(row['file_id'], 'TASK_REFERENCE_MISSING', f'Bank account missing from ERP: {key1}')
                    elif task in {'intercompany_pair', 'intercompany_account'}:
                        if task == 'intercompany_pair':
                            companies = parsed.get('erp/companies.json', [])
                            known = {company.get('code') for company in companies if isinstance(company, dict)}
                            missing = key1 not in known or key2 not in known
                        else:
                            accounts = parsed.get('erp/chart_of_accounts.jsonl', [])
                            missing = not any(account.get('account') == key1 for account in accounts)
                        if missing:
                            self._issue(row['file_id'], 'TASK_REFERENCE_MISSING', f'{task} reference missing: {key1}/{key2}')
            except (ValueError, KeyError, TypeError, IndexError) as exc:
                self._failed(row, exc)

    def _adapter(self, name: str) -> PhaseData:
        """Verify registered source bytes and bound the M0 reader to the catalog."""
        self._check_owner()
        root_value = self._meta('phase_root')
        if root_value is None:
            raise ValueError('Import a phase first')
        root = Path(root_value)
        relative = _relative(name if '/' in name else 'erp/' + name)
        if relative.parts[0] not in {'erp', 'tasks'}:
            raise ValueError('Exact adapter exposes only ERP and task sources')
        candidates = {str(relative)} if relative.suffix in {'.json', '.jsonl'} else {str(relative)+'.json', str(relative)+'.jsonl'}
        sources = self.rows('source_file')
        if not any(source['rel_path'] in candidates for source in sources):
            raise KeyError(name)
        for source in sources:
            if source['family'] in {'ERP', 'TASKS'}:
                payload = self._source_path(root, source['rel_path']).read_bytes()
                if hashlib.sha256(payload).hexdigest() != source['sha256']:
                    raise ValueError('Registered source changed; rebuild the landing')
        return PhaseData(root)

    def table(self, name: str) -> Any:
        if name in {'journal_lines', 'erp/journal_lines'}:
            data = self._adapter('journal_entries')
            return [dict(line, je_id=entry['id'], line_ref=f"{entry['id']}#{line['line']}",
                         company=entry['company'], posting_date=entry['posting_date'],
                         debit_cents=line['debit'], credit_cents=line['credit'],
                         amount_doc_cents=line.get('amount_doc'))
                    for entry in data.iter_journal() for line in entry['lines']]
        return self._adapter(name).table(name)

    def get(self, name: str, identity: Any) -> dict[str, Any]:
        _exact(identity)
        return self._adapter(name).get(name, identity)

    def find(self, name: str, **criteria: Any) -> list[dict[str, Any]]:
        _exact(criteria)
        if name in {'journal_lines', 'erp/journal_lines'}:
            return [row for row in self.table(name) if all(row.get(key) == value for key, value in criteria.items())]
        return self._adapter(name).find(name, **criteria)

    def store_facts(self, source_relative_path: str, facts: DocumentFacts) -> None:
        """Persist all candidates; project only singleton already-normalized fields."""
        self._check_owner()
        _relative(source_relative_path)
        if not isinstance(facts, DocumentFacts):
            raise TypeError('Expected DocumentFacts')
        for candidates in facts.fields.values():
            for fact in candidates:
                _exact(fact.value)
        sources = self.rows('source_file', rel_path=source_relative_path)
        if not sources or sources[0]['sha256'] != facts.source_sha256:
            raise ValueError('Facts do not match a registered original')
        source = sources[0]
        root = self._meta('phase_root')
        if root is None or hashlib.sha256(self._source_path(Path(root), source_relative_path).read_bytes()).hexdigest() != source['sha256']:
            raise ValueError('Registered attachment bytes changed; rebuild the landing')
        documents = self.rows('document', file_id=source['file_id'])
        if not documents:
            raise ValueError('Source is not a declared inbound document')
        document = documents[0]
        encoded = _json(facts.to_dict())
        if document['facts_json'] is not None:
            if json.loads(document['facts_json']) == facts.to_dict():
                return
            raise ValueError('Document facts changed; rebuild instead of overwriting evidence')
        columns = {row[1]: row[2] for row in self._connection.execute('PRAGMA table_info(document)').fetchall()}
        forbidden = {'document_id', 'file_id', 'item_id', 'attachment_seq', 'filename', 'filename_prefix',
                     'facts_json', 'extractor_version', 'method', 'extra', 'evidence'}
        projection = {'facts_json': encoded, 'extractor_version': facts.extractor_version,
                      'method': 'FACTS',
                      'evidence': _json({key: [asdict(fact.evidence) for fact in values] for key, values in facts.fields.items()})}
        methods = facts.fields.get('method', [])
        if len(methods) == 1:
            if methods[0].value not in {'FACTURAE_XML', 'CFDI_XML', 'PDF_TEXT', 'PDF_OCR', 'CSV', 'FACTS'}:
                raise ValueError('Unsupported explicit extraction method')
            projection['method'] = methods[0].value
        conflicts = []
        for key, candidates in facts.fields.items():
            if len(candidates) > 1:
                conflicts.append(key)
            if key in columns and key not in forbidden and len(candidates) == 1:
                value = candidates[0].value
                kind = columns[key]
                if value is not None and ((kind in {'BIGINT', 'INTEGER'} and type(value) is not int)
                        or (kind == 'BOOLEAN' and type(value) is not bool)
                        or (kind in {'VARCHAR', 'DATE'} and not isinstance(value, str))):
                    raise ValueError(f'{key} requires an explicit normalized {kind} value')
                projection[key] = value
        line_rows = []
        lines = facts.fields.get('lines', [])
        if len(lines) == 1:
            value = lines[0].value
            if not isinstance(value, list) or any(not isinstance(line, dict) for line in value):
                raise ValueError('Normalized lines must be a list of dictionaries')
            line_columns = {row[1]: row[2] for row in self._connection.execute('PRAGMA table_info(document_line)').fetchall()}
            for seq, line in enumerate(value, 1):
                if not set(line) <= set(line_columns) - {'document_id', 'seq'}:
                    raise ValueError('Unknown normalized line field')
                for key, field in line.items():
                    if field is not None and line_columns[key] in {'BIGINT', 'INTEGER'} and type(field) is not int:
                        raise ValueError(f'Line {key} must be exact integer units')
                line_rows.append(dict(line, document_id=document['document_id'], seq=seq))
        with self._transaction():
            assignments = ','.join('"'+key+'"=?' for key in projection)
            self._connection.execute(f'UPDATE document SET {assignments} WHERE document_id=?', [*projection.values(), document['document_id']])
            for line in line_rows:
                self._insert('document_line', line)
            for key in conflicts:
                self._issue(source['file_id'], 'FIELD_CONFLICT', f'Multiple candidates retained for {key}', key)
            self._connection.execute("UPDATE source_file SET status=?,parser=? WHERE file_id=?", ['PARTIAL' if conflicts else 'PARSED', facts.extractor_version, source['file_id']])


__all__ = ['LandingStore', 'SCHEMA_VERSION']
