# UX Job Hunter — Web App

A web-based job search tool that scrapes 80+ company career pages, scores each job against your resume using Claude AI, and shows ranked results with cover letter hooks.

## Quick Start (Local)

```bash
cd ux_job_hunter_web

# Install dependencies
pip install -r backend/requirements.txt

# Run the server
uvicorn backend.main:app --reload --port 8080

# Open http://localhost:8080
```

## How It Works

1. **Upload your resume** (PDF or TXT)
2. **AI analyzes it** and suggests job titles, skills, locations
3. **Customize your search** — edit keywords, pick experience levels
4. **Get scored results** — jobs ranked 1-10 with matching skills, gaps, and cover letter hooks

You'll need an [Anthropic API key](https://console.anthropic.com) (~$0.15-0.25 per search run with Sonnet).

## Deploy to Railway

```bash
# Install Railway CLI
npm install -g @railway/cli

# Deploy
railway login
railway init
railway up
```

Or use Docker:

```bash
docker build -t ux-job-hunter .
docker run -p 8080:8080 ux-job-hunter
```

## Architecture

- **Backend:** Python FastAPI — wraps existing job scraping + Claude evaluation pipeline
- **Frontend:** Vanilla HTML/JS + Tailwind CSS (no build step)
- **API key:** Users bring their own Anthropic key (entered in browser, never stored)
- **Data sources:** Greenhouse, Lever, Ashby job board APIs + Amazon Jobs API (~80 companies)

## Cost

All API costs are paid by the user through their own Anthropic key:
- ~50 jobs/run × ~1500 tokens/eval = ~75K tokens
- Claude Sonnet: ~$0.15-0.25 per run
- Claude Opus: ~$1-2 per run
