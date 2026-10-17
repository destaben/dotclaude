---
name: mcp-calendar-ops
description: Operations, parameters, and result limits for the Google Calendar MCP connector. Use whenever a task needs to read or create calendar events.
---

## Operations actually used here
- **Read/list events**: scope to a date range relevant to the request, not an
  open-ended future window.
- **Create event**: only on explicit request. Confirm date, time, and
  attendees before creating — an invite notifies other people, which isn't
  reversible by deleting the event afterward.

## Result limits
List only the fields needed (title, time, attendees) rather than full event
metadata, unless more detail was asked for.

## Avoid
Inviting external attendees or changing an existing event's time without
explicit confirmation — both affect other people's calendars.
