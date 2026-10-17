#!/usr/bin/env python3
"""Estimate USD cost for a Claude Code session transcript.

Reads a session's JSONL transcript, sums token usage per model (deduplicated
by message id, since streamed assistant turns repeat the same usage block
across multiple JSONL lines), applies config/pricing.json, and prints a
Markdown table.

Figures are an ESTIMATE at API list prices. A Claude Pro/Max subscription is
billed as a flat fee, not per token, so this does not reflect an actual charge.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PRICING_PATH = REPO_ROOT / "config" / "pricing.json"


def default_transcript_dir(cwd: str | None = None) -> Path:
    cwd = cwd or os.getcwd()
    slug = cwd.replace("/", "-")
    return Path.home() / ".claude" / "projects" / slug


def find_latest_transcript(cwd: str | None = None) -> Path | None:
    project_dir = default_transcript_dir(cwd)
    if not project_dir.is_dir():
        return None
    candidates = [p for p in project_dir.glob("*.jsonl") if p.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def parse_usage_by_model(transcript_path: Path) -> dict:
    """Sum token usage per model, deduplicating repeated usage blocks by message id."""
    seen_message_ids = set()
    usage_by_model: dict[str, dict[str, int]] = {}

    with open(transcript_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") != "assistant":
                continue
            message = obj.get("message") or {}
            usage = message.get("usage")
            model = message.get("model")
            message_id = message.get("id")
            if not usage or not model or not message_id:
                continue
            if message_id in seen_message_ids:
                continue
            seen_message_ids.add(message_id)

            totals = usage_by_model.setdefault(
                model,
                {
                    "input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                    "output_tokens": 0,
                },
            )
            for key in totals:
                totals[key] += int(usage.get(key, 0) or 0)

    return usage_by_model


def load_pricing(pricing_path: Path) -> dict:
    with open(pricing_path, encoding="utf-8") as f:
        return json.load(f)


def pricing_staleness_days(pricing: dict, today: date | None = None) -> int | None:
    """Days since pricing was fetched, or None if pricing has no _fetched_at."""
    fetched_at = pricing.get("_fetched_at")
    if not fetched_at:
        return None
    try:
        fetched_date = date.fromisoformat(fetched_at)
    except ValueError:
        return None
    return ((today or date.today()) - fetched_date).days


def pricing_staleness_warning(pricing: dict, today: date | None = None) -> str | None:
    """A one-line warning if pricing is older than its own _max_age_days, else None."""
    age_days = pricing_staleness_days(pricing, today)
    max_age_days = pricing.get("_max_age_days")
    if age_days is None or not isinstance(max_age_days, (int, float)):
        return None
    if age_days <= max_age_days:
        return None
    return (
        f"Pricing data is {age_days} days old (fetched {pricing.get('_fetched_at')}, "
        f"max age {int(max_age_days)} days) — refresh config/pricing.json before trusting these figures."
    )


def estimate_cost(model: str, totals: dict, pricing: dict) -> float | None:
    model_pricing = pricing.get("models", {}).get(model)
    if not model_pricing:
        return None
    input_price = model_pricing.get("input_per_mtok")
    output_price = model_pricing.get("output_per_mtok")
    if not isinstance(input_price, (int, float)) or not isinstance(output_price, (int, float)):
        return None

    billable_input = (
        totals["input_tokens"]
        + totals["cache_creation_input_tokens"]
        + totals["cache_read_input_tokens"]
    )
    cost = (billable_input / 1_000_000) * input_price
    cost += (totals["output_tokens"] / 1_000_000) * output_price
    return cost


def format_markdown_table(usage_by_model: dict, pricing: dict) -> str:
    lines = [
        "| Model | Input tokens | Cache read | Cache create | Output tokens | Est. cost (USD) |",
        "|---|---|---|---|---|---|",
    ]
    total_cost = 0.0
    any_unknown = False
    for model in sorted(usage_by_model):
        totals = usage_by_model[model]
        cost = estimate_cost(model, totals, pricing)
        if cost is None:
            cost_str = "TODO (pricing not set)"
            any_unknown = True
        else:
            cost_str = f"${cost:,.4f}"
            total_cost += cost
        lines.append(
            f"| {model} | {totals['input_tokens']:,} | {totals['cache_read_input_tokens']:,} | "
            f"{totals['cache_creation_input_tokens']:,} | {totals['output_tokens']:,} | {cost_str} |"
        )
    total_str = f"${total_cost:,.4f}" + (" (incomplete, see TODO rows)" if any_unknown else "")
    lines.append(f"\n**Estimated total: {total_str}**")
    lines.append(
        "\n_Estimate at API list prices. Claude Pro/Max is billed as a flat subscription, "
        "not per token, so this does not reflect what was actually charged._"
    )
    staleness_warning = pricing_staleness_warning(pricing)
    if staleness_warning:
        lines.append(f"\n**Warning:** {staleness_warning}")
    return "\n".join(lines)


def format_oneline(usage_by_model: dict, pricing: dict) -> str:
    total_cost = 0.0
    any_unknown = False
    for model, totals in usage_by_model.items():
        cost = estimate_cost(model, totals, pricing)
        if cost is None:
            any_unknown = True
        else:
            total_cost += cost
    suffix = "+" if any_unknown else ""
    stale_marker = " [stale pricing]" if pricing_staleness_warning(pricing) else ""
    return f"session est. ${total_cost:,.4f}{suffix} ({len(usage_by_model)} model(s)){stale_marker}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcript", type=Path, default=None, help="Path to a session JSONL transcript")
    parser.add_argument("--pricing", type=Path, default=DEFAULT_PRICING_PATH, help="Path to pricing.json")
    parser.add_argument("--oneline", action="store_true", help="Print a single-line summary for use in a statusLine")
    args = parser.parse_args(argv)

    transcript_path = args.transcript or find_latest_transcript()
    if transcript_path is None or not transcript_path.is_file():
        print("No session transcript found. Pass --transcript explicitly.", file=sys.stderr)
        return 1

    usage_by_model = parse_usage_by_model(transcript_path)
    pricing = load_pricing(args.pricing)
    if args.oneline:
        print(format_oneline(usage_by_model, pricing))
    else:
        print(format_markdown_table(usage_by_model, pricing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
