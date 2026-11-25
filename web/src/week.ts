// Where an event goes in the week grid. Pure functions, no React: easy to test.
//
// The backend sends UTC times (ISO strings). The grid shows Zurich wall-clock
// time, so every time is converted with the browser's timezone database
// (Intl), which knows the daylight-saving switches.

export const DAY_START = 7 * 60; // grid shows 07:00 ...
export const DAY_END = 24 * 60; // ... to midnight, in minutes
const MS_PER_DAY = 86_400_000;

const zurichFormat = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Europe/Zurich",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

/** A moment as Zurich calendar day ("2026-11-24") and minutes after midnight. */
export function zurich(iso: string): { day: string; minutes: number } {
  const parts: Record<string, string> = {};
  for (const part of zurichFormat.formatToParts(new Date(iso))) {
    parts[part.type] = part.value;
  }
  return {
    day: `${parts.year}-${parts.month}-${parts.day}`,
    minutes: Number(parts.hour) * 60 + Number(parts.minute),
  };
}

// Calendar days as whole numbers, so "next day" is +1 with no timezone in play.
function dayNumber(day: string): number {
  const [year = 0, month = 1, date = 1] = day.split("-").map(Number);
  return Date.UTC(year, month - 1, date) / MS_PER_DAY;
}

function fromDayNumber(n: number): string {
  return new Date(n * MS_PER_DAY).toISOString().slice(0, 10);
}

/** The Monday of the week containing this day. */
export function mondayOf(day: string): string {
  const n = dayNumber(day);
  const weekday = (new Date(n * MS_PER_DAY).getUTCDay() + 6) % 7; // Mon = 0
  return fromDayNumber(n - weekday);
}

/** The 7 days Mon..Sun starting at this Monday. */
export function weekDays(monday: string): string[] {
  const start = dayNumber(monday);
  return Array.from({ length: 7 }, (_, i) => fromDayNumber(start + i));
}

/** Column (0 = Monday) and vertical position in percent of the visible day. */
export interface Box {
  day: number;
  top: number;
  height: number;
}

/** Where [start, end) goes in the week of `monday`; null if it isn't visible. */
export function place(start: string, end: string, monday: string): Box | null {
  const from = zurich(start);
  const to = zurich(end);
  const day = dayNumber(from.day) - dayNumber(monday);
  if (day < 0 || day > 6) return null; // another week
  const endMinutes = to.day === from.day ? to.minutes : DAY_END; // past midnight: cut
  const top = Math.max(from.minutes, DAY_START);
  const bottom = Math.min(endMinutes, DAY_END);
  if (bottom <= top) return null; // entirely before 07:00
  const span = DAY_END - DAY_START;
  return {
    day,
    top: ((top - DAY_START) / span) * 100,
    height: ((bottom - top) / span) * 100,
  };
}

/** "14:00" in Zurich time. */
export function clock(iso: string): string {
  const { minutes } = zurich(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(Math.floor(minutes / 60))}:${pad(minutes % 60)}`;
}
