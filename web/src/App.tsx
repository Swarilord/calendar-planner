import { type FormEvent, useState } from "react";
import { ApiError, type Plan, api } from "./api";
import { WeekView } from "./WeekView";

interface Message {
  from: "you" | "planner" | "system";
  text: string;
}

/** Chat on the left, the week on the right; Confirm/Reject under the week. */
export function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [plan, setPlan] = useState<Plan | null>(null);
  const [busy, setBusy] = useState(false);

  const add = (from: Message["from"], text: string) =>
    setMessages((old) => [...old, { from, text }]);

  // Runs one backend action; any error becomes a message, never a blank page.
  async function run(action: () => Promise<void>) {
    setBusy(true);
    try {
      await action();
    } catch (error) {
      const text = error instanceof ApiError ? error.message : "Could not reach the server.";
      add("system", text);
    } finally {
      setBusy(false);
    }
  }

  function send(event: FormEvent) {
    event.preventDefault();
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    add("you", text);
    void run(async () => {
      const turn = await api.chat(text);
      add("planner", turn.reply);
      if (turn.plan_id) setPlan(await api.plan(turn.plan_id));
    });
  }

  function confirm() {
    if (!plan) return;
    void run(async () => {
      const result = await api.apply(plan.plan_id);
      add("system", `Added ${result.created} block(s) to your Study plan calendar.`);
      setPlan(await api.plan(plan.plan_id));
    });
  }

  function reject() {
    if (!plan) return;
    void run(async () => {
      setPlan(await api.reject(plan.plan_id));
      add("system", "Draft discarded.");
    });
  }

  return (
    <div className="app">
      <section className="chat">
        <div className="messages">
          {messages.length === 0 && (
            <p className="hint">Try: "Analysis sheet, about 4h, due Thursday evening"</p>
          )}
          {messages.map((m, i) => (
            <p key={i} className={m.from}>
              {m.text}
            </p>
          ))}
          {busy && <p className="hint">Thinking…</p>}
        </div>
        <form onSubmit={send}>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="What do you need to plan?"
            disabled={busy}
          />
          <button disabled={busy || !input.trim()}>Send</button>
        </form>
      </section>

      <section className="calendar">
        <WeekView plan={plan} />
        {plan?.status === "draft" && (
          <div className="actions">
            <span>Draft {plan.plan_id}: nothing is written until you confirm.</span>
            <button onClick={reject} disabled={busy}>
              Reject
            </button>
            <button className="primary" onClick={confirm} disabled={busy}>
              Confirm
            </button>
          </div>
        )}
        {plan?.status === "infeasible" && (
          <div className="actions">Not possible: {plan.reasons.join(" ")}</div>
        )}
      </section>
    </div>
  );
}
