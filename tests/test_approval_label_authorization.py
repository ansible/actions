"""Tests for the approval label authorization workflow's membership check."""

import os
import subprocess
from pathlib import Path
from typing import NamedTuple

WORKFLOW = (
    Path(__file__).parents[1]
    / ".github"
    / "workflows"
    / "approval-label-authorization.yml"
)


class GitHubEvent(NamedTuple):
    """The GitHub event fields consumed by the authorization workflow.

    Attributes:
        name: The GitHub event name.
        action: The event action.
        label: The label attached to the event.
    """

    name: str = "pull_request_target"
    action: str = "labeled"
    label: str = "breaking-change-approved"


def _workflow_script() -> str:
    """Return the workflow's inline shell script so tests exercise the real code.

    Returns:
        The workflow's inline shell script.
    """
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    run_line = next(
        index for index, line in enumerate(lines) if line == "        run: |"
    )
    script_lines = []

    for line in lines[run_line + 1 :]:
        if line and not line.startswith("          "):
            break
        script_lines.append(line[10:] if line else "")

    return "\n".join(script_lines)


def _run_workflow_script(
    tmp_path: Path,
    *,
    api_error: bool,
    membership: str = "active",
    event: GitHubEvent | None = None,
    approval_label: str = "breaking-change-approved",
) -> subprocess.CompletedProcess[str]:
    """Run the inline check with a fake gh command and controlled API result.

    Args:
        tmp_path: A temporary directory for the fake ``gh`` command.
        api_error: Whether the mocked API call should fail.
        membership: The team membership state returned by the mocked API.
        event: The triggering event's name, action, and label.

    Returns:
        The completed shell process.
    """
    event = event or GitHubEvent()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'if [[ "${1:-}" == api && "${2:-}" == --method && '
        '"${3:-}" == DELETE ]]; then\n'
        '  expected_endpoint="repos/${REPOSITORY}/issues/${PR_NUMBER}/labels/${LABEL_NAME}"\n'
        '  if [[ "${GH_TOKEN}" != "${LABEL_TOKEN}" || '
        '"${4:-}" != "${expected_endpoint}" ]]; then\n'
        "    echo 'unexpected label deletion request' >&2\n"
        "    exit 1\n"
        "  fi\n"
        '  printf \'%s\\n\' "${4}" >> "${MOCK_GH_CALLS}"\n'
        "  exit 0\n"
        "fi\n"
        'if [[ "${1:-}" == api && "${2:-}" == --method && '
        '"${3:-}" == POST ]]; then\n'
        '  expected_endpoint="repos/${REPOSITORY}/issues/${PR_NUMBER}/labels"\n'
        '  if [[ "${GH_TOKEN}" != "${LABEL_TOKEN}" || '
        '"${4:-}" != "${expected_endpoint}" || '
        '"${5:-}" != "-f" || "${6:-}" != "labels[]=${LABEL_NAME}" ]]; then\n'
        "    echo 'unexpected label restoration request' >&2\n"
        "    exit 1\n"
        "  fi\n"
        '  printf \'%s\\n\' "${4}?${6}" >> "${MOCK_GH_CALLS}"\n'
        "  exit 0\n"
        "fi\n"
        "if [[ ${MOCK_API_ERROR} == true ]]; then\n"
        "  echo 'gh: Not Found (HTTP 404)' >&2\n"
        "  exit 1\n"
        "fi\n"
        "printf '%s\\n' \"${MOCK_MEMBERSHIP}\"\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "GH_TOKEN": "test-token",
        "LABEL_TOKEN": "label-token",
        "ACTOR": "contributor",
        "TEAM_ORG": "ansible",
        "TEAM_SLUG": "ansible-staff-eng-leads",
        "LABEL_NAME": approval_label,
        "LABEL_ACTION": event.action,
        "EVENT_NAME": event.name,
        "EVENT_ACTION": event.action,
        "EVENT_LABEL": event.label,
        "REPOSITORY": "ansible/awx",
        "PR_NUMBER": "42",
        "MOCK_GH_CALLS": str(tmp_path / "gh_calls"),
        "MOCK_API_ERROR": str(api_error).lower(),
        "MOCK_MEMBERSHIP": membership,
    }
    return subprocess.run(
        ["/bin/bash", "-c", _workflow_script()],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_non_member_is_rejected_and_api_error_is_visible(tmp_path: Path) -> None:
    """A non-member API response fails authorization and retains gh diagnostics.

    Args:
        tmp_path: A temporary directory for the fake ``gh`` command.
    """
    result = _run_workflow_script(tmp_path, api_error=True)

    assert result.returncode != 0
    assert "gh: Not Found (HTTP 404)" in result.stderr
    assert "Could not verify whether contributor belongs to" in result.stdout


def test_active_team_member_is_authorized(tmp_path: Path) -> None:
    """An active team member can change the approval label.

    Args:
        tmp_path: A temporary directory for the fake ``gh`` command.
    """
    result = _run_workflow_script(tmp_path, api_error=False)

    assert result.returncode == 0
    assert "contributor is an active member" in result.stdout


def test_custom_approval_label_is_authorized(tmp_path: Path) -> None:
    """A configured custom label is checked against the same event label.

    Args:
        tmp_path: A temporary directory for the fake ``gh`` command.
    """
    result = _run_workflow_script(
        tmp_path,
        api_error=False,
        approval_label="api-change-approved",
        event=GitHubEvent(label="api-change-approved"),
    )

    assert result.returncode == 0
    assert "'api-change-approved' label change is authorized" in result.stdout


def test_pending_team_member_is_rejected_and_label_is_removed(tmp_path: Path) -> None:
    """A pending member is rejected and the newly added label is removed.

    Args:
        tmp_path: A temporary directory for the fake ``gh`` command.
    """
    result = _run_workflow_script(tmp_path, api_error=False, membership="pending")

    assert result.returncode != 0
    assert "contributor is not an active member" in result.stdout
    assert "Removed 'breaking-change-approved'" in result.stdout
    assert (tmp_path / "gh_calls").read_text(encoding="utf-8").splitlines() == [
        "repos/ansible/awx/issues/42/labels/breaking-change-approved"
    ]


def test_pending_team_member_cannot_remove_label(tmp_path: Path) -> None:
    """An unauthorized removal is reversed by restoring the approval label.

    Args:
        tmp_path: A temporary directory for the fake ``gh`` command.
    """
    result = _run_workflow_script(
        tmp_path,
        api_error=False,
        membership="pending",
        event=GitHubEvent(action="unlabeled"),
    )

    assert result.returncode != 0
    assert "contributor is not an active member" in result.stdout
    assert "Restored 'breaking-change-approved'" in result.stdout
    assert (tmp_path / "gh_calls").read_text(encoding="utf-8").splitlines() == [
        "repos/ansible/awx/issues/42/labels?labels[]=breaking-change-approved"
    ]


def test_reusable_workflow_filters_using_approval_label_input() -> None:
    """The reusable workflow owns filtering so callers do not hardcode labels.

    Returns:
        None.
    """
    workflow = WORKFLOW.read_text(encoding="utf-8")
    readme = (WORKFLOW.parent / "README-approval-label-authorization.md").read_text(
        encoding="utf-8"
    )

    assert "if: github.event.label.name == inputs.approval-label" in workflow
    assert "if: github.event.label.name == 'breaking-change-approved'" not in readme


def test_wrong_event_type_fails_instead_of_skipping(tmp_path: Path) -> None:
    """A caller using pull_request fails the security gate instead of skipping it.

    Args:
        tmp_path: A temporary directory for the fake ``gh`` command.
    """
    result = _run_workflow_script(
        tmp_path,
        api_error=False,
        event=GitHubEvent(name="pull_request"),
    )

    assert result.returncode != 0
    assert "must be called from a pull_request_target workflow" in result.stdout


def test_wrong_event_action_fails_instead_of_skipping(tmp_path: Path) -> None:
    """A caller using an unsupported action fails the security gate.

    Args:
        tmp_path: A temporary directory for the fake ``gh`` command.
    """
    result = _run_workflow_script(
        tmp_path,
        api_error=False,
        event=GitHubEvent(action="opened"),
    )

    assert result.returncode != 0
    assert "must be triggered by a labeled or unlabeled action" in result.stdout


def test_label_input_mismatch_fails_instead_of_skipping(tmp_path: Path) -> None:
    """A caller whose configured label differs from the event label fails.

    Args:
        tmp_path: A temporary directory for the fake ``gh`` command.
    """
    result = _run_workflow_script(
        tmp_path,
        api_error=False,
        event=GitHubEvent(label="other-label"),
    )

    assert result.returncode != 0
    assert "does not match the configured approval label" in result.stdout
