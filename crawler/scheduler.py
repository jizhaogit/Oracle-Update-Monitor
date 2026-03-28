"""
crawler/scheduler.py — Orchestrates the full crawl→parse→classify→store pipeline.

Runs:
  • on demand (call run_crawl() directly)
  • on a schedule via APScheduler (call start_scheduler())
"""

import logging
from datetime import datetime
from typing import Callable, Optional

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import CRAWL_INTERVAL_HOURS, CRAWL_ON_STARTUP, ORACLE_SOURCES
from crawler.fetcher import fetch_page
from crawler.parser import get_mock_records, parse_oracle_page
from processor.classifier import rule_classify as classify
from processor.summarizer import rule_based_summary
from storage.database import finish_crawl_run, get_cached_classification, start_crawl_run, upsert_update
from storage.file_store import save_raw_page

log = logging.getLogger(__name__)

# Optional callback: called whenever new updates are stored
# Signature: (new_count: int) -> None
_on_new_updates: Optional[Callable[[int], None]] = None


def register_update_callback(fn: Callable[[int], None]) -> None:
    global _on_new_updates
    _on_new_updates = fn


def run_crawl(seed_mock: bool = True) -> dict:
    """
    Execute one complete crawl cycle.

    Parameters
    ----------
    seed_mock : bool
        If True, insert sample/mock data when no real pages can be fetched
        (useful for first-time setup and offline testing).

    Returns
    -------
    dict with keys: sources_tried, updates_found, updates_new, status
    """
    log.info("═" * 60)
    log.info("Crawl started at %s", datetime.utcnow().isoformat())
    run_id       = start_crawl_run()
    sources_done = 0
    total_found  = 0
    total_new    = 0
    any_real     = False

    for source_name, meta in ORACLE_SOURCES.items():
        url      = meta["url"]
        category = meta["category"]
        service  = meta["service"]
        doc_type = meta["doc_type"]

        html = fetch_page(url)
        sources_done += 1

        if not html:
            log.warning("Skipping %s — no content returned", source_name)
            continue

        any_real = True
        save_raw_page(source_name, url, html, category)

        records = parse_oracle_page(
            html, source_name, url, category, service, doc_type
        )
        log.info("  %s → %d items parsed", source_name, len(records))

        for rec in records:
            # Reuse stored classification for already-known records (avoids LLM calls)
            if not rec.get("impact_level"):
                cached = get_cached_classification(source_name, rec["title"])
                if cached:
                    rec.update(cached)
            # Only call LLM for truly new records with no classification yet
            if not rec.get("impact_level"):
                rec = classify(rec)
            if not rec.get("summary"):
                rec["summary"] = rule_based_summary(rec["title"], rec["content"])

            stored, is_new = upsert_update(rec)
            total_found += 1
            if is_new:
                total_new += 1

    # ── Mock/seed fallback ─────────────────────────────────────────────────────
    if not any_real and seed_mock:
        log.info("No live pages fetched — seeding mock data")
        mock_records = get_mock_records()
        for rec in mock_records:
            rec = classify(rec)
            if not rec.get("summary"):
                rec["summary"] = rule_based_summary(rec["title"], rec["content"])

            stored, is_new = upsert_update(rec)
            total_found += 1
            if is_new:
                total_new += 1

    finish_crawl_run(run_id, sources_done, total_found, total_new, "success")
    log.info("Crawl finished: %d found, %d new", total_found, total_new)
    log.info("═" * 60)

    if _on_new_updates and total_new > 0:
        try:
            _on_new_updates(total_new)
        except Exception as exc:
            log.debug("Update callback error: %s", exc)

    return {
        "sources_tried": sources_done,
        "updates_found": total_found,
        "updates_new":   total_new,
        "status":        "success",
    }


# ── APScheduler ───────────────────────────────────────────────────────────────

_scheduler = None


def start_scheduler() -> None:
    global _scheduler
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.interval import IntervalTrigger

        _scheduler = BackgroundScheduler(daemon=True)
        _scheduler.add_job(
            run_crawl,
            trigger=IntervalTrigger(hours=CRAWL_INTERVAL_HOURS),
            id="oracle_crawl",
            name="Oracle OCI/OIC Crawl",
            replace_existing=True,
        )
        _scheduler.start()
        log.info("Scheduler started — crawl every %d hour(s)", CRAWL_INTERVAL_HOURS)

        if CRAWL_ON_STARTUP:
            import threading
            t = threading.Thread(target=run_crawl, name="initial-crawl", daemon=True)
            t.start()

    except Exception as exc:
        log.error("Failed to start scheduler: %s", exc)


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("Scheduler stopped")
