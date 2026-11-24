"""The committed OpenAPI schema is the one the server serves (P1-20).

The TypeScript client is generated from ``frontend/src/api/openapi.json``; a route or model
changed without refreshing it would leave the client describing an API that no longer
exists. CI regenerates the client from this file and fails when it is stale too.
"""
from __future__ import annotations

from tests.openapi_schema import SCHEMA_PATH, current_schema, render


def test_the_committed_schema_is_current() -> None:
    assert SCHEMA_PATH.exists(), "run python -m tests.openapi_schema --write"
    assert SCHEMA_PATH.read_text(encoding="utf-8") == render(current_schema()), (
        "the OpenAPI schema changed: run python -m tests.openapi_schema --write, then "
        "npm run generate:api in frontend/"
    )


def test_the_schema_names_no_local_path() -> None:
    text = SCHEMA_PATH.read_text(encoding="utf-8")
    for marker in ("C:\\\\", "\\Users\\\\", "/home/", "/Users/"):
        assert marker not in text
