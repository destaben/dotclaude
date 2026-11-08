#!/usr/bin/env python3
"""Pick the review out of a claude-code-action execution file and validate it.

Usage: check_review.py EXECUTION_FILE PR_NUMBER OUTPUT_FILE

Exit 0 and write the review to OUTPUT_FILE only when the run's final `result`
message succeeded and is a finished review (an errored final result is never
replaced by an earlier success):

* its first non-blank line is `## Review of PR #<n>` (optionally followed by
  a space or punctuation and more text, e.g. a commit sha), and
* its last non-blank line is
  `Result: <total> findings (<severe> severe, <non-severe> non-severe)` with
  total == severe + non-severe (markdown bold/backticks and a trailing period
  are tolerated), and
* it has a markdown heading for each agent (`bug-hunter` and `documenter`), so
  a review written before the documenter reported is not accepted. This is a
  heuristic, not proof that both ran: the prompt asks for one section per
  agent.

Anything else (a progress message, an empty result, a missing file) exits 3
and writes nothing, so the caller can retry or fail the job instead of posting
an unfinished review as if it were one. Exit 3 is reserved for "incomplete
review"; every other non-zero code (2 for misuse or an I/O error, 1 for an
uncaught crash or a syntax error) is a setup problem, so the workflow does not
retry on it.
"""
import json
import re
import sys
from pathlib import Path

RESULT_RE = re.compile(
    r"^Result: (\d+) findings? \((\d+) severe, (\d+) non-severe\)$"
)


def last_result(execution_file: Path):
    try:
        data = json.loads(execution_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return None
    # Only the run's final result counts: if it errored, an earlier success
    # must not be posted in its place.
    results = [m for m in data if isinstance(m, dict) and m.get("type") == "result"]
    if not results:
        return None
    final = results[-1]
    if final.get("subtype") != "success" or final.get("is_error"):
        return None
    text = final.get("result")
    return text if isinstance(text, str) else None


def unfence(text):
    """Drop a code fence wrapped around the whole message, if any."""
    lines = (text or "").strip().splitlines()
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1])
    return text or ""


def _norm(line):
    return line.lower().replace("bug hunter", "bug-hunter")


def _is_heading(line):
    return line.startswith("#") or (
        len(line) > 4 and line.startswith("**") and line.endswith("**")
    )


def validate(text, pr_number):
    """Return None if `text` is a finished review, else the reason it is not."""
    lines = [ln.strip() for ln in unfence(text).splitlines() if ln.strip()]
    if not lines:
        return "empty result"
    heading = f"## Review of PR #{pr_number}"
    # One markdown heading per agent, so a sentence that merely names an agent
    # ("still waiting for the documenter") does not count as its section.
    # A heading is a `#` line or a line that is only a bold label; "Bug Hunter"
    # spelled with a space counts as the bug-hunter.
    # Each agent needs its own heading: one line naming both does not count.
    used = set()
    for agent in ("bug-hunter", "documenter"):
        found = next(
            (
                i
                for i, ln in enumerate(lines[1:], 1)
                if i not in used and _is_heading(ln) and agent in _norm(ln)
            ),
            None,
        )
        if found is None:
            return f"review has no heading for {agent}"
        used.add(found)
    first = lines[0].replace("*", "").replace("`", "").strip()
    if not re.match(re.escape(heading) + r"(?![0-9A-Za-z])", first):
        return f"first line is not '{heading}'"
    last = lines[-1].replace("*", "").replace("`", "").rstrip(".").strip()
    match = RESULT_RE.match(last)
    if not match:
        return "last line is not 'Result: <n> findings (<n> severe, <n> non-severe)'"
    total, severe, non_severe = (int(g) for g in match.groups())
    if total != severe + non_severe:
        return "Result counts do not add up"
    return None


def main(argv):
    if len(argv) != 4:
        print(__doc__, file=sys.stderr)
        return 2
    execution_file, pr_number, output_file = argv[1], argv[2], Path(argv[3])
    text = last_result(Path(execution_file))
    reason = validate(text, pr_number)
    if reason:
        print(f"incomplete review, not posting: {reason}", file=sys.stderr)
        return 3
    output_file.write_text(unfence(text).strip() + "\n", encoding="utf-8")
    return 0


def run(argv):
    # Any uncaught error (unwritable output, ...) is a setup problem, not a bad
    # review: exit 2 so the workflow fails instead of spending a retry.
    try:
        return main(argv)
    except Exception as exc:  # noqa: BLE001
        print(f"check_review.py error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(run(sys.argv))
