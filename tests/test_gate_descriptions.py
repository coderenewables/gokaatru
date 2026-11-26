"""Every admissibility gate the server emits is described to the reader, and no other.

The Interrogate phase's Gates panel finds gates from the result rows' ``gate_*`` columns, so a
new gate shows up there on its own, but its words (what it measures, what it applies to, which
thresholds govern it) are kept in ``frontend/src/types/sweep.ts``'s ``GATE_META``. A gate
without an entry is shown with no explanation, and a threshold key that is not a field of
``GateThresholds`` shows "not recorded" against a value the manifest does carry under another
name. This reads both sides, as ``test_openapi_schema`` reads the committed client schema.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

from server.core.admissibility import GateThresholds

ROOT = Path(__file__).resolve().parents[1]
ADMISSIBILITY = ROOT / "server" / "core" / "admissibility.py"
SWEEP_TYPES = ROOT / "frontend" / "src" / "types" / "sweep.ts"


def _emitted_gates() -> set[str]:
    source = ADMISSIBILITY.read_text(encoding="utf-8").replace("\r\n", "\n")
    return set(re.findall(r'GateResult\(\s*"([a-z_]+)"', source))


def _gate_meta() -> dict[str, list[str]]:
    source = SWEEP_TYPES.read_text(encoding="utf-8").replace("\r\n", "\n")
    start = source.index("export const GATE_META")
    body = source[source.index("{", source.index("=", start)) + 1 : source.index("\n};", start)]
    entries = re.split(r"^  ([a-z_]+): \{$", body, flags=re.MULTILINE)[1:]
    meta: dict[str, list[str]] = {}
    for name, block in zip(entries[::2], entries[1::2]):
        keys = re.search(r"thresholdKeys: \[(.*?)\]", block, flags=re.DOTALL)
        assert keys is not None, f"{name} has no thresholdKeys"
        meta[name] = re.findall(r'"([a-z_]+)"', keys.group(1))
    return meta


def test_both_sides_are_read() -> None:
    assert len(_emitted_gates()) >= 8
    assert len(_gate_meta()) >= 8


def test_every_emitted_gate_is_described_and_no_other() -> None:
    assert set(_gate_meta()) == _emitted_gates()


def test_every_threshold_a_description_names_is_a_threshold() -> None:
    fields = {field.name for field in dataclasses.fields(GateThresholds)}
    for gate, keys in _gate_meta().items():
        assert set(keys) <= fields, f"{gate}: {sorted(set(keys) - fields)}"


def test_every_threshold_belongs_to_a_gate() -> None:
    named = {key for keys in _gate_meta().values() for key in keys}
    assert {field.name for field in dataclasses.fields(GateThresholds)} == named
