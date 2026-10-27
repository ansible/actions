# Approval label authorization

`approval-label-authorization.yml` is a reusable workflow that verifies the
person who applied or removed `breaking-change-approved` belongs to the
`ansible-staff-eng-leads` GitHub team in the organization that calls the
reusable workflow. It checks the actor from the
`pull_request_target` label event. If an actor is not an active member, or
membership cannot be verified, the workflow removes the label when the event
added it and fails the check.

## Caller workflow

Add a workflow to each repository that uses the label:

Replace `<FULL_COMMIT_SHA>` below with the full 40-character commit SHA in
`ansible/actions` that contains this reusable workflow. Pinning the SHA keeps
the security check from changing silently when the default branch moves.

```yaml
name: approval-label-authorization

on:
  pull_request_target:
    types: [labeled, unlabeled]

permissions:
  contents: read
  issues: read
  pull-requests: write

jobs:
  approval-label-authorization:
    if: github.event.label.name == 'breaking-change-approved'
    uses: ansible/actions/.github/workflows/approval-label-authorization.yml@<FULL_COMMIT_SHA>
    secrets:
      team-membership-token: ${{ secrets.TEAM_MEMBERSHIP_TOKEN }}
```

The reusable workflow does not check out or run pull request code. Keep the
caller on `pull_request_target` so `github.event.sender.login` identifies the
person who changed the label.

## Token and branch protection

`GITHUB_TOKEN` cannot read organization team membership. Configure the
`TEAM_MEMBERSHIP_TOKEN` repository or organization secret with a token granted
organization-member read access in the calling repository's organization. The
workflow derives the organization from the repository that calls it, so there
is no organization input to configure. The token must be able to read
membership for `ansible-staff-eng-leads` in that organization.

The caller also needs `pull-requests: write` permission. The workflow uses its
`GITHUB_TOKEN` to remove an unauthorized label; the separate membership token
is used only to check team membership.

The token is required. If the caller is a fork without this secret, the
authorization check fails because it cannot verify team membership.

Require the `approval-label-authorization` check in the repository's target
branch rules. This makes an unauthorized label change fail the merge gate. If
membership cannot be verified when the label is added, the workflow removes it
and fails the check; the Actions log retains the API error for troubleshooting.
The normal breaking-change workflow should separately fail when the approval
label is absent.

## Approval scope and new commits

This workflow checks **who** added or removed the label. It does not inspect the
pull request's code, bind the approval to a commit, or remove the label when new
commits are pushed. The label remains until someone removes it.

The breaking-change detection workflow is responsible for deciding **whether**
the approval label applies to the breaking changes in the current pull request.
If a new commit changes the scope of the approved breaking change, that workflow
or the approval process must require a fresh approval. The authorization check
here only verifies that label changes come from an active member of the approval
team.
