export type BotState = "active" | "inactive" | "failed" | "activating" | "deactivating" | "unknown";

export interface Status {
  bot: BotState;
  model: string;
  started_at: number | null;
  last_error: string | null;
  enabled: boolean;
  random_n: number;
  quiet_until: number;
}

export interface TraceSummary {
  id: number;
  kind: "reply" | "learn";
  chat_id: number | null;
  msg_id: number | null;
  user_name: string | null;
  trigger: string;
  outcome: "sent" | "fallback" | "canned" | "error" | "skipped" | null;
  error: string | null;
  reply: string | null;
  started: number;
  duration_ms: number | null;
  attempts: number;
}

export type StepStatus = "ok" | "rejected" | "skipped" | "error";

export interface Step {
  id: number;
  seq: number;
  kind: string;
  name: string | null;
  status: StepStatus;
  started: number;
  duration_ms: number;
  detail: Record<string, unknown>;
  has_prompt: boolean;
}

export interface TraceDetail {
  trace: TraceSummary;
  steps: Step[];
}

export interface Metrics {
  cards: {
    replies: number;
    median_ms: number | null;
    tok_s: number | null;
    rejections: number;
    good: number;
    bad: number;
  };
  series: { t: number; replies: number; p50_ms: number | null; p95_ms: number | null; tok_s: number | null }[];
  rejections_by_filter: Record<string, number>;
  ratings: { t: number; good: number; bad: number }[];
}

export interface Fact {
  id: number;
  kind: "fact" | "slang";
  text: string;
  about: number | null;
  source: string;
  created: number;
  updated: number;
  people: number[];
}

export interface Person {
  id: number;
  name: string;
  aliases: string[];
  user_id: number | null;
  fact_count: number;
}

export interface Relation {
  id: number;
  a: number;
  rel: string;
  b: number;
}

export interface PeopleGraph {
  people: Person[];
  relations: Relation[];
  comentions: { a: number; b: number; n: number }[];
}
