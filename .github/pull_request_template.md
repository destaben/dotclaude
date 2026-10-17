<!--
This file is the personal PR template used by the commit-and-pr skill in any
project (installed from the dotclaude config repo to ~/.claude/templates/),
and it also doubles as the native GitHub template for PRs opened against the
dotclaude repo itself — keep its content project-agnostic. If you're a human
filling this by hand, keep the same sections — automation and people use the
same shape.
-->

## Summary

<!-- One or two sentences: what changed and why. Not a diff restatement. -->

## Why

<!-- The motivation: a bug reproduced, a rule that needed to change, a gap that
     came up in use. Link a decision record if the project keeps one and this
     involved a judgment call. -->

## Test plan

<!-- Required by the testing-mindset skill.
     Two short bullet lists — not "tests pass." -->

**Tested:**
-

**Not tested:**
-

## Severity findings (only if this went through `/release`)

<!-- From the bug-hunter step, per release-policy. Leave this whole section
     out if the change skipped /release (e.g. via /pr). -->

- Severe findings: none / list + how fixed
- Non-severe findings: none / list + your decision

<!-- session-cost:start -->
<!-- session-cost:end -->
