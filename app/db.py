"""SQLite 저장소."""
from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Iterator, Optional

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    paid_at      TEXT NOT NULL,              -- 결제 일시 (YYYY-MM-DDTHH:MM)
    month        TEXT NOT NULL,              -- YYYY-MM
    card         TEXT NOT NULL,
    card_last4   TEXT DEFAULT '',
    merchant     TEXT NOT NULL,
    amount       INTEGER NOT NULL,           -- 취소는 음수
    is_cancel    INTEGER NOT NULL DEFAULT 0,
    installment  TEXT DEFAULT '',
    category     TEXT NOT NULL,
    source       TEXT DEFAULT 'sms',         -- sms | push | manual
    memo         TEXT DEFAULT '',
    raw_hash     TEXT UNIQUE,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tx_month ON transactions(month);

-- 파싱에 실패한 원문 (규칙 개선용)
CREATE TABLE IF NOT EXISTS raw_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at TEXT NOT NULL,
    source      TEXT,
    sender      TEXT,
    text        TEXT,
    status      TEXT                          -- parsed | ignored | duplicate
);
"""


def init_db() -> None:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as con:
        con.executescript(SCHEMA)


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def log_raw(source: str, sender: str, text: str, status: str) -> None:
    with connect() as con:
        con.execute(
            "INSERT INTO raw_messages(received_at, source, sender, text, status) VALUES (?,?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), source, sender, text, status),
        )


def find_duplicate(card: str, amount: int, paid_at: datetime, source: str) -> Optional[int]:
    """문자와 앱 푸시가 같은 결제를 두 번 알릴 때를 대비한 중복 검사.

    다른 경로(sms ↔ push)로 같은 카드·같은 금액이 DEDUP_MINUTES 안에 들어오면 같은 결제로 본다.
    같은 경로로 같은 금액을 연달아 결제한 경우(커피 2잔 따로 결제 등)는 별개 결제로 남긴다.
    """
    lo = (paid_at - timedelta(minutes=config.DEDUP_MINUTES)).isoformat(timespec="minutes")
    hi = (paid_at + timedelta(minutes=config.DEDUP_MINUTES)).isoformat(timespec="minutes")
    with connect() as con:
        row = con.execute(
            "SELECT id FROM transactions WHERE card=? AND amount=? AND source<>? AND paid_at BETWEEN ? AND ?",
            (card, amount, source, lo, hi),
        ).fetchone()
    return row["id"] if row else None


def insert_transaction(*, paid_at: datetime, card: str, card_last4: str, merchant: str, amount: int,
                       is_cancel: bool, installment: str, category: str, source: str,
                       raw_text: str = "", memo: str = "") -> Optional[int]:
    """저장된 id, 이미 같은 결제가 있으면 None."""
    paid = paid_at.isoformat(timespec="minutes")
    raw_hash = hashlib.sha256(f"{card}|{amount}|{paid}|{merchant}".encode()).hexdigest()
    with connect() as con:
        cur = con.execute(
            """INSERT OR IGNORE INTO transactions
               (paid_at, month, card, card_last4, merchant, amount, is_cancel, installment,
                category, source, memo, raw_hash, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (paid, paid[:7], card, card_last4, merchant, amount, int(is_cancel), installment,
             category, source, memo, raw_hash, datetime.now().isoformat(timespec="seconds")),
        )
        return cur.lastrowid if cur.rowcount else None


def list_transactions(month: str) -> list[dict]:
    with connect() as con:
        rows = con.execute(
            "SELECT * FROM transactions WHERE month=? ORDER BY paid_at", (month,)
        ).fetchall()
    return [dict(r) for r in rows]


def monthly_totals() -> list[dict]:
    with connect() as con:
        rows = con.execute(
            "SELECT month, SUM(amount) AS total, COUNT(*) AS cnt FROM transactions GROUP BY month ORDER BY month"
        ).fetchall()
    return [dict(r) for r in rows]


def update_transaction(tx_id: int, **fields) -> bool:
    allowed = {k: v for k, v in fields.items() if k in {"category", "memo", "merchant"} and v is not None}
    if not allowed:
        return False
    sets = ", ".join(f"{k}=?" for k in allowed)
    with connect() as con:
        cur = con.execute(f"UPDATE transactions SET {sets} WHERE id=?", (*allowed.values(), tx_id))
        return cur.rowcount > 0


def delete_transaction(tx_id: int) -> bool:
    with connect() as con:
        return con.execute("DELETE FROM transactions WHERE id=?", (tx_id,)).rowcount > 0


def recent_raw(limit: int = 30, status: Optional[str] = None) -> list[dict]:
    q = "SELECT * FROM raw_messages"
    args: tuple = ()
    if status:
        q += " WHERE status=?"
        args = (status,)
    q += " ORDER BY id DESC LIMIT ?"
    with connect() as con:
        return [dict(r) for r in con.execute(q, (*args, limit)).fetchall()]
