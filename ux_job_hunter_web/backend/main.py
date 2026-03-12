"""
UX Job Hunter — FastAPI Backend
================================
Serves the API endpoints and static frontend files.

Run locally:
    uvicorn backend.main:app --reload

Endpoints:
    POST /api/upload-resume     — Extract text from PDF/TXT
    POST /api/analyze-resume    — AI keyword extraction from resume
    POST /api/search            — Run job search pipeline (SSE stream)
    GET  /api/download-csv      — Download cached results as CSV
"""

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.resume_parser import extract_text
from backend.job_hunter import SearchConfig, JobDiscoverer, JobEvaluator, ResultsTracker

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("api")

app = FastAPI(title="UX Job Hunter API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory result cache: session_id -> {"jobs": [...], "timestamp": float}
_results_cache: dict[str, dict] = {}
_CACHE_TTL = 3600  # 1 hour


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    resume_text: str
    api_key: str
    model: str = "claude-haiku-4-5-20251001"


class SearchRequest(BaseModel):
    resume_text: str
    api_key: str
    job_titles: list[str]
    locations: list[str]
    experience_levels: list[str]
    posted_within_days: int = 7
    exclude_companies: list[str] = []
    model: str = "claude-haiku-4-5-20251001"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/api/upload-resume")
async def upload_resume(file: UploadFile = File(...)):
    """Extract text from an uploaded resume file."""
    contents = await file.read()

    if len(contents) > 5_000_000:  # 5 MB limit
        raise HTTPException(status_code=400, detail="File too large. Max 5 MB.")

    try:
        text = extract_text(contents, file.filename or "resume.txt")
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"resume_text": text, "filename": file.filename}


@app.post("/api/analyze-resume")
async def analyze_resume(req: AnalyzeRequest):
    """Use Claude to extract job titles, skills, and locations from a resume."""
    if not req.api_key:
        raise HTTPException(status_code=400, detail="API key is required.")

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=req.api_key)

        response = client.messages.create(
            model=req.model,
            max_tokens=1024,
            system="""You are a career advisor analyzing a resume. Extract structured information to help this person search for jobs.

Respond ONLY with valid JSON (no markdown, no backticks). Use this exact schema:
{
    "suggested_titles": ["5-10 job titles this person should search for, based on their skills and experience"],
    "key_skills": ["their top 10-15 skills relevant to job searching"],
    "locations": ["any location preferences mentioned or inferred, include 'Remote' if applicable"],
    "experience_level": ["list of applicable levels from: internship, entry_level, mid_level, senior"],
    "summary": "One sentence describing their professional profile"
}

Be generous with job title suggestions — include both exact-match titles and adjacent roles they could pursue.
For someone with academic/research background, include titles like UX Researcher, Design Researcher, Research Scientist, Mixed Methods Researcher, User Researcher, Qualitative Researcher, etc.""",
            messages=[{"role": "user", "content": f"Analyze this resume:\n\n{req.resume_text[:5000]}"}],
        )

        text = response.content[0].text.strip()
        text = re.sub(r"```json\s*", "", text)
        text = re.sub(r"```\s*", "", text)
        result = json.loads(text)
        return result

    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Failed to parse AI response. Try again.")
    except Exception as e:
        error_msg = str(e)
        if "authentication" in error_msg.lower() or "401" in error_msg:
            raise HTTPException(status_code=401, detail="Invalid API key. Check your Anthropic API key and try again.")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {error_msg}")


@app.post("/api/search")
async def search(req: SearchRequest):
    """Run the full job search pipeline, streaming progress via SSE."""
    if not req.api_key:
        raise HTTPException(status_code=400, detail="API key is required.")
    if not req.job_titles:
        raise HTTPException(status_code=400, detail="At least one job title is required.")

    session_id = str(uuid.uuid4())

    async def event_stream():
        loop = asyncio.get_event_loop()
        progress_queue = asyncio.Queue()

        def on_progress(data):
            progress_queue.put_nowait(data)

        def sse_event(data: dict) -> str:
            return f"data: {json.dumps(data)}\n\n"

        # --- Discovery phase ---
        yield sse_event({"type": "status", "phase": "discovery", "message": "Starting job discovery..."})

        config = SearchConfig(
            job_titles=req.job_titles,
            locations=req.locations,
            experience_levels=req.experience_levels,
            posted_within_days=req.posted_within_days,
            exclude_companies=req.exclude_companies,
            anthropic_api_key=req.api_key,
            claude_model=req.model,
            resume_text=req.resume_text,
        )

        discoverer = JobDiscoverer(config)

        # Run blocking discovery in thread pool
        def run_discovery():
            return discoverer.discover_all(on_progress=on_progress)

        discovery_task = loop.run_in_executor(None, run_discovery)

        # Stream progress while discovery runs
        while not discovery_task.done():
            try:
                event = await asyncio.wait_for(progress_queue.get(), timeout=0.5)
                yield sse_event({"type": "progress", **event})
            except asyncio.TimeoutError:
                continue

        jobs = await discovery_task

        # Drain remaining progress events
        while not progress_queue.empty():
            event = progress_queue.get_nowait()
            yield sse_event({"type": "progress", **event})

        yield sse_event({
            "type": "status",
            "phase": "discovery_complete",
            "message": f"Found {len(jobs)} matching jobs",
            "count": len(jobs),
        })

        if not jobs:
            yield sse_event({
                "type": "complete",
                "jobs": [],
                "session_id": session_id,
                "message": "No matching jobs found. Try broadening your job titles or adding more keywords.",
            })
            return

        # --- Evaluation phase ---
        if req.api_key:
            yield sse_event({"type": "status", "phase": "evaluation", "message": "Evaluating job fit with Claude..."})

            evaluator = JobEvaluator(config)

            def run_evaluation():
                return evaluator.evaluate_batch(jobs, on_progress=on_progress)

            eval_task = loop.run_in_executor(None, run_evaluation)

            while not eval_task.done():
                try:
                    event = await asyncio.wait_for(progress_queue.get(), timeout=0.5)
                    yield sse_event({"type": "progress", **event})
                except asyncio.TimeoutError:
                    continue

            jobs_evaluated = await eval_task

            # Drain remaining
            while not progress_queue.empty():
                event = progress_queue.get_nowait()
                yield sse_event({"type": "progress", **event})
        else:
            jobs_evaluated = jobs

        # Sort by fit score
        jobs_sorted = sorted(jobs_evaluated, key=lambda j: j.fit_score, reverse=True)

        # Cache results for CSV download
        _results_cache[session_id] = {
            "jobs": jobs_sorted,
            "timestamp": time.time(),
        }
        _cleanup_cache()

        # Send final results
        jobs_data = []
        for job in jobs_sorted:
            d = asdict(job)
            # Remove description from response (too large for JSON)
            d.pop("description", None)
            jobs_data.append(d)

        yield sse_event({
            "type": "complete",
            "jobs": jobs_data,
            "session_id": session_id,
            "message": f"Search complete! Found {len(jobs_sorted)} jobs.",
        })

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/download-csv")
async def download_csv(session_id: str):
    """Download cached search results as a CSV file."""
    if session_id not in _results_cache:
        raise HTTPException(status_code=404, detail="Results not found or expired. Run a new search.")

    entry = _results_cache[session_id]
    jobs = entry["jobs"]

    config = SearchConfig()
    tracker = ResultsTracker(config)
    csv_string = tracker.to_csv_string(jobs)

    return Response(
        content=csv_string,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=job_results.csv"},
    )


# ---------------------------------------------------------------------------
# Cache cleanup
# ---------------------------------------------------------------------------

def _cleanup_cache():
    """Remove expired entries from the results cache."""
    now = time.time()
    expired = [k for k, v in _results_cache.items() if now - v["timestamp"] > _CACHE_TTL]
    for k in expired:
        del _results_cache[k]


# ---------------------------------------------------------------------------
# Static files (frontend) — must be mounted LAST
# ---------------------------------------------------------------------------

frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
