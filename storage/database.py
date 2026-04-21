"""
storage/database.py — Database session management and CRUD helpers.
"""

import hashlib
import logging
from contextlib import contextmanager
from datetime import datetime
from typing import Generator, Optional

from sqlalchemy import create_engine, func, or_
from sqlalchemy.orm import scoped_session, sessionmaker

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import DATABASE_URL
from storage.models import AnalysisCache, Base, CrawlRun, OracleUpdate, UpdateVersion

log = logging.getLogger(__name__)

# ── Engine & Session factory ───────────────────────────────────────────────────
_engine  = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
# expire_on_commit=False keeps attribute values accessible after the session
# closes, preventing DetachedInstanceError when objects are used outside scope.
_factory = sessionmaker(bind=_engine, autoflush=False, autocommit=False,
                        expire_on_commit=False)
Session  = scoped_session(_factory)


def init_db() -> None:
    """
    Create all tables (idempotent) and migrate any missing columns.

    SQLAlchemy's create_all() only creates tables that don't exist yet —
    it never alters existing tables.  We therefore run explicit
    ALTER TABLE statements for every column added after the initial schema,
    catching the 'duplicate column' error so re-runs are safe.
    """
    Base.metadata.create_all(_engine)

    # Columns added in v2 (version-tracking feature)
    _add_column_if_missing("oracle_updates", "title_key",     "VARCHAR(64)")
    _add_column_if_missing("oracle_updates", "version_count", "INTEGER DEFAULT 1")
    # Columns added in v3 (analysis cache feature)
    _add_column_if_missing("analysis_cache", "ids_json",     "TEXT")
    _add_column_if_missing("analysis_cache", "analysis",     "TEXT")
    _add_column_if_missing("analysis_cache", "generated_at", "DATETIME")
    # Columns added in v4 (Oracle release code)
    _add_column_if_missing("oracle_updates", "release_code", "VARCHAR(20)")
    # Columns added in v5 (manual review flag)
    _add_column_if_missing("oracle_updates", "is_flagged", "BOOLEAN DEFAULT 0")
    _add_column_if_missing("oracle_updates", "flag_note",  "TEXT")
    # Columns added in v6 (user overrides — survive crawl refreshes)
    _add_column_if_missing("oracle_updates", "impact_overridden", "BOOLEAN DEFAULT 0")
    _add_column_if_missing("oracle_updates", "user_comment",      "TEXT")
    # Columns added in v7 (PSA / TES project tracking fields)
    _add_column_if_missing("oracle_updates", "tes_owner",         "VARCHAR(200)")
    _add_column_if_missing("oracle_updates", "psa_owner",         "VARCHAR(200)")
    _add_column_if_missing("oracle_updates", "function_category", "VARCHAR(200)")
    _add_column_if_missing("oracle_updates", "next_action",       "TEXT")
    _add_column_if_missing("oracle_updates", "profile_options",   "TEXT")
    _add_column_if_missing("oracle_updates", "psa_comments",      "TEXT")
    _add_column_if_missing("oracle_updates", "tes_status",        "VARCHAR(100)")

    # Data migration v5 — re-classify UI/Redwood records Low → Medium
    _backfill_ui_impact()

    log.info("Database initialised at %s", DATABASE_URL)


def _add_column_if_missing(table: str, column: str, col_type: str) -> None:
    """ALTER TABLE … ADD COLUMN if the column does not exist yet."""
    with _engine.connect() as conn:
        # PRAGMA returns one row per existing column
        result = conn.execute(
            __import__("sqlalchemy").text(f"PRAGMA table_info({table})")
        )
        existing = {row[1] for row in result}   # row[1] is the column name
        if column not in existing:
            conn.execute(
                __import__("sqlalchemy").text(
                    f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
                )
            )
            conn.commit()
            log.info("Migrated: added column %s.%s", table, column)


def _backfill_ui_impact() -> None:
    """
    One-time idempotent migration: promote Low-impact records that contain
    UI / new-feature keywords to Medium, and tag them as "Redwood UI".

    Rules (applied to title + content, case-insensitive):
      • Any of: "introduction", "redwood", "new experience", "redesigned",
        "new section"  →  Low  becomes  Medium
      • Any of: "redwood", "new experience"  →  adds "Redwood UI" tag
      • Already High remains High (never downgraded).
    """
    import json as _json

    _UI_MEDIUM_KW  = ["introduction", "redwood", "new experience",
                      "redesigned", "new section"]
    _UI_TAG_KW     = ["redwood", "new experience"]
    _UI_TAG        = "Redwood UI"

    with session_scope() as s:
        rows = (
            s.query(OracleUpdate)
             .filter(OracleUpdate.impact_level == "Low")
             .all()
        )
        promoted = 0
        tagged   = 0
        for rec in rows:
            text = ((rec.title or "") + " " + (rec.content or "")).lower()

            needs_medium = any(kw in text for kw in _UI_MEDIUM_KW)
            needs_tag    = any(kw in text for kw in _UI_TAG_KW)

            if needs_medium:
                rec.impact_level = "Medium"
                promoted += 1

            if needs_tag:
                try:
                    tags = _json.loads(rec._tags or "[]")
                    if _UI_TAG not in tags:
                        tags.append(_UI_TAG)
                        rec._tags = _json.dumps(tags)
                        tagged += 1
                except Exception:
                    pass

        if promoted or tagged:
            log.info("UI backfill: %d records promoted Low→Medium, %d tagged '%s'",
                     promoted, tagged, _UI_TAG)


@contextmanager
def session_scope() -> Generator:
    session = Session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ── Version tracking helper ────────────────────────────────────────────────────

def _title_key(source_name: str, title: str) -> str:
    """
    Stable SHA-256 identifier for a logical document (source + title).
    Used to detect when the *same* document is updated between crawls.
    """
    raw = f"{source_name.strip()}::{title.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ── Classification cache lookup ────────────────────────────────────────────────

def get_cached_classification(source_name: str, title: str) -> Optional[dict]:
    """
    Return the stored impact_level, summary, and tags for an already-known record,
    or None if this title has never been crawled before.
    Used by the scheduler to skip LLM calls for unchanged records.
    """
    tk = _title_key(source_name, title)
    with session_scope() as s:
        row = s.query(OracleUpdate).filter_by(title_key=tk).first()
        if row and row.impact_level:
            return {
                "impact_level": row.impact_level,
                "summary":      row.summary,
                "tags":         row.tags,
            }
    return None


# ── OracleUpdate CRUD ──────────────────────────────────────────────────────────

def upsert_update(data: dict) -> tuple[dict, bool]:
    """
    Insert or update an Oracle update, tracking version history.

    Logic:
      1. Look up by title_key (same logical document, any content).
      2. If found with SAME content_hash  → no change, return False.
      3. If found with DIFFERENT hash     → archive old content as a version,
                                            update main record, return True.
      4. Fall back to content_hash lookup for legacy rows without title_key.
      5. Nothing found                    → insert new row, return True.

    Always returns a plain dict (never a live ORM object).
    """
    tk = _title_key(data.get("source_name", ""), data.get("title", ""))

    with session_scope() as s:
        # ── 1. Look up by stable title_key ────────────────────────────────
        existing = s.query(OracleUpdate).filter_by(title_key=tk).first()

        # ── 2. Fallback: content_hash (covers rows seeded before versioning)
        if existing is None:
            existing = s.query(OracleUpdate).filter_by(
                content_hash=data["content_hash"]
            ).first()

        if existing is not None:
            # Same content — but backfill date / release_code if they were missing
            if existing.content_hash == data["content_hash"]:
                changed = False
                if existing.release_date is None and data.get("release_date"):
                    existing.release_date = data["release_date"]
                    changed = True
                if existing.release_code is None and data.get("release_code"):
                    existing.release_code = data["release_code"]
                    changed = True
                if changed:
                    s.flush()
                    log.debug("Backfilled date/code for id=%s: %s", existing.id, existing.title[:60])
                return existing.to_dict(), False

            # ── 3. Content changed: archive the old snapshot ───────────────
            old_ver_num = existing.version_count or 1
            snapshot = UpdateVersion(
                update_id    = existing.id,
                version_num  = old_ver_num,
                content_hash = existing.content_hash,
                title        = existing.title,
                content      = existing.content,
                summary      = existing.summary,
                _tags        = existing._tags,
                impact_level = existing.impact_level,
                release_date = existing.release_date,
                saved_at     = datetime.utcnow(),
            )
            s.add(snapshot)

            # Update the main record to the new content.
            # User overrides (impact_overridden, is_flagged, flag_note, user_comment)
            # are intentionally NOT touched — they survive crawl refreshes.
            existing.content       = data.get("content", existing.content)
            existing.summary       = data.get("summary")          # will be regenerated
            existing._tags         = data.get("_tags", existing._tags)
            # Only update impact if the user has NOT manually set it
            if not existing.impact_overridden:
                existing.impact_level = data.get("impact_level", existing.impact_level)
            existing.release_code  = data.get("release_code", existing.release_code)
            existing.content_hash  = data["content_hash"]
            existing.crawled_at    = datetime.utcnow()
            existing.is_new        = True
            existing.title_key     = tk
            existing.version_count = old_ver_num + 1

            s.flush()
            log.info("Updated existing record id=%s (now v%s): %s",
                     existing.id, existing.version_count, existing.title[:60])
            return existing.to_dict(), True

        # ── 4/5. New record ────────────────────────────────────────────────
        data["title_key"]     = tk
        data["version_count"] = 1
        record = OracleUpdate(**data)
        s.add(record)
        s.flush()
        s.refresh(record)
        log.debug("Inserted new update: %s", record.title[:80])
        return record.to_dict(), True


def get_update(update_id: int) -> Optional[OracleUpdate]:
    with session_scope() as s:
        return s.query(OracleUpdate).filter_by(id=update_id).first()


def get_update_dict(update_id: int) -> Optional[dict]:
    with session_scope() as s:
        rec = s.query(OracleUpdate).filter_by(id=update_id).first()
        return rec.to_dict() if rec else None


def get_updates_by_ids(ids: list[int]) -> list[dict]:
    """Fetch multiple updates by ID list."""
    if not ids:
        return []
    with session_scope() as s:
        rows = s.query(OracleUpdate).filter(OracleUpdate.id.in_(ids)).all()
        # Preserve the requested order
        order = {uid: i for i, uid in enumerate(ids)}
        rows.sort(key=lambda r: order.get(r.id, 9999))
        return [r.to_dict() for r in rows]


def list_updates(
    category:     Optional[str]  = None,
    service:      Optional[str]  = None,
    impact_level: Optional[str]  = None,
    is_new:       Optional[bool] = None,
    search:       Optional[str]  = None,
    limit:        int = 200,
    offset:       int = 0,
) -> list[dict]:
    with session_scope() as s:
        q = s.query(OracleUpdate)
        if category:
            q = q.filter(OracleUpdate.category == category)
        if service:
            q = q.filter(OracleUpdate.service == service)
        if impact_level:
            q = q.filter(OracleUpdate.impact_level == impact_level)
        if is_new is not None:
            q = q.filter(OracleUpdate.is_new == is_new)
        if search:
            like = f"%{search}%"
            q = q.filter(or_(
                OracleUpdate.title.ilike(like),
                OracleUpdate.content.ilike(like),
                OracleUpdate.summary.ilike(like),
            ))
        rows = (q.order_by(OracleUpdate.crawled_at.desc())
                  .offset(offset).limit(limit).all())
        return [r.to_dict() for r in rows]


def multi_keyword_search(keywords: list[str], limit: int = 100) -> list[dict]:
    """
    Search across title + summary + content for ANY of the given keywords (OR logic).
    Results are ranked by how many keywords matched (descending), then by date.
    """
    if not keywords:
        return []

    with session_scope() as s:
        # Collect all matching rows and count hits per row
        seen: dict[int, dict] = {}       # id → record dict
        hits: dict[int, int]  = {}       # id → keyword hit count

        for kw in keywords:
            like = f"%{kw}%"
            rows = (
                s.query(OracleUpdate)
                 .filter(or_(
                     OracleUpdate.title.ilike(like),
                     OracleUpdate.summary.ilike(like),
                     OracleUpdate.content.ilike(like),
                 ))
                 .all()
            )
            for row in rows:
                if row.id not in seen:
                    seen[row.id] = row.to_dict()
                    hits[row.id] = 0
                hits[row.id] += 1

    # Sort by hit count descending, then by release_date descending.
    # reverse=True works on both because ISO date strings sort lexicographically
    # ("2026-04-01" > "2025-01-01"), and higher hit counts should come first.
    # Rows with no date get "0000-00-00" so they sort last when reversed.
    ranked = sorted(
        seen.values(),
        key=lambda r: (hits[r["id"]], r.get("release_date") or "0000-00-00"),
        reverse=True,
    )
    return ranked[:limit]


def get_distinct_services() -> list[str]:
    with session_scope() as s:
        rows = s.query(OracleUpdate.service).distinct().all()
    return sorted(r[0] for r in rows if r[0])


def get_distinct_categories() -> list[str]:
    with session_scope() as s:
        rows = s.query(OracleUpdate.category).distinct().all()
    return sorted(r[0] for r in rows if r[0])


def get_stats() -> dict:
    with session_scope() as s:
        total    = s.query(func.count(OracleUpdate.id)).scalar() or 0
        new      = s.query(func.count(OracleUpdate.id)).filter(OracleUpdate.is_new == True).scalar() or 0
        by_cat   = s.query(OracleUpdate.category, func.count(OracleUpdate.id)).group_by(OracleUpdate.category).all()
        by_svc   = s.query(OracleUpdate.service,  func.count(OracleUpdate.id)).group_by(OracleUpdate.service).all()
        by_imp   = s.query(OracleUpdate.impact_level, func.count(OracleUpdate.id)).group_by(OracleUpdate.impact_level).all()
        last_run = (s.query(CrawlRun)
                     .filter(CrawlRun.status != "running")
                     .order_by(CrawlRun.completed_at.desc())
                     .first())
    return {
        "total":       total,
        "new":         new,
        "by_category": dict(by_cat),
        "by_service":  dict(by_svc),
        "by_impact":   dict(by_imp),
        "last_run":    last_run.to_dict() if last_run else None,
    }


def mark_all_seen() -> int:
    with session_scope() as s:
        n = s.query(OracleUpdate).filter(OracleUpdate.is_new == True).update({"is_new": False})
    return n


def delete_by_category(categories: list[str]) -> int:
    """
    Permanently delete all OracleUpdate rows whose category is in *categories*.
    Also removes any associated UpdateVersion rows (cascade via Python loop).

    Returns the number of rows deleted from oracle_updates.
    """
    if not categories:
        return 0
    with session_scope() as s:
        rows = s.query(OracleUpdate).filter(OracleUpdate.category.in_(categories)).all()
        ids  = [r.id for r in rows]
        if ids:
            s.query(UpdateVersion).filter(UpdateVersion.update_id.in_(ids)).delete(
                synchronize_session=False
            )
        n = len(rows)
        for r in rows:
            s.delete(r)
    log.info("Deleted %d record(s) with category in %s", n, categories)
    return n


def delete_legacy_records() -> int:
    """
    Delete stale mock/seed records that no longer match active sources:
      • HCM records whose doc_type is NOT 'whats_new'
        (legacy REST API mock records from before the HCM-only reconfiguration)
      • OCI records (OCI is not an active crawl source)

    OIC records are intentionally kept — OIC What's New and Release Notes
    are active sources and should never be purged here.

    Returns the total number of rows deleted.
    """
    from sqlalchemy import and_, or_
    with session_scope() as s:
        rows = s.query(OracleUpdate).filter(
            or_(
                OracleUpdate.category == "OCI",
                and_(
                    OracleUpdate.category == "HCM",
                    OracleUpdate.doc_type  != "whats_new",
                ),
            )
        ).all()
        ids = [r.id for r in rows]
        if ids:
            s.query(UpdateVersion).filter(UpdateVersion.update_id.in_(ids)).delete(
                synchronize_session=False
            )
        n = len(rows)
        for r in rows:
            s.delete(r)
    log.info("delete_legacy_records: removed %d record(s)", n)
    return n


# ── Version history ────────────────────────────────────────────────────────────

def get_versions(update_id: int) -> list[dict]:
    """Return all archived snapshots for a given update, oldest first."""
    with session_scope() as s:
        rows = (s.query(UpdateVersion)
                  .filter_by(update_id=update_id)
                  .order_by(UpdateVersion.version_num.asc())
                  .all())
    return [r.to_dict() for r in rows]


# ── AnalysisCache CRUD ─────────────────────────────────────────────────────────

def _analysis_ids_key(ids: list[int]) -> str:
    """Stable SHA-256 key for a sorted list of update IDs."""
    canonical = ",".join(str(i) for i in sorted(ids))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def get_analysis_cache(ids: list[int]) -> Optional[dict]:
    """Return the cached analysis for the given ID set, or None."""
    key = _analysis_ids_key(ids)
    with session_scope() as s:
        row = s.query(AnalysisCache).filter_by(ids_key=key).first()
        return row.to_dict() if row else None


def save_analysis_cache(ids: list[int], analysis: str) -> dict:
    """Insert or replace the cached analysis for the given ID set."""
    import json as _json
    key = _analysis_ids_key(ids)
    with session_scope() as s:
        row = s.query(AnalysisCache).filter_by(ids_key=key).first()
        if row:
            row.analysis     = analysis
            row.generated_at = datetime.now()
            row.ids_json     = _json.dumps(sorted(ids))
        else:
            row = AnalysisCache(
                ids_key      = key,
                ids_json     = _json.dumps(sorted(ids)),
                analysis     = analysis,
                generated_at = datetime.now(),
            )
            s.add(row)
        s.flush()
        return row.to_dict()


# ── CrawlRun CRUD ──────────────────────────────────────────────────────────────

def start_crawl_run() -> int:
    with session_scope() as s:
        run = CrawlRun(started_at=datetime.utcnow())
        s.add(run)
        s.flush()
        return run.id


def finish_crawl_run(run_id, sources_tried, updates_found, updates_new,
                     status="success", error=None):
    with session_scope() as s:
        run = s.query(CrawlRun).filter_by(id=run_id).first()
        if run:
            run.completed_at  = datetime.utcnow()
            run.sources_tried = sources_tried
            run.updates_found = updates_found
            run.updates_new   = updates_new
            run.status        = status
            run.error_message = error


def list_crawl_runs(limit: int = 20) -> list[dict]:
    with session_scope() as s:
        rows = (s.query(CrawlRun)
                  .order_by(CrawlRun.started_at.desc())
                  .limit(limit).all())
    return [r.to_dict() for r in rows]


def update_classification(update_id: int, impact_level: str,
                          tags: list, summary: str) -> None:
    """
    Overwrite the LLM-derived classification fields on a record.
    Unlike set_impact(), this does NOT set impact_overridden — it is used for
    bulk re-classification triggered by the user via "Mark Impact", not for
    manual per-record overrides.
    Records where impact_overridden=True are intentionally skipped so that
    the user's manual override survives a bulk re-run.
    """
    import json as _json
    with session_scope() as s:
        rec = s.query(OracleUpdate).filter(OracleUpdate.id == update_id).first()
        if rec is None:
            return
        if rec.impact_overridden:
            return          # honour manual override — never overwrite
        if impact_level:
            rec.impact_level = impact_level
        if tags is not None:
            rec._tags = _json.dumps(tags)
        if summary:
            rec.summary = summary


def set_impact(update_id: int, impact_level: Optional[str]) -> Optional[dict]:
    """
    Manually override the impact level of an update record.

    Parameters
    ----------
    update_id    : the oracle_updates.id to update
    impact_level : "High" | "Medium" | "Low" | None (None resets to auto-classify)

    Returns the updated record dict, or None if not found.
    """
    valid = {"High", "Medium", "Low", None}
    if impact_level not in valid:
        raise ValueError(f"impact_level must be one of {valid}")
    with session_scope() as s:
        rec = s.query(OracleUpdate).filter(OracleUpdate.id == update_id).first()
        if rec is None:
            return None
        rec.impact_level      = impact_level
        # Mark as overridden so crawl upserts won't reset it.
        # If impact_level is None (reset), clear the override flag too.
        rec.impact_overridden = impact_level is not None
    with session_scope() as s:
        rec = s.query(OracleUpdate).filter(OracleUpdate.id == update_id).first()
        return rec.to_dict() if rec else None


def set_comment(update_id: int, comment: str) -> Optional[dict]:
    """
    Save a free-text user comment on an update record.
    The comment is independent of the review flag and survives crawl refreshes.
    """
    with session_scope() as s:
        rec = s.query(OracleUpdate).filter(OracleUpdate.id == update_id).first()
        if rec is None:
            return None
        rec.user_comment = comment.strip()
    with session_scope() as s:
        rec = s.query(OracleUpdate).filter(OracleUpdate.id == update_id).first()
        return rec.to_dict() if rec else None


def set_psa_fields(update_id: int, fields: dict) -> Optional[dict]:
    """
    Save PSA / TES project tracking fields on an update record.
    Only the keys present in *fields* are updated; omitted keys are left as-is.

    Accepted keys (all optional):
        tes_owner, psa_owner, function_category,
        next_action, profile_options, psa_comments, tes_status
    """
    _allowed = {
        "tes_owner", "psa_owner", "function_category",
        "next_action", "profile_options", "psa_comments", "tes_status",
    }
    with session_scope() as s:
        rec = s.query(OracleUpdate).filter(OracleUpdate.id == update_id).first()
        if rec is None:
            return None
        for key, val in fields.items():
            if key in _allowed:
                setattr(rec, key, val if val else None)
    with session_scope() as s:
        rec = s.query(OracleUpdate).filter(OracleUpdate.id == update_id).first()
        return rec.to_dict() if rec else None


def set_flag(update_id: int, is_flagged: bool, note: str = "") -> Optional[dict]:
    """
    Set or clear the manual review flag on an update record.

    Parameters
    ----------
    update_id  : the oracle_updates.id to update
    is_flagged : True = flag for review, False = clear flag
    note       : free-text annotation (Jira URL, reason, etc.)

    Returns the updated record dict, or None if not found.
    """
    with session_scope() as s:
        rec = s.query(OracleUpdate).filter(OracleUpdate.id == update_id).first()
        if rec is None:
            return None
        rec.is_flagged = is_flagged
        rec.flag_note  = note.strip() if is_flagged else ""
    # Re-fetch outside the session (expire_on_commit=False keeps values)
    with session_scope() as s:
        rec = s.query(OracleUpdate).filter(OracleUpdate.id == update_id).first()
        return rec.to_dict() if rec else None
