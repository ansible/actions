"""Tests for the approval label authorization workflow's membership check."""

import os
import subprocess
from dataclasses import dataclass, field
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


@dataclass(frozen=True)
class WorkflowScenario:
    """Inputs that control the mocked GitHub API and triggering event.

    Attributes:
        api_error: Whether the mocked membership API call should fail.
        membership: The team membership state returned by the mock.
        event: The triggering event's name, action, and label.
        label_write_error: Whether mocked label writes should fail.
        label_present_after_restore: Whether verification reports the label.
    """

    api_error: bool = False
    membership: str = "active"
    event: GitHubEvent = field(default_factory=GitHubEvent)
    label_write_error: bool = False
    label_present_after_restore: bool = True


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
    scenario: WorkflowScenario | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the inline check with a fake gh command and controlled API result.

    Args:
        tmp_path: A temporary directory for the fake ``gh`` command.
        scenario: The mocked API behavior and triggering event.

    Returns:
        The completed shell process.
    """
    scenario = scenario or WorkflowScenario()
    event = scenario.event
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
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
        "  if [[ ${MOCK_LABEL_WRITE_ERROR} == true ]]; then\n"
        "    echo 'gh: label write failed' >&2\n"
        "    exit 1\n"
        "  fi\n"
        '  printf \'%s\\n\' "${4}?${6}" >> "${MOCK_GH_CALLS}"\n'
        "  exit 0\n"
        "fi\n"
        'if [[ "${1:-}" == api && "${2:-}" == --paginate ]]; then\n'
        '  expected_endpoint="repos/${REPOSITORY}/issues/${PR_NUMBER}/labels"\n'
        '  if [[ "${GH_TOKEN}" != "${LABEL_TOKEN}" || '
        '"${3:-}" != "${expected_endpoint}" || '
        '"${4:-}" != "--jq" || "${5:-}" != ".[].name" ]]; then\n'
        "    echo 'unexpected label verification request' >&2\n"
        "    exit 1\n"
        "  fi\n"
        '  printf \'%s\\n\' "${3}?${4}=${5}" >> "${MOCK_GH_CALLS}"\n'
        "  if [[ ${MOCK_LABEL_PRESENT_AFTER_RESTORE} == true ]]; then\n"
        "    printf '%s\\n' \"${LABEL_NAME}\"\n"
        "  fi\n"
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
        "LABEL_NAME": "breaking-change-approved",
        "LABEL_ACTION": event.action,
        "EVENT_NAME": event.name,
        "EVENT_ACTION": event.action,
        "EVENT_LABEL": event.label,
        "REPOSITORY": "ansible/awx",
        "PR_NUMBER": "42",
        "MOCK_GH_CALLS": str(tmp_path / "gh_calls"),
        "MOCK_API_ERROR": str(scenario.api_error).lower(),
        "MOCK_MEMBERSHIP": scenario.membership,
        "MOCK_LABEL_WRITE_ERROR": str(scenario.label_write_error).lower(),
        "MOCK_LABEL_PRESENT_AFTER_RESTORE": str(
            scenario.label_present_after_restore
        ).lower(),
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
    result = _run_workflow_script(
        tmp_path,
        scenario=WorkflowScenario(api_error=True),
    )

    assert result.returncode != 0
    assert "gh: Not Found (HTTP 404)" in result.stderr
    assert "Could not verify whether contributor belongs to" in result.stdout


def test_active_team_member_is_authorized(tmp_path: Path) -> None:
    """An active team member can change the approval label.

    Args:
        tmp_path: A temporary directory for the fake ``gh`` command.
    """
    result = _run_workflow_script(tmp_path)

    assert result.returncode == 0
    assert "contributor is an active member" in result.stdout


def test_other_label_event_is_ignored(tmp_path: Path) -> None:
    """Unrelated labels do not invoke the membership lookup.

    Args:
        tmp_path: A temporary directory for the fake ``gh`` command.
    """
    result = _run_workflow_script(
        tmp_path,
        scenario=WorkflowScenario(event=GitHubEvent(label="bug")),
    )

    assert result.returncode == 0
    assert "Ignoring 'labeled' event for unrelated label 'bug'" in result.stdout
    assert not (tmp_path / "gh_calls").exists()


def test_pending_team_member_is_rejected_and_label_is_removed(tmp_path: Path) -> None:
    """A pending member is rejected and the newly added label is removed.

    Args:
        tmp_path: A temporary directory for the fake ``gh`` command.
    """
    result = _run_workflow_script(
        tmp_path,
        scenario=WorkflowScenario(membership="pending"),
    )

    assert result.returncode != 0
    assert "contributor is not an active member" in result.stdout
    assert "Removed 'breaking-change-approved'" in result.stdout
    assert (tmp_path / "gh_calls").read_text(encoding="utf-8").splitlines() == [
        "repos/ansible/awx/issues/42/labels/breaking-change-approved"
    ]


def test_pending_team_member_cannot_remove_label(tmp_path: Path) -> None:
    """A restored and verified approval label makes the check pass.

    Args:
        tmp_path: A temporary directory for the fake ``gh`` command.
    """
    result = _run_workflow_script(
        tmp_path,
        scenario=WorkflowScenario(
            membership="pending",
            event=GitHubEvent(action="unlabeled"),
        ),
    )

    assert result.returncode == 0
    assert "contributor is not an active member" in result.stdout
    assert "Restored and verified 'breaking-change-approved'" in result.stdout
    assert "check passes because the approval state is intact" in result.stdout
    assert (tmp_path / "gh_calls").read_text(encoding="utf-8").splitlines() == [
        "repos/ansible/awx/issues/42/labels?labels[]=breaking-change-approved",
        "repos/ansible/awx/issues/42/labels?--jq=.[].name",
    ]


def test_unverified_member_removal_passes_after_restoration(tmp_path: Path) -> None:
    """Membership API failure is tolerated if the approval label is restored.

    Args:
        tmp_path: A temporary directory for the fake ``gh`` command.
    """
    result = _run_workflow_script(
        tmp_path,
        scenario=WorkflowScenario(
            api_error=True,
            event=GitHubEvent(action="unlabeled"),
        ),
    )

    assert result.returncode == 0
    assert "gh: Not Found (HTTP 404)" in result.stderr
    assert "The approval label was restored" in result.stdout


def test_member_removal_fails_if_label_is_missing_after_restore(
    tmp_path: Path,
) -> None:
    """A successful POST is insufficient if the label is still absent.

    Args:
        tmp_path: A temporary directory for the fake ``gh`` command.
    """
    result = _run_workflow_script(
        tmp_path,
        scenario=WorkflowScenario(
            membership="pending",
            event=GitHubEvent(action="unlabeled"),
            label_present_after_restore=False,
        ),
    )

    assert result.returncode != 0
    assert (
        "Could not verify that 'breaking-change-approved' was restored" in result.stdout
    )


def test_member_removal_fails_if_restoration_request_fails(tmp_path: Path) -> None:
    """An unsuccessful label restoration keeps the authorization check red.

    Args:
        tmp_path: A temporary directory for the fake ``gh`` command.
    """
    result = _run_workflow_script(
        tmp_path,
        scenario=WorkflowScenario(
            membership="pending",
            event=GitHubEvent(action="unlabeled"),
            label_write_error=True,
        ),
    )

    assert result.returncode != 0
    assert "Could not restore 'breaking-change-approved'" in result.stdout


def test_reusable_workflow_has_fixed_team_and_label_without_job_filter() -> None:
    """The policy team and label are fixed in the reusable workflow.

    Returns:
        None.
    """
    workflow = WORKFLOW.read_text(encoding="utf-8")
    readme = (WORKFLOW.parent / "README-approval-label-authorization.md").read_text(
        encoding="utf-8"
    )

    assert "if: github.event.label.name == inputs.approval-label" not in workflow
    assert "approval-label:" not in workflow
    assert "team-slug:" not in workflow
    assert "TEAM_SLUG: ansible-staff-eng-leads" in workflow
    assert "LABEL_NAME: breaking-change-approved" in workflow
    assert "      approval-label:" not in readme
    assert "types: [opened, synchronize, reopened, labeled, unlabeled]" in readme


def test_wrong_event_type_fails_instead_of_skipping(tmp_path: Path) -> None:
    """A caller using pull_request fails the security gate instead of skipping it.

    Args:
        tmp_path: A temporary directory for the fake ``gh`` command.
    """
    result = _run_workflow_script(
        tmp_path,
        scenario=WorkflowScenario(event=GitHubEvent(name="pull_request")),
    )

    assert result.returncode != 0
    assert "must be called from a pull_request_target workflow" in result.stdout


def test_lifecycle_events_complete_without_membership_lookup(tmp_path: Path) -> None:
    """Lifecycle events report success without needing a label actor check.

    Args:
        tmp_path: A temporary directory for the fake ``gh`` command.
    """
    for action in ("opened", "synchronize", "reopened"):
        event_dir = tmp_path / action
        result = _run_workflow_script(
            event_dir,
            scenario=WorkflowScenario(event=GitHubEvent(action=action, label="")),
        )

        assert result.returncode == 0
        assert f"Pull request lifecycle event '{action}'" in result.stdout
        assert not (event_dir / "gh_calls").exists()


def test_unsupported_event_action_fails_instead_of_skipping(tmp_path: Path) -> None:
    """A caller using an unsupported event action fails the security gate.

    Args:
        tmp_path: A temporary directory for the fake ``gh`` command.
    """
    result = _run_workflow_script(
        tmp_path,
        scenario=WorkflowScenario(event=GitHubEvent(action="closed")),
    )

    assert result.returncode != 0
    assert (
        "must be triggered by opened, synchronize, reopened, labeled, or unlabeled"
        in result.stdout
    )
