from collections.abc import Sequence


class DomainError(Exception):
    """A failure with a stable machine ``code`` (see docs/api-contracts.md section 1.3).

    The transport decides the status; the use case only names what went wrong.
    """

    def __init__(self, code: str, detail: str, diagnostics: Sequence[str] = ()) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.diagnostics = list(diagnostics)
