"""
storage/file_store.py — Persist raw HTML/text pages to disk.

Each page is saved under data/raw/<category>/<safe_filename>_<timestamp>.html
alongside a JSON sidecar with metadata.
"""

import hashlib
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import RAW_DIR

log = logging.getLogger(__name__)


def _safe_name(text: str) -> str:
    """Convert arbitrary string to a safe filename component."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", text)[:80]


def save_raw_page(
    source_name: str,
    url: str,
    html: str,
    category: str = "general",
) -> Path:
    """Write raw HTML + JSON sidecar.  Returns path to the HTML file."""
    folder = RAW_DIR / _safe_name(category)
    folder.mkdir(parents=True, exist_ok=True)

    ts        = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    slug      = _safe_name(source_name)
    html_path = folder / f"{slug}_{ts}.html"
    meta_path = folder / f"{slug}_{ts}.json"

    html_path.write_text(html, encoding="utf-8")
    meta = {
        "source_name": source_name,
        "url":         url,
        "category":    category,
        "fetched_at":  datetime.utcnow().isoformat(),
        "size_bytes":  len(html.encode("utf-8")),
        "sha256":      hashlib.sha256(html.encode("utf-8")).hexdigest(),
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    log.debug("Saved raw page → %s", html_path)
    return html_path


def list_raw_files(category: Optional[str] = None) -> list[Path]:
    """Return all saved HTML files, optionally filtered by category."""
    if category:
        folder = RAW_DIR / _safe_name(category)
        return sorted(folder.glob("*.html")) if folder.exists() else []
    return sorted(RAW_DIR.rglob("*.html"))
