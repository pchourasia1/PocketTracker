import os
import sqlite3
from datetime import date, timedelta

from werkzeug.security import generate_password_hash

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "expense_tracker.db")

CATEGORIES = ["Food", "Transport", "Bills", "Health", "Shopping", "Entertainment", "Other"]


def get_db():
    """Return a SQLite connection with dict-like rows and foreign keys enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create all tables if they don't already exist."""
    conn = get_db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT    NOT NULL,
            email         TEXT    NOT NULL UNIQUE,
            password_hash TEXT    NOT NULL,
            created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS expenses (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            amount      REAL    NOT NULL CHECK (amount > 0),
            category    TEXT    NOT NULL,
            date        TEXT    NOT NULL,
            description TEXT,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_expenses_user_date ON expenses (user_id, date);
        """
    )
    conn.commit()
    conn.close()


def seed_db():
    """Insert a demo user and sample expenses. Does nothing if any user exists."""
    conn = get_db()
    if conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
        conn.close()
        return

    cur = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Demo User", "demo@pockettracker.com", generate_password_hash("demo1234")),
    )
    user_id = cur.lastrowid

    today = date.today()
    samples = [
        (1500.00, "Bills", 2, "Electricity and internet"),
        (420.50, "Food", 1, "Weekly groceries"),
        (280.00, "Food", 5, "Dinner with friends"),
        (650.00, "Health", 8, "Pharmacy"),
        (120.00, "Transport", 3, "Metro card top-up"),
        (130.00, "Transport", 10, "Cab to airport"),
        (899.00, "Shopping", 12, "Running shoes"),
        (350.00, "Entertainment", 15, "Movie tickets"),
        (75.00, "Other", 20, "Stationery"),
    ]
    conn.executemany(
        "INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)",
        [
            (user_id, amount, category, (today - timedelta(days=days_ago)).isoformat(), description)
            for amount, category, days_ago, description in samples
        ],
    )
    conn.commit()
    conn.close()
