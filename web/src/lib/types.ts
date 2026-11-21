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
  kind: "reply" | "learn" | "describe";
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
  /** the chat it came from; null = the dashboard, or from before this was recorded */
  chat_id: number | null;
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

export interface Rating {
  kind: "feedback" | "correction";
  chat_id: number;
  msg_id: number;
  user_id: number;
  user_name: string | null;
  score: number | null;
  reason: string | null;
  text: string | null;
  ts: number;
  reviewed: boolean;
  original: string | null;
  trace_id: number | null;
}

export type StageKey = "context" | "retrieval" | "prompt" | "gen1" | "proof" | "gen2" | "filter" | "send";

export interface Pipeline {
  rates: {
    runs: number;
    sent: number;
    fallback: number;
    silent: number;
    first_try: number;
    avg_attempts: number | null;
  };
  nodes: { id: string; n: number }[];
  links: { source: string; target: string; value: number }[];
  stages: ({ t: number; n: number } & Record<StageKey, number | null>)[];
}

export interface Progress {
  id: number;
  kind: TraceSummary["kind"];
  user_name: string | null;
  trigger: string;
  started: number;
  steps: number;
  last: { kind: string; name: string | null; status: StepStatus };
}

export interface QualityPerson {
  name: string;
  runs: number;
  sent: number;
  fallback: number;
  silent: number;
  median_ms: number | null;
  good: number;
  bad: number;
}

export interface Quality {
  words: {
    word: string;
    n: number;
    traces: number;
    last: number;
    trace_id: number;
    claude: { verdict: "keep" | "fix"; fix: string | null } | null;
    known: boolean;
  }[];
  attempts: Record<string, number>;
  triggers: Record<string, number>;
  people: QualityPerson[];
  context: {
    limit: number;
    p50: number | null;
    p95: number | null;
    max: number | null;
    replies: number;
    facts: number | null;
    chunks: number | null;
    history: number | null;
  };
  activity: number[][]; // [weekday Mon=0][hour] -> messages
}

export interface ClaudeStatus {
  allowed: boolean;
  reason: "disabled in config" | "no API key" | "period ended" | "switched off" | "daily limit reached" | null;
  enabled: boolean;
  switch: boolean;
  key: boolean;
  until: string | null;
  calls_today: number;
  daily_limit: number;
  model: string;
}
