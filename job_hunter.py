"""
UX Research Job Hunter — Level 1 Automation Script
===================================================
A modular job search automation tool that scrapes job boards,
evaluates fit using Claude API, and outputs a ranked spreadsheet.

Structured so each module can be split into a separate agent later (Level 3).

Usage:
    1. Set your ANTHROPIC_API_KEY env variable
    2. Edit config.yaml with your preferences
    3. Run: python job_hunter.py
    4. Check output in results/jobs_YYYY-MM-DD.csv

Author: Built for Dejan Durić
"""

import os
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
    claude_model: str = "claude-sonnet-4-20250514"
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
# MODULE 1: DISCOVERY (→ future Agent A)
# ---------------------------------------------------------------------------

class JobDiscoverer:
    """
    Finds job postings from multiple sources.
    
    Supported sources:
    - Greenhouse boards (many tech companies)
    - Lever boards
    - Ashby boards (newer ATS, used by OpenAI, Notion, etc.)
    - Custom company career pages (FAANG, Snap, Canva)
    
    To add a new source, just add a scrape_* method.
    """
    
    def __init__(self, config: SearchConfig):
        self.config = config
        self.logger = logging.getLogger("discoverer")
        self.seen_urls: set = set()
    
    def discover_all(self) -> list[JobPosting]:
        """Run all discovery sources and return deduplicated results."""
        all_jobs = []
        
        # --- Greenhouse boards ---
        greenhouse_companies = self._load_greenhouse_companies()
        for company_slug in greenhouse_companies:
            try:
                jobs = self.scrape_greenhouse(company_slug)
                all_jobs.extend(jobs)
                time.sleep(1)  # Be polite
            except Exception as e:
                self.logger.warning(f"Greenhouse error for {company_slug}: {e}")
        
        # --- Lever boards ---
        lever_companies = self._load_lever_companies()
        for company_slug in lever_companies:
            try:
                jobs = self.scrape_lever(company_slug)
                all_jobs.extend(jobs)
                time.sleep(1)
            except Exception as e:
                self.logger.warning(f"Lever error for {company_slug}: {e}")
        
        # --- Ashby boards ---
        ashby_companies = self._load_ashby_companies()
        for company_slug in ashby_companies:
            try:
                jobs = self.scrape_ashby(company_slug)
                all_jobs.extend(jobs)
                time.sleep(1)
            except Exception as e:
                self.logger.warning(f"Ashby error for {company_slug}: {e}")
        
        # --- FAANG / big tech (direct career page scraping) ---
        try:
            faang_jobs = self.scrape_faang()
            all_jobs.extend(faang_jobs)
        except Exception as e:
            self.logger.warning(f"FAANG scraping error: {e}")
        
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
    
    # ---- FAANG / Big Tech (Playwright-powered scraping) ----
    
    def scrape_faang(self) -> list[JobPosting]:
        """
        Scrape FAANG and major tech career pages using Playwright.
        
        These companies use proprietary JS-rendered career sites.
        We use a headless browser to load the pages, wait for JS to render,
        then extract job listings.
        
        Falls back to direct search links if Playwright isn't installed
        or if scraping fails.
        
        SETUP:
            pip install playwright
            playwright install chromium
        """
        all_jobs = []
        
        faang_sources = [
            ("Google", self._scrape_google_careers),
            ("Microsoft", self._scrape_microsoft_careers),
            ("Amazon", self._scrape_amazon_careers),
            ("Apple", self._scrape_apple_careers),
            ("Meta", self._scrape_meta_careers),
            ("Snap", self._scrape_snap_careers),
            ("Canva", self._scrape_canva_careers),
        ]
        
        for company_name, scrape_fn in faang_sources:
            try:
                self.logger.info(f"Scraping FAANG: {company_name}")
                jobs = scrape_fn()
                all_jobs.extend(jobs)
                self.logger.info(f"  Found {len(jobs)} matching jobs at {company_name}")
                time.sleep(2)  # Extra polite with big tech
            except Exception as e:
                self.logger.warning(f"FAANG error for {company_name}: {e}")
        
        return all_jobs
    
    def _pw_scrape(self, url: str, wait_selector: str, extract_fn, 
                   fallback_title: str, fallback_url: str, 
                   company: str, source: str, timeout: int = 20000) -> list[JobPosting]:
        """
        Generic Playwright scraper with fallback to direct link.
        
        Args:
            url: Career page URL to load
            wait_selector: CSS selector to wait for (indicates page loaded)
            extract_fn: Function(page) -> list[dict] that extracts job data
            fallback_title: Title for the fallback direct link
            fallback_url: URL for the fallback direct link
            company: Company name
            source: Source identifier for the CSV
            timeout: How long to wait for page load (ms)
        
        Returns:
            List of JobPosting objects
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.logger.warning(
                f"Playwright not installed. Run: pip install playwright && playwright install chromium"
            )
            return [self._fallback_link(fallback_title, company, fallback_url, source)]
        
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-setuid-sandbox"]
                )
                context = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1280, "height": 800},
                )
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=timeout)
                
                # Wait for the job listings to render
                try:
                    page.wait_for_selector(wait_selector, timeout=timeout)
                except Exception:
                    # Page loaded but selector not found — might be empty or blocked
                    self.logger.warning(f"  Selector '{wait_selector}' not found on {url}")
                    browser.close()
                    return [self._fallback_link(fallback_title, company, fallback_url, source)]
                
                # Extra wait for any lazy-loaded content
                page.wait_for_timeout(2000)
                
                # Extract jobs using the provided function
                raw_jobs = extract_fn(page)
                browser.close()
                
                if not raw_jobs:
                    return [self._fallback_link(fallback_title, company, fallback_url, source)]
                
                # Convert to JobPosting objects and filter by title
                jobs = []
                for rj in raw_jobs:
                    title = rj.get("title", "")
                    if not self._matches_title(title):
                        continue
                    jobs.append(JobPosting(
                        title=title,
                        company=company,
                        location=rj.get("location", ""),
                        url=rj.get("url", fallback_url),
                        description=rj.get("description", "")[:3000],
                        date_posted=rj.get("date_posted", ""),
                        source=source,
                    ))
                
                if jobs:
                    return jobs
                else:
                    # Jobs were found but none matched our title filter
                    return [self._fallback_link(fallback_title, company, fallback_url, source)]
        
        except Exception as e:
            self.logger.warning(f"  Playwright failed for {company}: {e}")
            return [self._fallback_link(fallback_title, company, fallback_url, source)]
    
    def _fallback_link(self, title: str, company: str, url: str, source: str) -> JobPosting:
        """Create a direct search link as fallback when scraping fails."""
        return JobPosting(
            title=f"[Check {company} Careers] UX Researcher",
            company=company,
            location="Various",
            url=url,
            description=f"Direct link to {company}'s job search. Playwright scraping failed or returned no results.",
            source=source,
        )
    
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
                jobs.append(self._fallback_link(
                    "UX Researcher", "Amazon",
                    f"https://www.amazon.jobs/en/search?base_query={urllib.parse.quote(term)}",
                    "amazon_jobs"
                ))
            
            time.sleep(1)
        
        return jobs
    
    def _scrape_google_careers(self) -> list[JobPosting]:
        """
        Google Careers — Playwright scraper.
        
        Google's career site renders job cards as <li> elements.
        We search for "UX Researcher" and extract matching listings.
        
        SELECTOR NOTES (update if Google redesigns):
        - Job cards: li.lLd3Je (each job listing)
        - Job title: h3.QJPWVe inside each card
        - Location: span.r0wTof
        - Link: the card itself links to the job detail
        """
        url = "https://www.google.com/about/careers/applications/jobs/results/?q=UX%20Researcher&target_level=EARLY&target_level=MID"
        
        def extract(page):
            jobs = []
            # Try multiple selector strategies
            # Strategy 1: Known Google Careers selectors
            cards = page.query_selector_all("li.lLd3Je")
            if not cards:
                # Strategy 2: Generic approach — find all links with /jobs/ in href
                cards = page.query_selector_all("a[href*='/jobs/results/']")
            
            for card in cards[:20]:  # Cap at 20 to avoid overload
                try:
                    title_el = card.query_selector("h3") or card.query_selector("[role='heading']")
                    title = title_el.inner_text().strip() if title_el else ""
                    
                    loc_el = card.query_selector("span.r0wTof") or card.query_selector("span[class*='location']")
                    location = loc_el.inner_text().strip() if loc_el else ""
                    
                    link_el = card.query_selector("a[href*='/jobs/']") or card
                    href = link_el.get_attribute("href") or ""
                    if href and not href.startswith("http"):
                        href = f"https://www.google.com{href}"
                    
                    if title:
                        jobs.append({
                            "title": title,
                            "location": location,
                            "url": href,
                            "description": "",
                        })
                except Exception:
                    continue
            return jobs
        
        return self._pw_scrape(
            url=url,
            wait_selector="li.lLd3Je, a[href*='/jobs/results/'], [role='listitem']",
            extract_fn=extract,
            fallback_title="UX Researcher",
            fallback_url=url,
            company="Google",
            source="google_careers",
        )
    
    def _scrape_microsoft_careers(self) -> list[JobPosting]:
        """
        Microsoft Careers — Playwright scraper.
        
        SELECTOR NOTES (update if Microsoft redesigns):
        - Job cards: div[data-ph-at-id="jobs-list-item"]
        - Job title: h2 inside each card
        - Location: span.lh-lg
        """
        url = "https://careers.microsoft.com/us/en/search-results?keywords=UX%20Researcher"
        
        def extract(page):
            jobs = []
            cards = page.query_selector_all("div[data-ph-at-id='jobs-list-item']")
            if not cards:
                cards = page.query_selector_all("li[class*='jobs-list']")
            if not cards:
                # Generic fallback: any link containing /job/
                links = page.query_selector_all("a[href*='/job/']")
                for link in links[:20]:
                    title = link.inner_text().strip()
                    href = link.get_attribute("href") or ""
                    if href and not href.startswith("http"):
                        href = f"https://careers.microsoft.com{href}"
                    if title and len(title) > 5:
                        jobs.append({"title": title, "location": "", "url": href, "description": ""})
                return jobs
            
            for card in cards[:20]:
                try:
                    title_el = card.query_selector("h2") or card.query_selector("a")
                    title = title_el.inner_text().strip() if title_el else ""
                    
                    loc_el = card.query_selector("span.lh-lg") or card.query_selector("span[class*='location']")
                    location = loc_el.inner_text().strip() if loc_el else ""
                    
                    link_el = card.query_selector("a[href*='/job/']") or card.query_selector("a")
                    href = link_el.get_attribute("href") if link_el else ""
                    if href and not href.startswith("http"):
                        href = f"https://careers.microsoft.com{href}"
                    
                    if title:
                        jobs.append({"title": title, "location": location, "url": href, "description": ""})
                except Exception:
                    continue
            return jobs
        
        return self._pw_scrape(
            url=url,
            wait_selector="div[data-ph-at-id='jobs-list-item'], a[href*='/job/'], [role='listitem']",
            extract_fn=extract,
            fallback_title="UX Researcher",
            fallback_url=url,
            company="Microsoft",
            source="microsoft_careers",
        )
    
    def _scrape_apple_careers(self) -> list[JobPosting]:
        """
        Apple Jobs — Playwright scraper.
        
        SELECTOR NOTES:
        - Job cards: table#job-list tbody tr, or div.results a
        - Job title: td.table-col-1 a
        """
        url = "https://jobs.apple.com/en-us/search?search=UX%20Researcher"
        
        def extract(page):
            jobs = []
            # Apple uses a table or card-based layout
            rows = page.query_selector_all("table#job-list tbody tr")
            if not rows:
                rows = page.query_selector_all("a[href*='/en-us/details/']")
            
            for row in rows[:20]:
                try:
                    # Table row format
                    title_el = row.query_selector("td.table-col-1 a") or row.query_selector("a")
                    title = title_el.inner_text().strip() if title_el else row.inner_text().strip()
                    
                    loc_el = row.query_selector("td.table-col-2") or row.query_selector("span[class*='location']")
                    location = loc_el.inner_text().strip() if loc_el else ""
                    
                    link_el = row.query_selector("a[href*='/details/']") or row.query_selector("a") or row
                    href = link_el.get_attribute("href") if link_el else ""
                    if href and not href.startswith("http"):
                        href = f"https://jobs.apple.com{href}"
                    
                    if title and len(title) > 3:
                        jobs.append({"title": title, "location": location, "url": href, "description": ""})
                except Exception:
                    continue
            return jobs
        
        return self._pw_scrape(
            url=url,
            wait_selector="table#job-list, a[href*='/details/'], [role='listitem']",
            extract_fn=extract,
            fallback_title="UX Researcher",
            fallback_url=url,
            company="Apple",
            source="apple_jobs",
        )
    
    def _scrape_meta_careers(self) -> list[JobPosting]:
        """
        Meta Careers — Playwright scraper.
        
        SELECTOR NOTES:
        - Job cards: a[href*='/jobs/'] within results container
        - Cards typically have role title + location text
        """
        url = "https://www.metacareers.com/jobs?q=UX%20Researcher"
        
        def extract(page):
            jobs = []
            # Meta lists jobs as links/cards
            links = page.query_selector_all("a[href*='/jobs/']")
            
            seen_hrefs = set()
            for link in links[:30]:
                try:
                    href = link.get_attribute("href") or ""
                    # Filter to actual job detail pages (contain numeric ID)
                    if not re.search(r'/jobs/\d+', href):
                        continue
                    if href in seen_hrefs:
                        continue
                    seen_hrefs.add(href)
                    
                    if not href.startswith("http"):
                        href = f"https://www.metacareers.com{href}"
                    
                    text = link.inner_text().strip()
                    # The link text usually contains title and location separated by newlines
                    parts = [p.strip() for p in text.split("\n") if p.strip()]
                    title = parts[0] if parts else ""
                    location = parts[1] if len(parts) > 1 else ""
                    
                    if title:
                        jobs.append({"title": title, "location": location, "url": href, "description": ""})
                except Exception:
                    continue
            return jobs
        
        return self._pw_scrape(
            url=url,
            wait_selector="a[href*='/jobs/'], [role='listitem'], [data-testid]",
            extract_fn=extract,
            fallback_title="UX Researcher",
            fallback_url=url,
            company="Meta",
            source="meta_careers",
        )
    
    def _scrape_snap_careers(self) -> list[JobPosting]:
        """
        Snap Careers — Playwright scraper.
        
        SELECTOR NOTES:
        - Job listings at careers.snap.com/jobs
        - Cards are typically links with job title and location
        """
        url = "https://careers.snap.com/jobs?type=regular&role=Design+-+Research"
        
        def extract(page):
            jobs = []
            # Try finding job card links
            links = page.query_selector_all("a[href*='/jobs/']")
            
            seen = set()
            for link in links[:20]:
                try:
                    href = link.get_attribute("href") or ""
                    if href in seen or not href:
                        continue
                    seen.add(href)
                    if not href.startswith("http"):
                        href = f"https://careers.snap.com{href}"
                    
                    text = link.inner_text().strip()
                    parts = [p.strip() for p in text.split("\n") if p.strip()]
                    title = parts[0] if parts else ""
                    location = parts[1] if len(parts) > 1 else ""
                    
                    if title and len(title) > 3:
                        jobs.append({"title": title, "location": location, "url": href, "description": ""})
                except Exception:
                    continue
            return jobs
        
        return self._pw_scrape(
            url=url,
            wait_selector="a[href*='/jobs/'], [role='listitem']",
            extract_fn=extract,
            fallback_title="UX Researcher",
            fallback_url=url,
            company="Snap",
            source="snap_careers",
        )
    
    def _scrape_canva_careers(self) -> list[JobPosting]:
        """
        Canva Careers — Playwright scraper.
        
        SELECTOR NOTES:
        - Canva lists jobs at canva.com/careers/jobs/
        - Job cards contain title, team, and location info
        """
        url = "https://www.canva.com/careers/jobs/?query=researcher"
        
        def extract(page):
            jobs = []
            # Canva job cards are typically links to /careers/jobs/{slug}
            links = page.query_selector_all("a[href*='/careers/jobs/']")
            
            seen = set()
            for link in links[:20]:
                try:
                    href = link.get_attribute("href") or ""
                    if href in seen or not href or href.endswith("/jobs/") or "query=" in href:
                        continue
                    seen.add(href)
                    if not href.startswith("http"):
                        href = f"https://www.canva.com{href}"
                    
                    text = link.inner_text().strip()
                    parts = [p.strip() for p in text.split("\n") if p.strip()]
                    title = parts[0] if parts else ""
                    location = parts[-1] if len(parts) > 1 else ""
                    
                    if title and len(title) > 3:
                        jobs.append({"title": title, "location": location, "url": href, "description": ""})
                except Exception:
                    continue
            return jobs
        
        return self._pw_scrape(
            url=url,
            wait_selector="a[href*='/careers/jobs/'], [role='listitem']",
            extract_fn=extract,
            fallback_title="UX Researcher",
            fallback_url=url,
            company="Canva",
            source="canva_careers",
        )
    
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
            # Academic disciplines that signal strong fit for Dejan
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
        - Example: boards.greenhouse.io/airbnb → slug = "airbnb"
        
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


# ---------------------------------------------------------------------------
# MODULE 2: EVALUATOR (→ future Agent B)
# ---------------------------------------------------------------------------

class JobEvaluator:
    """
    Scores each job against your resume using Claude API.
    Returns structured JSON with fit score, reasoning, and gaps.
    """
    
    def __init__(self, config: SearchConfig):
        self.config = config
        self.logger = logging.getLogger("evaluator")
    
    def evaluate_batch(self, jobs: list[JobPosting]) -> list[JobPosting]:
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
            
            time.sleep(0.5)  # Rate limiting courtesy
        
        if skipped:
            self.logger.info(f"Skipped {skipped} non-UX jobs, saving ~${skipped * 0.005:.2f} in API costs")
        
        return jobs
    
    def _evaluate_single(self, client, job: JobPosting) -> dict:
        """Call Claude to evaluate a single job."""
        
        system_prompt = """You are a career advisor evaluating job fit for a UX researcher candidate.
You will receive the candidate's resume and a job description.

KEY CONTEXT ABOUT THIS CANDIDATE:
- PhD candidate (ABD) in Anthropology/Linguistic Anthropology — graduating Dec 2026
- Strong qualitative/ethnographic researcher transitioning from academia to industry UX
- 14 months of independent international fieldwork (impressive project management)
- Currently completing the Erdős Institute UX Research Bootcamp
- Tools: ELAN, Figma, Miro, Dovetail, Python
- Main gap: no prior industry UX title, limited quantitative/survey experience

SENIORITY CALIBRATION:
- Intern/New Grad/Junior roles (0-2 years): STRONG candidate — score 7-9
- Mid-level roles (2-4 years): GOOD candidate — their fieldwork and teaching count as applied experience. Score 6-8.
- Senior roles (5+ years industry): STRETCH — score 3-5 unless requirements are flexible
- Staff/Principal roles (8+ years): NOT A FIT — score 1-3

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
# MODULE 3: OUTPUT / TRACKER (→ future Agent C for cover letters)
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


# ---------------------------------------------------------------------------
# MAIN ORCHESTRATOR
# ---------------------------------------------------------------------------

def load_resume() -> str:
    """Load resume text from file or return embedded version."""
    # Try loading from file first
    for path in ["resume.txt", "resume.md", "Duric_Resume_2026.txt"]:
        if os.path.exists(path):
            with open(path) as f:
                return f.read()
    
    # Fallback: embedded resume (update this with your latest)
    return """Dejan Durić
734 395 1556 | Ann Arbor, MI | duric@umich.edu

SUMMARY
Mixed-methods researcher with 14 months of international fieldwork experience studying 
how people interact with digital tools in everyday settings. Skilled at turning complex 
qualitative data—video, screen recordings, interviews—into clear, actionable insights.
Seeking a Research Scientist or UX Research role.

EDUCATION
U of Michigan, PhD in American Culture and Linguistic Anthropology (GPA = 3.98) exp. 12/2026
U of Groningen, Master of Arts in North American Studies (Cum Laude) 2017
U of Groningen, Bachelor of Arts in American Studies 2015

SKILLS
Research Methods: Ethnographic fieldwork, participant observation, semi-structured interviews, 
conversation analysis, discourse analysis, experimental task design, screen recording analysis, 
thematic coding, independent project management
Languages: English, Bosnian/Croatian/Serbian, Dutch, German (conversational)
Tools: ELAN, Figma, Miro, Dovetail, Python
Certifications: Erdős Institute UX Research Bootcamp (exp. 2026), Framework for Data Collection 
and Analysis—quantitative methods (Coursera, in progress)

WORK EXPERIENCE
Ginsberg Center, U of Michigan — Graduate Learning Consultant (2024-2025)
- Facilitated 15+ workshops on community-engaged research methods and ethics
- Co-developed evaluation criteria for fellowship program, reviewed 60+ proposals

University of Michigan — Doctoral Field Research, Mostar, Bosnia (2022-2023)
- Independently designed/managed 14-month research project
- Managed multiple concurrent data streams (video, audio, screen recordings, field notes)

University of Michigan — Instructor & GSI (2020-2026)
- Designed two original courses enrolling 90+ students
- Mentored 75+ students across courses on race, identity, and American culture

SELECTED PROJECTS
How Smartphones Shape Face-to-Face Conversation (2024-2026)
- Developed the Screen-in-Talk framework for analyzing smartphone use in conversations
- Presented findings at multiple academic conferences

PUBLICATIONS
"Between Screens and Speech" (in prep., 2026)
Book reviews in Journal of Linguistic Anthropology (2023)
"""


def main():
    # --- Setup logging ---
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    logger = logging.getLogger("main")
    
    # --- Load config ---
    config = SearchConfig()
    config.load_from_yaml()
    
    # API key from env or config
    config.anthropic_api_key = (
        os.environ.get("ANTHROPIC_API_KEY", "") or config.anthropic_api_key
    )
    
    # Load resume
    config.resume_text = load_resume()
    
    # --- Validate ---
    if not config.anthropic_api_key:
        print("\n⚠️  No ANTHROPIC_API_KEY found.")
        print("   Set it via: export ANTHROPIC_API_KEY='sk-ant-...'")
        print("   Or add it to config.yaml")
        print("\n   Running in DISCOVERY-ONLY mode (no AI scoring).\n")
    
    # =========================================
    # STEP 1: DISCOVER
    # =========================================
    logger.info("Starting job discovery...")
    discoverer = JobDiscoverer(config)
    jobs = discoverer.discover_all()
    logger.info(f"Found {len(jobs)} matching jobs")
    
    # =========================================
    # STEP 2: EVALUATE (if API key is set)
    # =========================================
    if config.anthropic_api_key and jobs:
        logger.info("Evaluating job fit with Claude...")
        evaluator = JobEvaluator(config)
        jobs = evaluator.evaluate_batch(jobs)
    
    # =========================================
    # STEP 3: SAVE & REPORT
    # =========================================
    tracker = ResultsTracker(config)
    
    if jobs:
        filepath = tracker.save_csv(jobs)
        tracker.print_summary(jobs)
        print(f"  📁 Full results saved to: {filepath}\n")
    else:
        print("\nNo matching jobs found. Try adding more companies to the lists.")


if __name__ == "__main__":
    main()
