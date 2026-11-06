# Approval label authorization

`approval-label-authorization.yml` is a reusable workflow that verifies the
person who applied or removed `breaking-change-approved` belongs to the
`ansible-staff-eng-leads` GitHub team in the `ansible` organization. This is the
one centrally authorized team and label; callers cannot override either value.
For label events, it checks the actor from the `pull_request_target` event. If
an actor is not an active member, or membership cannot be verified, the
workflow reverses the label change. It removes an unauthorized addition and
fails the check because the approval label is absent. It restores an
unauthorized removal; if restoration succeeds, it verifies that the label is
present and passes only if the approval state is intact. The check fails if
the workflow cannot restore and verify the label.

## Caller workflow

Add a workflow to each repository that uses the label:

Replace `<FULL_COMMIT_SHA>` below with the full 40-character commit SHA in
`ansible/actions` that contains this reusable workflow. Pinning the SHA keeps
the security check from changing silently when the default branch moves.

```yaml
name: approval-label-authorization

on:
  pull_request_target:
    types: [opened, synchronize, reopened, labeled, unlabeled]

permissions:
  contents: read
  issues: read
  pull-requests: write

jobs:
  approval-label-authorization:
    uses: ansible/actions/.github/workflows/approval-label-authorization.yml@<FULL_COMMIT_SHA>
    with:
      app-client-id: >-
        ${{ vars.ANSIBLE_ORG_MEMBERS_READ_ONLY_APP_CLIENT_ID }}
    secrets:
      app-private-key: >-
        ${{ secrets.ANSIBLE_ORG_MEMBERS_READ_ONLY_APP_PRIVATE_KEY }}
```

The reusable workflow does not check out or run pull request code. Keep the
caller on `pull_request_target` so `github.event.sender.login` identifies the
person who changed the label. It validates the event inside the job, so do not
add a job-level condition that could skip the required check. The `opened`,
`synchronize`, and `reopened` events produce a successful check without a
membership lookup because they do not change the label. Events for other
labels are ignored; only `breaking-change-approved` is supported.

## Required Actions event policy

This caller uses `pull_request_target` because the check needs the GitHub App
secret to read team membership and a write-capable `GITHUB_TOKEN` to remove an
unauthorized label. For public repositories, GitHub's default Actions event
policy blocks `pull_request_target` unless an applicable event policy allows
it. GitHub plans to enforce this default on December 2, 2026. Before relying
on this check, an organization or enterprise owner, or a repository admin who
controls Actions policies, must allow `pull_request_target` for the affected
repositories and caller workflow. If policy blocks the event, this workflow
cannot enforce label authorization. See GitHub's documentation on
[`pull_request_target` policy](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target#default-policy-for-pull_request_target)
and [workflow execution policies](https://docs.github.com/en/actions/how-tos/administer/control-workflow-execution).

Switching this caller to `pull_request` is not a drop-in replacement. For pull
requests from forks, GitHub withholds repository and organization secrets and
makes `GITHUB_TOKEN` read-only. This workflow needs the App key to check team
membership and a write token to undo an unauthorized label change. If an
organization cannot allow `pull_request_target`, an alternative would need to
move this work to a trusted service, such as a GitHub App that handles label
events and reports a required check.

## Token and branch protection

Install the private `org-members-read-only` GitHub App in the `ansible`
organization only, with the organization-level **Members: read-only**
permission. Repositories in all four organizations can call this reusable
workflow; it always mints a token for the `ansible` installation and checks
membership in `ansible/ansible-staff-eng-leads`. The App does not need to be
installed in the other calling organizations or have repository permissions.

Configure the same App client ID and private key in each calling organization
(`ansible`, `ansible-automation-platform`, `syntara-orchestration`, and
`automation-nexus`) as organization-level Actions values. Grant access only to
the repositories using the caller workflow:

- Variable `ANSIBLE_ORG_MEMBERS_READ_ONLY_APP_CLIENT_ID`: the App client
  ID. This is not a secret.
- Secret `ANSIBLE_ORG_MEMBERS_READ_ONLY_APP_PRIVATE_KEY`: the App's
  private key.

The variable and secret must be configured separately in each organization;
the private key value is the same for the App in every caller organization.
The reusable workflow creates a short-lived installation token for the App's
`ansible` installation, scoped to **Members: read-only**, and uses it only for
the membership lookup in `ansible`.

The caller also needs `pull-requests: write` permission. The workflow uses its
`GITHUB_TOKEN` to reverse an unauthorized label change; the GitHub App
installation token is used only to check team membership.

Both the App client ID and private key must be configured for each caller. If
either value is missing, the App is not installed in `ansible`, or its
installation does not have Members read permission, token creation or the
membership lookup fails. The verification step still runs if token creation
fails so it can attempt to reverse a label change using the caller's
`GITHUB_TOKEN`.

Require the `approval-label-authorization` check in the repository's target
branch rules. It runs on pull request open, synchronize, reopen, and label
changes so the required check reports a result throughout the PR lifecycle. If
membership cannot be verified, the workflow reverses the label change; the
check fails if an addition is removed or a removal cannot be restored. The
Actions log retains the API error for troubleshooting. The normal
breaking-change workflow should separately fail when the approval label is
absent.

## Approval scope and new commits

This workflow checks **who** added or removed the label. It does not inspect the
pull request's code, bind the approval to a commit, or remove the label when new
commits are pushed. The authorization check reports a successful no-op on
`opened`, `synchronize`, and `reopened`; those events do not invalidate an
existing approval. Therefore, a new commit by itself does not require
re-approval: the label remains until someone removes it, and a check that only
tests whether the label exists will still see it.

There is currently no automated rule here for deciding whether a new commit
changes the approved breaking-change scope. The consuming repository's
breaking-change check or approval process must define and enforce that policy.
For example, a policy could require re-approval after every new commit, or only
when a change alters the breaking-change scope. The first can be enforced by
invalidating the label on each `synchronize` event; the second needs to compare
the current pull request with the revision that was approved. Until a consumer
implements one of those rules, this workflow only verifies that label changes
come from an active member of the approval team; it does not make an existing
approval expire.
