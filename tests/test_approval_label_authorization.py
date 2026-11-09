"""Tests for the approval-label authorization workflow's membership check."""

import json
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
        name: The event name.
        action: The event action.
        label: The label attached to the event.
    """

    name: str = "pull_request_target"
    action: str = "labeled"
    label: str = "breaking-change-approved"


@dataclass(frozen=True)
class WorkflowScenario:
    """Inputs controlling mock API responses and the triggering event.

    Attributes:
        api_error: Whether the membership endpoint should fail.
        membership: The membership state returned by the mock API.
        event: The event that triggers the workflow.
        label_write_error: Whether the mock should reject label changes.
        label_present: Whether the protected label currently exists.
        latest_actor: Actor on the latest label event.
        marker_ids: Label-event IDs trusted as bot-marked.
    """

    api_error: bool = False
    membership: str = "active"
    event: GitHubEvent = field(default_factory=GitHubEvent)
    label_write_error: bool = False
    label_present: bool = True
    latest_actor: str = "contributor"
    marker_ids: tuple[int, ...] = ()


def _workflow_script() -> str:
    """Extract the workflow's inline shell script.

    Returns:
        The shell script from the workflow file.
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
    """Run the real workflow script against a stateful fake ``gh`` command.

    Args:
        tmp_path: The temporary directory used for mock files.
        scenario: The event and API behavior to simulate.

    Returns:
        The completed workflow process.
    """
    scenario = scenario or WorkflowScenario()
    event = scenario.event
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    gh = bin_dir / "gh"

    if event.action == "unlabeled":
        timeline = [
            {
                "id": 100,
                "event": "labeled",
                "actor": {"login": scenario.latest_actor},
                "created_at": "2026-01-01T00:00:00Z",
                "label": {"name": "breaking-change-approved"},
            },
            {
                "id": 101,
                "event": "unlabeled",
                "actor": {"login": "contributor"},
                "created_at": "2026-01-02T00:00:00Z",
                "label": {"name": "breaking-change-approved"},
            },
        ]
    else:
        timeline = [
            {
                "id": 100,
                "event": "labeled",
                "actor": {"login": scenario.latest_actor},
                "created_at": "2026-01-01T00:00:00Z",
                "label": {"name": "breaking-change-approved"},
            }
        ]

    timeline_path = tmp_path / "timeline.json"
    timeline_path.write_text(json.dumps(timeline), encoding="utf-8")
    label_path = tmp_path / "label-present"
    label_path.write_text(str(scenario.label_present).lower(), encoding="utf-8")
    markers_path = tmp_path / "markers.json"
    markers_path.write_text(json.dumps(list(scenario.marker_ids)), encoding="utf-8")

    gh.write_text(
        r"""#!/usr/bin/env bash
set -euo pipefail
[[ "${1:-}" == api ]] || { echo "unexpected gh command" >&2; exit 1; }
method=GET
path=
filter=
form=
while (($#)); do
  case "$1" in
    --method) method="$2"; shift 2 ;;
    --jq) filter="$2"; shift 2 ;;
    -f) form="$2"; shift 2 ;;
    --paginate|--slurp) shift ;;
    *) if [[ "$1" == repos/* || "$1" == orgs/* ]]; then path="$1"; fi; shift ;;
  esac
done
printf '%s %s\n' "$method" "$path" >> "$MOCK_GH_CALLS"

if [[ "$path" == */timeline && "$method" == GET ]]; then
  jq -c 'sort_by(.created_at)' "$MOCK_TIMELINE_FILE"
  exit 0
fi
if [[ "$path" == */comments && "$method" == GET ]]; then
  event_id=$(sed -nE 's/.*label_event_id=([0-9]+).*/\1/p' <<<"$filter")
  if [[ -n "$event_id" ]] && jq -e --argjson id "$event_id" 'index($id) != null' "$MOCK_MARKERS_FILE" >/dev/null; then
    echo true
  else
    echo false
  fi
  exit 0
fi
if [[ "$path" == */comments && "$method" == POST ]]; then
  [[ "$LABEL_TOKEN" == "$GH_TOKEN" ]] || { echo "bad comment token" >&2; exit 1; }
  event_id=$(sed -nE 's/.*label_event_id=([0-9]+).*/\1/p' <<<"$form")
  [[ -n "$event_id" ]] || { echo "missing marker id" >&2; exit 1; }
  jq --argjson id "$event_id" 'if index($id) then . else . + [$id] end' "$MOCK_MARKERS_FILE" > "$MOCK_MARKERS_FILE.tmp"
  mv "$MOCK_MARKERS_FILE.tmp" "$MOCK_MARKERS_FILE"
  exit 0
fi
if [[ "$path" == */labels && "$method" == GET ]]; then
  if [[ $(cat "$MOCK_LABEL_PRESENT_FILE") == true ]]; then
    echo breaking-change-approved
  fi
  exit 0
fi
if [[ "$path" == */labels && "$method" == POST ]]; then
  [[ "$LABEL_TOKEN" == "$GH_TOKEN" ]] || { echo "bad label token" >&2; exit 1; }
  [[ "$MOCK_LABEL_WRITE_ERROR" != true ]] || { echo "gh: label write failed" >&2; exit 1; }
  echo true > "$MOCK_LABEL_PRESENT_FILE"
  jq '(map(.id) | max + 1) as $id | . + [{id:$id,event:"labeled",actor:{login:"github-actions[bot]"},created_at:"2026-01-03T00:00:00Z",label:{name:"breaking-change-approved"}}]' "$MOCK_TIMELINE_FILE" > "$MOCK_TIMELINE_FILE.tmp"
  mv "$MOCK_TIMELINE_FILE.tmp" "$MOCK_TIMELINE_FILE"
  exit 0
fi
if [[ "$path" == */labels/breaking-change-approved && "$method" == DELETE ]]; then
  [[ "$LABEL_TOKEN" == "$GH_TOKEN" ]] || { echo "bad label token" >&2; exit 1; }
  echo false > "$MOCK_LABEL_PRESENT_FILE"
  exit 0
fi
if [[ "$path" == orgs/*/memberships/* ]]; then
  [[ "$GH_TOKEN" == test-token ]] || { echo "bad membership token" >&2; exit 1; }
  if [[ "$MOCK_API_ERROR" == true ]]; then
    echo 'gh: Not Found (HTTP 404)' >&2
    exit 1
  fi
  echo "$MOCK_MEMBERSHIP"
  exit 0
fi
echo "unexpected endpoint: $method $path" >&2
exit 1
""",
        encoding="utf-8",
    )
    gh.chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "GH_TOKEN": "test-token",
        "LABEL_TOKEN": "label-token",
        "EVENT_ACTOR": "contributor",
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
        "MOCK_TIMELINE_FILE": str(timeline_path),
        "MOCK_LABEL_PRESENT_FILE": str(label_path),
        "MOCK_MARKERS_FILE": str(markers_path),
        "MOCK_API_ERROR": str(scenario.api_error).lower(),
        "MOCK_MEMBERSHIP": scenario.membership,
        "MOCK_LABEL_WRITE_ERROR": str(scenario.label_write_error).lower(),
    }
    return subprocess.run(
        ["/bin/bash", "-c", _workflow_script()],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_active_team_member_is_authorized_and_marker_is_written(
    tmp_path: Path,
) -> None:
    """An authorized label addition gets a bot marker for its event ID.

    Args:
        tmp_path: The temporary directory used by the scenario.
    """
    result = _run_workflow_script(tmp_path)

    assert result.returncode == 0
    assert "contributor is an active member" in result.stdout
    assert json.loads((tmp_path / "markers.json").read_text()) == [100]


def test_pending_member_is_rejected_and_label_is_removed(tmp_path: Path) -> None:
    """A non-member's label addition is removed and leaves the check failed.

    Args:
        tmp_path: The temporary directory used by the scenario.
    """
    result = _run_workflow_script(
        tmp_path,
        scenario=WorkflowScenario(membership="pending"),
    )

    assert result.returncode != 0
    assert "approval label could not be authorized" in result.stdout
    assert (tmp_path / "label-present").read_text().strip() == "false"


def test_membership_api_error_fails_closed_and_is_visible(tmp_path: Path) -> None:
    """Membership API errors are retained and the label is removed.

    Args:
        tmp_path: The temporary directory used by the scenario.
    """
    result = _run_workflow_script(
        tmp_path,
        scenario=WorkflowScenario(api_error=True),
    )

    assert result.returncode != 0
    assert "gh: Not Found (HTTP 404)" in result.stderr
    assert (tmp_path / "label-present").read_text().strip() == "false"


def test_lifecycle_event_accepts_present_label_with_valid_marker(
    tmp_path: Path,
) -> None:
    """A previously authorized label remains valid on a new commit.

    Args:
        tmp_path: The temporary directory used by the scenario.
    """
    result = _run_workflow_script(
        tmp_path,
        scenario=WorkflowScenario(
            event=GitHubEvent(action="synchronize", label=""),
            marker_ids=(100,),
        ),
    )

    assert result.returncode == 0
    assert "valid marker" in result.stdout
    assert "memberships" not in (tmp_path / "gh_calls").read_text()


def test_lifecycle_event_rejects_unmarked_unauthorized_label(
    tmp_path: Path,
) -> None:
    """A later success cannot mask a failed unauthorized cleanup.

    Args:
        tmp_path: The temporary directory used by the scenario.
    """
    result = _run_workflow_script(
        tmp_path,
        scenario=WorkflowScenario(
            event=GitHubEvent(action="synchronize", label=""),
            membership="pending",
        ),
    )

    assert result.returncode != 0
    assert "approval label could not be authorized" in result.stdout
    assert (tmp_path / "label-present").read_text().strip() == "false"


def test_unrelated_label_event_still_revalidates_present_approval(
    tmp_path: Path,
) -> None:
    """An unrelated-label event cannot skip current approval verification.

    Args:
        tmp_path: The temporary directory used by the scenario.
    """
    result = _run_workflow_script(
        tmp_path,
        scenario=WorkflowScenario(
            event=GitHubEvent(action="labeled", label="bug"),
            membership="pending",
        ),
    )

    assert result.returncode != 0
    assert (tmp_path / "label-present").read_text().strip() == "false"


def test_unrelated_event_with_no_approval_label_passes(tmp_path: Path) -> None:
    """Unrelated events pass when the protected approval label is absent.

    Args:
        tmp_path: The temporary directory used by the scenario.
    """
    result = _run_workflow_script(
        tmp_path,
        scenario=WorkflowScenario(
            event=GitHubEvent(action="labeled", label="bug"),
            label_present=False,
        ),
    )

    assert result.returncode == 0
    assert "approval label is absent" in result.stdout


def test_unmarked_label_by_active_member_gets_marker_on_lifecycle_event(
    tmp_path: Path,
) -> None:
    """A missed label-event run is recovered from trusted event history.

    Args:
        tmp_path: The temporary directory used by the scenario.
    """
    result = _run_workflow_script(
        tmp_path,
        scenario=WorkflowScenario(
            event=GitHubEvent(action="reopened", label=""),
            membership="active",
        ),
    )

    assert result.returncode == 0
    assert "current approval label is authorized" in result.stdout
    assert json.loads((tmp_path / "markers.json").read_text()) == [100]


def test_unauthorized_removal_restores_only_previously_marked_approval(
    tmp_path: Path,
) -> None:
    """An unauthorized removal preserves an approval with a valid marker.

    Args:
        tmp_path: The temporary directory used by the scenario.
    """
    result = _run_workflow_script(
        tmp_path,
        scenario=WorkflowScenario(
            event=GitHubEvent(action="unlabeled"),
            membership="pending",
            label_present=False,
            marker_ids=(100,),
        ),
    )

    assert result.returncode == 0
    assert "Restored the previously authorized approval" in result.stdout
    assert (tmp_path / "label-present").read_text().strip() == "true"
    assert json.loads((tmp_path / "markers.json").read_text()) == [100, 102]


def test_marked_approval_removal_fails_if_restoration_fails(
    tmp_path: Path,
) -> None:
    """A failed restoration cannot make an unauthorized removal pass.

    Args:
        tmp_path: The temporary directory used by the scenario.
    """
    result = _run_workflow_script(
        tmp_path,
        scenario=WorkflowScenario(
            event=GitHubEvent(action="unlabeled"),
            membership="pending",
            label_write_error=True,
            label_present=False,
            marker_ids=(100,),
        ),
    )

    assert result.returncode != 0
    assert "Could not safely restore and mark" in result.stdout
    assert (tmp_path / "label-present").read_text().strip() == "false"


def test_unmarked_approval_is_not_restored_after_removal(tmp_path: Path) -> None:
    """A removal cannot turn an unverified label into an authorized approval.

    Args:
        tmp_path: The temporary directory used by the scenario.
    """
    result = _run_workflow_script(
        tmp_path,
        scenario=WorkflowScenario(
            event=GitHubEvent(action="unlabeled"),
            membership="pending",
            label_present=False,
        ),
    )

    assert result.returncode != 0
    assert "without a valid authorization marker" in result.stdout
    assert (tmp_path / "label-present").read_text().strip() == "false"


def test_wrong_event_type_fails_instead_of_skipping(tmp_path: Path) -> None:
    """The reusable workflow rejects pull_request events explicitly.

    Args:
        tmp_path: The temporary directory used by the scenario.
    """
    result = _run_workflow_script(
        tmp_path,
        scenario=WorkflowScenario(event=GitHubEvent(name="pull_request")),
    )

    assert result.returncode != 0
    assert "must be called from a pull_request_target workflow" in result.stdout


def test_unsupported_event_action_fails_instead_of_skipping(
    tmp_path: Path,
) -> None:
    """Unsupported actions fail before querying GitHub.

    Args:
        tmp_path: The temporary directory used by the scenario.
    """
    result = _run_workflow_script(
        tmp_path,
        scenario=WorkflowScenario(event=GitHubEvent(action="closed")),
    )

    assert result.returncode != 0
    assert "must be triggered by opened, synchronize, reopened" in result.stdout


def test_reusable_workflow_uses_fixed_team_and_label_and_bot_markers() -> None:
    """The policy stays fixed and marker logic is documented."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    readme = (WORKFLOW.parent / "README-approval-label-authorization.md").read_text(
        encoding="utf-8"
    )

    assert "approval-label:" not in workflow
    assert "team-slug:" not in workflow
    assert "TEAM_SLUG: ansible-staff-eng-leads" in workflow
    assert "LABEL_NAME: breaking-change-approved" in workflow
    assert "github-actions[bot]" in workflow
    assert "synchronize" in readme
    assert "valid marker" in readme
