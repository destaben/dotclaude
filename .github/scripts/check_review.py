#!/usr/bin/env python3
"""Pick the review out of a claude-code-action execution file and validate it.

Usage: check_review.py EXECUTION_FILE PR_NUMBER OUTPUT_FILE

Exit 0 and write the review to OUTPUT_FILE only when the agent's last
successful `result` message is a finished review:

* its first non-blank line is `## Review of PR #<n>` (optionally followed by
  more text on that line, e.g. a commit sha), and
* its last non-blank line is
  `Result: <total> findings (<severe> severe, <non-severe> non-severe)` with
  total == severe + non-severe (markdown bold/backticks and a trailing period
  are tolerated), and
* it mentions both agents (`bug-hunter` and `documenter`), so a review written
  before the documenter reported is not accepted. This is a heuristic, not
  proof that both ran: the prompt asks for one section per agent.

Anything else (a progress message, an empty result, a missing file) exits 1
and writes nothing, so the caller can retry or fail the job instead of posting
an unfinished review as if it were one. Exit 2 means misuse, not a bad review.
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
        data = json.loads(execution_file.read_text())
    except (OSError, ValueError):
        return None
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return None
    results = [
        m.get("result")
        for m in data
        if isinstance(m, dict)
        and m.get("type") == "result"
        and m.get("subtype") == "success"
        and not m.get("is_error")
    ]
    return results[-1] if results and isinstance(results[-1], str) else None


def validate(text, pr_number):
    """Return None if `text` is a finished review, else the reason it is not."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return "empty result"
    heading = f"## Review of PR #{pr_number}"
    lowered = "\n".join(lines).lower()
    if "bug-hunter" not in lowered or "documenter" not in lowered:
        return "review does not cover both bug-hunter and documenter"
    first = lines[0]
    if first != heading and not first.startswith(heading + " "):
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
        return 1
    output_file.write_text(text.strip() + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
