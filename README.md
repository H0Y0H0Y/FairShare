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

- **Vision** (`qwen/qwen-2.5-vl-72b-instruct`) — used whenever an image is present.
- **Text** (`meta-llama/llama-3.1-8b-instruct`) — used for text-only logs and
  in-flow adjustments, to keep token cost low.

> **Provider note.** OpenRouter exposes the OpenAI-compatible `/chat/completions`
> API (it does **not** implement the Anthropic Messages API for third-party
> models like Qwen/Llama — this was verified live). The bot therefore uses the
> OpenAI SDK (`AsyncOpenAI`) with `base_url` pointed at OpenRouter and `image_url`
> content blocks for vision. All AI access is isolated in `ai/client.py` +
> `ai/parser.py`, so swapping providers is a two-file change.

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

Send the bot an expense:

- `Dinner 700, my share 500, yours 200`
- a photo of a receipt (it reads the total)
- a receipt photo **with a caption** like `my share is 500, yours is 200`

Then Confirm / Edit / Cancel the draft.

| Command    | Description                                    |
|------------|------------------------------------------------|
| `/balance` | Who owes whom over open expenses               |
| `/recent`  | Recent open expenses                           |
| `/settle`  | Close all open expenses and reset the balance  |
| `/cancel`  | Abandon the current draft                       |
| `/help`    | Usage help                                     |
```
