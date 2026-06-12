"""
TaskMarket — USDC bounties on Base Mainnet
Requires: npm install -g @daydreams/taskmarket (one-time) + taskmarket init (one-time)

To set up for GitHub Actions, run ONCE locally:
  1. npm install -g @daydreams/taskmarket
  2. taskmarket init
  3. Set withdrawal address: taskmarket wallet set-withdrawal-address <your_rabby_address>
  4. Copy ~/.taskmarket/keystore.json content → GitHub secret TASKMARKET_KEYSTORE

Then the agent auto-restores the keystore each run and can operate fully autonomously.
"""

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from agent.ai_chain import ai
from agent.memory import log_cycle

logger = logging.getLogger(__name__)

TASKMARKET_API = "https://api.taskmarket.dev"
KEYSTORE_PATH = Path.home() / ".taskmarket" / "keystore.json"


def _ensure_keystore() -> bool:
    """Restore keystore from env var if present, so it works in GitHub Actions."""
    env_keystore = os.environ.get("TASKMARKET_KEYSTORE")
    if env_keystore:
        KEYSTORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        KEYSTORE_PATH.write_text(env_keystore)
        logger.info("TaskMarket: keystore restored from env var")
        return True
    if KEYSTORE_PATH.exists():
        return True
    logger.warning("TaskMarket: no keystore found. Run 'taskmarket init' locally.")
    return False


def _taskmarket_cli(args: list[str]) -> str | None:
    """Run a taskmarket CLI command and return stdout."""
    if not _ensure_keystore():
        return None
    try:
        result = subprocess.run(
            ["taskmarket", *args],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            logger.warning(f"TaskMarket CLI error: {result.stderr.strip()[:200]}")
            return None
        return result.stdout
    except FileNotFoundError:
        logger.warning("TaskMarket CLI not found. Install: npm install -g @daydreams/taskmarket")
        return None
    except Exception as e:
        logger.warning(f"TaskMarket CLI failed: {e}")
        return None


def list_open_tasks() -> list[dict]:
    """Fetch open bounties from TaskMarket."""
    output = _taskmarket_cli(["task", "list", "--status", "open"])
    if not output:
        return []

    tasks = []

    # Try parsing as JSON first (new CLI format)
    try:
        data = json.loads(output)
        if isinstance(data, dict) and data.get("ok") and "data" in data:
            for task in data["data"].get("tasks", []):
                tasks.append({
                    "id": task.get("id", ""),
                    "description": task.get("description", ""),
                    "reward": str(task.get("reward", 0)),
                    "mode": "bounty",
                })
            return tasks
    except json.JSONDecodeError:
        pass

    # Fallback: parse as table format (old CLI format)
    for line in output.strip().split("\n"):
        if not line.strip() or line.startswith("ID") or "---" in line:
            continue
        parts = line.split()
        if len(parts) >= 4:
            tasks.append({
                "id": parts[0],
                "description": " ".join(parts[1:-2]),
                "reward": parts[-2] if len(parts) >= 2 else "?",
                "mode": parts[-1] if len(parts) >= 1 else "bounty",
            })

    return tasks


def fetch_task_details(task_id: str) -> dict | None:
    """Get detailed information about a specific task."""
    output = _taskmarket_cli(["task", "get", task_id])
    if not output:
        return None
    result = {"id": task_id, "raw": output}
    try:
        data = json.loads(output)
        if isinstance(data, dict) and data.get("ok") and "data" in data:
            task = data["data"]
            result.update({
                "id": task.get("id", task_id),
                "description": task.get("description", ""),
                "reward": str(task.get("reward", 0)),
            })
            return result
    except json.JSONDecodeError:
        pass

    # Fallback: parse as key:value lines
    for line in output.strip().split("\n"):
        if ":" in line:
            key, _, value = line.partition(":")
            result[key.strip().lower().replace(" ", "_")] = value.strip()
    return result


def complete_task(task_id: str, description: str, reward: float) -> dict:
    """
    Analyze a TaskMarket bounty, generate a solution, and submit it.
    Returns result dict.
    """
    logger.info(f"TaskMarket: working on {task_id} (${reward})")
    assessment = ai(
        f"Analyze this task for feasibility and suggest an approach:\n\n{description}",
        task="reason",
        max_tokens=500,
    )
    code = ai(
        f"Implement a solution for this TaskMarket bounty:\n\n{description}\n\n"
        f"Return only the code/solution. Keep it minimal and focused.",
        task="code",
        max_tokens=3000,
    )
    if not code or "ERROR:" in code:
        return {"success": False, "reason": "solution_generation_failed"}

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        sol_path = f.name

    try:
        output = _taskmarket_cli(["task", "submit", task_id, "--file", sol_path])
        submitted = output is not None
        log_cycle(
            vehicle="task_market",
            action=f"submit {task_id}",
            success=submitted,
            revenue=reward if submitted else 0,
            detail=json.dumps({"task_id": task_id, "reward": reward}),
        )
        return {"success": submitted, "task_id": task_id, "reward": reward}
    finally:
        Path(sol_path).unlink(missing_ok=True)


def run(dry_run: bool = False) -> dict:
    """
    Full TaskMarket cycle:
    1. Ensure keystore is available
    2. Fetch open tasks
    3. Pick best candidate
    4. Generate and submit solution
    """
    logger.info("TaskMarket cycle starting...")
    if not _ensure_keystore():
        return {"success": False, "reason": "no_keystore", "note": "Run 'taskmarket init' locally first"}

    tasks = list_open_tasks()
    logger.info(f"TaskMarket: {len(tasks)} open tasks")

    if not tasks:
        log_cycle("task_market", "scan", False, detail="No open tasks found")
        return {"success": False, "reason": "no_tasks"}

    candidates = []
    for task in tasks:
        reward_str = str(task.get("reward", "0")).replace("$", "").replace("USDC", "")
        try:
            reward = float(reward_str)
        except ValueError:
            reward = 0
        # Convert from micro-USDC (1 USDC = 1,000,000 micro-USDC)
        if reward > 1000:
            reward = reward / 1_000_000
        candidates.append((reward, task))

    if not candidates:
        logger.info("TaskMarket: no open tasks")
        log_cycle("task_market", "scan", False, detail="No open tasks found")
        return {"success": False, "reason": "no_tasks"}

    candidates.sort(key=lambda x: x[0], reverse=True)
    best_reward, best_task = candidates[0]
    task_id = best_task["id"]

    # Handle case where task_id is accidentally the full JSON string
    if isinstance(task_id, str) and task_id.startswith("{"):
        try:
            parsed = json.loads(task_id)
            if "data" in parsed and "tasks" in parsed["data"] and parsed["data"]["tasks"]:
                task_id = parsed["data"]["tasks"][0].get("id", task_id)
            elif "id" in parsed:
                task_id = parsed["id"]
        except Exception:
            pass

    logger.info(f"TaskMarket best: {task_id} ${best_reward}")

    if dry_run:
        return {"success": True, "dry_run": True, "task_id": task_id, "reward": best_reward}

    details = fetch_task_details(task_id)
    description = (details or {}).get("raw", best_task.get("description", ""))

    result = complete_task(task_id, description, best_reward)
    return result
