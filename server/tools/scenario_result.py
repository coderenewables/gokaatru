"""scenario_result — MCP surface for the sweep engine's fixed-prefix identity.

Part of GoKaatru MCP Server.

The sweep engine's HTTP routes have no MCP counterpart today (a pre-existing gap,
tracked separately). This module exists so the one new capability this file adds
— reading the fixed-prefix hash before any sweep runs — does not repeat that gap:
``server/api/routes/sweep.py``'s ``GET .../sweep/prefix-hash`` and this tool both
call the same ``fixed_prefix_hash`` in ``server.core.scenario_result``.
"""
from __future__ import annotations

from server.core.scenario_result import fixed_prefix_hash
from server.operations import operation
from server.schemas.results import scenario_result as result_models
from server.state.session import session


@operation(effect="read", stage="sweep", canvas=False, result=result_models.GetFixedPrefixHashResult)
def get_fixed_prefix_hash() -> dict:
    """Return the fixed-prefix hash for the current session, stamped before any sweep runs."""
    return {
        "fixed_prefix_hash": fixed_prefix_hash(session),
        "reanalysis_sources": sorted(session.reanalysis_interpolated),
        "cleaning_actions_count": len(session.cleaning_log),
    }
