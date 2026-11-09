"""Tests for changelog fragment workflow detection and skeleton generation logic.

These tests exercise the same algorithms used in the workflow YAML,
reimplemented in Python to enable regression testing without a live
GitHub Actions environment.
"""

import json
import re
import subprocess
from typing import Any

import pytest


def glob_match(pattern: str, filename: str) -> bool:
    """Port of the workflow's globMatch JS function.

    Args:
        pattern: Glob pattern (e.g. "openapi/*.yaml").
        filename: File path to test against the pattern.

    Returns:
        Whether the filename matches the pattern.
    """
    parts = pattern.split("*")
    escaped = [re.escape(s) for s in parts]
    regex = "[^/]*".join(escaped)
    return bool(re.fullmatch(regex, filename))


def classify_spec_changes(
    files: list[dict[str, Any]],
    spec_paths: str,
) -> list[dict[str, str]]:
    """Port of the workflow's changedSpecs detection logic.

    Args:
        files: List of file objects with filename, status, and optional
            previous_filename (matching GitHub's pull request files API).
        spec_paths: Glob pattern for OpenAPI spec files.

    Returns:
        List of changed spec objects with path, status, and optional
        previous_path.
    """
    changed_specs: list[dict[str, str]] = []
    for f in files:
        status = f["status"]
        if status not in ("added", "modified", "removed", "renamed"):
            continue

        if status == "renamed":
            old_matches = bool(
                f.get("previous_filename")
                and glob_match(spec_paths, f["previous_filename"])
            )
            new_matches = glob_match(spec_paths, f["filename"])
            if old_matches and not new_matches:
                changed_specs.append(
                    {"path": f["previous_filename"], "status": "removed"}
                )
            elif not old_matches and new_matches:
                changed_specs.append({"path": f["filename"], "status": "added"})
            elif old_matches and new_matches:
                changed_specs.append(
                    {
                        "path": f["filename"],
                        "previous_path": f["previous_filename"],
                        "status": "renamed",
                    }
                )
        elif glob_match(spec_paths, f["filename"]):
            changed_specs.append({"path": f["filename"], "status": status})

    return changed_specs


class TestGlobMatch:
    """Tests for the glob matching function used in spec detection."""

    def test_exact_match(self) -> None:
        """Spec file in the configured directory matches."""
        assert glob_match("openapi/*.yaml", "openapi/v1.yaml")

    def test_no_match_different_dir(self) -> None:
        """File in a different directory does not match."""
        assert not glob_match("openapi/*.yaml", "docs/v1.yaml")

    def test_no_match_nested(self) -> None:
        """Wildcard does not cross directory boundaries."""
        assert not glob_match("openapi/*.yaml", "openapi/sub/v1.yaml")

    def test_wildcard_extension(self) -> None:
        """Bare wildcard matches any filename in the directory."""
        assert glob_match("openapi/*", "openapi/spec.json")

    def test_dots_escaped(self) -> None:
        """Dots in the pattern are literal, not regex wildcards."""
        assert not glob_match("openapi/*.yaml", "openapi/v1-yaml")


class TestSpecChangeDetection:
    """Tests for spec change classification including renames."""

    def test_added_spec(self) -> None:
        files = [{"filename": "openapi/v2.yaml", "status": "added"}]
        result = classify_spec_changes(files, "openapi/*.yaml")
        assert result == [{"path": "openapi/v2.yaml", "status": "added"}]

    def test_modified_spec(self) -> None:
        files = [{"filename": "openapi/v1.yaml", "status": "modified"}]
        result = classify_spec_changes(files, "openapi/*.yaml")
        assert result == [{"path": "openapi/v1.yaml", "status": "modified"}]

    def test_removed_spec(self) -> None:
        files = [{"filename": "openapi/v1.yaml", "status": "removed"}]
        result = classify_spec_changes(files, "openapi/*.yaml")
        assert result == [{"path": "openapi/v1.yaml", "status": "removed"}]

    def test_renamed_out_of_spec_paths(self) -> None:
        """Rename from openapi/ to docs/ should be classified as removed."""
        files = [
            {
                "filename": "docs/v1.yaml",
                "previous_filename": "openapi/v1.yaml",
                "status": "renamed",
            }
        ]
        result = classify_spec_changes(files, "openapi/*.yaml")
        assert result == [{"path": "openapi/v1.yaml", "status": "removed"}]

    def test_renamed_into_spec_paths(self) -> None:
        """Rename from docs/ to openapi/ should be classified as added."""
        files = [
            {
                "filename": "openapi/v1.yaml",
                "previous_filename": "docs/v1.yaml",
                "status": "renamed",
            }
        ]
        result = classify_spec_changes(files, "openapi/*.yaml")
        assert result == [{"path": "openapi/v1.yaml", "status": "added"}]

    def test_renamed_within_spec_paths(self) -> None:
        """Rename within openapi/ should preserve both paths."""
        files = [
            {
                "filename": "openapi/v2.yaml",
                "previous_filename": "openapi/v1.yaml",
                "status": "renamed",
            }
        ]
        result = classify_spec_changes(files, "openapi/*.yaml")
        assert result == [
            {
                "path": "openapi/v2.yaml",
                "previous_path": "openapi/v1.yaml",
                "status": "renamed",
            }
        ]

    def test_renamed_neither_matches(self) -> None:
        """Rename between non-spec dirs should produce no changes."""
        files = [
            {
                "filename": "docs/v1.yaml",
                "previous_filename": "archive/v1.yaml",
                "status": "renamed",
            }
        ]
        result = classify_spec_changes(files, "openapi/*.yaml")
        assert result == []

    def test_non_spec_file_ignored(self) -> None:
        files = [{"filename": "README.md", "status": "modified"}]
        result = classify_spec_changes(files, "openapi/*.yaml")
        assert result == []

    def test_fragment_file_not_in_specs(self) -> None:
        files = [{"filename": "changelogs/fragments/fix.yaml", "status": "added"}]
        result = classify_spec_changes(files, "openapi/*.yaml")
        assert result == []


class TestSkeletonBreakingDetection:
    """Tests for oasdiff JSON level parsing in skeleton generation.

    The workflow uses jq to filter oasdiff changelog JSON. oasdiff v1.18.5
    serializes checker.Level as an integer (ERR=3, WARN=2, INFO=1), not
    a string.
    """

    @staticmethod
    def _run_jq_breaking_count(oasdiff_json: list[dict[str, Any]]) -> int:
        result = subprocess.run(  # noqa: S603
            [  # noqa: S607
                "jq",
                "-r",
                "[.[] | select(.level >= 3)] | length",
            ],
            input=json.dumps(oasdiff_json),
            capture_output=True,
            text=True,
            check=True,
        )
        return int(result.stdout.strip())

    @pytest.mark.skipif(
        subprocess.run(  # noqa: S603, S607
            ["jq", "--version"],
            capture_output=True,
        ).returncode
        != 0,
        reason="jq not installed",
    )
    def test_error_level_detected(self) -> None:
        """ERR (level=3) should be counted as breaking."""
        changes = [
            {
                "id": "api-path-removed-without-deprecation",
                "level": 3,
                "text": "API path removed",
                "path": "/api/v1/adhoc",
            }
        ]
        assert self._run_jq_breaking_count(changes) == 1

    @pytest.mark.skipif(
        subprocess.run(  # noqa: S603, S607
            ["jq", "--version"],
            capture_output=True,
        ).returncode
        != 0,
        reason="jq not installed",
    )
    def test_warn_level_not_breaking(self) -> None:
        """WARN (level=2) should not be counted as breaking."""
        changes = [
            {
                "id": "response-optional-property-removed",
                "level": 2,
                "text": "Optional property removed",
                "path": "/api/v1/users",
            }
        ]
        assert self._run_jq_breaking_count(changes) == 0

    @pytest.mark.skipif(
        subprocess.run(  # noqa: S603, S607
            ["jq", "--version"],
            capture_output=True,
        ).returncode
        != 0,
        reason="jq not installed",
    )
    def test_mixed_levels(self) -> None:
        """Only ERR-level entries count as breaking."""
        changes = [
            {"id": "api-path-added", "level": 1, "text": "Added"},
            {"id": "response-optional-property-removed", "level": 2, "text": "Warn"},
            {"id": "api-path-removed-without-deprecation", "level": 3, "text": "Err"},
        ]
        assert self._run_jq_breaking_count(changes) == 1
