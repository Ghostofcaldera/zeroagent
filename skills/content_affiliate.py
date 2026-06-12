"""
Content Affiliate Vehicle — FULLY IMPLEMENTED

Strategy based on real data:
- Dev.to has free publishing API and high SEO traffic
- Write technical articles → include affiliate links → passive income
- Best affiliate programs for developers (no approval needed):
  * DigitalOcean: $25 per referral (instant approval)
  * Namecheap: 20-35% commission (instant)
  * Groq / AI tool affiliates: recurring commissions
  * Gumroad: sell your own digital products (free, 10% fee)

The agent: picks trending topics → writes article → posts to Dev.to → logs it.
Human task: check which articles get traction → focus on those niches.
"""

import os
import re
import json
import logging
import requests
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from agent.ai_chain import ai
from agent.memory import log_cycle, get_db

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Affiliate links — replace with YOUR actual affiliate links after signup
# ---------------------------------------------------------------------------
AFFILIATE_LINKS = {
    "hostinger":    "https://www.hostinger.com?REFERRALCODE=EHKKARIUKAOL",  # 20% commission
    "namecheap":    "https://www.namecheap.com/?aff=YOUR_AFF",              # 20-35% — update when Impact approves
    "digitalocean": "https://www.digitalocean.com/?refcode=YOUR_REF",       # $25/referral
    "groq":         "https://groq.com",
    "railway":      "https://railway.app",
}

DEVTO_API = "https://dev.to/api"


# ---------------------------------------------------------------------------
# Topic discovery — free, no API key needed
# ---------------------------------------------------------------------------

def get_trending_topics() -> list[str]:
    """
    Scrape trending topics from free sources.
    Returns a list of article topic ideas.
    """
    topics = []

    # 1. GitHub trending repos (no auth needed)
    try:
        r = requests.get(
            "https://api.github.com/search/repositories",
            params={"q": "stars:>100 pushed:>2026-01-01", "sort": "stars", "per_page": 10},
            headers={"Accept": "application/vnd.github+json"},
            timeout=10,
        )
        if r.ok:
            for repo in r.json().get("items", [])[:5]:
                name = repo["name"]
                desc = repo.get("description", "")
                topics.append(f"How to use {name}: {desc}")
    except Exception as e:
        logger.warning(f"GitHub trending: {e}")

    # 2. Hacker News top stories (no auth)
    try:
        r = requests.get("https://hacker-news.firebaseio.com/v0/topstories.json", timeout=10)
        if r.ok:
            story_ids = r.json()[:5]
            for sid in story_ids:
                s = requests.get(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json", timeout=5)
                if s.ok:
                    data = s.json()
                    if data.get("type") == "story" and data.get("title"):
                        topics.append(f"Developer take on: {data['title']}")
    except Exception as e:
        logger.warning(f"HN topics: {e}")

    # 3. Fallback: evergreen developer topics that always get traffic
    fallback = [
        "Python automation scripts every developer should know in 2026",
        "Free AI APIs with no credit card required — complete 2026 guide",
        "Building a REST API with FastAPI and deploying free on Railway",
        "GitHub Actions tricks that will save you hours every week",
        "SQLite is underrated — why it's perfect for side projects",
        "n8n vs Zapier vs Make: which automation tool is actually free",
        "How to earn money as a developer with zero upfront investment",
        "Groq vs Gemini free tier: which AI API gives you the most for free",
    ]
    topics.extend(fallback[:3])

    return topics[:8]  # cap at 8 per cycle


# ---------------------------------------------------------------------------
# Article generation
# ---------------------------------------------------------------------------

def pick_best_topic(topics: list[str]) -> str:
    """Use AI to pick the topic most likely to get Dev.to traffic."""
    prompt = f"""You are a technical content strategist. 
Pick the ONE topic from this list most likely to get traffic on Dev.to in 2026.
Pick something with high search intent, practical value, and developer audience.

Topics:
{chr(10).join(f'- {t}' for t in topics)}

Reply with ONLY the exact topic string, nothing else."""
    return ai(prompt, task="reason").strip().strip('"').strip("'")


def write_article(topic: str) -> dict:
    """
    Generate a complete Dev.to article with affiliate links woven in naturally.
    Returns dict with title, content, tags.
    """
    aff_context = "\n".join([
        f"- {name}: {url}" for name, url in AFFILIATE_LINKS.items()
    ])

    prompt = f"""Write a complete, high-quality technical article for Dev.to about:
"{topic}"

Requirements:
- Length: 800-1200 words
- Format: Markdown with headers, code blocks where relevant
- Tone: Practical, no-fluff, developer-to-developer
- Include 1-3 natural mentions of relevant tools from this list where genuinely useful:
{aff_context}
  Only mention a tool if it genuinely fits the content. Never be spammy.
- End with a "Resources" section linking to the tools mentioned
- Start with a compelling hook (1-2 sentences explaining why this matters)
- Include at least one code example if relevant
- Tags: suggest 4 relevant Dev.to tags at the very end in format: TAGS: tag1, tag2, tag3, tag4

Write the full article now:"""

    content = ai(prompt, task="content", max_tokens=2000)

    # Extract title (first # heading)
    lines = content.split("\n")
    title = topic  # fallback
    for line in lines:
        if line.startswith("# "):
            title = line[2:].strip()
            break

    # Extract tags
    tags = ["webdev", "programming", "productivity", "tutorial"]
    for line in reversed(lines):
        if line.startswith("TAGS:"):
            raw = line.replace("TAGS:", "").strip()
            tags = [t.strip() for t in raw.split(",")][:4]
            content = content.replace(line, "").strip()
            break

    return {"title": title, "content": content, "tags": tags}


# ---------------------------------------------------------------------------
# Dev.to publishing
# ---------------------------------------------------------------------------

def publish_to_devto(article: dict) -> dict:
    """
    Publish article to Dev.to via their free API.
    Returns the published article data or error.
    
    Get your API key: https://dev.to/settings/extensions → "DEV Community API Keys"
    """
    api_key = os.environ.get("DEVTO_API_KEY", "")
    if not api_key:
        logger.warning("DEVTO_API_KEY not set — skipping publish, saving draft locally")
        save_draft(article)
        return {"error": "no_api_key", "saved_locally": True}

    payload = {
        "article": {
            "title": article["title"],
            "body_markdown": article["content"],
            "published": True,
            "tags": article["tags"][:4],
        }
    }

    try:
        r = requests.post(
            f"{DEVTO_API}/articles",
            headers={"api-key": api_key, "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
        if r.status_code == 201:
            data = r.json()
            url = data.get("url", "")
            logger.info(f"Published: {url}")
            return {"success": True, "url": url, "id": data.get("id")}
        else:
            logger.warning(f"Dev.to publish failed: {r.status_code} {r.text}")
            save_draft(article)
            return {"error": r.text, "status": r.status_code}
    except Exception as e:
        save_draft(article)
        return {"error": str(e)}


def save_draft(article: dict):
    """Save article locally when Dev.to publish fails."""
    import time
    fname = f"logs/draft_{int(time.time())}.md"
    with open(fname, "w") as f:
        f.write(f"# {article['title']}\n\n")
        f.write(f"Tags: {', '.join(article['tags'])}\n\n")
        f.write(article["content"])
    logger.info(f"Draft saved: {fname}")


# ---------------------------------------------------------------------------
# Log published content
# ---------------------------------------------------------------------------

def log_content(title: str, url: str, tags: list):
    db = get_db()
    db.execute(
        "INSERT INTO content_log (ts, title, platform, url) VALUES (?, ?, ?, ?)",
        (datetime.now(timezone.utc).isoformat(), title, "dev.to", url),
    )
    db.commit()
    db.close()


# ---------------------------------------------------------------------------
# Main vehicle function
# ---------------------------------------------------------------------------

def run(dry_run: bool = False) -> dict:
    """
    Full content affiliate cycle:
    1. Get trending topics
    2. Pick best one (not already published)
    3. Write article with affiliate links
    4. Publish to Dev.to
    5. Log result
    """
    logger.info("Content affiliate cycle starting...")

    # Get already-published titles to avoid duplicates
    db = get_db()
    published_titles = {
        r[0] for r in db.execute("SELECT title FROM content_log").fetchall()
    }
    db.close()

    topics = get_trending_topics()
    # Filter already-published
    fresh_topics = [t for t in topics if t not in published_titles]
    if not fresh_topics:
        fresh_topics = topics  # if all published somehow, just repeat cycle

    topic = pick_best_topic(fresh_topics)
    logger.info(f"Writing article: {topic}")

    article = write_article(topic)

    if dry_run:
        print(f"\n--- DRY RUN: Would publish ---")
        print(f"Title: {article['title']}")
        print(f"Tags: {article['tags']}")
        print(f"Content preview: {article['content'][:300]}...")
        return {"success": True, "dry_run": True, "title": article["title"]}

    result = publish_to_devto(article)
    url = result.get("url", "local_draft")
    success = result.get("success", False)

    log_content(article["title"], url, article["tags"])
    log_cycle(
        vehicle="content_affiliate",
        action=f"published: {article['title'][:60]}",
        success=success,
        revenue=0,  # revenue comes later from clicks; updated manually
        detail=json.dumps({"url": url, "tags": article["tags"]}),
    )

    return {
        "success": success,
        "title": article["title"],
        "url": url,
        "tags": article["tags"],
    }
