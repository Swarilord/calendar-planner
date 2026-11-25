# Eval dataset

`cases_v1.jsonl`: 50 user requests (35 `train`, 15 `test`), one JSON object per
line. Each has a fixed `now`, a named calendar from `calendars.json`, the gold
`PlanRequest` (`expected`) and whether a valid plan exists (`expect_feasible`).

The `test` split is held out: it is never shown to the prompt optimiser (GEPA)
and only used for final scores. Once a version has been scored, it is frozen;
changes go into `cases_v2.jsonl`.

## How the gold answers were made

Drafted in one batch and reviewed case by case (2026-11-24), most of them
twice. They follow the conventions below,
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

## Parser prompt versions

| Version | Made by |
|---|---|
| `parser_v1.md` | written by hand (Phase 4) |
| `parser_v2.md` | GEPA, unchanged (budget 150, `gemini-3.5-flash-lite`, train split only) |
| `parser_v3.md` | GEPA + hand fix: v2 with three review fixes, made before any test-split run |

The hand fixes in v3, found by reading v2 (not by looking at test results):
"this weekend" starts on Saturday, not Friday; the parser answers in XML, not
JSON; times are written in local time with offset, never "converted to UTC".

## Results (24 Nov 2026, `gemini-3.5-flash-lite`, free tier)

Success = the right "impossible" answer, or a plan with no rule broken when
checked against the gold request. Outages (Gemini's 503/429) are counted
separately and left out of the rates.

**Test split** (15 held-out cases, never seen by GEPA):

| Baseline | Prompt | Answered | Success | Feasible/infeasible right | Parse exact | Invalid output |
|---|---|---|---|---|---|---|
| A: Gemini plans directly (run 1) | `direct_v1` | 15/15 | 11/15 (73%) | 100% | – | 0 |
| A: Gemini plans directly (run 2) | `direct_v1` | 15/15 | 10/15 (67%) | 100% | – | 0 |
| B: parser + solver | `parser_v1` | 15/15 | 14/15 (93%) | 93% | 33% | 0 |
| B: parser + solver | `parser_v2` (GEPA) | 13/15 | 11/13 (85%) | 92% | 38% | 1 |
| B: parser + solver | `parser_v3` (GEPA + hand fix) | 15/15 | **15/15 (100%)** | 100% | 47% | 0 |

**Train split** (35 cases): B with `parser_v1` 29/32 (91%), A 26/32 (81%), 3
outages each.

A second `parser_v3` test run stopped after 5 cases on rate limits (429) and
is not reported.

### Error analysis

- **A fails on arithmetic and rules, B on wording.** Test-split A failures are
  wrong totals (c02, c13, c17, c41), blocks outside the horizon or before the
  earliest start (c08, c20) and a too-short block (c02). B never broke a rule
  the parser had read correctly: every B failure traces back to a parse
  mistake.
- **Same model, same prompt, different result.** A's two runs differ by one
  case (73% vs 67%), so with 15 cases a difference of one or two cases is
  noise. B beats A in every run on both splits, by 2 to 5 cases.
- **c06 ("20 hours tomorrow, free from 8 to 22") is the case v3 fixed.** v1
  missed "tomorrow" as the earliest start, so the solver spread the work over
  today and tomorrow and said "feasible". v3 read the start correctly; the
  solver then proved it impossible.
- **Parse exact rose from 33% (v1) to 47% (v3)**, mostly fewer horizon
  mistakes ("this week" ends Sunday, not Saturday). Horizon mistakes rarely
  change the plan, so they cost little success.
- **GEPA's raw v2 was worse than v1 on success** (85% vs 93%): one invalid
  output (c41) and a missed earliest start (c20). The hand fixes in v3 (XML
  not JSON, local times) remove the likely cause of the invalid output.
- **Still wrong in every version:** the daily cap in c06 (the parser turns
  "fit 20 hours" into a 20 h cap), max_block_min set without being asked
  (c32), and deadlines on DST days off by one hour (c28).
