import type { Plan } from "./api";
import { DAY_END, DAY_START, clock, mondayOf, place, weekDays, zurich } from "./week";

const HOURS = Array.from(
  { length: (DAY_END - DAY_START) / 60 },
  (_, i) => DAY_START / 60 + i,
);
const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

interface Item {
  title: string;
  start: string;
  end: string;
  kind: "busy" | "mine" | "proposed";
}

/** One week, Zurich time, 07:00-24:00: events grey, proposed blocks highlighted. */
export function WeekView({ plan }: { plan: Plan | null }) {
  const showBlocks = plan?.status === "draft";
  const items: Item[] = [
    ...(plan?.events ?? []).map((e) => ({ ...e, kind: e.mine ? "mine" : "busy" }) as Item),
    ...(showBlocks ? plan.blocks : []).map(
      (b) => ({ title: b.task_name, start: b.start, end: b.end, kind: "proposed" }) as Item,
    ),
  ];
  // Show the week of the first proposed block, else of today.
  const anchor = (showBlocks && plan.blocks[0]?.start) || new Date().toISOString();
  const monday = mondayOf(zurich(anchor).day);
  const days = weekDays(monday);

  return (
    <div className="week">
      <div className="week-head">
        <div />
        {days.map((day, i) => (
          <div key={day}>
            {DAY_NAMES[i]} {day.slice(8)}.{day.slice(5, 7)}.
          </div>
        ))}
      </div>
      <div className="week-body">
        <div className="hours">
          {HOURS.map((h) => (
            <div key={h}>{String(h).padStart(2, "0")}:00</div>
          ))}
        </div>
        {days.map((day, column) => (
          <div key={day} className="day">
            {items.map((item, i) => {
              const box = place(item.start, item.end, monday);
              if (box === null || box.day !== column) return null;
              return (
                <div
                  key={i}
                  className={`item ${item.kind}`}
                  style={{ top: `${box.top}%`, height: `${box.height}%` }}
                  title={`${item.title} ${clock(item.start)}-${clock(item.end)}`}
                >
                  <strong>{item.title}</strong> {clock(item.start)}-{clock(item.end)}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
