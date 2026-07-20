# CLAUDE.md

Guidance for working in this repo. Read alongside `README.md` (user-facing) and
`DEPLOY.md` (hosting).

## What this is

FairShare is a self-hosted Telegram bot for tracking shared expenses between
**exactly two** partners. A message (text, receipt photo, or photo+caption) is
parsed by an LLM into a draft, the user confirms it via inline buttons, and it's
written to a SQLite ledger. `/settle` closes the open expenses and resets the
running balance.

The two-partner assumption is baked in everywhere (partner ids are the fixed
literals `1` and `2`, seeded from env). Don't generalize to N partners without a
deliberate, repo-wide change.

## Commands

```bash
# run locally (needs a populated .env — see .env.example)
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
DB_PATH=./data/expenses.db python -m app.main

# tests (fast, no network — the AI layer is not exercised in tests)
pip install -r requirements-dev.txt
pytest                 # or: pytest -q
pytest tests/test_repository.py -k settle
```

`pytest.ini` sets `asyncio_mode = auto`, so `async def test_*` needs no
`@pytest.mark.asyncio` (though some files add `pytestmark` anyway).

## Architecture (layers, top to bottom)

- `app/main.py` — entrypoint. Builds the `Application`, wires handlers into two
  handler groups, opens/closes the DB in `post_init`/`post_shutdown`, runs long
  polling. **New commands must be registered here** (and usually added to
  `_COMMANDS` for the Telegram command menu).
- `app/bot/` — the Telegram layer.
  - `conversation.py` — the expense-entry `ConversationHandler` state machine
    (`on_input → CONFIRMING → ADJUSTING`). Drafts live only in
    `context.user_data` until confirmed; the DB is never touched mid-flow.
  - `handlers.py` — stateless commands (`/balance`, `/summary`, `/recent`,
    `/settle`, `/delete`, `/help`) and their callback-query handlers.
  - `views.py` — all message rendering (Telegram **HTML** parse mode). Keep
    presentation here, not in handlers. `render_balance` is the canonical
    "who owes whom" string.
  - `keyboards.py` — inline keyboards + `cf:` callback-data tokens.
- `app/ai/` — LLM parsing. `parser.py` (`parse_expense`, `merge_expense`) is the
  public API; `router.py` picks vision vs text model; `prompts.py` builds system
  prompts; `client.py` is the OpenAI-SDK client pointed at OpenRouter.
- `app/db/` — `repository.py` (all SQL, operates on an `aiosqlite.Connection`,
  the testable seam), `database.py` (connection lifecycle + schema init +
  partner seeding), `schema.sql` (idempotent, applied on every boot).
- `app/models.py` — dataclasses shared across layers (`ExpenseDraft`, `Balance`,
  `RecentExpense`, `OpenSummary`, `LineItem`).
- `app/config.py` — the single typed `Settings` object (`get_settings()`,
  `lru_cache`d). Read config through it, never `os.environ` directly.
- `app/utils/money.py` — cents ⇄ human amount helpers.

## Conventions and invariants (important)

- **Money is integer cents everywhere** past the parsing boundary. Never carry
  floats through the ledger. Use `to_cents` / `format_cents` / `split_even` from
  `app/utils/money.py`. A share invariant is enforced on insert: shares must
  re-sum to the total (`ExpenseDraft.is_balanced`,
  `insert_expense_with_shares`).
- **Partner identity has two forms**: internal `partner_id` (1/2) and Telegram
  user id. Convert via `Settings.partner_by_id` / `partner_by_telegram_id` /
  `other_partner`. `allowed_telegram_ids` is the whitelist.
- **Open vs settled**: an expense is *open* while `settlement_id IS NULL`.
  `/settle` stamps every open row with a new settlement id (history is kept, rows
  are never deleted). Balances and summaries are computed over open expenses
  only.
- **`Balance` is signed from partner 1's perspective** (`net_cents > 0` → p2 owes
  p1). Use `.creditor_id`, `.debtor_id`, `.magnitude_cents` rather than
  re-deriving the sign. Only the creditor may confirm a settlement
  (`Balance.may_confirm_settle`).
- **Authorize inline-button taps in the callback**, not just the command. Buttons
  are visible to everyone in a group chat, so any callback that mutates state
  re-checks `query.from_user.id` (see `settle_callback` / `delete_callback`).
- **Rendering is HTML parse mode**; escape user/partner-derived text with
  `html.escape` when interpolating into a message.
- **Group support**: entries in a group are prefixed with `/add`; the conversation
  strips that prefix. Group Privacy means the bot only sees `/add`, its own
  messages' replies, and captions starting with `/add` — keep that working.
- **The AI layer is non-deterministic and network-bound.** `parser.py` retries
  transient provider failures and repairs non-JSON replies once. Some
  corrections (explicit renames) are handled deterministically to override the
  model — see `_explicit_description`. Tests do **not** call the network; don't
  add tests that hit OpenRouter.

## Testing notes

- `tests/conftest.py` injects a minimal env before app modules load and uses
  `DB_PATH=:memory:`. Repository tests spin up a fresh in-memory `Database`.
- Handler/callback functions aren't unit-tested directly. When adding logic to a
  handler, prefer extracting a pure, testable helper (e.g. a method on a model,
  like `Balance.may_confirm_settle`) and unit-test that.

## Gotchas

- One poller per bot token — run a single instance.
- `CURRENCY_SYMBOL` may be empty; `format_cents` handles that.
- Callback-data is limited to 64 bytes; tokens are deliberately short
  (`cf:`, `st:`, `del:`).
- Don't remove the `bool` rejection in `to_cents` (bool is an int subclass).
