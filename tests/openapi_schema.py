"""The HTTP API's OpenAPI schema, committed for the generated TypeScript client (P1-20).

``frontend/src/api/openapi.json`` is the schema the client in ``frontend/src/api/schema.d.ts``
is generated from (``npm run generate:api``). Refresh both after any change to a route, an
operation's parameters or a result model:

    python -m tests.openapi_schema --write
    cd frontend && npm run generate:api
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "frontend" / "src" / "api" / "openapi.json"


def current_schema() -> dict[str, Any]:
    from server.api.main import create_app

    return create_app().openapi()


def render(schema: dict[str, Any]) -> str:
    return json.dumps(schema, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="overwrite the committed schema")
    args = parser.parse_args(argv)
    text = render(current_schema())
    if args.write:
        SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
        SCHEMA_PATH.write_text(text, encoding="utf-8", newline="\n")
        print(f"{len(text):,} characters written to {SCHEMA_PATH}")
        return 0
    same = SCHEMA_PATH.exists() and SCHEMA_PATH.read_text(encoding="utf-8") == text
    print("identical to the committed schema" if same else "different from the committed schema")
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main())
