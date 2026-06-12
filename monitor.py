"""
ZeroAgent Monitor — dashboard for revenue & activity tracking.
"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path("memory/agent.db")


def get_db():
    return sqlite3.connect(DB_PATH)


def show_dashboard():
    db = get_db()
    db.row_factory = sqlite3.Row

    print("=" * 60)
    print("  ZEROAGENT DASHBOARD")
    print("=" * 60)

    # Vehicles summary
    rows = db.execute("SELECT * FROM vehicles ORDER BY cycles_run DESC").fetchall()
    print(f"\n{'VEHICLE':<22} {'RUNS':>5} {'OK%':>6} {'EARNED':>10}")
    print("-" * 50)
    for r in rows:
        rate = (r["cycles_success"] / r["cycles_run"] * 100) if r["cycles_run"] else 0
        print(f"{r['name']:<22} {r['cycles_run']:>5} {rate:>5.0f}% {r['total_earned']:>8.2f}")

    # Recent cycles
    print(f"\n{'RECENT CYCLES':-^60}")
    rows = db.execute(
        "SELECT ts, vehicle, action, revenue, success, detail FROM cycles ORDER BY id DESC LIMIT 10"
    ).fetchall()
    for r in rows:
        status = "✅" if r["success"] else "❌"
        print(f"  {status} [{r['ts']}] {r['vehicle']}: {r['action'][:50]}")
        if r["revenue"]:
            print(f"     Revenue: ${r['revenue']:.2f}")

    # Published content
    print(f"\n{'PUBLISHED CONTENT':-^60}")
    rows = db.execute(
        "SELECT ts, title, platform, url, views, revenue FROM content_log ORDER BY id DESC LIMIT 10"
    ).fetchall()
    if rows:
        for r in rows:
            print(f"  📝 [{r['ts']}] {r['title'][:50]}")
            print(f"     {r['platform']} | Views: {r['views']} | Rev: ${r['revenue']:.2f}")
    else:
        print("  (none yet)")

    # Rate limits
    print(f"\n{'API USAGE TODAY':-^60}")
    rows = db.execute("SELECT provider, calls FROM api_usage WHERE date=date('now')").fetchall()
    limits = {"gemini": 1500, "groq_8b": 14400, "groq_70b": 1000, "openrouter": 100}
    for r in rows:
        limit = limits.get(r["provider"], 999999)
        pct = r["calls"] / limit * 100
        print(f"  {r['provider']:<15} {r['calls']:>5}/{limit:<5} ({pct:.0f}%)")

    db.close()


def show_help():
    print("""
Commands:
  python monitor.py           Show dashboard
  python monitor.py --revenue Show all revenue entries
  python monitor.py --log N   Show details of cycle N
""")


def show_revenue():
    db = get_db()
    rows = db.execute(
        "SELECT ts, vehicle, action, revenue, success FROM cycles WHERE revenue > 0 ORDER BY id"
    ).fetchall()
    if rows:
        total = sum(r["revenue"] for r in rows)
        print(f"\nRevenue entries ({len(rows)}, total: ${total:.2f}):")
        for r in rows:
            print(f"  ${r['revenue']:<8.2f} [{r['ts']}] {r['vehicle']}: {r['action'][:40]}")
    else:
        print("No revenue recorded yet.")
    db.close()


if __name__ == "__main__":
    import sys
    if len(sys.argv) == 1:
        show_dashboard()
    elif sys.argv[1] == "--revenue":
        show_revenue()
    elif sys.argv[1] == "--help":
        show_help()
    else:
        show_help()
