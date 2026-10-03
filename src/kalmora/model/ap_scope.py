"""Identity of an explicitly resolved AP event or invoice."""
from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class ApScope:
    company: str
    vendor: str
    currency: str
