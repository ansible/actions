"""Tests for oasdiff taxonomy mapping and breaking change detection."""

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

TESTS_DIR = Path(__file__).parent
REPO_ROOT = TESTS_DIR.parent.parent
CONFIG_DIR = REPO_ROOT / "config"
TAXONOMY_MAP_PATH = CONFIG_DIR / "oasdiff-taxonomy-map.json"
WORKFLOW_PATH = (
    REPO_ROOT / ".github" / "workflows" / "oasdiff-detect-breaking-changes.yml"
)
BASE_SPEC = TESTS_DIR / "base-spec.yaml"


def _oasdiff_available() -> bool:
    try:
        subprocess.run(
            ["oasdiff", "--help"],
            capture_output=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False
    return True


def test_taxonomy_map_is_valid_json() -> None:
    """Taxonomy mapping file must be valid JSON with expected structure."""
    data = json.loads(TAXONOMY_MAP_PATH.read_text())
    assert "mapping" in data
    assert isinstance(data["mapping"], dict)
    assert len(data["mapping"]) > 0
    for key, value in data["mapping"].items():
        assert isinstance(key, str), f"Key {key!r} must be a string"
        assert value.startswith("Category "), (
            f"Value {value!r} must start with 'Category '"
        )


def test_taxonomy_map_covers_all_categories() -> None:
    """Taxonomy mapping must cover at least categories 1-8, 10."""
    data = json.loads(TAXONOMY_MAP_PATH.read_text())
    categories_present = set(data["mapping"].values())
    for cat_num in [1, 2, 3, 4, 5, 6, 7, 8, 10]:
        matches = [
            c for c in categories_present if c.startswith(f"Category {cat_num}:")
        ]
        assert len(matches) > 0, f"Category {cat_num} has no mapping entries"


def _extract_inline_taxonomy(workflow_text: str) -> dict[str, str]:
    pairs = re.findall(
        r'"([a-z][a-z0-9-]+)":\s*"(Category \d+:[^"]+)"',
        workflow_text,
    )
    return dict(pairs)


def test_taxonomy_map_in_sync_with_workflow() -> None:
    """Inline taxonomy in the workflow must match the JSON reference file."""
    json_data = json.loads(TAXONOMY_MAP_PATH.read_text())
    json_mapping = json_data["mapping"]

    workflow_text = WORKFLOW_PATH.read_text()
    inline_mapping = _extract_inline_taxonomy(workflow_text)

    assert inline_mapping, "Could not extract inline taxonomy from workflow"

    json_keys = set(json_mapping.keys())
    inline_keys = set(inline_mapping.keys())

    missing_from_workflow = json_keys - inline_keys
    assert not missing_from_workflow, (
        f"Keys in JSON but missing from workflow inline map: {missing_from_workflow}"
    )

    extra_in_workflow = inline_keys - json_keys
    assert not extra_in_workflow, (
        f"Keys in workflow inline map but missing from JSON: {extra_in_workflow}"
    )

    for key in json_keys:
        assert json_mapping[key] == inline_mapping[key], (
            f"Value mismatch for {key!r}: "
            f"JSON={json_mapping[key]!r}, workflow={inline_mapping[key]!r}"
        )


def test_base_spec_is_valid_yaml() -> None:
    """Base test spec must be parseable."""
    data: dict[str, Any] = yaml.safe_load(BASE_SPEC.read_text())  # type: ignore[no-untyped-call]
    assert data["openapi"].startswith("3.")
    assert "paths" in data
    assert "components" in data


@pytest.mark.skipif(not _oasdiff_available(), reason="oasdiff CLI not installed")
class TestOasdiffDetection:
    """Integration tests that require oasdiff CLI to be installed."""

    def _run_oasdiff(self, revised_spec: Path) -> dict[str, Any]:
        result = subprocess.run(
            [
                "oasdiff",
                "breaking",
                str(BASE_SPEC),
                str(revised_spec),
                "--format",
                "json",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.stdout.strip():
            parsed: dict[str, Any] = json.loads(result.stdout)
            return parsed
        return {}

    def _has_breaking_changes(self, revised_spec: Path) -> bool:
        result = subprocess.run(
            [
                "oasdiff",
                "breaking",
                str(BASE_SPEC),
                str(revised_spec),
                "--fail-on",
                "ERR",
            ],
            capture_output=True,
            check=False,
        )
        return result.returncode != 0

    def test_detects_endpoint_removal(self) -> None:
        """Category 1: removing an endpoint is a breaking change."""
        spec = TESTS_DIR / "breaking-remove-endpoint.yaml"
        assert self._has_breaking_changes(spec)

    def test_detects_field_removal(self) -> None:
        """Category 2: removing a response field is a breaking change."""
        spec = TESTS_DIR / "breaking-remove-field.yaml"
        assert self._has_breaking_changes(spec)

    def test_detects_required_field_addition(self) -> None:
        """Category 3: adding a required request field is a breaking change."""
        spec = TESTS_DIR / "breaking-required-field.yaml"
        assert self._has_breaking_changes(spec)

    def test_nonbreaking_passes_cleanly(self) -> None:
        """Non-breaking: adding an optional response field should pass."""
        spec = TESTS_DIR / "nonbreaking-add-field.yaml"
        assert not self._has_breaking_changes(spec)

    def test_identical_specs_pass(self) -> None:
        """Comparing a spec to itself should produce no breaking changes."""
        assert not self._has_breaking_changes(BASE_SPEC)
