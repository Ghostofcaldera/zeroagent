# ZeroAgent

Autonomous earning agent — zero investment. Runs on free AI tiers (Gemini, Groq, OpenRouter, Ollama) via GitHub Actions every 30 minutes.

## Vehicles
- **Content Affiliate** — scrapes trending dev topics, generates articles with affiliate links, publishes to Dev.to
- **Bounty Hunter** — finds stale GitHub bounty issues, filters scams, posts intent comments, submits PRs

## Setup
1. Fork or clone this repo
2. Add these secrets in Settings → Secrets and variables → Actions:
   - `GEMINI_API_KEY`
   - `GROQ_API_KEY`
   - `OPENROUTER_API_KEY`
   - `DEVTO_API_KEY`
   - `GITHUB_TOKEN`
3. Enable the workflow in Actions tab

The agent runs automatically every 30 minutes. Run manually with `workflow_dispatch`.
