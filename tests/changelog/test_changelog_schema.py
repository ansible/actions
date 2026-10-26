"""Tests for changelog fragment schema validation."""

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

try:
    import jsonschema
except ImportError:
    jsonschema = None  # type: ignore[assignment]

TESTS_DIR = Path(__file__).parent
REPO_ROOT = TESTS_DIR.parent.parent
SCHEMA_PATH = REPO_ROOT / "config" / "changelog-fragment-schema.json"


def _load_schema() -> dict[str, Any]:
    """Load the changelog fragment JSON Schema."""
    return json.loads(SCHEMA_PATH.read_text())  # type: ignore[no-untyped-call]


def _load_fragment(name: str) -> dict[str, Any]:
    """Load a changelog fragment YAML fixture."""
    return yaml.safe_load((TESTS_DIR / name).read_text())  # type: ignore[no-untyped-call]


def test_schema_is_valid_json() -> None:
    """Schema file must be valid JSON with expected structure."""
    schema = _load_schema()
    assert "$schema" in schema, "Schema must declare $schema key"
    assert "type" in schema, "Schema must declare type"
    assert "required" in schema, "Schema must declare required fields"
    assert "properties" in schema, "Schema must declare properties"


def test_schema_allows_additional_properties() -> None:
    """Schema must allow additional properties for service-specific fields."""
    schema = _load_schema()
    # additionalProperties must not be false (can be true or undefined)
    assert schema.get("additionalProperties") is not False, (
        "Schema must allow additional properties (additionalProperties must not be false)"
    )


@pytest.mark.skipif(jsonschema is None, reason="jsonschema not installed")
@pytest.mark.parametrize(
    "fixture",
    [
        "valid-basic.yaml",
        "valid-deprecated-with-migration.yaml",
        "valid-multi-type.yaml",
        "valid-multi-endpoint.yaml",
        "valid-wildcard-endpoint.yaml",
        "valid-security-with-cve.yaml",
        "valid-no-endpoint.yaml",
        "valid-extra-fields.yaml",
    ],
)
def test_valid_fragment_passes(fixture: str) -> None:
    """Valid changelog fragments must pass schema validation."""
    schema = _load_schema()
    fragment = _load_fragment(fixture)
    jsonschema.validate(fragment, schema)  # type: ignore[attr-defined]


@pytest.mark.skipif(jsonschema is None, reason="jsonschema not installed")
@pytest.mark.parametrize(
    "fixture",
    [
        "invalid-missing-title.yaml",
        "invalid-bad-type.yaml",
        "invalid-todo-summary.yaml",
        "invalid-breaking-no-migration.yaml",
        "invalid-deprecated-no-migration.yaml",
        "invalid-deprecated-list-no-migration.yaml",
        "invalid-glob-endpoint.yaml",
    ],
)
def test_invalid_fragment_fails(fixture: str) -> None:
    """Invalid changelog fragments must fail schema validation."""
    schema = _load_schema()
    fragment = _load_fragment(fixture)
    with pytest.raises(jsonschema.ValidationError):  # type: ignore[attr-defined]
        jsonschema.validate(fragment, schema)  # type: ignore[attr-defined]
