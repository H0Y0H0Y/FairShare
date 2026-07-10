# FairShare 🤝

A self-hosted, AI-powered Telegram bot for tracking shared expenses between two
partners. Send it text, a receipt photo, or a photo with a caption — it parses
the expense, shows you a draft to confirm, and keeps a running "who owes whom"
balance you can reset whenever you settle up.

## Features

- **Multimodal input** — plain text, a receipt image, or an image **+ caption**
  bundled into a single AI request.
- **Confirm-before-save state machine** — every entry is parsed into a draft you
  review (Confirm / Edit / Cancel) before it touches the database, so concurrent
  messages can't corrupt a transaction.
- **Custom splits** — an explicit per-partner breakdown per expense (not just
  50/50).
- **Running balance + settle** — `/balance` shows the net; `/settle` closes all
  open expenses and resets the tally to zero (history is retained).
- **Private** — only whitelisted Telegram IDs can use it.
- **Durable** — local SQLite on a persistent Docker volume; money stored as
  integer cents (no float drift).

## Architecture

```
app/
  main.py            entrypoint: build Application, wire handlers, run polling
  config.py          typed Settings loaded from env
  models.py          ExpenseDraft, Balance, RecentExpense
  bot/               conversation state machine, commands, keyboards, views
  ai/                OpenRouter client, model routing, prompts, parser
  db/                schema.sql, connection lifecycle, repository queries
  utils/money.py     cents <-> human amount helpers
data/                SQLite DB (mounted volume)  ← gitignored
```

Layering: `bot → ai + db → utils`. All AI access is isolated behind
`ai/parser.py`, so swapping the OpenRouter SDK is a one-module change.

## Models

Both are configurable via env (`VISION_MODEL` / `TEXT_MODEL`) — see
[`.env.example`](.env.example) for the current defaults. As of now:

- **Vision** — `qwen/qwen-2.5-vl-72b-instruct`, used whenever an image is present
  (receipts, photo + caption).
- **Text** — `openai/gpt-4o-mini`, used for text-only logs and in-flow
  adjustments. It's cheap, extracts custom splits reliably, and is served
  first-party by OpenAI (no multi-provider routing).

> **Why gpt-4o-mini for text?** Two cheaper open models were tried first and
> rejected during live testing: `meta-llama/llama-3.1-8b-instruct` inconsistently
> dropped explicit splits (logging 50/50 when the user said 500/200), and
> `qwen/qwen-2.5-72b-instruct` was flaky under OpenRouter's provider
> rate-limits/fallbacks. `gpt-4o-mini` was reliable across the board.

> **Provider note.** OpenRouter exposes the OpenAI-compatible `/chat/completions`
> API (it does **not** implement the Anthropic Messages API for third-party
> models like Qwen/Llama — verified live). The bot therefore uses the OpenAI SDK
> (`AsyncOpenAI`) with `base_url` pointed at OpenRouter and `image_url` content
> blocks for vision. All AI access is isolated in `ai/client.py` +
> `ai/parser.py`, so swapping providers/SDKs is a two-file change. The parser
> also retries transient upstream failures (rate limits, bad-provider fallbacks).

## Setup

1. Copy env and fill it in:
   ```bash
   cp .env.example .env
   # set TELEGRAM_BOT_TOKEN, both PARTNER_* ids/names, OPENROUTER_API_KEY
   ```
   Get each partner's numeric Telegram ID from [@userinfobot](https://t.me/userinfobot).

2. Run locally:
   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   DB_PATH=./data/expenses.db python -m app.main
   ```

3. Run the tests:
   ```bash
   pip install -r requirements-dev.txt
   pytest
   ```

## Docker / Dokploy

```bash
docker compose up --build
```

The database lives at `/app/data/expenses.db` inside the container. On Dokploy,
attach a **persistent volume** (or host path) to `/app/data` so the ledger
survives redeploys. The container runs as a non-root user that owns `/app/data`.

## Usage

**In a private chat** with the bot, just send the expense:

- `Lunch 450, my share 250` (the other share is derived)
- a photo of a receipt (it reads the total)
- a receipt photo **with a caption** like `my share is 500, yours is 200`

**In a group**, prefix it with `/add` (works with Telegram Group Privacy left on):

- `/add Lunch 450, my share 250`
- a photo captioned `/add …`

Either way the bot shows a draft — tap **✅ Confirm**, **✏️ Edit**, or **❌ Cancel**.
To edit, send your correction (e.g. `my share 400`); **in a group you must _reply_
to the bot's message** so it reaches the bot under Group Privacy.

| Command    | Description                                          |
|------------|------------------------------------------------------|
| `/add`     | Log an expense in a group (e.g. `/add Taxi 300`)     |
| `/summary` | Open transactions, per-partner totals, and who owes  |
| `/balance` | One-line net: who owes whom over open expenses       |
| `/recent`  | Recent open expenses                                 |
| `/settle`  | Close all open expenses and reset the balance to zero|
| `/cancel`  | Abandon the current draft                            |
| `/help`    | Usage help                                           |

`/settle` never deletes rows — it stamps open expenses as closed (`settlement_id`)
and starts a fresh tally, so history is retained and fully auditable.
