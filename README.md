# FairShare 🤝

A self-hosted, AI-powered Telegram bot for tracking shared expenses between two
partners. Send it text, a receipt photo, or a photo with a caption — it parses
the expense, shows a draft to confirm, and keeps a running "who owes whom"
balance you can reset whenever you settle up.

## Features

- **Multimodal input** — plain text, a receipt image, or an image **+ caption**.
- **Confirm-before-save** — every entry is parsed into a draft you review
  (Confirm / Edit / Cancel) before it's written.
- **Custom splits** — an explicit per-partner amount per expense (not just 50/50).
- **Running balance + settle** — `/balance` shows the net; `/settle` closes open
  expenses and resets the tally (history is kept).
- **Private** — only whitelisted Telegram IDs can use it.
- **Durable** — SQLite on a persistent volume; money stored as integer cents.

## Project layout

```
app/
  main.py            entrypoint: build Application, wire handlers, run polling
  config.py          typed Settings loaded from env
  models.py          ExpenseDraft, Balance, RecentExpense, OpenSummary
  bot/               conversation state machine, commands, keyboards, views
  ai/                OpenRouter client, model routing, prompts, parser
  db/                schema.sql, connection lifecycle, repository queries
  utils/money.py     cents <-> human amount helpers
data/                SQLite DB (mounted volume)  ← gitignored
```

## Models

Called via OpenRouter; configurable with `VISION_MODEL` / `TEXT_MODEL` (defaults
in [`.env.example`](.env.example)):

- **Vision** — `qwen/qwen-2.5-vl-72b-instruct` (used when an image is present).
- **Text** — `openai/gpt-4o-mini` (text-only logs and in-flow edits).

## Setup

1. Configure env:
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

3. Tests:
   ```bash
   pip install -r requirements-dev.txt && pytest
   ```

## Docker

```bash
docker compose up --build
```

The DB lives at `/app/data/expenses.db`. Mount a persistent volume at `/app/data`
so it survives redeploys. Run a single instance (Telegram allows one poller per
token).

## Usage

**Private chat** — send the expense directly:

- `Lunch 450, my share 250` (the other share is derived)
- a receipt photo, or a photo captioned `my share is 500, yours is 200`

**Group** — prefix with `/add` (leave Telegram Group Privacy on):

- `/add Lunch 450, my share 250`
- a photo captioned `/add …`

The bot shows a draft — tap **✅ Confirm**, **✏️ Edit**, or **❌ Cancel**. To edit,
send a correction (e.g. `my share 400`) or a new receipt photo; **in a group,
_reply_ to the bot's message** so it reaches the bot under Group Privacy.

| Command    | Description                                          |
|------------|------------------------------------------------------|
| `/add`     | Log an expense in a group (e.g. `/add Taxi 300`)     |
| `/summary` | Open transactions, per-partner totals, and who owes  |
| `/balance` | Net: who owes whom over open expenses                |
| `/recent`  | Recent open expenses                                 |
| `/settle`  | Close all open expenses and reset the balance        |
| `/cancel`  | Abandon the current draft                            |
| `/help`    | Usage help                                           |

`/settle` doesn't delete rows — it marks open expenses closed and starts a fresh
tally, so history is retained.
