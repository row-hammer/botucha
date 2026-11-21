# How Botucha works

The reference behind the [README](../README.md): every rule, limit and design decision, with the reasons.

- [When he speaks](#when-he-speaks)
- [Bursts, restarts and crashes](#bursts-restarts-and-crashes)
- [Memory](#memory)
- [Learning](#learning)
- [The prompt](#the-prompt)
- [Reply quality](#reply-quality)
- [Claude proofreading](#claude-proofreading)
- [Prices](#prices)
- [Images](#images)
- [The web dashboard](#the-web-dashboard)
- [Backups and restore](#backups-and-restore)
- [Configuration reference](#configuration-reference)
- [Making the persona yours](#making-the-persona-yours)
- [Evaluating changes](#evaluating-changes)
- [Models tested](#models-tested)
- [Security model](#security-model)
- [Testing](#testing)
- [Project layout](#project-layout)
- [Roadmap](#roadmap)

## When he speaks

`trigger.py`, pure decision logic.

1. Messages from other bots and from himself, empty messages, messages older than process start and
   messages while he is switched off never trigger anything. An anonymous group admin counts as a person.
2. **Direct** (a mention, a reply to him, his name matched by `bot_name_regex`, or any message in an allowed
   private chat): always answered, ignoring cooldown and `/tyla`, but limited to `user_calls_per_min` per
   person per minute, counted together with that person's commands. The first call over the limit gets one
   🥱 and the rest are ignored; the admin's commands are not limited.
3. **Uninvited**: blocked during `/tyla` and the cooldown. Otherwise a keyword (a word prefix; case and
   Lithuanian letters ignored) replies with `keyword_prob`, else a random 1/`random_n` reply, else a
   1/`reaction_n` emoji reaction from `reactions`.

Commands sent while the bot was offline are stored but never executed or answered.

## Bursts, restarts and crashes

`worker.py`: one reply worker, one generation at a time. After a trigger it waits until the chat has been
quiet for `burst_quiet_s` (at most `burst_max_s`), then answers everything that triggered in that window in
one go. Triggers that arrive while he is generating form the next batch.

Stopping or restarting never drops a reply someone asked for:

- on stop, the reply being generated and any queued behind it get up to 60 s to go out (the unit allows 75);
- the unanswered replies (the rest of the running batch and the queue) are always saved in the database, so
  after a stop that ran out of time, or a crash, direct calls at most 10 minutes old are answered on the next
  start, and the traces the last run left open are closed;
- uninvited replies are not repeated;
- an error in one chat never costs the other chats in the same batch their reply;
- if a background loop (learning, backups, state sync, the worker) dies, the bot exits with an error so
  systemd restarts it.

## Memory

`memory.py`, `store.py`, `chunking.py`. Everything lives in `botucha.db`:

| Table | Contents |
|---|---|
| `messages` | every message: who, when, text, reply-to. Also the future fine-tuning dataset. |
| `chunks` (+ FTS5) | windows of consecutive messages, closed by 30 min of silence, 15 messages or 1200 characters, with a `bge-m3` embedding |
| `facts` (+ FTS5) | facts and slang with source (`auto`, `cmd:<user id>` or `web`), the chat they came from, timestamps and embedding |
| `people`, `fact_people` | people (members and friends) with word forms; each fact linked to everyone it mentions |
| `relations` | explicit directed relations between people (`a – rel → b`) |
| `profiles` | a short profile per member |
| `feedback`, `corrections` | ratings and better versions of his replies |
| `traces`, `trace_steps` | the step-by-step record of every reply and learning run (dashboard) |
| `spell_fixes`, `known_words` | Claude's spelling verdicts and words approved on the dashboard |
| `state` | cursors, settings shared with the dashboard, unanswered replies |

**People.** Every member has exactly one person, found by user id; two members with the same display name
are two people. A friend the admin added who later joins keeps their person.

**Search** is hybrid: the cosine ranking and the FTS5 word-match ranking are merged by reciprocal rank
fusion, so a conversation holding a rare word you ask about is found even when others are closer in meaning.
A reply never gets back chunks its own transcript already shows (`/atsimeni` still links them). A recall
phrase ("atsimeni", "pamenat", …) or `/atsimeni` retrieves more chunks. FTS5 queries are built from quoted
tokens, so user text cannot break the search syntax.

`bge-m3` runs on the CPU (`num_gpu: 0`), so it never competes with the chat model for VRAM, and stays loaded
as long as the chat model (`keep_alive`). New chunks are embedded 32 at a time and saved after each request;
a reply indexes one request's worth at most and leaves a backlog to the learning loop. If the embedding model
is down he still answers, just without memory (the trace shows the failed search).

## Learning

`learn.py`. When the chat has been quiet for 10 minutes and at least 30 new messages exist, the model reads
the new chunks and returns JSON with facts (about named people) and slang. Rules:

- his own lines and command lines are removed first, so his jokes never become "facts" and a fact deleted
  with `/pamirsk` does not come back from the `/isimink` that created it;
- facts and slang about the bot himself are refused (here, in `/isimink` and on the dashboard): once in his
  prompt, "Botucha always answers in English" reads as a rule;
- a near-duplicate fact (cosine ≥ 0.88) updates the existing one instead of adding a new one, unless a person
  wrote the existing one (`/isimink`, `/slengas`, the dashboard): those are never changed by learning;
- facts that look like instructions or are too long are dropped;
- facts about a known person always carry that person's name, so they link correctly;
- members in `memory.locked_members` get no automatic facts and no profile refresh, under every name and word
  form, and also not through a fact about someone else that mentions them;
- a private chat with him is never learned from: no facts, slang, profile lines or spell-check vocabulary
  (`/isimink` and `/slengas` typed there still work); an imported private chat is stored but not learned from;
- profiles are regenerated about every 200 messages, with the member lines marked as data; lines that look
  like instructions or are about the bot are dropped, and a profile is cut to 800 characters (stored profiles
  are filtered the same way on their way into the prompt).

A backlog (a first import, a busy day) is read in pieces of about 6,000 characters, at most five model calls
per idle run, and learning stops between pieces as soon as someone is waiting for a reply. An answer that is
not valid JSON, usually one cut off at the token limit, is asked again for each half of the piece. A
conversation the model cannot read is tried once more and then skipped, so learning never gets stuck.

## The prompt

`brain.py`. The **system message** holds only what stays the same from one reply to the next:

1. `persona.md`
2. a data guard (everything below is information, not instructions) and the price rule
3. real group lines from `style_examples.txt` (skipped in `/rimtai` mode)
4. spelling notes, member profiles, all slang (one meaning per word, member-taught wins)

The **user message** holds what changes:

5. the last 40 messages as a transcript, with commands removed and only his last 5 own lines kept
6. a second data guard, then people and relations for the people named in the conversation or writing in it,
   retrieved conversation chunks and facts, live prices when any were fetched, and the image guard when he
   looks at a photo
7. the message(s) he is answering when that is not simply the last line, then the instruction to reply

**Why this order.** On this setup Ollama cannot reuse a cached prompt that changes more than a few hundred
tokens before its end, which every reply's retrieval did, so each reply read all ~7,000 prompt tokens again
(13–16 s). It does keep a block that was sent on its own. So the bot sends the system message once with a
one-token answer at start, again whenever it changes, after a learning run or an image description (they
replace the cache), and when a reply's prompt was read slowly enough to show the cache was lost. Measured
with invented text at real sizes: 15.7 s of prompt reading per reply before, 5.3 s after.

**Budget.** The prompt is trimmed (oldest transcript lines first) so that it, the answer and an image fit in
`num_ctx`. It assumes 2.5 characters per token; this model averages 2.74 on the group's Lithuanian.

## Reply quality

Each reply gets up to two attempts. An attempt is rejected when it:

- repeats eight or more words of the persona verbatim (quoted examples in the persona are allowed);
- repeats one of his last 20 messages (exactly or nearly);
- contains a letter from a script other than Latin, Lithuanian or Cyrillic (a known Gemma glitch);
- contains a word that is in neither the hunspell dictionary nor the words members themselves use.

A flagged word alone never costs a second generation (measured: the retry spelled better 3 times out of 17
and cost a median 7 s). The proofreader is asked if it is enabled; otherwise a direct call gets the draft as
it is (shown as a fallback on the dashboard) and an uninvited reply is dropped. The second attempt is for the
other rejections. Names he was told about (people, their word forms, facts written by a person) count as
known words, and so does a capitalised two-word name at the start of a sentence.

Lines written as another member, a friend or a chat-format role (`Name: …`) are dropped; a name or alias
shorter than four letters only counts when the label is exactly that. Direct calls that still fail get a
short canned line; uninvited replies stay silent.

## Claude proofreading

`proofread.py`, optional. When a draft fails **only** the spell check, Botucha can ask Claude (Anthropic
API) about the flagged words. Claude gets the draft reply and the flagged words, nothing else: no chat
history, no member messages, no persona. It answers per word with structured JSON: `keep` (a real word,
name or slang) or a replacement of one to three words. Botucha applies the replacements itself and runs every
filter again, so Claude cannot rewrite the reply.

Every verdict is stored. The most frequent fixes go into the prompt as spelling notes ("nužvelgei (ne
nužvalgai)"), and words Claude judged real can be approved on the Quality page as known words. Approving a
word also drops any note that "corrected" it, which is how a wrong fix is taken back. Both keep working
after Claude is switched off.

It is off unless `[claude] enabled = true` and `ANTHROPIC_API_KEY` is in `.env`. It switches itself off
after `until`, stops for the day at `daily_limit` calls, and has an on/off switch on the Quality page. It
uses `claude-opus-5-5` at low effort with refusal fallbacks enabled; at a few dozen flagged drafts a day it
costs cents per day.

## Prices

`prices.py`. Names map to Yahoo symbols (`spx` → `^GSPC`, `vwce` → `VWCE.DE`, `nvidi…` → `NVDA`, `btc` →
`BTC-USD`, …); stems of 4+ letters match Lithuanian word forms. At most 3 symbols per reply, cached for 5
minutes (256 symbols at most), 5-second timeout. Only text shaped like a real ticker is ever sent to Yahoo,
escaped in the URL.

## Images

`images.py`. A photo is stored as `[nuotrauka] <caption>` with Telegram's file id; nothing is downloaded until
he replies. A reply looks at one image at most: the one the answered message replies to, otherwise the
newest in the burst. It is downloaded into memory only (Telegram's ≤1280 px size, max 5 MB), sent to the model
with a guard line, and if the model fails on it the second attempt runs on text only. After the reply he
writes a ≤20-word description and the stored text becomes `[nuotrauka: <description>] <caption>`, so
history, search and learning see it. Stickers, GIFs and video are ignored.

This needs a chat model with vision. A GGUF import has none until you attach the matching projector:

```
FROM /path/to/model.gguf
FROM /path/to/mmproj-<model>.gguf        # e.g. mmproj-gemma-4-31B-it-Q8_0.gguf from ggml-org
```

`ollama show <model>` then lists `vision`. At startup the log says `vision: yes` or `vision: no`.

## The web dashboard

| Page | What it shows / does |
|---|---|
| Overview | bot status and last error; replies, median reply time, tok/s, first-try and fallback rates, ratings; 24 h / 7 d / 30 d |
| Pipeline | how replies flow through generation, the filters and Claude (click any box to see those replies), time per stage, what he is doing now |
| Quality | flagged words with Claude's verdict and "add to known words", Claude status and switch, context use, attempts, triggers, per-person table, activity heatmap |
| Thinking | every reply and learning run, live; each one's step graph and timeline |
| Memory | facts and slang: search, filter by person or source, add, edit, delete |
| People | graph of people and relations; drag between people or use a person's panel to add a relation |
| Ratings | 👍/👎 and corrections next to his original message; mark reviewed; export JSONL for fine-tuning |
| Controls | on/off, uninvited reply frequency, quiet mode, start/stop/restart, recent log |
| Persona & Settings | edit `persona.md` with a diff before saving; edit selected `config.toml` values (backed up, comments kept) |

**The thinking graph.** Every reply leaves a trace of its steps: context → memory search → prompt →
generation → filters → send, with a second generation or Claude when an attempt is rejected. Click a step to
see which facts and old conversations were used (cosine score, word match), the prompt size per section and
the full prompt, the raw model text, and which filter rejected an attempt and why. Tracing never blocks a
reply. Traces are kept for 30 days, full prompts for 7.

**How changes reach the bot.** Both services share `botucha.db`. Memory edits and persona changes apply to
the next reply. On/off, frequency and quiet mode go through the `state` table, which the bot reads every 5
seconds. Other config changes need a restart (the page offers one).

**Security.** It listens on `127.0.0.1` only and has no login. Requests with any other `Host` header are
refused (DNS rebinding), and every change needs a per-start token that other websites cannot read (CSRF).
`.env` is never shown or edited. Memory edits go through the same filters and limits as chat commands.
Written files and backups are private (600). The live stream reconnects by itself after the service restarts.

For UI work, run the API with `BOTUCHA_WEB_DEV=1` and `cd web && npm run dev` (port 3000, `/api` is proxied).

## Backups and restore

Once a day the bot copies the database to `backups/daily/botucha-YYYY-MM-DD.db` (SQLite online backup,
integrity-checked, mode 600) and keeps the last 7. To restore, stop **both** services first:

```bash
systemctl --user stop botucha botucha-web
uv run python -m botucha.restore backups/daily/botucha-YYYY-MM-DD.db --config config.toml
systemctl --user start botucha botucha-web
```

It refuses while anything still has the database open, keeps the current one as
`backups/botucha-before-restore-<time>.db`, and removes the leftover `-wal` / `-shm` files. Never copy a
backup over `botucha.db` by hand: a leftover write-ahead log is replayed onto the copied file, and the result
silently mixes old and new data while still passing an integrity check.

## Configuration reference

`config.toml` (copy of `config.example.toml`). Tokens come from `.env` (`BOTUCHA_TOKEN`, and
`ANTHROPIC_API_KEY` for proofreading), never from `config.toml`.

| Key | Default | Meaning |
|---|---|---|
| `telegram.chat_ids` | – | chats he works in; everything else is ignored (groups are left) |
| `telegram.admin_id` | – | your user ID for admin commands |
| `telegram.bot_name_regex` | `botuch\w*` | what counts as calling him by name (case and Lithuanian letters ignored) |
| `model.chat_model` | `gemma4-31b-heretic-q4-32k` | Ollama chat model |
| `model.embed_model` | `bge-m3` | embedding model for memory search |
| `model.num_ctx` / `num_predict` | 32768 / 150 | context size / max reply tokens (`/rimtai` uses at least 450) |
| `model.keep_alive` | `30m` | how long Ollama keeps both models loaded |
| `model.temperature` | 0.7 | lower = fewer invented words, higher = more random humor |
| `model.min_p` | 0.05 | drops unlikely tokens, which cuts invented words (0 = off) |
| `trigger.keywords` | spx, vwce, akcij, … | word prefixes for uninvited replies |
| `trigger.keyword_prob` | 0.5 | chance to reply on a keyword |
| `trigger.random_n` | 25 | random reply 1 in n messages; `/daznis`, Controls and Settings all set the live value |
| `trigger.cooldown_s` | 180 | minimum seconds between uninvited replies |
| `trigger.reaction_n` / `reactions` | 15 / 🤡 🗿 … | chance and emoji for reactions (Telegram's allowed reactions only) |
| `trigger.burst_quiet_s` / `burst_max_s` | 5 / 20 | burst waiting |
| `trigger.tyla_default_min` | 60 | default `/tyla` length (at most a week) |
| `trigger.user_calls_per_min` | 5 | direct calls and commands per person per minute (admin commands exempt) |
| `paths.*` | | database, persona, style examples, optional export |
| `memory.locked_members` | [] | user IDs whose memory you keep by hand |
| `prices.enabled` / `prices.aliases` | true / {} | live prices, extra `stem = SYMBOL` names |
| `claude.enabled` / `until` / `daily_limit` / `model` | false / – / 100 / `claude-opus-5-5` | optional Claude proofreading |

## Making the persona yours

`persona.md` is plain text (Lithuanian in the example) and is read on every reply. The example persona is an
old trader who answers like a normal friend first and uses his backstory only as seasoning, uses the group's
slang where it fits, points out the thinking error behind an insult, warns a friend before a truly bad money
decision, and never admits to being a bot.

Tips from tuning it:

- **Quoted phrases get copied verbatim.** Use quotes only for lines you want him to say.
- **Write rules about himself so he can repeat them in first person**, or he says "tave" instead of "mane".
- **"Use slang in almost every reply" makes him overuse it.** "Where it fits" works better.
- After any change, run the eval below and read the replies.

## Evaluating changes

```bash
# fixed prompts in the group's style -> eval/out/<date>-<model>.md (runs on an in-memory copy of the DB)
BOTUCHA_TOKEN=offline uv run python -m botucha.evaluation persona --config config.toml
BOTUCHA_TOKEN=offline uv run python -m botucha.evaluation persona --config config.toml --model other-model
# memory search: top conversation chunk for each query in eval/prompts.toml [memory]
BOTUCHA_TOKEN=offline uv run python -m botucha.evaluation memory --config config.toml
```

The report flags replies that are empty, too long (except `/rimtai`) or written as another member.

## Models tested

Lithuanian chat with slang, on an RTX 5060 Ti 16 GB:

| Model | Result |
|---|---|
| Gemma 4 31B (uncensored, Q4) | Best persona and slang understanding, no refusals, ~7 tok/s (part runs on CPU), fine for short replies. |
| Gemma 4 26B-A4B (MoE) | ~70 tok/s, but weaker Lithuanian. |
| EuroLLM 22B | Good group feel, but refuses dark humor and copies memory verbatim. |
| EuroLLM 9B | Fast, but impersonates members and states wrong facts. |

## Security model

He has **no tools**: he cannot run commands, read files or browse. The worst a successful manipulation can
do is make him say something odd. On top of that:

- only configured chats are served; unknown groups are left right away;
- admin commands are checked by user ID;
- Ollama listens on `localhost` only;
- memory, people, slang and old chats are passed to the model as data behind explicit guards;
- `/isimink`, `/slengas`, the dashboard and learning refuse instruction-like, oversized or bot-describing
  entries, and profiles are filtered the same way;
- persona leaks are detected and regenerated;
- there is a per-user limit on direct calls and commands;
- the dashboard listens on `127.0.0.1` only, checks the `Host` header and requires a token for changes.

## Testing

Telegram and Ollama sit behind small protocols (`Outbox`, `LLM`, `Embedder`), so the whole flow is tested
with fakes (`tests/fakes.py`): no Telegram, Ollama, GPU or API key needed.

`npm run test:e2e` starts `web/e2e/server.py` (the real API and built UI over a throwaway database of invented
data, with a fake systemd) and runs Playwright with the system Chromium (`CHROMIUM_PATH` to point elsewhere).
Every page is opened in light/dark, EN/LT and desktop/phone, and fails on console errors, failed API calls,
horizontal scroll or untranslated keys; the interaction tests click through every page's controls.

## Project layout

```
botucha/
  __main__.py      aiogram adapter: polling, reactions, startup and shutdown
  app.py           the core: incoming messages, replies, learning loop, restart recovery
  trigger.py       pure decision logic: reply / react / nothing
  worker.py        debounced single reply worker
  brain.py         prompt building, generation, reply cleanup and filters
  memory.py        chunks, facts, slang, people, profiles, hybrid search
  store.py         SQLite schema, migrations and basic storage
  learn.py         idle-time fact/slang extraction and profile refresh
  commands.py      chat commands
  guard.py         instruction, bot-mention and prompt-leak detection
  spell.py         hunspell + group vocabulary invented-word check
  proofread.py     optional Claude proofreading, spelling notes, known words
  images.py        photo text forms, description cleanup, limits
  prices.py        Yahoo Finance quotes, ticker detection, cache
  backup.py        daily database copy
  restore.py       put a backup back safely
  trace.py         step traces of replies and learning runs
  webapi/          dashboard API (FastAPI)
data/hunspell/     Lithuanian hunspell dictionary (LibreOffice, BSD licence, see COPYING)
deploy/            systemd user units
web/               dashboard UI (Next.js static export, shadcn/ui, recharts, xyflow)
```

## Roadmap

- LoRA fine-tuning on the collected messages, ratings and corrections once there are a few thousand messages
  (on 16 GB VRAM this means a ~9–12B model).
- Keeping memory per chat (every fact already records the chat it came from).
- `/pataisyk word → word` to fix a single word.
- Optional explicit web search (`/ieskok`) through a self-hosted SearXNG.
- Voice messages.
