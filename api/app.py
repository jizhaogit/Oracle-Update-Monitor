"""
api/app.py — FastAPI backend for Oracle OCI/OIC Monitor.

Endpoints
---------
GET  /                    — health check
GET  /stats               — summary statistics
GET  /updates             — list updates (filterable, paginated)
GET  /updates/{id}        — single update detail
GET  /categories          — distinct category list
GET  /services            — distinct service list
GET  /crawl-runs          — crawl audit log
POST /crawl               — trigger manual crawl
POST /mark-seen           — mark all new → seen
POST /ask                 — Q&A over stored documents
"""

import logging
import threading
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

UI_HTML = Path(__file__).parent.parent / "ui" / "index.html"

from storage.database import (
    get_analysis_cache, save_analysis_cache,
    get_stats, get_update, get_updates_by_ids, get_versions,
    list_crawl_runs, list_updates, set_comment, set_flag, set_impact,
    get_distinct_categories, get_distinct_services, mark_all_seen,
)
from processor.summarizer import ask as qa_ask
from processor.analyzer import analyze_impact
from processor.jira_client import fetch_jira_issues_from_notes

log = logging.getLogger(__name__)

# In-memory job store for async analyze requests
# { job_id: {status, analysis, from_cache, generated_at, error} }
_analyze_jobs: dict = {}

app = FastAPI(
    title="Oracle OCI/OIC Monitor API",
    description="Browse, search, and query Oracle cloud documentation updates.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Models ─────────────────────────────────────────────────────────────────────

class AskRequest(BaseModel):
    question: str

class AnalyzeRequest(BaseModel):
    ids: list[int]
    force: bool = False   # True = regenerate even if cached

class FlagRequest(BaseModel):
    is_flagged: bool
    note: str = ""        # Jira URL, reason, or any free-text annotation

class ImpactRequest(BaseModel):
    impact_level: Optional[str]   # "High" | "Medium" | "Low" | null (reset to auto)

class CommentRequest(BaseModel):
    comment: str = ""


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/")
def index():
    """Serve the browser UI."""
    if UI_HTML.exists():
        return FileResponse(str(UI_HTML), media_type="text/html")
    return {"status": "ok", "service": "Oracle OCI/OIC Monitor"}


@app.get("/health")
def health():
    return {"status": "ok", "service": "Oracle OCI/OIC Monitor"}


@app.get("/stats")
def stats():
    return get_stats()


@app.get("/updates")
def list_updates_endpoint(
    category:     Optional[str]  = Query(None),
    service:      Optional[str]  = Query(None),
    impact_level: Optional[str]  = Query(None),
    is_new:       Optional[bool] = Query(None),
    search:       Optional[str]  = Query(None),
    limit:        int            = Query(5000, ge=1, le=5000),
    offset:       int            = Query(0, ge=0),
):
    return list_updates(
        category=category,
        service=service,
        impact_level=impact_level,
        is_new=is_new,
        search=search,
        limit=limit,
        offset=offset,
    )


@app.get("/updates/{update_id}")
def get_update_endpoint(update_id: int):
    rec = get_update(update_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Update not found")
    return rec.to_dict()


@app.post("/updates/{update_id}/impact")
def override_impact(update_id: int, body: ImpactRequest):
    """
    Manually override (or reset) the impact level of a single update.

    Body:
        impact_level : "High" | "Medium" | "Low" | null  (null = reset to auto)
    """
    valid = {"High", "Medium", "Low", None}
    if body.impact_level not in valid:
        raise HTTPException(status_code=400,
                            detail=f"impact_level must be one of {list(valid)}")
    rec = set_impact(update_id, body.impact_level)
    if rec is None:
        raise HTTPException(status_code=404, detail="Update not found")
    return rec


@app.post("/updates/{update_id}/comment")
def save_comment(update_id: int, body: CommentRequest):
    """Save (or clear) a free-text user comment on a single update."""
    rec = set_comment(update_id, body.comment)
    if rec is None:
        raise HTTPException(status_code=404, detail="Update not found")
    return rec


@app.post("/updates/{update_id}/flag")
def flag_update(update_id: int, body: FlagRequest):
    """
    Set or clear the manual 'Needs Review' flag on a single update.

    Body:
        is_flagged : true to flag, false to clear
        note       : optional free-text (Jira URL, reason, etc.)
    """
    rec = set_flag(update_id, body.is_flagged, body.note)
    if rec is None:
        raise HTTPException(status_code=404, detail="Update not found")
    return rec


@app.get("/categories")
def categories():
    return get_distinct_categories()


@app.get("/services")
def services():
    return get_distinct_services()


@app.get("/crawl-runs")
def crawl_runs(limit: int = Query(20, ge=1, le=100)):
    return list_crawl_runs(limit=limit)


@app.post("/crawl")
def trigger_crawl():
    from crawler.scheduler import run_crawl
    t = threading.Thread(target=run_crawl, daemon=True)
    t.start()
    return {"status": "started", "message": "Crawl triggered in background"}


@app.post("/mark-seen")
def mark_seen():
    n = mark_all_seen()
    return {"marked_seen": n}


@app.post("/ask")
def ask_question(body: AskRequest):
    answer = qa_ask(body.question)
    return {"question": body.question, "answer": answer}


@app.post("/analyze")
def analyze_updates(body: AnalyzeRequest):
    """
    Start an async impact analysis job.
    - Returns cached result immediately (status="done", from_cache=True) when available.
    - Otherwise starts a background LLM job and returns {job_id, status="running"}.
    - Poll GET /analyze/{job_id} for the result.
    """
    if not body.ids:
        raise HTTPException(status_code=400, detail="No IDs provided")

    # Return cached result instantly — no LLM needed
    if not body.force:
        try:
            cached = get_analysis_cache(body.ids)
        except Exception as exc:
            log.warning("Cache read failed: %s", exc)
            cached = None
        if cached:
            return {
                "job_id":       None,
                "status":       "done",
                "from_cache":   True,
                "analysis":     cached["analysis"],
                "generated_at": cached["generated_at"],
            }

    records = get_updates_by_ids(body.ids)
    if not records:
        raise HTTPException(status_code=404, detail="No updates found for given IDs")

    # Pre-fetch any Jira issues linked via flag_note (fast — done before thread starts)
    jira_issues: list = []
    try:
        jira_issues = fetch_jira_issues_from_notes(records)
    except Exception as exc:
        log.warning("Jira pre-fetch raised an exception (analysis continues): %s", exc)

    # Separate into successful fetches and failures so the UI can warn clearly
    jira_ok     = [j for j in jira_issues if not j.get("fetch_error")]
    jira_failed = [{"key": j["key"], "url": j["url"], "error": j["fetch_error"]}
                   for j in jira_issues if j.get("fetch_error")]

    if jira_ok:
        log.info("Jira context loaded for: %s", [j["key"] for j in jira_ok])
    if jira_failed:
        log.warning("Jira fetch failed for: %s", [(j["key"], j["error"]) for j in jira_failed])

    # Start background job so the HTTP request returns immediately
    job_id = str(uuid.uuid4())
    _analyze_jobs[job_id] = {
        "status": "running", "analysis": None,
        "from_cache": False, "generated_at": None, "error": None,
        "jira_keys":    [j["key"] for j in jira_ok],
        "jira_failed":  jira_failed,
    }

    def _run():
        try:
            analysis = analyze_impact(records, jira_issues=jira_issues or None)
            generated_at = None
            try:
                saved = save_analysis_cache(body.ids, analysis)
                generated_at = saved["generated_at"]
            except Exception as exc:
                log.warning("Cache write failed: %s", exc)
            _analyze_jobs[job_id].update({
                "status": "done", "analysis": analysis, "generated_at": generated_at,
            })
        except Exception as exc:
            log.error("Analyze job %s failed: %s", job_id, exc)
            _analyze_jobs[job_id].update({"status": "error", "error": str(exc)})

    threading.Thread(target=_run, name=f"analyze-{job_id[:8]}", daemon=True).start()
    return {
        "job_id":       job_id,
        "status":       "running",
        "jira_keys":    [j["key"] for j in jira_ok],
        "jira_failed":  jira_failed,
    }


@app.get("/analyze/{job_id}")
def get_analyze_job(job_id: str):
    """Poll for the result of an async analyze job."""
    job = _analyze_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/updates/{update_id}/versions")
def get_update_versions(update_id: int):
    """Return all historical snapshots for one update."""
    return get_versions(update_id)


@app.get("/jira-test")
def jira_test(url: str = Query(..., description="Full Jira browse URL to test")):
    """
    Diagnostic endpoint — test whether a Jira ticket can be fetched.
    Example: GET /jira-test?url=https://jira.tssi.ca/browse/BGCO-4817
    """
    from processor.jira_client import _extract_urls, fetch_jira_issue
    matches = _extract_urls(url)
    if not matches:
        raise HTTPException(status_code=400, detail="No Jira browse URL detected in input")
    base_url, key = matches[0]
    issue = fetch_jira_issue(base_url, key)
    return {
        "key":           issue["key"],
        "url":           issue["url"],
        "fetch_error":   issue.get("fetch_error"),
        "summary":       issue.get("summary"),
        "status":        issue.get("status"),
        "description_preview": (issue.get("description") or "")[:400],
        "comment_count": len(issue.get("comments") or []),
        "comments_preview": [
            {"author": c["author"], "body": c["body"][:200]}
            for c in (issue.get("comments") or [])
        ],
    }


@app.get("/conclusion")
def conclusion(ids: str = Query(..., description="Comma-separated update IDs")):
    """
    Return enriched records for the given IDs, each including their full
    version history so the UI can render a Previous vs Current comparison.
    """
    id_list = []
    for part in ids.split(","):
        part = part.strip()
        if part.isdigit():
            id_list.append(int(part))

    if not id_list:
        raise HTTPException(status_code=400, detail="No valid IDs provided")

    records = get_updates_by_ids(id_list)
    # Attach version history to each record
    for rec in records:
        rec["versions"] = get_versions(rec["id"])
    return records
