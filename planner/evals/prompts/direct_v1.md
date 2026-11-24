Plan the user's work directly: read the request, list the tasks you understood,
and place time blocks for them in the calendar yourself.

Understanding the request (same conventions as the parser)
- Read relative dates ("today", "Thursday", "next week") relative to `now`. A
  weekday means the next such day; today counts only if that time is ahead.
- Write datetimes as ISO 8601 with the Europe/Zurich offset of that date:
  +01:00 in winter, +02:00 in summer (last Sunday of March to last Sunday of
  October). A deadline without a time means 23:59 that day.
- Durations are multiples of 15 minutes; round estimates up ("about 50 min" ->
  60). A recurring wish ("1h every day") is one task per day, named with the
  day, e.g. "Revision Wed", from 00:00 to 23:59 of that day.
- Morning is 06:00-12:00, afternoon 12:00-18:00, evening 18:00-24:00.

Placing blocks
- Blocks never overlap each other or the calendar's events.
- Each task's blocks add up to exactly its duration, start after its earliest
  start, end by its deadline, and stay inside the hours and free times the user
  asked for. Start after `now`.
- Blocks are at least 30 minutes (or the whole task, if shorter), and no longer
  than a block limit the user names. Respect a daily work limit.
- Prefer earlier times; avoid 11:00-12:00 (lunch) and work after 20:00 where
  possible.
- Each block's task_name is exactly the name of one of your tasks.
- If the request cannot be met, set feasible to false and give no blocks.
