# oasdiff breaking-change gate

Reusable GitHub Actions workflow that runs
[oasdiff](https://github.com/oasdiff/oasdiff) on OpenAPI spec changes in a
pull request and gates on the `breaking-change-approved` label.

Implements the CI enforcement described in
[AAP-53276 §5](https://github.com/ansible/handbook/pull/1636) (API Change
Approval Process).

## Behavior

| Scenario | Result |
|---|---|
| No breaking changes detected | Pass |
| Breaking change detected + `breaking-change-approved` label present | Pass |
| Breaking change detected + label missing | **Fail** (blocks the PR) |
| Spec file is new (doesn't exist on the target branch) | Skip |

The workflow always compares the spec on the PR head against the spec on the
**target branch** (`github.event.pull_request.base.sha`), so it works
identically whether the PR targets `devel`, `stable-*`, `main`, or any other
branch.

## Inputs

<!-- markdownlint-disable MD013 -->

| Input | Required | Default | Description |
|---|---|---|---|
| `spec` | Yes | — | Path to the OpenAPI spec file relative to the repo root. Supports glob patterns (e.g. `api/openapi*.yaml`). |
| `oasdiff-version` | No | `latest` | oasdiff version to install. |
| `approval-label` | No | `breaking-change-approved` | GitHub label that signals an approved breaking change. |

<!-- markdownlint-enable MD013 -->

## Permissions

The workflow requires these minimum permissions from the caller:

```yaml
permissions:
  contents: read
  pull-requests: read
```

## Usage

### Basic — single spec file

```yaml
# .github/workflows/api-check.yml
name: API breaking-change check
on:
  pull_request:
    paths:
      - "api/openapi.yaml"
jobs:
  breaking-change-gate:
    uses: ansible/actions/.github/workflows/oasdiff-breaking.yml@main
    with:
      spec: api/openapi.yaml
```

### Multiple spec files via glob

```yaml
jobs:
  breaking-change-gate:
    uses: ansible/actions/.github/workflows/oasdiff-breaking.yml@main
    with:
      spec: "api/**/*.yaml"
```

### Pinned oasdiff version

```yaml
jobs:
  breaking-change-gate:
    uses: ansible/actions/.github/workflows/oasdiff-breaking.yml@main
    with:
      spec: openapi/spec.yaml
      oasdiff-version: "2.6.1"
```

## How it works

1. Checks out the PR with full git history (`fetch-depth: 0`).
2. Installs oasdiff.
3. For each file matching the `spec` glob:
   - Extracts the base-branch version of the spec via `git show`.
   - Runs `oasdiff breaking` with `--fail-on ERR`.
4. If any breaking change is found, checks the PR labels for
   `breaking-change-approved` via the GitHub API.
5. Writes a summary (with oasdiff output) to the GitHub Actions Job Summary.

## Who can apply the label?

Per the API Change Approval Process, only a member of the
[ansible-staff-eng-leads](https://github.com/orgs/ansible/teams/ansible-staff-eng-leads/members)
GitHub team may apply the `breaking-change-approved` label, and only after
Sr. Director-level sign-off from both Engineering and Business Unit leadership.

## See also

- [API Change Approval Process (AAP-53276)](https://github.com/ansible/handbook/pull/1636)
- [oasdiff documentation](https://github.com/oasdiff/oasdiff)
- [ANSTRAT-2346: API Contract Stability and Lifecycle Management](https://handbook.eng.ansible.com/System-Design-Plans/ANSTRAT-2346-API-Contract-Stability-and-Lifecycle-Management/)
