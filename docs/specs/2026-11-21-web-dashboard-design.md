# Botucha web dashboard — design

Status: approved in conversation, 2026-11-21.

## Goal

A local website for running Botucha: manage memory, people, relations, ratings, persona, config and the
service, and see how the bot performs and how each reply was produced ("thinking" = a step trace of the
pipeline, not model reasoning; the chat model keeps `think=False`).

Success: open any reply Botucha sent and see, as a graph, why he spoke, which memory he used (with
scores), how long each step took, and which filter rejected an attempt and why.

## Constraints

- Local only, single user, no login. Listens on `127.0.0.1:8765`.
- UI libraries: the same family as the reference project — Next.js 16 (static export), React 19,
  shadcn/radix, Tailwind 4, recharts, @xyflow/react, @tanstack/react-table, zustand, sonner,
  lucide-react, react-hook-form + zod, next-themes, Biome. No g6, calendars or maps.
- UI language: English by default, Lithuanian selectable; choice remembered in the browser.
  Every UI string has an EN and an LT key.
- Light and dark theme.
- The bot's behaviour in chat does not change. Chat commands keep working.
- Tracing must never block or fail a reply.
- No personal data in the repo (same rules as the rest of the project).

## Architecture

```
Telegram ─► botucha (bot service) ── writes traces, reads state ──► botucha.db (SQLite, WAL)
                │                                                    ▲
                ▼                                                    │
            Ollama                                    botucha-web (new service)
                                                      FastAPI + uvicorn, 127.0.0.1:8765
                                                      /api/*      JSON, uses botucha.Store / Memory
                                                      /api/live   SSE (new traces, status)
                                                      /           static UI from web/out
```

- Two systemd user services. The web service keeps working when the bot is stopped or crashed.
- Both open the same SQLite file. `Store` sets `PRAGMA busy_timeout=5000` (WAL is already on).
- Node is needed only to build the UI; runtime is Python only.

Code layout:

- `botucha/trace.py` — `Tracer`, trace/step model, retention cleanup.
- `botucha/webapi/` — FastAPI app: `app.py` (factory, security middleware, static files),
  one router module per area (`status`, `traces`, `memory`, `people`, `ratings`, `control`, `settings`).
- `web/` — Next.js app; `web/out` is the build output served by the API.
- `deploy/botucha-web.service` — systemd unit (`UMask=0077`).
- Entry point: `uv run python -m botucha.webapi`.

## Tracing (bot side)

New tables:

```
traces(id, kind TEXT  -- 'reply' | 'learn'
       chat_id, msg_id, user_name, trigger TEXT, outcome TEXT  -- sent|fallback|canned|error|skipped
       error TEXT, reply TEXT, started REAL, duration_ms REAL)
trace_steps(id, trace_id, seq, kind TEXT, name TEXT, status TEXT  -- ok|rejected|skipped|error
            started REAL, duration_ms REAL, detail TEXT  -- JSON
            prompt TEXT NULL)  -- full prompt, prompt step only
```

Trigger reasons: `direct`, `keyword:<word>`, `random:1/<n>`, `serious`, `recall`, `reaction`.
The trigger code returns its reason; `Job` carries it.

Steps written for a reply:

| step | detail |
|---|---|
| `context` | history size, own lines dropped |
| `retrieval` | chunks and facts used, each with id, text preview, FTS rank, cosine score; prices |
| `prompt` | characters and estimated tokens per section (persona, guard, prices, style, profiles, people, slang, chunks, facts, history); full prompt in `prompt` |
| `generation` (one per attempt) | attempt, model, prompt_eval_count, eval_count, eval/load/total durations, tok/s, raw text |
| `filter` (one per attempt) | each check (leak, repeat, foreign script, spelling) with pass/fail and reason |
| `send` | Telegram message ids |

`learn` traces: chunks read, facts and slang added or rejected with the reason.

Implementation notes:

- `OllamaLLM.chat` returns text plus stats (`ChatResult`); the `LLM` protocol and fakes are updated.
- `generate_reply` and `Memory` search take an optional tracer; with none they behave exactly as now.
- `Tracer` swallows its own errors (logs a warning).
- Retention: traces 30 days, full prompts 7 days. Cleanup runs hourly in the bot.

## State shared with the bot

- `enabled`, `random_n` (already in `state`) and `quiet_until` (new) are read from `state` every 5 s,
  so changes from the website reach the bot in ≤5 s.
- Persona is already read on every reply. Memory, people and slang are read from the DB on every reply.
- Config changes need a restart; the UI offers one.

## Pages

1. **Overview**
   - Bot status from `systemctl --user is-active botucha`, model, uptime, last error.
   - Cards: replies today, median reply time, tok/s, filter rejections, 👍/👎.
   - Charts for 24 h / 7 d / 30 d: reply time p50/p95, replies per hour, rejections by filter, ratings.
2. **Thinking**
   - Live table of traces: time, who, trigger, duration, attempts, outcome; filter by outcome and kind.
   - Trace view: xyflow graph of steps left to right. Retries branch downward. Colour by status, a
     duration bar per node.
   - Above the graph, a waterfall timeline. Clicking a node opens a side panel with the details: memory
     used with scores, full prompt, raw model text, filter reasons.
3. **Memory**
   - Facts and slang tables: search; filter by person and by source (auto / member-taught); add, edit,
     delete.
4. **People**
   - xyflow graph: nodes are people, solid edges are explicit relations (labelled), faint edges are
     co-mention in facts.
   - Side panel: aliases, facts, relations.
   - Add a person or a relation; drag from one person to another to create a relation.
5. **Ratings**
   - 👍/👎 and corrections, each with the original message and a link to its trace.
   - Mark as reviewed (new `reviewed` column on `feedback` and `corrections`).
   - Export to JSONL (prompt context, reply, rating, correction).
6. **Controls**
   - On/off, quiet N minutes, random frequency 1/n.
   - Restart, start and stop the bot service; last 50 journal lines.
7. **Persona & Settings**
   - Persona editor with a diff before save and a timestamped backup in `backups/`.
   - Form for selected config values (model temperature and num_predict, trigger settings, keywords),
     validated through `load_config`, with a backup of `config.toml` before writing.
   - Shows which changes apply immediately and which need a restart.
   - `.env` is never shown or edited.

## Security

- Bind to `127.0.0.1` only.
- Reject requests whose `Host` is not `localhost:8765` or `127.0.0.1:8765` (DNS rebinding).
- Every non-GET request needs `X-Botucha-Token`. The token is random per service start and served by
  `GET /api/session`. There is no CORS, so other origins can neither read the token nor send it.
- New facts and slang pass `looks_like_instruction` and the length limits, as in chat.
- Locked members stay protected from automatic learning; manual edits are allowed.
- Backups and written files get mode 600.

## Errors

- **Bot down:** the UI shows "Stopped", the journal tail and a Start button.
- **Ollama down while adding a fact:** clear "embeddings unavailable" error; nothing is stored.
- **Database busy for more than 5 s:** 503 and a "try again" toast.
- **Invalid config or persona** (empty, or over the prompt budget): rejected with a field-level
  message; nothing written.
- **Trace write failure:** logged, and the reply is still sent.

## Testing

- **pytest:**
  - Tracer: steps, timings, error swallowing.
  - `_reply` with a fake LLM records every step, including a filter rejection followed by attempt 2.
  - `learn` trace.
  - State polling (≤5 s).
  - Retention cleanup.
  - API through httpx: each endpoint; Host and token checks; persona/config validation and backups;
    memory edits go through `Memory`.
- **UI:**
  - `biome check`;
  - `next build` (static export);
  - an i18n key check (EN and LT have the same keys);
  - a manual pass of every page against real traces.

## Rollout

1. Tracing in the bot (tables, `Tracer`, LLM stats, trigger reasons, state polling, retention).
2. Web API skeleton + security + Overview + Thinking.
3. Memory + People.
4. Ratings + Controls + Persona & Settings, systemd unit, README.

Each stage leaves the bot working and the tests green.
