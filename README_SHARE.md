# UX Job Hunter

Automated job search tool that scrapes 80+ company career pages, scores each job against your resume using Claude AI, and outputs a ranked spreadsheet with cover letter hooks.

## What It Does

The script runs a 3-step pipeline:

1. **Discover** - Scrapes Greenhouse, Lever, and Ashby job boards (used by most tech companies) plus FAANG career pages (Google, Amazon, Meta, Apple, Microsoft, Snap, Canva). Finds UX Research, Design Research, Mixed Methods, and related roles.

2. **Evaluate** - Sends each job description + your resume to Claude AI, which scores fit on a 1-10 scale. It identifies matching skills, gaps, and writes a one-line cover letter hook for each role.

3. **Save** - Outputs a CSV file ranked by fit score. Open it in Excel or Google Sheets to browse your best matches.

## Setup (5 minutes)

### 1. Install Python

You need Python 3.9 or newer. Check if you have it:

```bash
python3 --version
```

If not installed, download from [python.org](https://www.python.org/downloads/).

### 2. Install Dependencies

```bash
pip install anthropic pyyaml
```

**Optional** (for scraping Google, Apple, Meta career pages directly):
```bash
pip install playwright
playwright install chromium
```
Without Playwright, those companies will show as direct search links instead of individual job listings. Everything else works fine without it.

### 3. Get a Claude API Key

1. Go to [console.anthropic.com](https://console.anthropic.com)
2. Create an account and add a payment method
3. Go to API Keys and create a new key (starts with `sk-ant-...`)
4. Keep this key private — don't share it or commit it to GitHub

**Cost:** The tool uses Claude Sonnet by default. Expect roughly $0.15-0.25 per run (evaluating ~50 jobs). You can switch to Claude Opus in `config.yaml` for deeper analysis (~$1-2/run).

### 4. Add Your Resume

**Option A (recommended):** Save your resume as a plain text file called `resume.txt` in the same folder as the script. Just copy-paste the text from your resume — no special formatting needed.

**Option B:** Open `job_hunter_share.py`, find the `load_resume()` function (search for "PASTE YOUR RESUME TEXT HERE"), and paste your resume text directly into that placeholder.

### 5. Set Your API Key

**Option A (terminal):**
```bash
export ANTHROPIC_API_KEY="sk-ant-your-key-here"
```

**Option B (config file):** Uncomment and fill in the `anthropic_api_key` line in `config.yaml`:
```yaml
anthropic_api_key: "sk-ant-your-key-here"
```

## Running It

```bash
python job_hunter_share.py
```

The script takes a few minutes to run (it's politely rate-limiting itself). You'll see progress in the terminal. Results appear in the `results/` folder as a CSV file named with today's date.

## Customizing Your Search

### Edit config.yaml

```yaml
# Job titles to search for — add or remove as needed
job_titles:
  - "UX Researcher"
  - "User Researcher"
  - "Design Researcher"
  - "Mixed Methods Researcher"
  # Add more titles here

# Your preferred locations
locations:
  - "Remote"
  - "New York, NY"
  - "San Francisco, CA"
  # Add your city here

# Experience levels: entry_level, mid_level, internship
experience_levels:
  - entry_level
  - mid_level
  - internship

# Only show jobs posted within this many days
posted_within_days: 7

# Companies to skip (already applied, not interested, etc.)
exclude_companies: []

# AI model: claude-sonnet-4-20250514 (cheaper) or claude-opus-4-6 (deeper)
claude_model: "claude-sonnet-4-20250514"
```

### For Anthropologists Transitioning to UX

The tool is already configured for UX Research roles, but you might want to add titles that match your specific background:

```yaml
job_titles:
  - "UX Researcher"
  - "User Researcher"
  - "Design Researcher"
  - "Mixed Methods Researcher"
  - "Qualitative Researcher"
  - "Ethnographic Researcher"      # add this
  - "Social Scientist"             # add this
  - "Behavioral Researcher"        # add this
  - "Research Scientist UX"
```

The AI evaluator already understands that academic research skills — ethnography, qualitative methods, fieldwork, IRB experience, participant recruitment — transfer directly to UX research. It will score you fairly even without prior industry UX titles.

### Adding More Companies

The script comes with 80+ companies pre-configured. To add more:

1. Go to a company's careers page
2. Look at the URL:
   - `boards.greenhouse.io/companyname` → add `"companyname"` to `_load_greenhouse_companies()` in the script
   - `jobs.lever.co/companyname` → add to `_load_lever_companies()`
   - `jobs.ashbyhq.com/companyname` → add to `_load_ashby_companies()`

## Understanding the Output CSV

Open the results CSV in Excel or Google Sheets. Key columns:

| Column | What It Means |
|--------|--------------|
| **fit_score** | 1-10 rating of how well you match (7+ = strong, 5-6 = worth trying, <5 = stretch) |
| **seniority_level** | intern / junior / mid / senior / staff |
| **title** | Job title |
| **company** | Company name |
| **url** | Direct link to the job posting |
| **matching_skills** | Skills from your resume that match the role |
| **skill_gaps** | What you're missing (useful for cover letters) |
| **cover_letter_hook** | A one-liner connecting your experience to this role — use as a starting point |

### How to Use the Results

1. Sort by `fit_score` descending
2. Focus on roles scoring 6 or higher
3. Read the `skill_gaps` column to know what to address in your cover letter
4. Use the `cover_letter_hook` as inspiration for your opening paragraph
5. Click the `url` to go directly to the application

## Running Daily (Optional)

You can set this up to run automatically every morning:

```bash
# Mac/Linux: add to crontab (run 'crontab -e')
0 8 * * * cd /path/to/ux_job_hunter && export ANTHROPIC_API_KEY="your-key" && python job_hunter_share.py >> cron.log 2>&1
```

## Tips for Anthropologists Making the Transition

- **Your fieldwork IS research experience.** Long-term ethnographic fieldwork demonstrates project management, participant recruitment, data collection, and analysis at a depth most industry researchers never achieve.
- **Frame ethnographic methods as "qualitative user research at scale."** Interviews, participant observation, and thematic analysis are core UX research methods.
- **IRB experience = research ethics.** Companies value researchers who understand consent, privacy, and ethical data handling.
- **Focus on roles scoring 6+ in your results.** The AI understands the academic-to-industry translation.
- **Use the cover_letter_hook column** as a starting point for applications — it's designed to connect your academic background to each specific role.
- **Don't skip "Research Scientist" roles.** At companies like Google, Meta, and Amazon, these are often UX research positions that value PhD-level methodological rigor.

## Troubleshooting

**"No ANTHROPIC_API_KEY found"** — The script runs in discovery-only mode (finds jobs but can't score them). Set your API key per step 5 above.

**"No resume found"** — Save your resume as `resume.txt` in the same folder, or paste it into the script.

**"No matching jobs found"** — Try adding more companies to the lists in the script, or broaden your job titles in `config.yaml`.

**Playwright errors** — Playwright is optional. If it's causing issues, just uninstall it (`pip uninstall playwright`). You'll still get jobs from 80+ companies via Greenhouse/Lever/Ashby. Only FAANG direct scraping requires it.

**Rate limiting / timeout errors** — The script is polite with 1-2 second delays between requests. If a company's API is down, it skips gracefully and moves on.
