# Botucha

A local Telegram bot for the "draugų grupė" group: an old degenerate trader whose mind was uploaded into an
RTX 5060 Ti. He talks like the group, remembers conversations and learns facts and slang from the chat.
Everything runs on this PC through Ollama.

## Setup

1. **Create the bot** in Telegram with [@BotFather](https://t.me/BotFather): `/newbot`, pick a name
   (Botucha) and a username ending in `bot`.
2. **Turn off privacy mode** in BotFather: `/setprivacy` → pick the bot → **Disable**. Without this the bot
   only sees messages that mention it, so it can't learn or react to keywords. (If the bot was already in a
   group, remove it and add it again after changing this.)
3. **Token:** `cp .env.example .env` and put the token from BotFather in it. Never commit `.env`.
4. **Config:** `config.toml` already exists on this PC with the real values (`cp config.example.toml config.toml` on a fresh checkout; it is git-ignored). Check:
   - `chat_ids`: the Bot API ID of each group (a supergroup ID is `-100` followed by the `id` in the export's
     `result.json`). To add a test group, start the bot, write anything in
     the test group, and copy the ID from the log line `ignoring chat -100…`.
   - `admin_id`: your Telegram user ID (the digits of your `from_id` in the export).
   - `chat_model`: the Ollama model. Default `gemma4-31b-heretic-q4-32k`.
5. **Models:** `ollama pull bge-m3` (memory search; already done on this PC).
6. **Memory from the export:** happens automatically on first start. To do it ahead of time (takes ~3 min):
   `BOTUCHA_TOKEN=offline uv run python -m botucha.evaluation bootstrap --config config.toml`
   (already done: `botucha.db` holds 842 messages, 61 chunks, 17 facts/slang, 3 profiles).

## Run

Foreground (for trying it out):

```bash
uv run python -m botucha --config config.toml
```

As a service that starts at login and restarts on crashes:

```bash
mkdir -p ~/.config/systemd/user
ln -sf ~/Projects/botucha/deploy/botucha.service ~/.config/systemd/user/botucha.service
systemctl --user daemon-reload
systemctl --user enable --now botucha
journalctl --user -u botucha -f        # logs
```

To start at boot without logging in: `loginctl enable-linger $USER` (optional). When the PC is off, Botucha
is offline.

**Try it in a private test group first** (just you and the bot), then add him to "draugų grupė".

## Commands

| Who | Command | What |
|---|---|---|
| everyone | `/isimink <tekstas>` | store a fact |
| everyone | `/slengas <zodis> = <reiksme>` | teach slang |
| everyone | `/ka_zinai [@vardas]` | what he knows about someone (with fact numbers) |
| everyone | `/atsimeni <ko ieskot>` | find an old conversation, with links |
| everyone | `/rimtai <klausimas>` or "rimtai" in a message to him | a straight answer |
| everyone | `/tyla [min]` | no uninvited replies for N minutes (default 60) |
| everyone | reply to his message with `/gerai` or `/blogai [kodel]` | rate a reply (also 👍❤️🔥🤣😁💯 good, 👎💩🤮😴🥱 bad as reactions; reactions need him to be a group admin) |
| admin | `/pamirsk <nr>`, `/taisyk <nr> <tekstas>` | delete / correct a fact |
| admin | `/daznis <n>` | uninvited replies ~1 in n messages (default 25) |
| admin | `/isjunk`, `/ijunk` | off / on |
| admin | `/statusas` | model, memory, uptime, last error |
| admin | `/ivertinimai` | good/bad totals and the last 10 bad replies with reasons |

He always answers when mentioned, replied to, or called "botucha"; sometimes on keywords (spx, vwce,
akcijos, kripto, btc, leverage, short, parduot, nvidia, coreweave) or at random; at most one uninvited
reply or reaction per 3 minutes.

## Changing him

- **Character:** edit `persona.md` (plain Lithuanian text), then restart.
- **Style examples:** `style_examples.txt`, regenerate with
  `uv run python -m botucha.style "<export>/result.json" style_examples.txt`.
- **After any persona or model change**, run the eval and read the output in `eval/out/`:
  `BOTUCHA_TOKEN=offline uv run python -m botucha.evaluation persona --config config.toml [--model NAME]`
  and `... evaluation memory --config config.toml` for memory search.

## Development

`uv run pytest` runs the test suite (no Telegram or GPU needed).

Private data (`.env`, `config.toml`, `botucha.db`, `style_examples.txt`, `eval/out/`) is git-ignored.
