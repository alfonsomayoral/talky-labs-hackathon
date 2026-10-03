---
status: accepted
---

# The comparator wraps the organizer's scorer and is the only reader of golden

The comparator calls the original `score.py` for every official number and derives per-entity detail from it, instead of reimplementing the formulas. It lives in a separate evaluator package that is the sole reader of golden; solver modules cannot import it. We accepted being bound to `score.py`'s internal functions (and pinning its hash) in exchange for never diverging from the organizer's score; a port would be easier to extend but would drift silently if the scorer changes for `phase_test`.
