"""
UX Research Job Hunter — Web Backend Module
=============================================
Adapted from job_hunter_share.py for use with a FastAPI web frontend.

Removes Playwright/FAANG scrapers and CLI entrypoints.
Adds progress callbacks for real-time SSE streaming.

Author: Dejan Duric
"""

import os
import io
import json
import csv
import time
import re
import logging
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

@dataclass
class SearchConfig:
    """All tunable knobs in one place. Override via config.yaml or CLI."""

    # --- Target roles ---
    job_titles: list = field(default_factory=lambda: [
        "UX Researcher",
        "User Researcher",
        "Research Scientist UX",
        "Mixed Methods Researcher",
        "Qualitative Researcher",
        "Design Researcher",
        "UXR Intern",
        "UX Research Intern",
        "Research Scientist Intern",
    ])

    # --- Location preferences ---
    locations: list = field(default_factory=lambda: [
        "Ann Arbor, MI",
        "Detroit, MI",
        "Chicago, IL",
        "Remote",
        "New York, NY",
        "San Francisco, CA",
        "Seattle, WA",
    ])

    # --- Filters ---
    experience_levels: list = field(default_factory=lambda: [
        "entry_level",
        "mid_level",
        "internship",
    ])
    posted_within_days: int = 7
    exclude_companies: list = field(default_factory=list)

    # --- Resume text (your resume, used for fit scoring) ---
    resume_text: str = ""

    # --- API settings ---
    anthropic_api_key: str = ""
    claude_model: str = "claude-haiku-4-5-20251001"
    max_tokens: int = 1024

    # --- Output ---
    output_dir: str = "results"

    def load_from_yaml(self, path: str = "config.yaml"):
        """Optionally load overrides from a YAML file."""
        try:
            import yaml
            with open(path) as f:
                overrides = yaml.safe_load(f) or {}
            for k, v in overrides.items():
                if hasattr(self, k):
                    setattr(self, k, v)
        except FileNotFoundError:
            pass  # Use defaults
        except ImportError:
            pass  # PyYAML not installed, use defaults


# ---------------------------------------------------------------------------
# DATA MODEL
# ---------------------------------------------------------------------------

@dataclass
class JobPosting:
    """A single scraped job listing."""
    title: str = ""
    company: str = ""
    location: str = ""
    url: str = ""
    description: str = ""
    date_posted: str = ""
    source: str = ""           # "greenhouse", "lever", "linkedin", etc.
    salary_range: str = ""
    experience_level: str = ""

    # --- Filled in by the evaluator ---
    fit_score: float = 0.0     # 1-10
    seniority_level: str = ""  # intern/junior/mid/senior/staff
    fit_reasoning: str = ""
    matching_skills: str = ""
    skill_gaps: str = ""
    cover_letter_hook: str = ""  # One-liner to personalize outreach


# ---------------------------------------------------------------------------
# MODULE 1: DISCOVERY (-> future Agent A)
# ---------------------------------------------------------------------------

class JobDiscoverer:
    """
    Finds job postings from multiple sources.

    Supported sources:
    - Greenhouse boards (many tech companies)
    - Lever boards
    - Ashby boards (newer ATS, used by OpenAI, Notion, etc.)
    - SmartRecruiters (Visa, IKEA, Spotify, etc.)
    - Workable (Hotjar, Mural, dscout, etc.)
    - BambooHR (Qualtrics, FullStory, Pendo, etc.)
    - Amazon Jobs (public JSON API)

    To add a new source, just add a scrape_* method.
    """

    def __init__(self, config: SearchConfig):
        self.config = config
        self.logger = logging.getLogger("discoverer")
        self.seen_urls: set = set()

    def discover_all(self, on_progress=None) -> list[JobPosting]:
        """Run all discovery sources and return deduplicated results."""
        all_jobs = []

        # --- Greenhouse boards ---
        greenhouse_companies = self._load_greenhouse_companies()
        for company_slug in greenhouse_companies:
            try:
                jobs = self.scrape_greenhouse(company_slug)
                all_jobs.extend(jobs)
                if on_progress:
                    on_progress({"phase": "discovery", "source": "greenhouse", "company": company_slug, "found_so_far": len(all_jobs)})
                time.sleep(1)  # Be polite
            except Exception as e:
                self.logger.warning(f"Greenhouse error for {company_slug}: {e}")

        # --- Lever boards ---
        lever_companies = self._load_lever_companies()
        for company_slug in lever_companies:
            try:
                jobs = self.scrape_lever(company_slug)
                all_jobs.extend(jobs)
                if on_progress:
                    on_progress({"phase": "discovery", "source": "lever", "company": company_slug, "found_so_far": len(all_jobs)})
                time.sleep(1)
            except Exception as e:
                self.logger.warning(f"Lever error for {company_slug}: {e}")

        # --- Ashby boards ---
        ashby_companies = self._load_ashby_companies()
        for company_slug in ashby_companies:
            try:
                jobs = self.scrape_ashby(company_slug)
                all_jobs.extend(jobs)
                if on_progress:
                    on_progress({"phase": "discovery", "source": "ashby", "company": company_slug, "found_so_far": len(all_jobs)})
                time.sleep(1)
            except Exception as e:
                self.logger.warning(f"Ashby error for {company_slug}: {e}")

        # --- SmartRecruiters boards ---
        smartrecruiters_companies = self._load_smartrecruiters_companies()
        for company_id in smartrecruiters_companies:
            try:
                jobs = self.scrape_smartrecruiters(company_id)
                all_jobs.extend(jobs)
                if on_progress:
                    on_progress({"phase": "discovery", "source": "smartrecruiters", "company": company_id, "found_so_far": len(all_jobs)})
                time.sleep(1)
            except Exception as e:
                self.logger.warning(f"SmartRecruiters error for {company_id}: {e}")

        # --- Workable boards ---
        workable_companies = self._load_workable_companies()
        for subdomain in workable_companies:
            try:
                jobs = self.scrape_workable(subdomain)
                all_jobs.extend(jobs)
                if on_progress:
                    on_progress({"phase": "discovery", "source": "workable", "company": subdomain, "found_so_far": len(all_jobs)})
                time.sleep(1)
            except Exception as e:
                self.logger.warning(f"Workable error for {subdomain}: {e}")

        # --- BambooHR boards ---
        bamboohr_companies = self._load_bamboohr_companies()
        for subdomain in bamboohr_companies:
            try:
                jobs = self.scrape_bamboohr(subdomain)
                all_jobs.extend(jobs)
                if on_progress:
                    on_progress({"phase": "discovery", "source": "bamboohr", "company": subdomain, "found_so_far": len(all_jobs)})
                time.sleep(1)
            except Exception as e:
                self.logger.warning(f"BambooHR error for {subdomain}: {e}")

        # --- Amazon Jobs (public JSON API, no Playwright) ---
        try:
            amazon_jobs = self._scrape_amazon_careers()
            all_jobs.extend(amazon_jobs)
            if on_progress:
                on_progress({"phase": "discovery", "source": "amazon_jobs", "company": "amazon", "found_so_far": len(all_jobs)})
        except Exception as e:
            self.logger.warning(f"Amazon scraping error: {e}")

        # --- Deduplicate ---
        unique_jobs = []
        for job in all_jobs:
            if job.url not in self.seen_urls:
                self.seen_urls.add(job.url)
                unique_jobs.append(job)

        self.logger.info(f"Discovered {len(unique_jobs)} unique jobs")
        return unique_jobs

    # ---- Greenhouse (public JSON API) ----

    def scrape_greenhouse(self, company_slug: str) -> list[JobPosting]:
        """
        Greenhouse exposes a public JSON API:
        https://boards-api.greenhouse.io/v1/boards/{slug}/jobs

        No auth needed. Returns all open jobs.
        """
        import urllib.request

        url = f"https://boards-api.greenhouse.io/v1/boards/{company_slug}/jobs?content=true"
        self.logger.info(f"Scraping Greenhouse: {company_slug}")

        req = urllib.request.Request(url, headers={"User-Agent": "JobHunter/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        jobs = []
        for item in data.get("jobs", []):
            title = item.get("title", "")
            if not self._matches_title(title):
                continue

            location_name = item.get("location", {}).get("name", "")

            # Parse HTML description to plain text
            raw_html = item.get("content", "")
            description = self._strip_html(raw_html)

            posted = item.get("updated_at", "")[:10]

            job = JobPosting(
                title=title,
                company=company_slug.replace("-", " ").title(),
                location=location_name,
                url=item.get("absolute_url", ""),
                description=description[:3000],  # Truncate for token savings
                date_posted=posted,
                source="greenhouse",
            )
            jobs.append(job)

        return jobs

    # ---- Lever (public JSON API) ----

    def scrape_lever(self, company_slug: str) -> list[JobPosting]:
        """
        Lever also has a public API:
        https://api.lever.co/v0/postings/{slug}?mode=json
        """
        import urllib.request

        url = f"https://api.lever.co/v0/postings/{company_slug}?mode=json"
        self.logger.info(f"Scraping Lever: {company_slug}")

        req = urllib.request.Request(url, headers={"User-Agent": "JobHunter/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        jobs = []
        for item in data:
            title = item.get("text", "")
            if not self._matches_title(title):
                continue

            location_name = item.get("categories", {}).get("location", "")
            description_plain = item.get("descriptionPlain", "")
            additional = " ".join(
                lst.get("text", "") + " " + lst.get("content", "")
                for lst in item.get("lists", [])
            )

            job = JobPosting(
                title=title,
                company=company_slug.replace("-", " ").title(),
                location=location_name,
                url=item.get("hostedUrl", ""),
                description=(description_plain + "\n" + self._strip_html(additional))[:3000],
                date_posted=datetime.fromtimestamp(
                    item.get("createdAt", 0) / 1000
                ).strftime("%Y-%m-%d") if item.get("createdAt") else "",
                source="lever",
            )
            jobs.append(job)

        return jobs

    # ---- Ashby (public JSON API) ----

    def scrape_ashby(self, company_slug: str) -> list[JobPosting]:
        """
        Ashby has a public posting API:
        https://api.ashbyhq.com/posting-api/job-board/{slug}

        No auth needed. Returns all open job postings as JSON.
        """
        import urllib.request

        url = f"https://api.ashbyhq.com/posting-api/job-board/{company_slug}"
        self.logger.info(f"Scraping Ashby: {company_slug}")

        req = urllib.request.Request(url, headers={"User-Agent": "JobHunter/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        jobs = []
        for item in data.get("jobs", []):
            title = item.get("title", "")
            if not self._matches_title(title):
                continue

            # Location from address fields
            address = item.get("address", {}).get("postalAddress", {}) if item.get("address") else {}
            location_parts = [
                address.get("addressLocality", ""),
                address.get("addressRegion", ""),
                address.get("addressCountry", ""),
            ]
            location_name = item.get("location", "")
            if not location_name:
                location_name = ", ".join(p for p in location_parts if p)
            if item.get("isRemote"):
                location_name = f"{location_name} (Remote)" if location_name else "Remote"

            # Description: prefer plain text, fall back to stripping HTML
            description = item.get("descriptionPlain", "")
            if not description:
                description = self._strip_html(item.get("descriptionHtml", ""))

            posted = item.get("publishedAt", "")[:10] if item.get("publishedAt") else ""

            job = JobPosting(
                title=title,
                company=company_slug.replace("-", " ").title(),
                location=location_name,
                url=item.get("jobUrl", ""),
                description=description[:3000],
                date_posted=posted,
                source="ashby",
            )
            jobs.append(job)

        return jobs

    # ---- Amazon Jobs (public JSON API, no Playwright) ----

    def _scrape_amazon_careers(self) -> list[JobPosting]:
        """
        Amazon Jobs has a public JSON API — no Playwright needed.
        https://www.amazon.jobs/en/search.json?base_query=UX+Researcher
        """
        import urllib.request
        import urllib.parse

        jobs = []

        for term in ["UX Researcher", "User Experience Researcher"]:
            api_url = f"https://www.amazon.jobs/en/search.json?base_query={urllib.parse.quote(term)}&category%5B%5D=user-experience-design&category%5B%5D=research-science"

            req = urllib.request.Request(api_url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept": "application/json",
            })

            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode())

                for item in data.get("jobs", []):
                    title = item.get("title", "")
                    if not self._matches_title(title):
                        continue

                    jobs.append(JobPosting(
                        title=title,
                        company="Amazon",
                        location=item.get("normalized_location", item.get("location", "")),
                        url=f"https://www.amazon.jobs{item.get('job_path', '')}",
                        description=self._strip_html(item.get("description", ""))[:3000],
                        date_posted=item.get("posted_date", ""),
                        source="amazon_jobs",
                    ))
            except Exception:
                self.logger.warning(f"Amazon search failed for term: {term}")

            time.sleep(1)

        return jobs

    # ---- SmartRecruiters (public JSON API) ----

    def scrape_smartrecruiters(self, company_id: str) -> list[JobPosting]:
        """
        SmartRecruiters has a public API:
        https://api.smartrecruiters.com/v1/companies/{id}/postings
        """
        import urllib.request

        url = f"https://api.smartrecruiters.com/v1/companies/{company_id}/postings?limit=100"
        self.logger.info(f"Scraping SmartRecruiters: {company_id}")

        req = urllib.request.Request(url, headers={"User-Agent": "JobHunter/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        jobs = []
        for item in data.get("content", []):
            title = item.get("name", "")
            if not self._matches_title(title):
                continue

            location = item.get("location", {})
            location_parts = [
                location.get("city", ""),
                location.get("region", ""),
                location.get("country", ""),
            ]
            location_name = ", ".join(p for p in location_parts if p)
            if location.get("remote"):
                location_name = f"{location_name} (Remote)" if location_name else "Remote"

            # Get posting date
            released = item.get("releasedDate", "")[:10] if item.get("releasedDate") else ""

            # SmartRecruiters listing endpoint doesn't include full description,
            # so we use the company/job name context
            department = item.get("department", {}).get("label", "")
            description = f"{title} at {company_id.replace('-', ' ').title()}. Department: {department}."

            job_id = item.get("id", "")
            job_url = f"https://jobs.smartrecruiters.com/{company_id}/{job_id}"

            jobs.append(JobPosting(
                title=title,
                company=item.get("company", {}).get("name", company_id.replace("-", " ").title()),
                location=location_name,
                url=job_url,
                description=description[:3000],
                date_posted=released,
                source="smartrecruiters",
            ))

        return jobs

    # ---- Workable (public JSON API) ----

    def scrape_workable(self, subdomain: str) -> list[JobPosting]:
        """
        Workable has a public widget API:
        https://apply.workable.com/api/v1/widget/accounts/{subdomain}
        """
        import urllib.request

        url = f"https://apply.workable.com/api/v1/widget/accounts/{subdomain}"
        self.logger.info(f"Scraping Workable: {subdomain}")

        req = urllib.request.Request(url, headers={"User-Agent": "JobHunter/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        jobs = []
        for item in data.get("jobs", []):
            title = item.get("title", "")
            if not self._matches_title(title):
                continue

            location_name = item.get("location", "")
            if item.get("telecommuting"):
                location_name = f"{location_name} (Remote)" if location_name else "Remote"

            posted = item.get("published", "")[:10] if item.get("published") else ""

            shortcode = item.get("shortcode", "")
            job_url = f"https://apply.workable.com/{subdomain}/j/{shortcode}/" if shortcode else ""

            description = item.get("description", "")

            jobs.append(JobPosting(
                title=title,
                company=subdomain.replace("-", " ").title(),
                location=location_name,
                url=job_url,
                description=self._strip_html(description)[:3000],
                date_posted=posted,
                source="workable",
            ))

        return jobs

    # ---- BambooHR (public job board API) ----

    def scrape_bamboohr(self, subdomain: str) -> list[JobPosting]:
        """
        BambooHR has a public job board API:
        https://{subdomain}.bamboohr.com/careers/list
        """
        import urllib.request

        url = f"https://{subdomain}.bamboohr.com/careers/list"
        self.logger.info(f"Scraping BambooHR: {subdomain}")

        req = urllib.request.Request(url, headers={
            "User-Agent": "JobHunter/1.0",
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        jobs = []
        for item in data.get("result", []):
            title = item.get("jobOpeningName", "")
            if not self._matches_title(title):
                continue

            location_parts = [
                item.get("location", {}).get("city", ""),
                item.get("location", {}).get("state", ""),
                item.get("location", {}).get("country", ""),
            ]
            location_name = ", ".join(p for p in location_parts if p)

            posted = item.get("datePosted", "")[:10] if item.get("datePosted") else ""

            job_id = item.get("id", "")
            job_url = f"https://{subdomain}.bamboohr.com/careers/{job_id}" if job_id else ""

            department = item.get("departmentLabel", "")
            description = f"{title}. Department: {department}." if department else title

            jobs.append(JobPosting(
                title=title,
                company=subdomain.replace("-", " ").title(),
                location=location_name,
                url=job_url,
                description=description[:3000],
                date_posted=posted,
                source="bamboohr",
            ))

        return jobs

    # ---- Helpers ----

    def _matches_title(self, title: str) -> bool:
        """Check if a job title matches our target roles (fuzzy)."""
        title_lower = title.lower()

        # --- EXCLUDE obviously wrong roles first ---
        exclude_keywords = [
            "machine learning", "ml engineer", "ml research",
            "genai research scientist", "pre-training", "post-training",
            "biological", "biology", "life science",
            "software engineer", "data engineer", "devops",
            "sales", "marketing", "account executive",
            "vision research", "audio research", "speech research",
            "interpretability", "alignment finetuning",
            "reward model", "llm eval", "ai algorithm",
            "6g", "vlm",  # Very specific ML/hardware roles
        ]
        if any(ex in title_lower for ex in exclude_keywords):
            return False

        # --- INCLUDE matching UX/user research roles ---
        keywords = [
            # Core UX research titles
            "ux research", "user research", "design research",
            "uxr ",  # "UXR " with space to avoid false matches
            # Research scientist / academic-adjacent
            "research scientist", "research analyst",
            # Method-specific titles
            "mixed method", "qualitative research", "quantitative research",
            # Broader research roles that may fit
            "insights research", "product research", "behavioral scientist",
            "human factors", "experience research",
            # Intern/entry level
            "research intern", "ux intern", "design intern",
            "user experience intern", "research associate",
            # Internship-specific patterns
            "intern, research", "intern, ux", "intern, design",
            "intern - research", "intern – research",
        ]
        return any(kw in title_lower for kw in keywords)

    def _is_ux_relevant(self, description: str) -> bool:
        """
        Quick local check: does the description mention UX-related terms?
        Used to skip obviously irrelevant jobs BEFORE sending to Claude.
        Saves API credits.
        """
        if not description:
            return True  # No description = can't filter, let Claude decide

        desc_lower = description.lower()
        ux_signals = [
            "qualitative", "user interview", "usability",
            "ethnograph", "survey", "ux ", "user experience",
            "user research", "design research", "mixed method",
            "participant", "focus group", "persona",
            "journey map", "card sort", "tree test",
            "user need", "user behavior", "human factor",
            "human-computer", "hci",
            # Academic disciplines that signal strong fit
            "anthropolog", "linguist", "ethnograph",
            "social science", "sociology",
        ]
        return any(signal in desc_lower for signal in ux_signals)

    def _strip_html(self, html: str) -> str:
        """Remove HTML tags. Good enough for job descriptions."""
        return re.sub(r"<[^>]+>", " ", html).strip()

    def _load_greenhouse_companies(self) -> list[str]:
        """
        Curated list of companies with Greenhouse boards.

        HOW TO FIND MORE:
        - Check a company's careers page URL — if it contains
          "greenhouse.io" or "boards.greenhouse.io", grab the slug.
        - Example: boards.greenhouse.io/airbnb -> slug = "airbnb"

        Add/remove companies as you like.
        """
        return [
            # ===== Big tech / platforms (VERIFIED working) =====
            "airbnb",
            "figma",
            "duolingo",
            "stripe",
            "discord",
            "pinterest",
            "lyft",
            "coinbase",
            "roblox",
            "databricks",
            "dropbox",
            "squarespace",
            "hubspot",
            "twilio",
            "gitlab",
            "reddit",
            "grammarly",
            "airtable",
            "webflow",
            "calendly",
            "wayfair",       # Recovered: was using embed URL format
            "doordashusa",   # Recovered: slug is doordashusa, not doordash

            # ===== AI / ML companies =====
            "anthropic",
            "scaleai",

            # ===== Fintech =====
            "robinhood",
            "chime",
            "brex",
            "affirm",
            "sofi",
            "mercury",

            # ===== Health / wellness =====
            "calm",
            "cerebral",

            # ===== E-commerce / marketplace =====
            "instacart",
            "poshmark",
            "faire",
            "stockx",

            # ===== Enterprise / productivity =====
            "asana",
            "lattice",
            "gusto",
            "carta",
            "braze",
            "amplitude",
            "mixpanel",
            "contentful",

            # ===== Research-heavy / mission-driven =====
            "wikimedia",
            "khanacademy",
            "mozilla",
            "coursera",

            # ===== Media / entertainment =====
            "buzzfeed",
            "medium",

            # ===== Consulting / agencies =====
            "ideo",

            # ===== Hardware / devices =====
            "peloton",

            # ===== Travel =====
            "tripadvisor",

            # ===== Samsung (has intern programs) =====
            "samsungresearchamericainternship",

            # Add more here!
        ]

    def _load_lever_companies(self) -> list[str]:
        """
        Same idea for Lever-based boards.
        Check: jobs.lever.co/{slug}
        """
        return [
            # ===== VERIFIED working =====
            "netflix",
            "spotify",        # Moved here from Greenhouse — confirmed on Lever

            # ===== Tech / SaaS =====
            "lever",          # Lever themselves

            # ===== Research / UX agencies =====
            "blinkux",
            "viget",

            # ===== Ed-tech / learning =====
            "articulate",

            # ===== Consumer / marketplace =====
            "rover",

            # ===== Fintech =====
            "tala",

            # ===== Healthcare =====
            "includedhealth",

            # Add more here!
        ]

    def _load_ashby_companies(self) -> list[str]:
        """
        Curated list of companies with Ashby job boards.

        HOW TO FIND MORE:
        - If a company's careers page links to jobs.ashbyhq.com/{slug},
          the slug goes here.
        - Public API: api.ashbyhq.com/posting-api/job-board/{slug}

        Add/remove companies as you like.
        """
        return [
            # ===== AI / ML companies =====
            "openai",

            # ===== Big tech / platforms =====
            "notion",

            # ===== E-commerce / marketplace =====
            "etsy",

            # ===== Enterprise / productivity =====
            "linear",
            "loom",
            "miro",
            "retool",

            # ===== Fintech =====
            "plaid",
            "ramp",

            # ===== Other tech =====
            "snap-inc",       # Snap may also have Ashby board
            "doordash",       # DoorDash may have Ashby in addition to Greenhouse
            "monday",
            "rippling",

            # Add more here!
        ]

    def _load_smartrecruiters_companies(self) -> list[str]:
        """
        Curated list of companies using SmartRecruiters.

        HOW TO FIND MORE:
        - Check a company's careers page — if it uses SmartRecruiters,
          the API ID is usually the company name in lowercase.
        - API: api.smartrecruiters.com/v1/companies/{id}/postings
        """
        return [
            # ===== Large enterprises =====
            "Visa",
            "IKEA",
            "Bosch",
            "Samsungelectronics",
            "Adidas",

            # ===== Tech =====
            "Spotify",
            "Skyscanner",
            "Booking",

            # ===== Consulting / services =====
            "Accenture",
            "Deloitte",

            # ===== Other =====
            "PhilipMorrisInternational",
            "Zalando",

            # Add more here!
        ]

    def _load_workable_companies(self) -> list[str]:
        """
        Curated list of companies using Workable.

        HOW TO FIND MORE:
        - Check if a company's careers page URL contains "apply.workable.com/{subdomain}"
        - API: apply.workable.com/api/v1/widget/accounts/{subdomain}
        """
        return [
            # ===== Tech / SaaS =====
            "mural",
            "testio",
            "maze-1",
            "hotjar",
            "typeform",
            "dovetail",
            "usertesting",
            "userlytics",

            # ===== Design / creative =====
            "invisionapp",
            "abstract",

            # ===== Research platforms =====
            "dscout",
            "respondent",

            # Add more here!
        ]

    def _load_bamboohr_companies(self) -> list[str]:
        """
        Curated list of companies using BambooHR.

        HOW TO FIND MORE:
        - Check if a company's careers page URL contains "{company}.bamboohr.com/careers"
        - API: {subdomain}.bamboohr.com/careers/list
        """
        return [
            # ===== Tech =====
            "qualtrics",
            "fullstory",
            "pendo",
            "mixpanel",
            "heap",

            # ===== Design / UX =====
            "blink",
            "fuzzymath",

            # ===== Research =====
            "userinterviews",

            # Add more here!
        ]


# ---------------------------------------------------------------------------
# MODULE 2: EVALUATOR (-> future Agent B)
# ---------------------------------------------------------------------------

class JobEvaluator:
    """
    Scores each job against your resume using Claude API.
    Returns structured JSON with fit score, reasoning, and gaps.
    """

    def __init__(self, config: SearchConfig):
        self.config = config
        self.logger = logging.getLogger("evaluator")

    def evaluate_batch(self, jobs: list[JobPosting], on_progress=None) -> list[JobPosting]:
        """Score all jobs. Returns the same list with fit fields populated."""
        import anthropic

        client = anthropic.Anthropic(api_key=self.config.anthropic_api_key)

        # Pre-filter: skip jobs whose descriptions are clearly not UX-related
        # This saves API credits on irrelevant "Research Scientist" ML roles
        discoverer = JobDiscoverer(self.config)

        skipped = 0
        for i, job in enumerate(jobs):
            # Skip API call if description clearly isn't UX-related
            # (but always evaluate jobs with no description, like FAANG links)
            if job.description and not discoverer._is_ux_relevant(job.description):
                self.logger.info(f"Skipping [{i+1}/{len(jobs)}]: {job.title} @ {job.company} (not UX-relevant)")
                job.fit_score = 0
                job.fit_reasoning = "Skipped: job description doesn't mention UX/user research terms"
                skipped += 1
                if on_progress:
                    on_progress({"phase": "evaluation", "current": i+1, "total": len(jobs), "title": job.title, "company": job.company})
                continue

            self.logger.info(f"Evaluating [{i+1}/{len(jobs)}]: {job.title} @ {job.company}")
            try:
                result = self._evaluate_single(client, job)
                job.fit_score = result.get("fit_score", 0)
                job.seniority_level = result.get("seniority_level", "")
                job.fit_reasoning = result.get("reasoning", "")
                job.matching_skills = result.get("matching_skills", "")
                job.skill_gaps = result.get("skill_gaps", "")
                job.cover_letter_hook = result.get("cover_letter_hook", "")
            except Exception as e:
                self.logger.warning(f"Evaluation failed for {job.url}: {e}")
                job.fit_score = 0
                job.fit_reasoning = f"Error: {e}"

            if on_progress:
                on_progress({"phase": "evaluation", "current": i+1, "total": len(jobs), "title": job.title, "company": job.company})

            time.sleep(0.5)  # Rate limiting courtesy

        if skipped:
            self.logger.info(f"Skipped {skipped} non-UX jobs, saving ~${skipped * 0.005:.2f} in API costs")

        return jobs

    def _evaluate_single(self, client, job: JobPosting) -> dict:
        """Call Claude to evaluate a single job."""

        system_prompt = """You are a career advisor evaluating job fit for a UX researcher candidate.
You will receive the candidate's resume and a job description.

KEY CONTEXT ABOUT THIS CANDIDATE:
- Review the candidate's resume carefully to understand their background
- Consider their education level, research experience, and transferable skills
- Academic research experience (fieldwork, IRB, data analysis, participant recruitment)
  transfers meaningfully to UX research
- Look for both direct UX experience and adjacent/transferable experience

SENIORITY CALIBRATION:
- Intern/New Grad/Junior roles (0-2 years): If candidate has relevant academic research, score 7-9
- Mid-level roles (2-4 years): If candidate has substantial research experience, score 6-8
- Senior roles (5+ years industry): Unless candidate has equivalent industry experience, score 3-5
- Staff/Principal roles (8+ years): Score 1-3 unless candidate clearly qualifies

Respond ONLY with valid JSON (no markdown, no backticks). Use this exact schema:
{
    "fit_score": <float 1-10>,
    "seniority_level": "<intern/junior/mid/senior/staff>",
    "reasoning": "<2-3 sentences on overall fit>",
    "matching_skills": "<comma-separated list of matching skills>",
    "skill_gaps": "<comma-separated list of gaps or missing requirements>",
    "cover_letter_hook": "<one compelling sentence connecting their experience to this role>"
}"""

        user_prompt = f"""## Candidate Resume
{self.config.resume_text}

## Job Posting
Title: {job.title}
Company: {job.company}
Location: {job.location}

Description:
{job.description[:2500]}

Evaluate this candidate's fit for this role. Be honest about gaps but also recognize that academic research experience (fieldwork, IRB, data analysis, participant recruitment) transfers meaningfully to UX research.
A score of 7+ means strong fit, 5-6 is worth applying with a good cover letter, below 5 is a stretch."""

        response = client.messages.create(
            model=self.config.claude_model,
            max_tokens=self.config.max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        text = response.content[0].text.strip()
        # Clean potential markdown fences
        text = re.sub(r"```json\s*", "", text)
        text = re.sub(r"```\s*", "", text)

        return json.loads(text)


# ---------------------------------------------------------------------------
# MODULE 3: OUTPUT / TRACKER (-> future Agent C for cover letters)
# ---------------------------------------------------------------------------

class ResultsTracker:
    """
    Saves results to CSV and optionally generates cover letter drafts.
    """

    def __init__(self, config: SearchConfig):
        self.config = config
        self.logger = logging.getLogger("tracker")
        Path(config.output_dir).mkdir(parents=True, exist_ok=True)

    def save_csv(self, jobs: list[JobPosting], filename: str = None) -> str:
        """Save evaluated jobs to a CSV, sorted by fit score descending."""
        if not filename:
            filename = f"jobs_{datetime.now().strftime('%Y-%m-%d')}.csv"

        filepath = os.path.join(self.config.output_dir, filename)

        # Sort by fit score, best first
        jobs_sorted = sorted(jobs, key=lambda j: j.fit_score, reverse=True)

        fieldnames = [
            "fit_score", "seniority_level", "title", "company", "location", "url",
            "date_posted", "source", "salary_range",
            "fit_reasoning", "matching_skills", "skill_gaps",
            "cover_letter_hook",
        ]

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for job in jobs_sorted:
                row = asdict(job)
                # Only write the columns we care about
                writer.writerow({k: row[k] for k in fieldnames})

        self.logger.info(f"Saved {len(jobs_sorted)} jobs to {filepath}")
        return filepath

    def to_csv_string(self, jobs: list[JobPosting]) -> str:
        """Return evaluated jobs as a CSV string, sorted by fit score descending."""
        jobs_sorted = sorted(jobs, key=lambda j: j.fit_score, reverse=True)

        fieldnames = [
            "fit_score", "seniority_level", "title", "company", "location", "url",
            "date_posted", "source", "salary_range",
            "fit_reasoning", "matching_skills", "skill_gaps",
            "cover_letter_hook",
        ]

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for job in jobs_sorted:
            row = asdict(job)
            writer.writerow({k: row[k] for k in fieldnames})

        return output.getvalue()

    def print_summary(self, jobs: list[JobPosting]):
        """Print a quick summary to terminal."""
        if not jobs:
            print("\nNo jobs found. Try broadening your search terms or adding more companies.")
            return

        jobs_sorted = sorted(jobs, key=lambda j: j.fit_score, reverse=True)

        print(f"\n{'='*70}")
        print(f"  JOB SEARCH RESULTS — {datetime.now().strftime('%Y-%m-%d')}")
        print(f"  Found {len(jobs)} jobs, showing top matches")
        print(f"{'='*70}\n")

        for i, job in enumerate(jobs_sorted[:15]):
            emoji = "🟢" if job.fit_score >= 7 else "🟡" if job.fit_score >= 5 else "🔴"
            level = f" [{job.seniority_level}]" if job.seniority_level else ""
            print(f"  {emoji} [{job.fit_score:.1f}]{level} {job.title}")
            print(f"     {job.company} — {job.location}")
            print(f"     {job.url}")
            if job.cover_letter_hook:
                print(f"     💡 {job.cover_letter_hook}")
            print()
