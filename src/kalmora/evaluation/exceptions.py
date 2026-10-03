"""Source cases the organizer's data cannot explain; documented in docs/discrepancies.md."""

KNOWN_EXCEPTIONS: dict[tuple[str, str], str] = {
    ("ap", "API004469"): "Golden journal 1100-2026-5100000822 has partner=null on its 40700000 advance line; "
                         "the creditor is V100121. Documented in docs/discrepancies.md; golden is not modified.",
}
