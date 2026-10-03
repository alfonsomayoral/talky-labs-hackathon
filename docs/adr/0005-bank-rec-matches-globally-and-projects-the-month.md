---
status: proposed
---

# Bank reconciliation matches over all statement months and projects the target month

The July reconciliation matches the statement lines of all four months (April to July) against the 572 book lines posted from April, processing months in chronological order, and then reports the July view: July statement lines, July-posted book lines and earlier book lines paired with a July statement line. A July-posted book line that pairs with an earlier-month statement line is reported as an unmatched prior-period item. We accepted a larger matching universe and a projection step in exchange for telling a prior-period item from a real error and for never pairing a month-end fee entry with the wrong month; reconciling July alone is simpler but cannot make that distinction, and carrying state month by month would need adjustment history the package does not provide. Only this approach reproduces the milestone's reference structure (216 one-to-one, 8 grouped, 61 unmatched bank lines, 9 unmatched book lines).
