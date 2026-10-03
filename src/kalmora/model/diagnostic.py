type Diagnostic = str
"""A validation finding: ``<path>: <problem>``.

The path pinpoints the field (``company``, ``lines[2].partner``) and the problem is a
short phrase (``required for open-item account``, ``unbalanced by 150 cents``).
``validate_entry`` returns *all* findings at once, and an empty list means the entry is
valid. Diagnostics are data, not exceptions: the caller decides whether to correct,
hold or abort.
"""
