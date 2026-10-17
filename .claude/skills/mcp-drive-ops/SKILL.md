---
name: mcp-drive-ops
description: Operations, parameters, and result limits for the Google Drive MCP connector. Use whenever a task needs to find, read, or organize files in Drive.
---

## Operations actually used here
- **Search**: filter by name, folder, or type before listing — don't page
  through an entire Drive.
- **Read**: fetch a file's content only when its content is actually needed,
  not just its existence.
- **Move/rename/share**: only on explicit request; confirm the target folder
  or audience before a share action, since Drive sharing is visible to others.

## Result limits
Summarize large documents instead of pulling their full text into context
unless the task requires verbatim content.

## Avoid
Changing sharing permissions or deleting files without being asked. Drive
operations that change who can see a file are not easily reversible in effect
(even if technically undoable), so confirm first.
