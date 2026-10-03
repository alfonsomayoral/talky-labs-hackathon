"""v0 rule engines ported from the research prototypes (AP decision and coding, AR billing).

They read only the phase package (tasks, ERP, inbox) and never golden. ``kalmora solve-ap`` and
``kalmora solve-ar-billing`` drive them; the typed backend modules remain the place to harden each rule.
"""
