# 0001 — Pipeline, agents, and the decision council

- Date: 2026-10-25 (consolidates the former 0001, 0002, and 0005, and records the council)
- Status: accepted

## Decisions
1. **Per-agent model and effort.** Every agent sets `model` and `effort`
   (`low`/`medium`/`high`/`xhigh`/`max`) in its frontmatter. Both fields are
   supported on agents and skills; no workaround is needed.
2. **The pipeline is ordered steps, not hooks.** `/release` runs five steps
   written in its command file: full tests, bug-hunter, severity routing,
   documenter, commit-and-pr. `settings.json` has no `hooks` key and the
   validator enforces that. "Gate" here means the documented order, which the
   agent follows; the harness does not enforce it, but the validator checks
   that `release.md` numbers these steps in this order. If stronger enforcement is
   ever needed, add a hook deliberately and revisit this. The real backstops are the
   validator, the CI PR review, and your own review of the PR. `/pr` skips the
   gate on purpose, for changes you have already verified.
3. **One `bug-hunter` for local and CI review.** `claude-code-action` looks
   for no particular agent name (it is all explicit in the workflow's YAML),
   and the fully automatic "Code Review" product is Team/Enterprise only, so a
   custom workflow is the only route on Pro. Two agents would drift apart.
   That GitHub expects no name was verified, not assumed; revisit if a
   naming requirement ever appears.
4. **A decision council.** `/council` puts a design choice to advisors with
   distinct lenses, then a chair issues one verdict that settles the choice.
   - **Quick (default, 3 calls):** contrarian (risk), outsider (cold read),
     chair. **Full (6 calls):** adds first principles, visionary (opportunity),
     executor (next action). Rules for when to use which are in the
     `council-policy` skill.
   - Contrarian, first principles, and chair run on Sonnet at medium; the
     others on Haiku at low. Advisors answer in 150 words, the chair in 200.
   - The outsider gets only the question, options, and artifact, never the
     conversation. It keeps `Read` because the docs define no tool-less agent
     and an empty `tools:` is undocumented; its prompt forbids reading.
   - A subagent cannot spawn subagents, so the command orchestrates, not an
     agent. `/plan` convenes it only for costly-to-reverse choices.
   - The verdict never replaces your approval of a plan or any confirmation
     the global rules require. `subagent_spawn_warning` is 7 so a full council
     does not trip it.

## Validation (2026-10-25)
The council reviewed the earlier decisions on hooks, the settings merge, CI
review, and model assignment. All four were kept; the changes it asked for are
recorded below and in 0002 and 0003; the release-order check and the CI and
settings changes from them are done. The first review ran through
`general-purpose` with each advisor's file as its brief, because new agents
register only after a session restart. Advisor claims were checked against the
files by the chair; one (that a malformed `settings.json` gets overwritten)
was wrong.

## Follow-ups (not yet done)
- After a restart, test whether an empty `tools:` gives the outsider no tools.
