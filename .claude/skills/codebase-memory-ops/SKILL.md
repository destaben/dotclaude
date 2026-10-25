---
name: codebase-memory-ops
description: Graph-first code exploration via the codebase-memory-mcp connector, to find code and assess change impact with far fewer file reads. Use before reading or grepping source in any project where the connector is available, and in planner, implementer and bug-hunter work.
---

## When this applies
Only if the `codebase-memory-mcp` tools are present in this session. If they
are not, ignore this skill and explore with `Grep`/`Glob`/`Read` as usual —
never fail or stall because the connector is missing.

## Why
A graph query returns a symbol, its callers or its source in a few hundred
tokens; reading whole files to find the same thing costs several times more.
Use it for **structure**, and keep `Read`/`Grep` for **content**.

## Workflow
1. **Check the index once per project.** `list_projects` (or `index_status`).
   If the project is missing, the main session indexes it with `index_repository`
   (`async: true`, then `status: true` until it finishes; never block on a large
   synchronous index) — this call prompts for approval. Subagents only check:
   if the project is unindexed they fall back to `Grep`/`Read` and say so.
2. **Orient** with `get_architecture` (or `get_graph_schema`) instead of
   listing directories and opening files.
3. **Locate** with `search_graph` (symbol/semantic) or `search_code` (text) with
   a small `limit`; page with `offset` only if needed.
4. **Read narrowly:** `get_file_outline` for a file's shape, `get_code_snippet`
   for one function — then `Read` with `offset`/`limit` only if more is needed.
5. **Before changing a symbol:** `trace_path` for callers and callees, and
   `detect_changes` on the working diff for blast radius and affected tests.
6. **Before claiming something is absent, unused, or fully covered:**
   `check_index_coverage` on the paths or scope. A clean result means "no
   recorded gap", not proof — confirm negatives with `Grep`.

## Fall back to Read/Grep when
- The file is not code the graph models (plain prose, JSON/YAML config, lockfiles,
  generated or ignored files) or `check_index_coverage` reports a gap.
- The index looks stale: the files changed since the last index and the project
  is not being watched (`index_status` shows `watch`). Re-index, or read directly.
- You need exact surrounding text to make an edit — edits always rest on a real `Read`.

## Avoid
- Calling `query_graph` (raw Cypher) when `search_graph` or `trace_path` answers it.
- Unbounded queries: always set `limit`, and set `trace_path` depth deliberately.
- `delete_project`, `manage_adr` writes, or `ingest_traces` unless asked.
- Letting large graph output pile up in the main context: for broad exploration,
  delegate to a subagent (see Token rules in `CLAUDE.md`) and take back a summary.
