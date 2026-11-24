# Eval dataset

`cases_v1.jsonl`: 50 user requests (35 `train`, 15 `test`), one JSON object per
line. Each has a fixed `now`, a named calendar from `calendars.json`, the gold
`PlanRequest` (`expected`) and whether a valid plan exists (`expect_feasible`).

The `test` split is held out: it is never shown to the prompt optimiser (GEPA)
and only used for final scores. Once a version has been scored, it is frozen;
changes go into `cases_v2.jsonl`.

## How the gold answers were made

Drafted and reviewed by Claude (2026-11-24); most cases were also reviewed by
me (the project author) the same day. They follow the conventions below,
which match the parser prompt `parser_v1.md`. Automatic checks
(`tests/test_eval_data.py`): every gold answer validates as a `PlanRequest`,
the horizon starts at `now` and covers every deadline, and the CP-SAT solver
agrees with `expect_feasible` (a feasible gold plan must also pass the checker).

Judgement calls worth a second opinion: c02, c07, c08, c09, c33, c45, c49.

## Conventions

Times
- Times are Europe/Zurich, written with the offset valid on that date.
- A weekday means the next such day; today counts if the time is still ahead.
  "Next week" is Monday to Sunday of the following week.
- A deadline without a time is 23:59 that day. "Before Saturday" is Friday 23:59.
- The horizon starts at `now`. It ends at the next Monday 00:00, or at the end of
  a period the user names ("today", "tomorrow", "next week", "between Thursday
  and Saturday", "tomorrow afternoon"), and is stretched to cover the latest
  deadline.

Tasks
- Durations are rounded up to multiples of 15 minutes ("about 50 min" is 60,
  "1h40" is 105).
- "Every day" starts today and runs to the end of the horizon; "until Friday"
  includes Friday. Each day is a task named "<name> <Day>", from 00:00 to 23:59.
- "Tomorrow", "this weekend", "next week" and "after X" also set an earliest
  start at the beginning of that period.
- A block length is set only if the user names one ("at most 2 hours in one go",
  "a single 5-hour block").

Wishes
- Morning 06:00-12:00, afternoon 12:00-18:00, evening 18:00-24:00.
- Defaults (from 2026-11-24): work between 07:00 and midnight, at most 12 h per
  day. A gold answer leaves these fields out unless the user changes them.
- "Nothing before 9" sets day_start for every day; "keep X free" is a blocked
  window. "Keep lunch free" adds a blocked 11:00-12:00 window on each day.
- Lunch is 11:00-12:00 unless changed; "no lunch break" sets both to null.
