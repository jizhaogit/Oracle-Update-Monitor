"""
storage/models.py — SQLAlchemy ORM models.
"""

import json
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class OracleUpdate(Base):
    """One release-note / what's-new entry from Oracle documentation."""

    __tablename__ = "oracle_updates"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    source_name   = Column(String(200), nullable=False)
    source_url    = Column(String(500), nullable=False)
    category      = Column(String(50),  nullable=False)   # OCI | OIC
    service       = Column(String(100), nullable=False)
    doc_type      = Column(String(50),  nullable=False)   # release_notes | whats_new

    title         = Column(String(500), nullable=False)
    content       = Column(Text, nullable=False)
    summary       = Column(Text, nullable=True)
    _tags         = Column("tags", Text, nullable=True)
    impact_level  = Column(String(20),  nullable=True)    # High | Medium | Low
    release_date  = Column(DateTime,    nullable=True)
    crawled_at    = Column(DateTime,    default=datetime.utcnow)
    content_hash  = Column(String(64),  unique=True, nullable=False)
    is_new        = Column(Boolean,     default=True)
    vector_id     = Column(String(100), nullable=True)

    # ── Version tracking ──────────────────────────────────────────────────────
    # title_key: SHA-256 of (source_name + title) — stable identifier across
    # content changes, lets us detect when the same document is updated.
    title_key     = Column(String(64),  nullable=True, index=True)
    version_count = Column(Integer,     default=1)        # how many versions exist

    # ── Tag helpers ───────────────────────────────────────────────────────────
    @property
    def tags(self) -> list[str]:
        if self._tags:
            try:
                return json.loads(self._tags)
            except Exception:
                return []
        return []

    @tags.setter
    def tags(self, value: list[str]) -> None:
        self._tags = json.dumps(value)

    def to_dict(self) -> dict:
        return {
            "id":            self.id,
            "source_name":   self.source_name,
            "source_url":    self.source_url,
            "category":      self.category,
            "service":       self.service,
            "doc_type":      self.doc_type,
            "title":         self.title,
            "content":       self.content,
            "summary":       self.summary,
            "tags":          self.tags,
            "impact_level":  self.impact_level,
            "release_date":  self.release_date.isoformat() if self.release_date else None,
            "crawled_at":    self.crawled_at.isoformat() if self.crawled_at else None,
            "is_new":        self.is_new,
            "title_key":     self.title_key,
            "version_count": self.version_count or 1,
        }

    def __repr__(self) -> str:
        return f"<OracleUpdate id={self.id} title={self.title[:50]!r}>"


class UpdateVersion(Base):
    """
    Historical snapshot of an OracleUpdate record.
    Created whenever the live content of a known document changes between crawls.
    """

    __tablename__ = "update_versions"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    update_id     = Column(Integer, nullable=False, index=True)  # FK → oracle_updates.id
    version_num   = Column(Integer, nullable=False, default=1)   # 1 = oldest snapshot
    content_hash  = Column(String(64), nullable=True)
    title         = Column(String(500), nullable=True)
    content       = Column(Text, nullable=True)
    summary       = Column(Text, nullable=True)
    _tags         = Column("tags", Text, nullable=True)
    impact_level  = Column(String(20),  nullable=True)
    release_date  = Column(DateTime,    nullable=True)
    saved_at      = Column(DateTime,    default=datetime.utcnow)  # when we archived this

    @property
    def tags(self) -> list[str]:
        if self._tags:
            try:
                return json.loads(self._tags)
            except Exception:
                return []
        return []

    def to_dict(self) -> dict:
        return {
            "id":           self.id,
            "update_id":    self.update_id,
            "version_num":  self.version_num,
            "content_hash": self.content_hash,
            "title":        self.title,
            "content":      self.content,
            "summary":      self.summary,
            "tags":         self.tags,
            "impact_level": self.impact_level,
            "release_date": self.release_date.isoformat() if self.release_date else None,
            "saved_at":     self.saved_at.isoformat() if self.saved_at else None,
        }


class AnalysisCache(Base):
    """
    Cached AI analysis result for a specific set of update IDs.
    Keyed by a SHA-256 hash of the sorted ID list so the same selection
    always resolves to the same cache entry.
    """

    __tablename__ = "analysis_cache"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    ids_key     = Column(String(64), unique=True, nullable=False, index=True)
    ids_json    = Column(Text, nullable=False)   # JSON array of sorted IDs
    analysis    = Column(Text, nullable=False)   # Markdown text from LLM
    generated_at = Column(DateTime, default=datetime.now)

    def to_dict(self) -> dict:
        return {
            "ids_key":      self.ids_key,
            "ids":          json.loads(self.ids_json),
            "analysis":     self.analysis,
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
        }


class CrawlRun(Base):
    """Audit log for each scheduler run."""

    __tablename__ = "crawl_runs"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    started_at    = Column(DateTime, default=datetime.utcnow)
    completed_at  = Column(DateTime, nullable=True)
    sources_tried = Column(Integer,  default=0)
    updates_found = Column(Integer,  default=0)
    updates_new   = Column(Integer,  default=0)
    status        = Column(String(20), default="running")
    error_message = Column(Text, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id":            self.id,
            "started_at":    self.started_at.isoformat() if self.started_at else None,
            "completed_at":  self.completed_at.isoformat() if self.completed_at else None,
            "sources_tried": self.sources_tried,
            "updates_found": self.updates_found,
            "updates_new":   self.updates_new,
            "status":        self.status,
            "error_message": self.error_message,
        }
