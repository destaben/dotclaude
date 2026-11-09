# handoff_sections.awk: the one reader for handoff sections. worker_run.sh (the owner's review and the
# consent gate, and the reading of a worker's escalation and checkpoint) and worker_entrypoint.sh (the prompt
# the worker is given, and the commit title) both call it, so they see the same text.
#
# A heading is a line that starts with "##" followed by a space, a tab, or the end of the line ("###" is not a
# heading). The comparison ignores trailing spaces, tabs and carriage returns.
#
#   awk -v mode=instructions -f handoff_sections.awk FILE   the Task, Context and Acceptance sections
#   awk -v mode=section -v want=Name -f handoff_sections.awk FILE   the body of one section (heading excluded)
#   awk -v mode=check -f handoff_sections.awk FILE   the heading lines that are not canonical, with line
#       numbers. Canonical means exactly one of the names below, with nothing else on the line. Used on handoffs
#       the owner supplies: a non-canonical heading is refused, not guessed at.

function norm(s) {
  sub(/[ \t\r]+$/, "", s)
  return s
}

function is_heading(s) {
  return (s ~ /^##([ \t]|$)/)
}

BEGIN {
  canonical["## Task"] = 1
  canonical["## Context"] = 1
  canonical["## Acceptance"] = 1
  canonical["## Untrusted input"] = 1
  canonical["## Checkpoint"] = 1
  canonical["## Escalation"] = 1
  keep = 0
}

mode == "check" {
  if (is_heading($0) && !($0 in canonical)) {
    printf "%d:%s\n", NR, "non-canonical heading"
  }
  next
}

{
  line = norm($0)
  if (is_heading(line)) {
    if (mode == "instructions") {
      keep = (line == "## Task" || line == "## Context" || line == "## Acceptance")
    } else {
      keep = (line == "## " want)
    }
    next
  }
  if (keep) print
}
