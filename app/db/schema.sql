-- FairShare schema. Idempotent: safe to run on every boot.
-- Money is stored in integer minor units (cents).

PRAGMA journal_mode = WAL;   -- robust concurrent reads on a mounted volume
PRAGMA foreign_keys = ON;

-- The two fixed partners (ids 1 and 2). Seeded/updated from env on init.
CREATE TABLE IF NOT EXISTS partners (
    id           INTEGER PRIMARY KEY,        -- 1, 2
    telegram_id  INTEGER UNIQUE,             -- for sender -> partner resolution
    name         TEXT NOT NULL
);

-- A settlement event ("we squared up"). Snapshots the net at close time.
CREATE TABLE IF NOT EXISTS settlements (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    settled_at   TEXT    NOT NULL,           -- 'YYYY-MM-DD HH:MM:SS'
    net_cents    INTEGER NOT NULL,           -- magnitude owed at close
    direction    TEXT    NOT NULL,           -- 'p1_owes_p2' | 'p2_owes_p1' | 'even'
    note         TEXT
);

-- The ledger. One row per purchase.
CREATE TABLE IF NOT EXISTS expenses (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    description   TEXT    NOT NULL,
    total_cents   INTEGER NOT NULL CHECK (total_cents > 0),
    paid_by       INTEGER NOT NULL REFERENCES partners(id),
    expense_date  TEXT    NOT NULL,          -- strict 'YYYY-MM-DD'
    created_at    TEXT    NOT NULL,          -- 'YYYY-MM-DD HH:MM:SS' (audit)
    created_by_tg INTEGER,                   -- telegram id of the logger
    settlement_id INTEGER REFERENCES settlements(id),  -- NULL = OPEN, else CLOSED
    raw_input     TEXT                       -- original text/caption (audit/debug)
);

-- Explicit split: exactly one row per partner per expense.
CREATE TABLE IF NOT EXISTS expense_shares (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    expense_id   INTEGER NOT NULL REFERENCES expenses(id) ON DELETE CASCADE,
    partner_id   INTEGER NOT NULL REFERENCES partners(id),
    share_cents  INTEGER NOT NULL CHECK (share_cents >= 0),
    UNIQUE (expense_id, partner_id)
);

CREATE INDEX IF NOT EXISTS idx_expenses_open  ON expenses(settlement_id);
CREATE INDEX IF NOT EXISTS idx_shares_expense ON expense_shares(expense_id);
