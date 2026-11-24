"""Results of the fixed-prefix hash operation (P1-19)."""
from __future__ import annotations

from server.schemas.results._base import Result


class GetFixedPrefixHashResult(Result):
    fixed_prefix_hash: str
    reanalysis_sources: list[str]
    cleaning_actions_count: int
