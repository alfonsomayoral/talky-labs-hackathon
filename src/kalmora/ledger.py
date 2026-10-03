"""Recorded ledger and independent adjustment projections.

Local balances are signed debit minus credit. Document amounts remain intact.
An adjustment owner is (event_id, stage): import and application are distinct.
"""
from collections import defaultdict
from collections.abc import Iterable, Iterator
from copy import deepcopy
from typing import Self
from .model import (AccountCode, BalanceKey, Cents, JournalEntry, OpenItemKey,
                    Provenance)
from .money import integer

def iter_entries(entries: Iterable[JournalEntry]) -> Iterator[JournalEntry]:
    """Normalize ERP entry groups without losing original IDs or line numbers.

    Yields deep copies, so the input is never mutated. Each line receives its
    entry's ``company``, a positional ``line`` and, when the entry has an ``id``,
    ``book_line`` (``id#line``). Raises ValueError for a malformed entry and
    TypeError for non-integer amounts.
    """
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

def is_open_item_account(account: AccountCode) -> bool:
    """True for accounts managed by open items (vendors, customers, intercompany, factoring)."""
    prefixes = ('400', '410', '403', '407', '430', '431', '433', '436',
                '438', '552', '2423', '1633')
    return account.startswith(prefixes) or account in ('49000000', '55300000')

class Ledger:
    """In-memory general ledger of the group: the recorded journal plus, optionally, the
    solver's adjustments.

    Two roles, kept apart on purpose. The **recorded** book is what the ERP already holds
    (history that must not be posted again) and is rebuilt with ``from_entries``. A
    **projection** (``project()``) is an independent copy onto which adjustments are added,
    so reasoning about "what if I post this?" never contaminates the recorded book, and the
    closing trial balance is simply ``recorded + adjustments``.

    All amounts are integer cents in each company's local currency; companies are never
    summed together. Every adjustment is stamped with its ``(event_id, stage)`` provenance,
    which makes a close idempotent: replaying an event cannot double-post it.
    """

    def __init__(self) -> None:
        self._entries: list[JournalEntry] = []
        self._owners: set[tuple[str, str]] = set()
        self._ids: set[str] = set()

    @classmethod
    def from_entries(cls, entries: Iterable[JournalEntry]) -> Self:
        """Rebuild a book from stored entries, keeping restored provenance.

        Raises ValueError on duplicate journal ids, duplicate ``(event_id, stage)``
        owners or malformed provenance.
        """
        ledger = cls()
        for entry in iter_entries(entries):
            if 'provenance' in entry:
                provenance: object = entry['provenance']
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

    def iter_entries(self) -> Iterator[JournalEntry]:
        """Iterate normalized copies of every entry, in insertion order."""
        return iter_entries(self._entries)

    @property
    def entries(self) -> list[JournalEntry]:
        """Copies of all entries; mutating them does not affect the book."""
        return list(self.iter_entries())

    def project(self) -> Self:
        """Independent deep copy on which adjustments can be added safely."""
        return deepcopy(self)

    def balances(self) -> dict[BalanceKey, Cents]:
        """Trial balance: ``debit - credit`` per (company, account), in local cents.

        Assets and expenses come out positive, liabilities and income negative. It covers the
        whole loaded journal (no period cut) and is the grain at which the result is compared
        with the reference trial balance.
        """
        result: defaultdict[BalanceKey, Cents] = defaultdict(int)
        for entry in self._entries:
            for line in entry['lines']:
                result[BalanceKey(entry['company'], line['account'])] += line['debit'] - line['credit']
        return dict(result)

    def open_items(self) -> dict[OpenItemKey, Cents]:
        """Open-item sub-ledger: ``debit - credit`` per (company, account, partner, assignment).

        Only open-item accounts are included (vendors, customers, intercompany, factoring).
        A zero balance means the item has been cleared; a non-zero one is still owed or due,
        and is what payment application, FX revaluation and bad-debt provisioning work on.
        """
        result: defaultdict[OpenItemKey, Cents] = defaultdict(int)
        for entry in self._entries:
            for line in entry['lines']:
                if is_open_item_account(line['account']):
                    key = OpenItemKey(entry['company'], line['account'], line.get('partner'),
                                      line.get('assignment'))
                    result[key] += line['debit'] - line['credit']
        return dict(result)

    def add_entry(self, entry: JournalEntry, *, event_id: str, stage: str) -> None:
        """Validate and append an adjustment, stamping its ``(event_id, stage)`` provenance.

        Raises ValueError for a repeated owner, a repeated journal id or any
        ``validate_entry`` diagnostic; the book is unchanged on failure.
        """
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
        normalized['provenance'] = Provenance(event_id=event_id, stage=stage)
        self._owners.add(owner)
        if normalized.get('id'):
            self._ids.add(normalized['id'])
        self._entries.append(normalized)
