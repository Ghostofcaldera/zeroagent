"""
Persistent memory layer.

Fixes from original design:
1. Vehicles loaded from DB, not hardcoded in __init__ — pivots survive restarts.
2. Cycle state persisted so GitHub Actions can continue across runs.
3. Blacklist table prevents wasting tokens on scam repos (from real experiment data).
4. Rate limit tracking per provider to avoid 429 errors.
"""

import sqlite3
import json
import os
import subprocess
from datetime import datetime, date, timezone
from pathlib import Path

DB_PATH = Path("memory/agent.db")


def get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def init_db():
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS vehicles (
            name TEXT PRIMARY KEY,
            enabled INTEGER DEFAULT 1,
            total_earned REAL DEFAULT 0,
            cycles_run INTEGER DEFAULT 0,
            cycles_success INTEGER DEFAULT 0,
            last_run TEXT,
            last_success TEXT,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS cycles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            vehicle TEXT NOT NULL,
            action TEXT,
            cost REAL DEFAULT 0,
            revenue REAL DEFAULT 0,
            success INTEGER DEFAULT 0,
            detail TEXT
        );

        CREATE TABLE IF NOT EXISTS blacklist (
            repo TEXT PRIMARY KEY,
            reason TEXT,
            added_ts TEXT
        );

        CREATE TABLE IF NOT EXISTS content_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT,
            title TEXT,
            platform TEXT,
            url TEXT,
            affiliate_links TEXT,
            views INTEGER DEFAULT 0,
            revenue REAL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS api_usage (
            provider TEXT,
            date TEXT,
            calls INTEGER DEFAULT 0,
            PRIMARY KEY (provider, date)
        );

        CREATE TABLE IF NOT EXISTS state (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated TEXT
        );
    """)

    # Seed vehicles if first run
    existing = db.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0]
    if existing == 0:
        vehicles = [
            ("bounty_hunting",   1),
            ("content_affiliate", 1),
            ("micro_saas",       1),
            ("github_sponsors",  1),
        ]
        # Note: airdrop_farming removed from default — treat as manual lottery
        db.executemany(
            "INSERT INTO vehicles (name, enabled) VALUES (?, ?)", vehicles
        )

    # Seed known scam/honeypot repos from real experiments
    known_blacklist = [
        ("UnsafeLabs/Bounty-Hunters",        "31 PRs closed without merge — honeypot"),
        ("SecureBananaLabs/bug-bounty",       "21 PRs closed — scam"),
        ("OFFER-HUB/offer-hub-monorepo",      "4 PRs closed — unresponsive"),
        ("ClankerNation/OpenAgents",          "3 PRs closed — honeypot"),
        ("Xconfess/Xconfess",                 "5 open 0 merged — ghost project"),
        ("ritik4ever/stellar-bounty-board",   "5 open 0 merged — ghost project"),
        ("Devsol-01/Nestera",                 "4 open 0 merged — ghost project"),
    ]
    for repo, reason in known_blacklist:
        db.execute(
            "INSERT OR IGNORE INTO blacklist (repo, reason, added_ts) VALUES (?, ?, ?)",
            (repo, reason, datetime.now(timezone.utc).isoformat()),
        )

    db.commit()
    db.close()


def get_state(key: str, default=None):
    db = get_db()
    row = db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
    db.close()
    if row:
        try:
            return json.loads(row["value"])
        except Exception:
            return row["value"]
    return default


def set_state(key: str, value):
    db = get_db()
    db.execute(
        "INSERT OR REPLACE INTO state (key, value, updated) VALUES (?, ?, ?)",
        (key, json.dumps(value), datetime.now(timezone.utc).isoformat()),
    )
    db.commit()
    db.close()


def get_vehicles() -> list[dict]:
    db = get_db()
    rows = db.execute(
        "SELECT * FROM vehicles WHERE enabled=1 ORDER BY name"
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def log_cycle(vehicle: str, action: str, success: bool, revenue: float = 0, detail: str = ""):
    db = get_db()
    db.execute(
        "INSERT INTO cycles (ts, vehicle, action, revenue, success, detail) VALUES (?, ?, ?, ?, ?, ?)",
        (datetime.now(timezone.utc).isoformat(), vehicle, action, revenue, int(success), detail),
    )
    db.execute(
        "UPDATE vehicles SET cycles_run=cycles_run+1, last_run=?, "
        "cycles_success=cycles_success+?, total_earned=total_earned+?, "
        "last_success=CASE WHEN ? THEN ? ELSE last_success END "
        "WHERE name=?",
        (datetime.now(timezone.utc).isoformat(), int(success), revenue,
         int(success), datetime.now(timezone.utc).isoformat(), vehicle),
    )
    db.commit()
    db.close()


def is_blacklisted(repo: str) -> bool:
    db = get_db()
    row = db.execute("SELECT 1 FROM blacklist WHERE repo=?", (repo,)).fetchone()
    db.close()
    return row is not None


def add_to_blacklist(repo: str, reason: str):
    db = get_db()
    db.execute(
        "INSERT OR IGNORE INTO blacklist (repo, reason, added_ts) VALUES (?, ?, ?)",
        (repo, reason, datetime.now(timezone.utc).isoformat()),
    )
    db.commit()
    db.close()


def track_api_call(provider: str):
    """Track daily API usage to avoid exceeding free tier limits."""
    db = get_db()
    today = date.today().isoformat()
    db.execute(
        "INSERT INTO api_usage (provider, date, calls) VALUES (?, ?, 1) "
        "ON CONFLICT(provider, date) DO UPDATE SET calls=calls+1",
        (provider, today),
    )
    db.commit()
    db.close()


def get_api_usage(provider: str) -> int:
    db = get_db()
    today = date.today().isoformat()
    row = db.execute(
        "SELECT calls FROM api_usage WHERE provider=? AND date=?",
        (provider, today),
    ).fetchone()
    db.close()
    return row["calls"] if row else 0


def get_success_rate(vehicle: str) -> float:
    db = get_db()
    row = db.execute(
        "SELECT cycles_run, cycles_success FROM vehicles WHERE name=?", (vehicle,)
    ).fetchone()
    db.close()
    if not row or row["cycles_run"] == 0:
        return 0.5  # optimistic default for new vehicles
    return row["cycles_success"] / row["cycles_run"]


def autopivot():
    """
    Disable vehicles with <20% success rate after 10+ cycles.
    Pivots survive restarts because they're stored in DB.
    """
    db = get_db()
    vehicles = db.execute(
        "SELECT name, cycles_run, cycles_success FROM vehicles WHERE enabled=1"
    ).fetchall()
    disabled = []
    for v in vehicles:
        if v["cycles_run"] >= 10:
            rate = v["cycles_success"] / v["cycles_run"]
            if rate < 0.20:
                db.execute(
                    "UPDATE vehicles SET enabled=0, notes=? WHERE name=?",
                    (f"Auto-disabled: {rate:.0%} success after {v['cycles_run']} cycles", v["name"]),
                )
                disabled.append(v["name"])
    db.commit()
    db.close()
    return disabled


def git_commit_memory():
    """Commit memory DB and logs to Git for persistence across GitHub Actions runs."""
    try:
        subprocess.run(["git", "config", "user.name", "ZeroAgent"], check=False)
        subprocess.run(["git", "config", "user.email", "agent@zero.local"], check=False)
        subprocess.run(["git", "add", "memory/", "logs/"], check=False)
        result = subprocess.run(
            ["git", "diff", "--staged", "--quiet"],
            capture_output=True,
        )
        if result.returncode != 0:  # there are staged changes
            subprocess.run(
                ["git", "commit", "-m", f"Agent state {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}"],
                check=False,
            )
            subprocess.run(["git", "push"], check=False)
    except Exception as e:
        print(f"Git commit failed (non-fatal): {e}")
