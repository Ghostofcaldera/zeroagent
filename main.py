"""
ZeroAgent — Autonomous earning agent, zero investment.
Fixes all bugs from original design:
1. Vehicles load from DB (pivots persist)
2. No vehicle returns None/crashes learn()
3. Git commit fixed (permissions: contents: write required in workflow)
4. Auto-pivot stored in DB
5. AI provider order corrected for real 2026 free tier limits
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Load .env file FIRST, before any other imports that might need API keys
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

# Set up logging
Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(f"logs/cycle_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.log"),
    ],
)
logger = logging.getLogger("ZeroAgent")

from agent.memory import (
    init_db,
    get_vehicles,
    get_success_rate,
    log_cycle,
    autopivot,
    git_commit_memory,
    get_state,
    set_state,
)


# ---------------------------------------------------------------------------
# Vehicle dispatch
# ---------------------------------------------------------------------------

def run_vehicle(name: str, dry_run: bool = False) -> dict:
    """Dispatch to the correct skill module. All return dicts, never None."""
    try:
        if name == "content_affiliate":
            from skills.content_affiliate import run
            return run(dry_run=dry_run)

        elif name == "bounty_hunting":
            from skills.bounty_hunter import run
            return run(dry_run=dry_run)

        elif name == "micro_saas":
            # Not yet implemented — return structured placeholder
            return {
                "success": False,
                "reason": "not_implemented",
                "note": "Micro-SaaS requires manual setup. See README for instructions.",
            }

        elif name == "github_sponsors":
            return {
                "success": False,
                "reason": "not_implemented",
                "note": "GitHub Sponsors requires account setup. See README.",
            }

        else:
            return {"success": False, "reason": f"unknown_vehicle: {name}"}

    except Exception as e:
        logger.error(f"Vehicle {name} crashed: {e}", exc_info=True)
        return {"success": False, "reason": f"exception: {str(e)}"}


# ---------------------------------------------------------------------------
# Vehicle selection
# ---------------------------------------------------------------------------

def select_vehicle(vehicles: list[dict]) -> str:
    """
    Score vehicles by: success_rate * autonomy_weight
    Prioritize content_affiliate first (fastest to first revenue),
    then bounty_hunting.
    """
    # Fixed autonomy weights
    weights = {
        "content_affiliate": 5,   # highest — fully implemented, easiest income
        "bounty_hunting":    4,
        "micro_saas":        2,    # low until implemented
        "github_sponsors":   1,
    }

    best = None
    best_score = -1

    for v in vehicles:
        name = v["name"]
        success_rate = get_success_rate(name)
        weight = weights.get(name, 1)
        score = success_rate * weight

        # Alternate vehicles to avoid running same one every cycle
        last_vehicle = get_state("last_vehicle", "")
        if name == last_vehicle:
            score *= 0.5  # de-prioritize last-run vehicle

        if score > best_score:
            best_score = score
            best = name

    return best or "content_affiliate"


# ---------------------------------------------------------------------------
# Health checks
# ---------------------------------------------------------------------------

def health_check() -> tuple[bool, str]:
    """Check that we have at least one usable AI provider."""
    has_key = any([
        os.environ.get("GEMINI_API_KEY"),
        os.environ.get("GROQ_API_KEY"),
        os.environ.get("OPENROUTER_API_KEY"),
    ])
    if not has_key:
        # Check if Ollama is running locally
        try:
            import requests
            r = requests.get("http://localhost:11434/api/tags", timeout=3)
            if r.ok:
                return True, "ollama"
        except Exception:
            pass
        return False, "no_ai_provider"

    return True, "ok"


def check_rate_limits() -> dict:
    """Return current daily usage vs limits for each provider."""
    from agent.memory import get_api_usage
    return {
        "gemini":      {"used": get_api_usage("gemini"),      "limit": 1500},
        "groq_8b":     {"used": get_api_usage("groq_8b"),     "limit": 14400},
        "groq_70b":    {"used": get_api_usage("groq_70b"),    "limit": 1000},
        "openrouter":  {"used": get_api_usage("openrouter"),  "limit": 100},
    }


# ---------------------------------------------------------------------------
# Main cycle
# ---------------------------------------------------------------------------

def run_cycle(dry_run: bool = False):
    """
    One complete agent cycle. Called by GitHub Actions every N minutes.
    Runs ALL primary vehicles in sequence each cycle for maximum earnings:
      1. content_affiliate → publish article with affiliate links
      2. bounty_hunting   → scan Opire + GitHub for dollar bounties
    All results are logged and committed back to the repo.
    """
    logger.info(f"=== Cycle start {datetime.now(timezone.utc).isoformat()} ===")

    # 1. Init DB on first run
    init_db()

    # 2. Health check
    ok, reason = health_check()
    if not ok:
        logger.error(f"Health check failed: {reason}")
        logger.error("Set at least one of: GEMINI_API_KEY, GROQ_API_KEY, GROQ_API_KEY")
        return

    results = {}

    # 3. Run primary vehicles in sequence
    primary_vehicles = ["content_affiliate", "bounty_hunting"]
    for vehicle_name in primary_vehicles:
        logger.info(f"--- Running vehicle: {vehicle_name} ---")
        try:
            result = run_vehicle(vehicle_name, dry_run=dry_run)
            logger.info(f"{vehicle_name} result: {result}")
            results[vehicle_name] = result

            success = result.get("success", False)
            if "error" in result and not success:
                log_cycle(
                    vehicle=vehicle_name,
                    action="orchestrator_run",
                    success=False,
                    detail=json.dumps(result),
                )
        except Exception as e:
            logger.error(f"Vehicle {vehicle_name} crashed: {e}", exc_info=True)
            results[vehicle_name] = {"success": False, "reason": f"exception: {str(e)}"}

    # 4. Auto-pivot check (only if not dry run)
    if not dry_run:
        disabled = autopivot()
        if disabled:
            logger.info(f"Auto-pivoted away from: {disabled}")

    # 5. Log rate limits for monitoring
    limits = check_rate_limits()
    for provider, data in limits.items():
        pct = data["used"] / data["limit"] * 100 if data["limit"] else 0
        if pct > 80:
            logger.warning(f"{provider} rate limit at {pct:.0f}%: {data['used']}/{data['limit']}")

    # 6. Commit memory to Git (persists across GitHub Actions runs)
    if not dry_run:
        git_commit_memory()

    logger.info(f"=== Cycle complete ===")
    return results


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Run without publishing/submitting")
    parser.add_argument("--vehicle", default=None, help="Force a specific vehicle")
    parser.add_argument("--init", action="store_true", help="Just initialize the DB")
    args = parser.parse_args()

    if args.init:
        init_db()
        print("Database initialized.")
        sys.exit(0)

    if args.vehicle:
        # Override vehicle selection
        init_db()
        ok, _ = health_check()
        if not ok:
            print("ERROR: No AI provider available. Set API keys.")
            sys.exit(1)
        result = run_vehicle(args.vehicle, dry_run=args.dry_run)
        print(json.dumps(result, indent=2))
    else:
        run_cycle(dry_run=args.dry_run)
