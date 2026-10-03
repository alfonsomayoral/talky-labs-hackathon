"""Recorded ledger and independent adjustment projections.

Local balances are signed debit minus credit. Document amounts remain intact.
An adjustment owner is (event_id, stage): import and application are distinct.
"""
from collections import defaultdict
from copy import deepcopy
from .money import integer

def iter_entries(entries):
    """Normalize ERP entry groups without losing original IDs or line numbers."""
    for original in entries:
        entry = deepcopy(original)
        if (not isinstance(entry, dict) or not entry.get('company')
                or not isinstance(entry.get('lines'), list)):
            raise ValueError('entry requires company and lines')
        for index, line in enumerate(entry['lines'], 1):
            line.setdefault('company', entry['company'])
            line.setdefault('line', index)
            if line['company'] != entry['company']:
                raise ValueError('entry and line company differ')
            if entry.get('id'):
                line['book_line'] = f"{entry['id']}#{line['line']}"
            integer(line['debit'])
            integer(line['credit'])
        yield entry

def is_open_item_account(account):
    prefixes = ('400', '410', '403', '407', '430', '431', '433', '436',
                '438', '552', '2423', '1633')
    return account.startswith(prefixes) or account in ('49000000', '55300000')

class Ledger:

    def __init__(self):
        self._entries = []
        self._owners = set()
        self._ids = set()

    @classmethod
    def from_entries(cls, entries):
        ledger = cls()
        for entry in iter_entries(entries):
            if 'provenance' in entry:
                provenance = entry['provenance']
                if not isinstance(provenance, dict):
                    raise ValueError('restored provenance requires event_id and stage')
                if any(not isinstance(provenance.get(field), str) or not provenance[field]
                       for field in ('event_id', 'stage')):
                    raise ValueError('restored provenance requires event_id and stage')
                owner = (provenance['event_id'], provenance['stage'])
                if owner in ledger._owners:
                    raise ValueError(f'duplicate restored adjustment stage: {owner}')
                ledger._owners.add(owner)
            if entry.get('id') in ledger._ids:
                raise ValueError(f"duplicate journal id: {entry['id']}")
            if entry.get('id'):
                ledger._ids.add(entry['id'])
            ledger._entries.append(entry)
        return ledger

    def iter_entries(self):
        return iter_entries(self._entries)

    @property
    def entries(self):
        return list(self.iter_entries())

    def project(self):
        return deepcopy(self)

    def balances(self):
        result = defaultdict(int)
        for entry in self._entries:
            for line in entry['lines']:
                result[entry['company'], line['account']] += line['debit'] - line['credit']
        return dict(result)

    def open_items(self):
        result = defaultdict(int)
        for entry in self._entries:
            for line in entry['lines']:
                if is_open_item_account(line['account']):
                    key = (entry['company'], line['account'], line.get('partner'),
                           line.get('assignment'))
                    result[key] += line['debit'] - line['credit']
        return dict(result)

    def add_entry(self, entry, *, event_id, stage):
        if (not isinstance(event_id, str) or not event_id
                or not isinstance(stage, str) or not stage):
            raise ValueError('event_id and stage are required provenance')
        owner = (event_id, stage)
        if owner in self._owners:
            raise ValueError(f'duplicate adjustment stage: {owner}')
        from .validation import validate_entry
        errors = validate_entry(entry)
        if errors:
            raise ValueError('; '.join(errors))
        normalized = next(iter_entries([entry]))
        if normalized.get('id') in self._ids:
            raise ValueError('duplicate journal id')
        normalized['provenance'] = {'event_id': event_id, 'stage': stage}
        self._owners.add(owner)
        if normalized.get('id'):
            self._ids.add(normalized['id'])
        self._entries.append(normalized)
