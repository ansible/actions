"""Tests for the approval label authorization workflow's membership check."""

import os
import subprocess
from pathlib import Path

WORKFLOW = (
    Path(__file__).parents[1]
    / ".github"
    / "workflows"
    / "approval-label-authorization.yml"
)


def _workflow_script() -> str:
    """Return the workflow's inline shell script so tests exercise the real code."""
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
    tmp_path: Path, *, api_error: bool
) -> subprocess.CompletedProcess[str]:
    """Run the inline check with a fake gh command and controlled API result."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/usr/bin/env bash\n"
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
        "ACTOR": "contributor",
        "TEAM_ORG": "ansible",
        "TEAM_SLUG": "ansible-staff-eng-leads",
        "LABEL_NAME": "breaking-change-approved",
        "LABEL_ACTION": "labeled",
        "MOCK_API_ERROR": str(api_error).lower(),
        "MOCK_MEMBERSHIP": "active",
    }
    return subprocess.run(
        ["/bin/bash", "-c", _workflow_script()],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_non_member_is_rejected_and_api_error_is_visible(tmp_path: Path) -> None:
    """A non-member API response fails authorization and retains gh diagnostics."""
    result = _run_workflow_script(tmp_path, api_error=True)

    assert result.returncode != 0
    assert "gh: Not Found (HTTP 404)" in result.stderr
    assert "Could not verify whether contributor belongs to" in result.stdout


def test_active_team_member_is_authorized(tmp_path: Path) -> None:
    """An active team member can change the approval label."""
    result = _run_workflow_script(tmp_path, api_error=False)

    assert result.returncode == 0
    assert "contributor is an active member" in result.stdout
