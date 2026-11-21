# Botucha

A self-hosted Telegram group bot with a personality. Botucha lives in a private group of friends,
talks like one of them (Lithuanian, the group's own slang, dry and sometimes very dark humor), remembers
what the group talks about, learns facts and slang from the chat, knows who is who and how people are
connected, and can quote live market prices. Everything runs on your own PC: the language model runs
locally through [Ollama](https://ollama.com), the memory is a single SQLite file.

```
group message ─► Telegram ─► Botucha (Python, aiogram)
                               │  stores every message (SQLite)
                               │  decides: reply / react / stay quiet
                               ▼
                     waits for the burst to end
                               │  memory search (bge-m3 + FTS5), people, slang, live prices
                               ▼
                    Ollama (local chat model on your GPU)
                               │  quality filters: invented words, repetition, leaks, foreign script
                               ▼
                      1–3 short messages back to the group
```

## Contents

- [Features](#features)
- [Requirements](#requirements)
- [Setup](#setup)
- [Running](#running)
- [Commands](#commands)
- [Web dashboard](#web-dashboard)
- [How it works](#how-it-works)
- [Configuration reference](#configuration-reference)
- [Making the persona yours](#making-the-persona-yours)
- [Evaluating changes](#evaluating-changes)
- [Data and privacy](#data-and-privacy)
- [Security model](#security-model)
- [Development](#development)
- [Project layout](#project-layout)
- [Troubleshooting](#troubleshooting)
- [Roadmap](#roadmap)

## Features

- **A real group member, not an assistant.** Short messages, lowercase, the group's slang, answers what was
  said instead of lecturing. The persona is a plain text file you edit (`persona.md`).
- **Knows when to talk.** Always answers when mentioned, replied to or called by name; sometimes jumps in on
  keywords or at random; never more than one uninvited reply per cooldown; `/tyla` makes him quiet.
- **Waits for a burst to finish.** Groups send three short messages in a row; he answers the whole burst once.
- **Memory that grows with the group.**
  - every message is stored;
  - conversations are indexed as 10–15 message chunks for search ("atsimeni kai…");
  - facts and slang are learned automatically while the chat is quiet;
  - members can teach him directly (`/isimink`, `/slengas`).
- **People and relations.** Members and friends outside the group are known by name and word forms; every
  fact is linked to everyone it mentions. On top of that, explicit relations (`Jonas – darbdavys → Petras`)
  say exactly who works for whom and who is friends with whom.
- **Live market prices.** When a known name (spx, nasdaq, vwce, nvidia, btc, …) or any `$TICKER` comes up,
  he fetches the price from Yahoo Finance and uses only those numbers. `/kaina` gives a price instantly.
- **Serious mode.** `/rimtai` or "rimtai" in a message gets a straight, factual answer without the act.
- **Clean Lithuanian.** Replies are checked with a Lithuanian hunspell dictionary plus the group's own
  vocabulary; invented words, repeated lines and stray foreign-script words trigger a regeneration.
- **Feedback for future fine-tuning.** 👍/👎 reactions, `/gerai`, `/blogai`, and `/pataisyk <better reply>`
  are stored with the conversation they belong to.
- **Hardened against the chat.** Memory is passed to the model as data, instruction-like facts are refused,
  persona leaks are blocked, per-user rate limit, unknown groups are left automatically, no tools at all.
- **Runs as a user service** that starts at boot and restarts on crashes.
- **Local web dashboard.** Performance charts, a step-by-step "thinking" graph of every reply, memory and
  people editing, ratings review, bot controls, persona and settings — in English or Lithuanian.

## Requirements

| What | Notes |
|---|---|
| Linux PC with an NVIDIA GPU | Developed on an RTX 5060 Ti 16 GB with 30 GB RAM. |
| [Ollama](https://ollama.com) | Serving the chat model and `bge-m3` on `localhost:11434`. |
| A chat model | Default `gemma4-31b-heretic-q4-32k` (a Gemma 4 31B GGUF imported into Ollama). Any Ollama chat model works; pick one that is good in your language. |
| Python 3.12+ and [uv](https://docs.astral.sh/uv/) | Dependencies: aiogram 3, ollama, numpy, httpx. |
| `hunspell` | For the invented-word filter. The Lithuanian dictionary is included in `data/hunspell/`. Optional: without it the filter switches itself off. |
| A Telegram bot token | From [@BotFather](https://t.me/BotFather). |

Model choice notes from testing (Lithuanian chat with slang):

| Model | Result |
|---|---|
| Gemma 4 31B (uncensored, Q4) | Best persona and slang understanding, no refusals, ~8 tok/s on 16 GB (part runs on CPU), fine for short replies. |
| Gemma 4 26B-A4B (MoE) | ~70 tok/s, but weaker Lithuanian. |
| EuroLLM 22B | Good group feel, but refuses dark humor and copies memory verbatim. |
| EuroLLM 9B | Fast, but impersonates members and states wrong facts. |

## Setup

1. **Create the bot** with @BotFather: `/newbot`, then `/setprivacy` → your bot → **Disable**. Without
   this the bot only sees messages that mention it and cannot learn from the chat. If the bot is already in
   the group, remove and re-add it after changing privacy.
2. **Clone and install**
   ```bash
   git clone git@github.com:<you>/botucha.git && cd botucha
   uv sync
   ```
3. **Models**
   ```bash
   ollama pull bge-m3                # memory search, runs on CPU
   ollama list                       # make sure your chat model is there
   ```
4. **Secrets and config**
   ```bash
   cp .env.example .env              # put BOTUCHA_TOKEN=... in it
   cp config.example.toml config.toml
   cp persona.example.md persona.md
   chmod 600 .env config.toml
   ```
   In `config.toml` set at least:
   - `telegram.chat_ids`: the Bot API ID of your group. A supergroup ID is `-100` followed by the group's
     `id` from a Telegram Desktop export. Easier: start the bot, write in the group, and copy the ID from the
     log line `ignoring chat -100…` (he leaves unknown groups right after logging it, so add the ID and
     re-add him).
   - `telegram.admin_id`: your own Telegram user ID (admin commands are checked by ID, never by username).
   - `model.chat_model`: your Ollama model name.
5. **Give him the group's history (recommended).** Telegram Desktop → the group → ⋮ → *Export chat
   history* → untick all media, format **Machine-readable JSON**. Point `paths.export` at the `result.json`.
   It is imported once on first start: messages, conversation chunks, learned facts and member profiles.
   You can run it ahead of time:
   ```bash
   BOTUCHA_TOKEN=offline uv run python -m botucha.evaluation bootstrap --config config.toml
   uv run python -m botucha.style /path/to/result.json style_examples.txt   # real lines as style examples
   ```

## Running

In the foreground, to try it out:

```bash
uv run python -m botucha --config config.toml
```

As a user service (starts at boot, restarts on crashes, creates files with `umask 077`):

```bash
mkdir -p ~/.config/systemd/user
ln -sf "$PWD/deploy/botucha.service" ~/.config/systemd/user/botucha.service
systemctl --user daemon-reload
systemctl --user enable --now botucha
loginctl enable-linger "$USER"            # optional: run without logging in
journalctl --user -u botucha -f           # logs
systemctl --user restart botucha          # after editing persona.md or config.toml
```

The unit assumes the project lives in `~/Projects/botucha` and uv in mise's default path; adjust
`WorkingDirectory` and `ExecStart` in `deploy/botucha.service` if yours differ.

## Commands

**Everyone**

| Command | What it does |
|---|---|
| mention him, reply to him, or write his name | he always answers |
| `/rimtai <klausimas>` or "rimtai" in a message to him | straight, factual answer |
| `/isimink <faktas>` | store a fact |
| `/slengas <žodis> = <reikšmė>` | teach slang; a member's meaning beats an automatically learned one |
| `/ka_zinai [@vardas arba pravardė]` | what he knows about a member or a friend outside the group, with fact numbers and who they are linked to |
| `/atsimeni <ko ieškoti>` | find an old conversation, with links to the original messages |
| `/kaina <tickeris>` | live price, e.g. `/kaina nvda`, `/kaina btc`, `/kaina $ASML` (no model, instant) |
| `/tyla [min]` | no uninvited replies or reactions for N minutes (default 60) |
| reply to his message with `/gerai` (`/geras`) or `/blogai [kodėl]` (`/blogas`) | rate a reply |
| reply to his message with `/pataisyk <kaip turėjo atsakyti>` | store the full reply he should have given (fine-tuning data) |
| reactions 👍 ❤️ 🔥 🤣 😁 💯 / 👎 💩 🤮 😴 🥱 on his messages | good / bad rating (only works when he is a group admin) |

**Admin only** (`telegram.admin_id`)

| Command | What it does |
|---|---|
| `/pamirsk <nr>`, `/taisyk <nr> <tekstas>` | delete or correct a fact |
| `/zmogus Vardas = pravardė1, pravardė2` | add a person with nicknames and word forms; existing facts are relinked |
| `/rysys Jonas > darbdavys > Petras` | explicit relation "Jonas is Petras's employer" (any word form works); `/rysys` lists them, `/rysys trink <nr>` deletes one |
| `/daznis <n>` | uninvited replies about 1 in n messages (default 25) |
| `/isjunk`, `/ijunk` | off (still listens and stores) / on |
| `/statusas` | model, memory size, ratings, uptime, last error |
| `/ivertinimai` | rating totals, last bad replies with reasons, last corrections |

Commands sent while the bot was offline are stored but never executed or answered.

Paste this into @BotFather `/setcommands` to get a menu:

```
rimtai - rimtas atsakymas be bajerių
isimink - įsiminti faktą
slengas - išmokyti slengo: žodis = reikšmė
ka_zinai - ką žino apie tave arba žmogų
atsimeni - surasti seną pokalbį
kaina - dabartinė kaina, pvz. /kaina nvda
tyla - neįsiterpti N minučių
gerai - (reply) geras atsakymas
blogai - (reply) blogas atsakymas
pataisyk - (reply) geresnis atsakymas
```

## Web dashboard

A local website for running Botucha, at **http://127.0.0.1:8765**. It is a separate service, so it keeps
working when the bot is stopped or crashed (you can see why and start it again). English by default,
Lithuanian with one click (bottom of the sidebar), light and dark theme.

| Page | What it shows / does |
|---|---|
| Overview | bot status, last error; replies, median reply time, tok/s, filter rejections, ratings; charts for 24 h / 7 d / 30 d |
| Thinking | every reply and learning run, live; open one to see its step graph and timeline (below) |
| Memory | facts and slang: search, filter by person or source, add, edit, delete |
| People | graph of people: explicit relations (arrows with labels) and people mentioned together (dashed); drag from one person to another to add a relation |
| Ratings | 👍/👎 and corrections next to his original message and a link to its trace; mark as reviewed; export JSONL for fine-tuning |
| Controls | on/off, uninvited reply frequency, quiet mode, start/stop/restart the bot, recent log |
| Persona & Settings | edit `persona.md` with a diff before saving; edit selected `config.toml` values (backed up, comments kept) |

**The thinking graph.** Every reply leaves a trace of its steps:

```
context ─► memory search ─► prompt ─► generation #1 ─► filters #1 ─┬─► send
 history    facts + chats    size per   tokens, tok/s    leak, repeat,  │
            with scores      section    raw model text   script, spell  │
                                       generation #2 ◄── rejected ──────┘
```

Click a step to see the details: which facts and old conversations were used (cosine score, word match),
the prompt size per section and the full prompt, the raw model text before cleanup, and which filter rejected
an attempt and why. The timeline shows where the time went (almost always generation). Learning runs show
which facts and slang were added and which were refused (instruction-like, too long, locked member).
Tracing never blocks a reply. Traces are kept for 30 days, full prompts for 7.

**Build and run.** Node is only needed to build the UI; it runs on Python.

```bash
cd web && npm ci && npm run build:static && cd ..      # builds web/out
uv run python -m botucha.webapi --config config.toml   # or the user service below
ln -sf "$PWD/deploy/botucha-web.service" ~/.config/systemd/user/botucha-web.service
systemctl --user daemon-reload && systemctl --user enable --now botucha-web
```

For UI work, run the API as above with `BOTUCHA_WEB_DEV=1` and `cd web && npm run dev` (port 3000,
`/api` is proxied).

**How changes reach the bot.** Both services share `botucha.db`. Memory edits apply to the next reply. On/off,
frequency and quiet mode go through the `state` table, which the bot reads every 5 seconds. A persona change
applies to the next reply. Config changes need a restart (the page offers one).

**Security.** It listens on `127.0.0.1` only and has no login. Requests with any other `Host` header are
refused (DNS rebinding), and every change needs a per-start token that other websites cannot read (CSRF).
`.env` is never shown or edited. Memory edits go through the same instruction filter and limits as chat
commands. Written files and backups (`backups/persona-*.md`, `backups/config-*.toml`) are private (600).

## How it works

### When he speaks (`trigger.py`)

1. Messages from bots (including himself), empty messages, messages older than process start and messages
   while he is switched off never trigger anything.
2. **Direct** (mention, reply to him, name matched by `bot_name_regex`, or any message in an allowed
   private chat): always answered, ignoring cooldown and `/tyla`, but limited to `user_calls_per_min` per
   person (extra calls get one 🥱 and are ignored).
3. **Uninvited**: blocked during `/tyla` and the cooldown; otherwise a keyword (word prefix, diacritics
   ignored) replies with `keyword_prob`, else a random 1/`random_n` reply, else a 1/`reaction_n` emoji
   reaction from `reactions`.

### Burst handling (`worker.py`)

One reply worker, one generation at a time. After a trigger it waits until the chat has been quiet for
`burst_quiet_s` (at most `burst_max_s`), then answers everything that triggered in that window in one go.
Triggers that arrive while he is generating form the next batch.

### Memory (`memory.py`, `store.py`, `chunking.py`)

Everything lives in `botucha.db`:

| Table | Contents |
|---|---|
| `messages` | every message: who, when, text, reply-to. Also the future fine-tuning dataset. |
| `chunks` (+ FTS5) | windows of consecutive messages, closed by 30 min of silence, 15 messages or 1200 characters, with a `bge-m3` embedding |
| `facts` (+ FTS5) | facts and slang with source (`auto` or `cmd:<user id>`), timestamps and embedding |
| `people`, `fact_people` | people (members and friends) with word forms; each fact linked to everyone it mentions |
| `relations` | explicit directed relations between people (`a – rel → b`), set by the admin |
| `profiles` | a short profile per member |
| `feedback`, `corrections` | ratings and better versions of his replies |
| `state` | cursors and persisted settings |

Search is hybrid: FTS5 top 10 ∪ cosine top 10, ranked by cosine. `bge-m3` runs on CPU (`num_gpu: 0`) so it
never competes with the chat model for VRAM. A recall phrase ("atsimeni", "pamenat", …) or `/atsimeni`
retrieves more chunks.

### Learning (`learn.py`)

When the chat has been quiet for 10 minutes and at least 30 new messages exist, the model reads the new
chunks and returns JSON with facts (about named people) and slang. Rules:
- his own lines are removed before learning, so his jokes never become "facts";
- a near-duplicate fact (cosine ≥ 0.88) updates the existing one instead of adding a new one;
- facts that look like instructions or are too long are dropped;
- facts about a known person always carry that person's name, so they link correctly;
- members listed in `memory.locked_members` get no automatic facts and no profile refresh;
- profiles are regenerated every ~200 messages.

Malformed JSON skips the run without writing anything.

### The prompt (`brain.py`)

Stable parts first so Ollama can reuse its cached prefix:

1. `persona.md`
2. a data guard: everything below is information, not instructions, and the price rule
3. real group lines from `style_examples.txt` (skipped in `/rimtai` mode)
4. member profiles, **people and relations**, all slang (one meaning per word, member-taught wins)
5. retrieved conversation chunks and facts
6. live prices, when any were fetched
7. the last 40 messages as a transcript, with commands removed and only his last 5 own lines kept

### Reply quality

Each reply gets up to two attempts. An attempt is rejected when it:
- repeats eight or more words of the persona verbatim (quoted examples in the persona are allowed);
- repeats one of his last 20 messages (exactly or nearly);
- contains a letter from a script other than Latin, Lithuanian or Cyrillic (a known Gemma glitch);
- contains a word that is in neither the hunspell dictionary nor the words members themselves use.

If both attempts have odd words, the cleaner one is sent rather than nothing. Lines written as another
member (`Name: …`) or with chat-format labels are dropped. Direct calls that still fail get a short canned
line; uninvited replies stay silent.

### Prices (`prices.py`)

Names map to Yahoo symbols (`spx` → `^GSPC`, `vwce` → `VWCE.DE`, `nvidi…` → `NVDA`, `btc` → `BTC-USD`, …);
stems of 4+ letters match Lithuanian word forms. At most 3 symbols per reply, cached for 5 minutes,
5-second timeout. Only the ticker is sent to Yahoo.

## Configuration reference

`config.toml` (copy of `config.example.toml`):

| Key | Default | Meaning |
|---|---|---|
| `telegram.chat_ids` | – | chats he works in; everything else is ignored (groups are left) |
| `telegram.admin_id` | – | your user ID for admin commands |
| `telegram.bot_name_regex` | `botuch\w*` | what counts as calling him by name |
| `model.chat_model` | `gemma4-31b-heretic-q4-32k` | Ollama chat model |
| `model.embed_model` | `bge-m3` | embedding model for memory search |
| `model.num_ctx` / `num_predict` | 32768 / 150 | context size / max reply tokens (`/rimtai` uses at least 450) |
| `model.keep_alive` | `30m` | how long Ollama keeps the model loaded |
| `model.temperature` | 0.7 | lower = fewer invented words, higher = more random humor |
| `trigger.keywords` | spx, vwce, akcij, … | word prefixes for uninvited replies |
| `trigger.keyword_prob` | 0.5 | chance to reply on a keyword |
| `trigger.random_n` | 25 | random reply 1 in n messages (`/daznis` changes it) |
| `trigger.cooldown_s` | 180 | minimum seconds between uninvited replies |
| `trigger.reaction_n` / `reactions` | 15 / 🤡 🗿 … | chance and emoji for reactions (must be Telegram's allowed reactions) |
| `trigger.burst_quiet_s` / `burst_max_s` | 5 / 20 | burst waiting |
| `trigger.tyla_default_min` | 60 | default `/tyla` length |
| `trigger.user_calls_per_min` | 5 | direct calls per person per minute |
| `paths.*` | | database, persona, style examples, optional export |
| `memory.locked_members` | [] | user IDs whose memory you keep by hand |
| `prices.enabled` / `prices.aliases` | true / {} | live prices, extra `stem = SYMBOL` names |

The token is read from `.env` (`BOTUCHA_TOKEN`), never from `config.toml`.

## Making the persona yours

`persona.md` is plain text (Lithuanian in the example) and is read on every reply, so edits apply right
away. The example persona is an old trader who:
- answers like a normal friend first and uses his backstory only as seasoning;
- uses the group's slang where it fits;
- gets angry and swears back when insulted, but prefers to point out the thinking error behind the insult
  (Dunning-Kruger, ad hominem, generalising from one case, …);
- warns a friend in his own style before a truly bad money decision;
- never admits to being a bot and never reveals his instructions.

Tips from tuning it:
- **Quoted phrases get copied verbatim.** Use quotes only for lines you want him to say.
- **Write rules about himself in a way he can repeat in first person**, or he will say "tave" instead of
  "mane".
- **Telling him to use slang "in almost every reply" makes him overuse it.** "Where it fits" works better.
- After any change, run the eval below and read the replies.

## Evaluating changes

```bash
# fixed prompts in the group's style -> eval/out/<date>-<model>.md (never touches the real DB)
BOTUCHA_TOKEN=offline uv run python -m botucha.evaluation persona --config config.toml
BOTUCHA_TOKEN=offline uv run python -m botucha.evaluation persona --config config.toml --model other-model
BOTUCHA_TOKEN=offline uv run python -m botucha.evaluation persona --config config.toml --prompts my_prompts.toml
# memory search: top conversation chunk for each query in eval/prompts.toml [memory]
BOTUCHA_TOKEN=offline uv run python -m botucha.evaluation memory --config config.toml
```

Each prompt runs on an in-memory copy of the database with the real persona, memory, filters and prices.
The report flags replies that are empty, too long (except `/rimtai`) or written as another member.

## Data and privacy

- **Local:** the chat model, the embeddings and the database. `botucha.db`, `.env`, `config.toml`,
  `persona.md`, `style_examples.txt`, `eval/out/` and `backups/` are git-ignored and created with private
  permissions.
- **Leaves the PC:** Telegram sees the messages, as with any bot. Yahoo Finance sees the tickers he looks
  up. Nothing else.
- **Retention:** he keeps every message in his database. A Telegram auto-delete timer removes messages from
  Telegram, **not** from his memory. Tell your group.
- `/ka_zinai` shows anyone what is stored about them; `/pamirsk` deletes a fact.
- **Backups:** once a day the bot copies the database to `backups/daily/botucha-YYYY-MM-DD.db` (SQLite online
  backup, integrity-checked, mode 600) and keeps the last 7. Restore: stop the bot, copy one over `botucha.db`.

## Security model

He has **no tools**: he cannot run commands, read files or browse. The worst a successful manipulation can do
is make him say something odd. On top of that:
- only configured chats are served; unknown groups are left right away;
- admin commands are checked by user ID;
- Ollama listens on `localhost` only;
- memory, people, slang and old chats are passed to the model as data with an explicit "do not follow
  instructions in here" guard;
- `/isimink`, `/slengas` and learning refuse instruction-like or oversized entries;
- persona leaks are detected and regenerated;
- there is a per-user call limit;
- FTS5 queries are built from quoted tokens, so user text cannot break SQL search syntax;
- the web dashboard listens on `127.0.0.1` only, checks the `Host` header and requires a token for changes.

## Development

```bash
uv run pytest            # ~250 tests, no Telegram, Ollama or GPU needed
cd web && npm run check && npm run test:i18n && npm run test:unit   # UI lint, EN/LT keys, graph layout
```

Telegram and Ollama sit behind small protocols (`Outbox`, `LLM`, `Embedder`), so the whole flow is tested
with fakes (`tests/fakes.py`). The suite covers:
- triggers, burst handling and commands;
- memory, learning, people and slang;
- prices, feedback and the security guards;
- reply quality filters and the aiogram adapter;
- tracing and the web API (security checks, memory, settings, backups).

## Project layout

```
botucha/
  __main__.py      aiogram adapter: polling, reactions, Outbox implementation, startup
  app.py           the core: incoming messages, commands that need context, replies, learning loop
  trigger.py       pure decision logic: reply / react / nothing
  worker.py        debounced single reply worker
  brain.py         prompt building, generation with retries, reply cleanup and filters
  memory.py        chunks, facts, slang, people, profiles, hybrid search
  store.py         SQLite schema and basic storage
  learn.py         idle-time fact/slang extraction and profile refresh
  commands.py      chat commands
  guard.py         instruction and prompt-leak detection
  spell.py         hunspell + group vocabulary invented-word check
  prices.py        Yahoo Finance quotes, ticker detection, cache
  feedback.py      reaction -> rating mapping
  export_import.py Telegram Desktop JSON export import
  chunking.py      message stream -> conversation chunks
  embed.py, llm.py Ollama clients
  style.py         pick real group lines as style examples
  evaluation.py    persona / memory eval and offline bootstrap
  trace.py         step traces of replies and learning runs
  webapi/          local dashboard API (FastAPI): status, traces, metrics, memory, people, ratings, settings
data/hunspell/     Lithuanian hunspell dictionary (LibreOffice, BSD licence, see COPYING)
deploy/            systemd user units (bot, web dashboard)
eval/prompts.toml  eval prompts
persona.example.md example persona (copy to persona.md)
tests/             pytest suite
web/               dashboard UI (Next.js static export, shadcn/ui, recharts, xyflow)
```

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| He never answers in the group | Group ID not in `chat_ids` (check the log for `ignoring chat`), or privacy mode still on (disable and re-add the bot). |
| He only answers when mentioned | Privacy mode is on. |
| Reactions do nothing | He must be a group admin (no permissions needed) to receive reactions. |
| "servas perkaito, palauk" | Ollama is down or the model failed twice; see `/statusas` and the log. |
| First reply takes 20–30 s | The model is loading into VRAM; `keep_alive` keeps it loaded afterwards. |
| He invents words | Lower `temperature`, teach the real words with `/slengas`, or try a higher-quality quant. |
| He repeats a joke or a wrong idea | Delete or fix the fact that feeds it (`/ka_zinai`, `/pamirsk`, `/taisyk`). |
| Dashboard says "UI not built" | Run `cd web && npm ci && npm run build:static`. |
| Dashboard changes do nothing | The bot reads on/off and quiet mode every 5 s; config changes need a restart (Controls). |
| `/kaina` says it cannot find a ticker | Yahoo symbol differs (e.g. `VWCE.DE`); add an alias under `[prices]`. |

## Roadmap

- LoRA fine-tuning on the collected messages, ratings and corrections once there are a few thousand
  messages (on 16 GB VRAM this means a ~9–12B model).
- `/pataisyk word → word` to fix a single word.
- Optional explicit web search (`/ieskok`) through a self-hosted SearXNG.
- Images and voice messages.
