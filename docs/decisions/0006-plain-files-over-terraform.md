# 0006 — PR/issue templates and the review workflow are plain files, not Terraform

- Date: 2026-10-17
- Status: accepted

## Context
The user has Terraform experience and is open to it, but also explicitly
asked for whatever requires less configuration when another option fits as
well. This change added a PR template, two issue form templates, and a
GitHub Actions workflow for PR review.

## Decision
All three are plain files under `.github/` (`pull_request_template.md`,
`ISSUE_TEMPLATE/*.yml`, `workflows/claude-pr-review.yml`), committed directly
to the repo — no Terraform, no GitHub provider, no state file. GitHub reads
these by convention straight from the repo; there is nothing to provision.

## Why not Terraform here
Terraform earns its cost when there's actual *infrastructure* to provision
and track — branch protection rules, repo visibility/settings, webhooks,
team/collaborator access, secrets management across many repos. None of that
was asked for in this change. Reaching for Terraform to manage content that
GitHub already treats as "just files in the repo" would add a provider,
credentials, and a state file to maintain for zero functional gain over
committing the files directly.

## When to revisit
If this repo later needs to manage branch protection, required status
checks, or repo-level settings as code — or the same templates/workflow need
to be rolled out identically across many repos — Terraform's GitHub provider
(or a lighter `gh` CLI script, which needs no state file) becomes worth
comparing. Not needed for this change.
