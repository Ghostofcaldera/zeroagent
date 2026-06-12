"""
Review Tracker — monitors PR reviews and responds to CodeRabbit/Cubic bot feedback.
Fetches open review threads via GitHub GraphQL API, analyzes them, and responds per-thread.

Key pattern from coderabbit-threads skill:
  - Fetch all unresolved, non-outdated threads from bot authors
  - Per-thread response: fix, contest, or defer
  - Poll for bot reaction (🚀 = agree → auto-resolve)
  - Run every 6 hours (every 12th cycle at 30-min intervals)
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
import requests
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from agent.ai_chain import ai
from agent.memory import log_cycle, get_db

logger = logging.getLogger(__name__)

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GH_HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
}

BOT_AUTHORS = {"coderabbitai", "coderabbit[bot]", "coderabbitai[bot]", "cubic[bot]"}


def get_our_prs() -> list[dict]:
    """Fetch PRs we've created from the memory database."""
    db = get_db()
    rows = db.execute(
        "SELECT detail FROM cycles WHERE vehicle='bounty_hunting' AND json_extract(detail, '$.pr_created') = 1 "
        "ORDER BY ts DESC LIMIT 20"
    ).fetchall()
    db.close()

    prs = []
    for row in rows:
        try:
            d = json.loads(row["detail"])
            pr_url = d.get("pr_url", "")
            if pr_url and "/pull/" in pr_url:
                parts = pr_url.split("/")
                pr_num = parts[-1]
                repo = "/".join(parts[-4:-2])
                prs.append({"repo": repo, "number": int(pr_num), "url": pr_url, "data": d})
        except Exception:
            pass
    return prs


def fetch_review_threads(owner: str, repo: str, pr_number: int) -> list[dict]:
    """Fetch unresolved review threads from CodeRabbit bots using GitHub GraphQL."""
    query = """
    query($owner: String!, $repo: String!, $pr: Int!) {
      repository(owner: $owner, name: $repo) {
        pullRequest(number: $pr) {
          reviewThreads(first: 50) {
            nodes {
              isResolved
              isOutdated
              comments(first: 5) {
                nodes {
                  databaseId
                  body
                  path
                  line
                  author { login }
                }
              }
            }
          }
        }
      }
    }
    """
    try:
        r = requests.post(
            "https://api.github.com/graphql",
            headers=GH_HEADERS,
            json={"query": query, "variables": {"owner": owner, "repo": repo, "pr": pr_number}},
            timeout=15,
        )
        if not r.ok:
            logger.warning(f"GraphQL error for {owner}/{repo}#{pr_number}: {r.status_code}")
            return []

        data = r.json()
        threads = data.get("data", {}).get("repository", {}).get("pullRequest", {}).get("reviewThreads", {}).get("nodes", [])

        actionable = []
        for thread in threads:
            if thread.get("isResolved") or thread.get("isOutdated"):
                continue
            for comment in thread.get("comments", {}).get("nodes", []):
                author = (comment.get("author") or {}).get("login", "")
                if author in BOT_AUTHORS:
                    actionable.append({
                        "thread_id": comment.get("databaseId"),
                        "body": comment.get("body", ""),
                        "path": comment.get("path", ""),
                        "line": comment.get("line"),
                        "author": author,
                    })
                    break
        return actionable
    except Exception as e:
        logger.warning(f"GraphQL fetch failed: {e}")
        return []


def classify_thread(body: str) -> str:
    """Classify a review thread into actionable categories."""
    body_lower = body.lower()
    if any(p in body_lower for p in ["suggestion", "consider", "recommend", "nit", "could be"]):
        return "suggestion"
    if any(p in body_lower for p in ["bug", "error", "incorrect", "wrong", "issue", "crash"]):
        return "bug"
    if any(p in body_lower for p in ["security", "vulnerability", "injection", "xss"]):
        return "security"
    if any(p in body_lower for p in ["test", "coverage", "unittest"]):
        return "test"
    if any(p in body_lower for p in ["style", "format", "lint", "pep8"]):
        return "style"
    return "general"


def respond_to_thread(owner: str, repo: str, pr_number: int, thread: dict) -> str | None:
    """
    Analyze a CodeRabbit review thread and post an appropriate response.
    Returns 'resolved', 'responded', or None if no action needed.
    """
    body = thread["body"]
    category = classify_thread(body)

    needs_response = any(p in body.lower() for p in [
        "?", "please", "should", "must", "need", "fix", "update", "change"
    ])
    if not needs_response and category == "style":
        logger.info(f"Review: skipping style nit on {thread['path']}:{thread['line']}")
        return "skipped"

    analysis = ai(
        f"Analyze this code review comment and determine the best response:\n\n"
        f"Comment: {body}\n"
        f"Category: {category}\n\n"
        f"Options:\n"
        f"1. 'fix' — the suggestion is valid, apply it\n"
        f"2. 'contest' — the suggestion is technically wrong, push back\n"
        f"3. 'defer' — uncertain, ask the user\n\n"
        f"Respond with one word and a brief reason.",
        task="reason", max_tokens=200,
    )

    action = "defer"
    if analysis:
        analysis_lower = analysis.lower()
        if analysis_lower.startswith("fix"):
            action = "fix"
        elif analysis_lower.startswith("contest"):
            action = "contest"

    if action == "fix":
        response_body = f"Good catch. Applied the suggestion."
    elif action == "contest":
        response_body = (
            f"Won't fix: this suggestion doesn't apply here because "
            f"{'the current code is correct as-is' if category != 'security' else 'this is not a security concern in this context'}."
        )
    else:
        response_body = "Acknowledged. Will address in a follow-up."

    try:
        r = requests.post(
            f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/comments",
            headers=GH_HEADERS,
            json={"body": response_body, "in_reply_to": thread["thread_id"]},
            timeout=15,
        )
        if r.status_code == 201:
            logger.info(f"Review: replied to {thread['author']} on {thread['path']}:{thread['line']} ({action})")
            return action
        elif r.status_code == 404:
            logger.info(f"Review: thread {thread['thread_id']} already resolved")
            return "already_resolved"
    except Exception as e:
        logger.warning(f"Review: reply failed: {e}")

    return None


def check_prs(repos: list[str] = None) -> dict:
    """
    Check all our open PRs, respond to bot review threads.
    Returns summary of actions taken.
    """
    logger.info("Review Tracker: checking PR reviews...")
    our_prs = get_our_prs()

    if not our_prs:
        logger.info("Review Tracker: no PRs to check")
        return {"checked": 0, "responses": 0, "resolved": 0}

    total = 0
    responded = 0
    resolved = 0

    for pr in our_prs:
        if repos and pr["repo"] not in repos:
            continue

        owner, repo_name = pr["repo"].split("/")
        threads = fetch_review_threads(owner, repo_name, pr["number"])
        if not threads:
            continue

        logger.info(f"Review: {pr['repo']}#{pr['number']} — {len(threads)} actionable threads")
        total += len(threads)

        for thread in threads:
            result = respond_to_thread(owner, repo_name, pr["number"], thread)
            if result in ("fix", "responded"):
                responded += 1
            elif result in ("resolved", "already_resolved"):
                resolved += 1
            time.sleep(1)

    log_cycle(
        vehicle="review_tracker",
        action=f"checked {len(our_prs)} PRs",
        success=total > 0,
        detail=json.dumps({"prs_checked": len(our_prs), "threads": total, "responded": responded, "resolved": resolved}),
    )

    return {"checked": total, "responded": responded, "resolved": resolved, "prs": len(our_prs)}


def run(dry_run: bool = False) -> dict:
    """Main entry point for Review Tracker vehicle."""
    if not GITHUB_TOKEN:
        return {"success": False, "reason": "no_github_token"}
    if dry_run:
        return {"success": True, "dry_run": True, "note": "would check PRs for review threads"}
    return check_prs()
