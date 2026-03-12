# UX Job Hunter 🔍

Automated UX Research job search tool that scrapes job boards, evaluates fit using Claude, and outputs a ranked spreadsheet.

## Quick Start

```bash
# 1. Install dependencies
pip install anthropic pyyaml

# 2. Set your API key
export ANTHROPIC_API_KEY="sk-ant-..."

# 3. Run it
python job_hunter.py

# 4. Check results
open results/jobs_2026-02-13.csv
```

## How It Works

The script runs three modules in sequence:

| Module | What it does | Future agent |
|--------|-------------|--------------|
| **Discoverer** | Scrapes Greenhouse + Lever job boards for UX research roles | Agent A |
| **Evaluator** | Sends each job + your resume to Claude for fit scoring (1-10) | Agent B |
| **Tracker** | Saves ranked results to CSV with reasoning and cover letter hooks | Agent C |

## Customization

Edit `config.yaml` to change:
- Target job titles and keywords
- Preferred locations
- Companies to include/exclude
- Claude model (Sonnet for daily runs, Opus for deep analysis)

### Adding Companies

Find the company's ATS slug:
- **Greenhouse**: Look for `boards.greenhouse.io/{slug}` on their careers page
- **Lever**: Look for `jobs.lever.co/{slug}` on their careers page

Then add the slug to `_load_greenhouse_companies()` or `_load_lever_companies()` in `job_hunter.py`.

## Running Daily (Cron / GitHub Actions)

### Cron (Mac/Linux)
```bash
# Run every morning at 8am
0 8 * * * cd /path/to/ux_job_hunter && python job_hunter.py >> cron.log 2>&1
```

### GitHub Actions
Create `.github/workflows/job_search.yml`:
```yaml
name: Daily Job Search
on:
  schedule:
    - cron: '0 13 * * *'  # 8am EST
  workflow_dispatch:

jobs:
  search:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install anthropic pyyaml
      - run: python job_hunter.py
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
      - uses: actions/upload-artifact@v4
        with:
          name: job-results
          path: results/
```

## Upgrade Path to Level 3 (Multi-Agent)

The code is already structured for this. Each module becomes its own agent:

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Agent A:    │────▶│  Agent B:    │────▶│  Agent C:    │
│  Discoverer  │     │  Evaluator   │     │  Writer      │
│              │     │              │     │              │
│  Scrapes     │     │  Scores fit  │     │  Drafts      │
│  job boards  │     │  via Claude  │     │  cover       │
│              │     │              │     │  letters     │
└─────────────┘     └─────────────┘     └─────────────┘
        │                                       │
        ▼                                       ▼
   jobs.json                            results.csv
                                        cover_letters/
```

To upgrade:
1. Wrap each class in a LangGraph node or CrewAI agent
2. Define the handoff schema (JobPosting dataclass already works)
3. Add a human-in-the-loop approval step before Agent C generates materials
4. Optionally add an Agent D that auto-fills application forms

## Cost Estimate

- ~50 jobs/day × ~1500 tokens per evaluation ≈ 75K tokens/day
- With Claude Sonnet: roughly $0.15-0.25/day
- With Claude Opus: roughly $1-2/day

## Limitations

- LinkedIn scraping is not included (their anti-bot measures are aggressive; use their job alerts email instead and pipe those in)
- Only covers Greenhouse and Lever ATS platforms currently
- No auto-apply functionality (intentional — you want human review)
