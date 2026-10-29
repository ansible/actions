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
    with:
      app-client-id: ${{ vars.ANSIBLE_AAP_API_CHANGE_APPROVAL_BOT_APP_CLIENT_ID }}
    secrets:
      app-private-key: ${{ secrets.ANSIBLE_AAP_API_CHANGE_APPROVAL_BOT_APP_PRIVATE_KEY }}
```

The reusable workflow does not check out or run pull request code. Keep the
caller on `pull_request_target` so `github.event.sender.login` identifies the
person who changed the label.

## Token and branch protection

The GitHub App must be installed in each calling organization with the
organization-level **Members: read-only** permission. In each organization,
configure these Actions values and grant access only to repositories using the
caller workflow:

- Variable `ANSIBLE_AAP_API_CHANGE_APPROVAL_BOT_APP_CLIENT_ID`: the App client
  ID. This is not a secret.
- Secret `ANSIBLE_AAP_API_CHANGE_APPROVAL_BOT_APP_PRIVATE_KEY`: the App's
  private key.

The values are organization-specific settings, even when the same App is used
across multiple organizations. The caller passes the variable and secret to
the reusable workflow. It mints an installation token for the calling
repository's organization, scoped to **Members: read-only**, and uses that
short-lived token only for the team-membership lookup. The App must be
installed in the organization, and the team must be visible to the App.

The caller also needs `pull-requests: write` permission. The workflow uses its
`GITHUB_TOKEN` to remove an unauthorized label; the GitHub App installation
token is used only to check team membership.

Both the App client ID and private key must be configured. If either value is
missing, the App is not installed in the calling organization, or the
installation does not have Members read permission, token creation or the
membership lookup fails and the authorization check fails closed. The
verification step still runs if token creation fails so it can attempt to
remove a newly added label using the caller's `GITHUB_TOKEN`.

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
