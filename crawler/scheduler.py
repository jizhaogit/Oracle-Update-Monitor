"""
crawler/scheduler.py — Orchestrates the full crawl→parse→classify→store pipeline.

Runs:
  • on demand (call run_crawl() directly)
  • on a schedule via APScheduler (call start_scheduler())
"""

import hashlib
import logging
import re
from datetime import datetime
from typing import Callable, Optional
from urllib.parse import urljoin

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import CRAWL_INTERVAL_HOURS, CRAWL_ON_STARTUP, CRAWL_SCHEDULE_ENABLED, HCM_EXTRA_RELEASES, ORACLE_SOURCES
from crawler.fetcher import fetch_page
from crawler.parser import (
    get_mock_records,
    parse_hcm_detail_page,
    parse_hcm_feature_page,
    parse_hcm_hub_modules,
    parse_hcm_toc,
    parse_oracle_page,
    _parse_oracle_release,
)
from processor.classifier import rule_classify as classify
from processor.summarizer import rule_based_summary
from storage.database import finish_crawl_run, get_cached_classification, start_crawl_run, upsert_update
from storage.file_store import save_raw_page

log = logging.getLogger(__name__)

# Optional callback: called whenever new updates are stored
# Signature: (new_count: int) -> None
_on_new_updates: Optional[Callable[[int], None]] = None

# Base URL for the Oracle HCM readiness docs
_HCM_READINESS_BASE = "https://docs.oracle.com/en/cloud/saas/readiness/"

# Maximum modules to crawl from the hub, and features per module
_HCM_MAX_MODULES  = 80   # hub(~20) × extra releases(default 1) + margin
_HCM_MAX_FEATURES = 60


def _store_rec(rec: dict, source_name: str) -> bool:
    """Classify, summarise, upsert one record. Returns True if newly inserted/updated."""
    cached = get_cached_classification(source_name, rec["title"])
    if cached:
        rec.update(cached)
    if not rec.get("impact_level"):
        rec = classify(rec)
    if not rec.get("summary"):
        rec["summary"] = rule_based_summary(rec["title"], rec["content"])
    _stored, is_new = upsert_update(rec)
    return is_new


def _crawl_hcm_readiness(
    source_name: str,
    source_url: str,
    category: str,
    service: str,
    doc_type: str,
) -> tuple[int, int]:
    """
    Full three-step HCM readiness crawl:
      1. Fetch hcm.html → parse embedded JSON to get the module list.
      2. For each module: store a parent record, then fetch toc.htm for feature URLs.
      3. For each feature URL: fetch, parse, and store as a child record titled
         "{parent_title} — {feature_title}".

    hcm.html is fully JS-rendered, but the server inlines a script block that
    lists all module paths so we can discover every module without JS execution.

    Returns (total_found, total_new).
    """
    html, page_date = fetch_page(source_url)
    if not html:
        log.warning("HCM hub page unreachable: %s", source_url)
        return 0, 0

    save_raw_page(source_name, source_url, html, category)

    modules = parse_hcm_hub_modules(html)
    if not modules:
        log.warning("No HCM modules found in hub page — JS may not have been inlined")
        return 0, 0

    # ── Expand with previous-release equivalents ──────────────────────────
    # The hub only lists the current release for each module (e.g. 26B).
    # For each extra release in HCM_EXTRA_RELEASES (default: ["26A"]),
    # derive the equivalent path by substituting the release code.
    # Example: "hcm/26b/comp-26b/index.html" → "hcm/26a/comp-26a/index.html"
    existing_paths: set[str] = {m["path"] for m in modules}
    for extra_rc in HCM_EXTRA_RELEASES:
        extra_lower = extra_rc.lower()   # e.g. "26a"
        for mod in list(modules):
            # Match pattern: hcm/{hub_rc}/{module_code}-{hub_rc}/index.html
            m = re.match(r"hcm/(\w+)/(\w+)-(\w+)/index\.html", mod["path"])
            if not m:
                continue
            hub_rc      = m.group(1)     # e.g. "26b"
            module_code = m.group(2)     # e.g. "comp"
            if hub_rc.lower() == extra_lower:
                continue                  # already this release
            new_path  = f"hcm/{extra_lower}/{module_code}-{extra_lower}/index.html"
            if new_path in existing_paths:
                continue
            new_title = re.sub(r"\b\d{2}[A-D]\b", extra_rc,
                                mod["title"], flags=re.IGNORECASE)
            existing_paths.add(new_path)
            modules.append({"title": new_title, "path": new_path})

    log.info("HCM hub: crawling %d modules (incl. extra releases: %s) …",
             min(len(modules), _HCM_MAX_MODULES), HCM_EXTRA_RELEASES)
    total_found = 0
    total_new   = 0

    for mod in modules[:_HCM_MAX_MODULES]:
        mod_title    = mod["title"]           # e.g. "Payroll What's New 26B"
        mod_path     = mod["path"]            # e.g. "hcm/26b/payr-26b/index.html"
        parent_title = f"HCM — {mod_title}"  # e.g. "HCM — Payroll What's New 26B"
        mod_url      = urljoin(_HCM_READINESS_BASE, mod_path)

        # Release code & date from the module title (e.g. "26B" → Apr 2026)
        rel_date, rel_code = _parse_oracle_release(mod_title)
        if not rel_date and page_date:
            rel_date = page_date

        # ── Parent record (one per module) ────────────────────────────────
        parent_content = (
            f"Oracle Fusion Cloud HCM {mod_title}. "
            "See individual feature entries below for full details."
        )
        parent_hash = hashlib.sha256(
            f"{mod_url}|{parent_title}|{parent_content[:500]}".encode()
        ).hexdigest()
        parent_rec = {
            "source_name":  source_name,
            "source_url":   mod_url,
            "category":     category,
            "service":      service,
            "doc_type":     doc_type,
            "title":        parent_title[:480],
            "content":      parent_content,
            "summary":      None,
            "_tags":        "[]",
            "impact_level": None,
            "release_date": rel_date,
            "release_code": rel_code,
            "content_hash": parent_hash,
            "is_new":       True,
            "vector_id":    None,
        }
        is_new = _store_rec(parent_rec, source_name)
        total_found += 1
        if is_new:
            total_new += 1

        # ── TOC page → feature URLs ───────────────────────────────────────
        toc_path = mod_path.replace("index.html", "toc.htm")
        toc_url  = urljoin(_HCM_READINESS_BASE, toc_path)

        toc_html, _ = fetch_page(toc_url)
        if not toc_html:
            log.warning("  HCM toc unreachable: %s", toc_url)
            continue

        feature_urls = parse_hcm_toc(toc_html, toc_url)
        log.info("  %s → %d features", mod_title, len(feature_urls))

        # ── Feature pages → child records ─────────────────────────────────
        for feat_url in feature_urls[:_HCM_MAX_FEATURES]:
            feat_html, feat_date = fetch_page(feat_url)
            if not feat_html:
                continue

            child_rec = parse_hcm_feature_page(
                feat_html, parent_title, feat_url,
                source_name, category, service, doc_type,
            )
            if not child_rec:
                continue

            # Use page Last-Modified as date fallback
            if not child_rec.get("release_date") and feat_date:
                child_rec["release_date"] = feat_date
            if not child_rec.get("release_code") and rel_code:
                child_rec["release_code"] = rel_code

            is_new = _store_rec(child_rec, source_name)
            total_found += 1
            if is_new:
                total_new += 1

    log.info("HCM readiness crawl complete: %d found, %d new", total_found, total_new)
    return total_found, total_new


def _follow_hcm_detail_links(
    parent_records: list[dict],
    source_name: str,
    category: str,
    service: str,
    doc_type: str,
) -> tuple[int, int]:
    """
    Legacy: for hub records that embed detail-page links in their content
    ("description — Links: url1, url2"), fetch those pages and parse feature
    headings as child records.  Kept for non-hub HCM sources that still use
    the old link-embedding approach.

    Returns (total_found, total_new).
    """
    found = 0
    new   = 0

    for rec in parent_records:
        content = rec.get("content", "")
        m = re.search(r"— Links: (.+)$", content)
        if not m:
            continue

        raw_urls     = [u.strip() for u in m.group(1).split(",") if u.strip()]
        parent_title = rec["title"]
        parent_url   = rec.get("source_url", "")

        for url in raw_urls[:3]:
            if not url.startswith("http"):
                url = urljoin(parent_url, url)

            html, page_date = fetch_page(url)
            if not html:
                log.warning("  HCM detail link unreachable: %s", url)
                continue

            child_records = parse_hcm_detail_page(
                html, parent_title, url, source_name, category, service, doc_type
            )
            if page_date:
                for cr in child_records:
                    if not cr.get("release_date"):
                        cr["release_date"] = page_date

            for child_rec in child_records:
                cached = get_cached_classification(source_name, child_rec["title"])
                if cached:
                    child_rec.update(cached)
                if not child_rec.get("impact_level"):
                    child_rec = classify(child_rec)
                if not child_rec.get("summary"):
                    child_rec["summary"] = rule_based_summary(
                        child_rec["title"], child_rec["content"]
                    )
                _stored, is_new = upsert_update(child_rec)
                found += 1
                if is_new:
                    new += 1

    return found, new


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

        # ── HCM What's New: dedicated multi-step crawl ────────────────────
        # The hub page (hcm.html) is fully JS-rendered but inlines a script
        # block listing all module paths.  We parse that JSON, then crawl
        # each module's toc.htm and individual feature pages directly.
        if category == "HCM" and doc_type == "whats_new":
            sources_done += 1
            log.info("HCM readiness hub — starting multi-step crawl …")
            d_found, d_new = _crawl_hcm_readiness(
                source_name, url, category, service, doc_type
            )
            total_found += d_found
            total_new   += d_new
            if d_found > 0:
                any_real = True
            continue

        # ── Standard crawl for all other sources ──────────────────────────
        html, page_date = fetch_page(url)
        sources_done += 1

        if not html:
            log.warning("Skipping %s — no content returned", source_name)
            continue

        any_real = True
        save_raw_page(source_name, url, html, category)

        records = parse_oracle_page(
            html, source_name, url, category, service, doc_type,
            page_date=page_date,
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

    # ── HCM What's New mock seeding ───────────────────────────────────────────
    # Always ensure the 26A mock records (parent + children) are present so the
    # app has meaningful data even before the first live crawl succeeds.
    if seed_mock:
        for mock_rec in get_mock_records():
            if (mock_rec.get("category") == "HCM"
                    and mock_rec.get("doc_type") == "whats_new"):
                if not mock_rec.get("impact_level"):
                    mock_rec = classify(mock_rec)
                if not mock_rec.get("summary"):
                    mock_rec["summary"] = rule_based_summary(
                        mock_rec["title"], mock_rec["content"]
                    )
                _stored, is_new = upsert_update(mock_rec)
                total_found += 1
                if is_new:
                    total_new += 1

    # ── Full mock/seed fallback (all sources failed) ───────────────────────────
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

    if not CRAWL_SCHEDULE_ENABLED:
        log.info(
            "Automatic crawling is DISABLED (CRAWL_SCHEDULE=false). "
            "Use the 'Crawl Now' button in the UI to trigger a crawl manually."
        )
        return

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
