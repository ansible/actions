# Reusable Github Actions and settings

This repository aims to host Github Actions and settings that can easily
be reused by other repositories.

Please note that at this moment this is in "pre-alpha" development status,
so if you want to be an early adopter or have an active involvement with its
development, contact Ansible DevTools team.

## Reusable Workflows

### Naming Convention

Reusable workflows follow `<category>-<action>-<target>.yml` (e.g.,
`oasdiff-detect-breaking-changes.yml`).

### oasdiff: Breaking Change Detection

Detects breaking API changes in PRs by comparing OpenAPI specs against
the target branch baseline using [oasdiff](https://github.com/Tufin/oasdiff).
Breaking changes are classified per the
[API Lifecycle Standards](https://github.com/ansible/handbook/pull/1628) taxonomy.

**Consumer setup — two workflow files in your repo:**

```yaml
# .github/workflows/breaking-change-check.yml
name: Breaking Change Detection
on:
  pull_request:
    paths:
      - "openapi/**"     # adjust to your spec file paths
      - "schema.json"
jobs:
  detect:
    uses: ansible/actions/.github/workflows/oasdiff-detect-breaking-changes.yml@<sha>
    with:
      spec-path: "schema.json"  # path to your OpenAPI spec
```

```yaml
# .github/workflows/breaking-change-comment.yml
name: Breaking Change PR Comment
on:
  workflow_run:
    workflows: ["Breaking Change Detection"]
    types: [completed]
jobs:
  comment:
    uses: ansible/actions/.github/workflows/oasdiff-post-breaking-change-comment.yml@<sha>
```

**Inputs (`oasdiff-detect-breaking-changes.yml`):**

| Input | Required | Default | Description |
|---|---|---|---|
| `spec-path` | Yes | — | Path to the OpenAPI spec file |
| `override-label` | No | `breaking-change-approved` | Override label |
| `oasdiff-version` | No | `1.18.5` | oasdiff CLI version |
| `fail-on-breaking` | No | `true` | Set `false` for dry-run mode |

**Override mechanism:** When a PR has the `breaking-change-approved` label
(applied by [`ansible-staff-eng-leads`](https://github.com/orgs/ansible/teams/ansible-staff-eng-leads)
team members after completing the
[API Change Approval Process](https://handbook.eng.ansible.com/proposals/AAP-53276-api-change-approval-process)),
breaking changes pass with a warning instead of blocking.

## Components
