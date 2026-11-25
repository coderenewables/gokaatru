"""Every operation's result model describes what it really returns (P1-19, decisions/0009).

Each operation declares the Pydantic model of its result (``server/schemas/results``), and
the generated route publishes it in the OpenAPI schema for the TypeScript client. The routes
never validate against it, so a wrong model would mislead the client rather than fail a
call; this test is what keeps the two in step. Every response ``tests/operation_samples.py``
collects, from every operation and both dry runs, must validate strictly against its model as
it crosses the wire: undeclared fields refused, and a declared type that does not match
refused.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from server.api.main import create_app
from server.operations import REGISTRY
from tests.operation_samples import Samples, collect


@pytest.fixture(scope="module")
def samples(tmp_path_factory) -> Samples:
    with pytest.MonkeyPatch.context() as monkeypatch:
        return collect(tmp_path_factory.mktemp("results"), monkeypatch)


def test_every_operation_declares_its_result() -> None:
    assert sorted(op.name for op in REGISTRY if op.result is None) == []
    assert sorted(op.name for op in REGISTRY if op.dry_run is not None and op.preview_result is None) == []


def test_every_operation_has_a_real_response(samples: Samples) -> None:
    assert sorted(REGISTRY.names() - set(samples.by_operation)) == []
    assert sorted(op.name for op in REGISTRY if op.dry_run is not None) == sorted(samples.previews)


@pytest.mark.parametrize("name", sorted(op.name for op in REGISTRY))
def test_each_response_validates_against_its_model(name: str, samples: Samples) -> None:
    model = REGISTRY.get(name).result
    for wire in samples.by_operation[name]:
        try:
            model.model_validate_json(wire, strict=True)
        except ValidationError as exc:
            pytest.fail(f"{name}: {exc}")


@pytest.mark.parametrize("name", sorted(op.name for op in REGISTRY if op.dry_run is not None))
def test_each_preview_validates_against_its_model(name: str, samples: Samples) -> None:
    model = REGISTRY.get(name).preview_result
    for wire in samples.previews[name]:
        model.model_validate_json(wire, strict=True)


def test_a_model_refuses_a_field_it_does_not_declare(samples: Samples) -> None:
    model = REGISTRY.get("compute_weibull_params").result
    wire = samples.by_operation["compute_weibull_params"][0]
    with pytest.raises(ValidationError, match="extra"):
        model.model_validate_json(wire[:-1] + ', "undeclared": 1}', strict=True)


def test_every_operation_route_has_a_typed_response_in_openapi() -> None:
    with TestClient(create_app()) as client:
        spec = client.get("/openapi.json").json()
    schemas = spec["components"]["schemas"]
    untyped = []
    for path, item in spec["paths"].items():
        if "/operations/" not in path:
            continue
        responses = item["post"]["responses"]
        reference = responses["200"]["content"]["application/json"]["schema"].get("$ref", "")
        if not reference.startswith("#/components/schemas/") or reference.rsplit("/", 1)[1] not in schemas:
            untyped.append(path)
        for status in ("400", "502"):
            assert responses[status]["content"]["application/json"]["schema"]["$ref"].endswith("/ErrorDetail")
    assert untyped == []


def test_result_schema_names_are_not_module_qualified() -> None:
    """Two models of one name get a module-qualified schema name, which the generated
    TypeScript client would carry as a type name."""
    with TestClient(create_app()) as client:
        names = client.get("/openapi.json").json()["components"]["schemas"]
    assert sorted(name for name in names if name.startswith("server__")) == []
