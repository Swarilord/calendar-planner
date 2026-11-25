// The backend's endpoints, typed. These types mirror the Pydantic models in
// planner/api/app.py; times are ISO strings in UTC.

export interface ChatOut {
  reply: string;
  tool_calls: string[];
  plan_id: string | null;
}

export interface Block {
  task_name: string;
  start: string;
  end: string;
}

export interface CalendarEvent {
  title: string;
  start: string;
  end: string;
  mine: boolean; // created by this app
}

export interface Plan {
  plan_id: string;
  status: "draft" | "infeasible" | "applied" | "rejected";
  blocks: Block[];
  events: CalendarEvent[];
  reasons: string[];
}

export interface ApplyOut {
  created: number;
  already_there: number;
}

/** Thrown for any non-2xx answer; `message` is the backend's explanation. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function call<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data.detail === "string" ? data.detail : response.statusText;
    throw new ApiError(response.status, detail);
  }
  return data as T;
}

export const api = {
  chat: (message: string) => call<ChatOut>("POST", "/chat", { message }),
  plan: (id: string) => call<Plan>("GET", `/plans/${id}`),
  apply: (id: string) => call<ApplyOut>("POST", `/plans/${id}/apply`),
  reject: (id: string) => call<Plan>("POST", `/plans/${id}/reject`),
};
