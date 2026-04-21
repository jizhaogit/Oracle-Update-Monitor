"""
crawler/parser.py — Parse Oracle OCI/OIC documentation pages into
                    structured update records.

Strategy
--------
1. Try service-specific CSS selectors for known Oracle page layouts.
2. Fall back to generic heuristics (headings + following paragraphs).
3. If nothing is found, treat the whole visible text as one entry.
4. Always include sample/mock data so the UI is never empty on first run.
"""

import hashlib
import logging
import re
from datetime import datetime
from typing import Optional

from bs4 import BeautifulSoup, Tag

log = logging.getLogger(__name__)

# ── Date patterns ──────────────────────────────────────────────────────────────
_DATE_PATTERNS = [
    (r"\b(\w+ \d{1,2},?\s+\d{4})\b",         "%B %d, %Y"),
    (r"\b(\w+ \d{4})\b",                       "%B %Y"),
    (r"\b(\d{4}-\d{2}-\d{2})\b",               "%Y-%m-%d"),
    (r"\b(\d{1,2}/\d{1,2}/\d{4})\b",           "%m/%d/%Y"),
]

# Oracle uses a YYX release naming convention where:
#   YY = 2-digit year (24 = 2024, 25 = 2025 …)
#   X  = quarterly letter: A = Q1 (Jan), B = Q2 (Apr), C = Q3 (Jul), D = Q4 (Oct)
_ORACLE_RELEASE_RE = re.compile(r"\b(\d{2})([A-D])\b", re.IGNORECASE)
_ORACLE_QUARTER_MONTH = {"A": 1, "B": 4, "C": 7, "D": 10}


def _parse_oracle_release(text: str) -> tuple[Optional[datetime], Optional[str]]:
    """
    Extract an Oracle YYX release code from *text* and return (date, code).

    Example: "26A" → (datetime(2026, 1, 1), "26A")
             "25D" → (datetime(2025, 10, 1), "25D")
    Returns (None, None) if no release code is found.
    """
    m = _ORACLE_RELEASE_RE.search(text)
    if not m:
        return None, None
    yy  = int(m.group(1))
    ltr = m.group(2).upper()
    year  = 2000 + yy
    month = _ORACLE_QUARTER_MONTH[ltr]
    code  = f"{yy}{ltr}"          # normalise to upper-case, e.g. "26A"
    return datetime(year, month, 1), code


def _parse_date(text: str) -> Optional[datetime]:
    # Try Oracle release code first (higher priority for HCM/OIC titles)
    dt, _ = _parse_oracle_release(text)
    if dt:
        return dt
    for pattern, fmt in _DATE_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            try:
                raw = m.group(1).replace(",", "").strip()
                raw = re.sub(r"\s+", " ", raw)
                return datetime.strptime(raw, fmt.replace(",", ""))
            except ValueError:
                continue
    return None


def _make_hash(title: str, content: str, url: str) -> str:
    payload = f"{url}|{title}|{content[:500]}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


# ── Oracle-specific selectors ──────────────────────────────────────────────────
def _try_oracle_release_notes(soup: BeautifulSoup) -> list[dict]:
    """Parse standard Oracle release-note page structure."""
    items: list[dict] = []

    # Oracle docs often use <section>, <article>, or <div class="section">
    sections = (
        soup.find_all("section")
        or soup.find_all("article")
        or soup.find_all("div", class_=re.compile(r"(section|release|notes?|entry)", re.I))
    )

    for sec in sections[:50]:   # cap at 50 items per page
        heading = sec.find(re.compile(r"^h[1-6]$"))
        if not heading:
            continue
        title = _clean(heading.get_text())
        if len(title) < 5:
            continue
        # Grab the paragraph text following the heading
        paras = sec.find_all(["p", "li", "ul"])
        content = " ".join(_clean(p.get_text()) for p in paras if p.get_text(strip=True))
        if not content:
            content = _clean(sec.get_text())
        date = _parse_date(content) or _parse_date(title)
        items.append({"title": title, "content": content, "release_date": date})

    return items


def _try_whats_new_list(soup: BeautifulSoup) -> list[dict]:
    """Parse 'What's New' style pages which are often definition lists or tables."""
    items: list[dict] = []

    # Try definition list pattern
    dts = soup.find_all("dt")
    for dt in dts[:50]:
        title = _clean(dt.get_text())
        dd = dt.find_next_sibling("dd")
        content = _clean(dd.get_text()) if dd else ""
        if len(title) < 5:
            continue
        date = _parse_date(content)
        items.append({"title": title, "content": content, "release_date": date})

    if items:
        return items

    # Try table rows
    rows = soup.find_all("tr")
    for row in rows[1:51]:   # skip header row
        cells = row.find_all(["td", "th"])
        if len(cells) >= 2:
            title   = _clean(cells[0].get_text())
            content = _clean(" ".join(c.get_text() for c in cells[1:]))
            if len(title) < 5:
                continue
            date = _parse_date(content) or _parse_date(title)
            items.append({"title": title, "content": content, "release_date": date})

    return items


def _generic_heading_parse(soup: BeautifulSoup) -> list[dict]:
    """Generic fallback: each H2/H3 becomes a separate entry."""
    items: list[dict] = []
    for heading in soup.find_all(["h2", "h3"])[:50]:
        title = _clean(heading.get_text())
        if len(title) < 5:
            continue
        parts = []
        for sibling in heading.next_siblings:
            if isinstance(sibling, Tag):
                if sibling.name in ("h2", "h3"):
                    break
                parts.append(_clean(sibling.get_text()))
        content = " ".join(p for p in parts if p)[:2000]
        date    = _parse_date(content) or _parse_date(title)
        items.append({"title": title, "content": content, "release_date": date})
    return items


# ── OIC-specific parsers ───────────────────────────────────────────────────────

def _try_oic_whats_new(soup: BeautifulSoup) -> list[dict]:
    """
    Parse Oracle OIC 'What's New' page.

    The page uses a flat sibling structure inside <div class="letterstyle">:
      <div class="sect4">  — release section heading (h3 + description div)
      <div class="sect5">  — feature sub-section (h4 + table inside a div)
      <div class="sect5">  — another sub-section under the same release
      <div class="sect4">  — next release section
      ...

    sect4 and sect5 divs are all direct children of letterstyle at the same
    level — sect5 does NOT nest inside sect4.

    This parser produces:
      1. One record per sect4 heading (e.g. "Oracle Integration Generation 2
         End of Life", "October 2025") with description text as content.
      2. One record per feature table row inside each sect5, titled
         "<Release> — <Feature name>" for full context.

    Falls back to generic h3-based parsing if the letterstyle structure is
    not found (e.g. Oracle changes their page layout).

    Caps: 60 release sections · 15 rows per sub-section table · 500 total.
    """
    items:  list[dict] = []
    seen:   set[str]   = set()
    MAX_TOTAL           = 500
    MAX_SECTIONS        = 60
    MAX_ROWS_PER_TABLE  = 15

    def _add_section(title: str, content: str) -> None:
        if title in seen or len(title) < 3:
            return
        seen.add(title)
        date = _parse_date(title) or _parse_date(content)
        items.append({"title": title, "content": content or title,
                      "release_date": date})

    def _add_feature(section_title: str, feat_name: str,
                     feat_desc: str, date) -> None:
        if len(feat_name) < 4:
            return
        full_title = f"{section_title} — {feat_name}"
        key = full_title.lower()
        if key in seen:
            return
        seen.add(key)
        items.append({"title": full_title[:480],
                      "content": feat_desc or feat_name,
                      "release_date": date})

    # ── Primary: letterstyle flat-sibling structure ─────────────────────────
    letterstyle = soup.find("div", class_="letterstyle")
    if letterstyle:
        current_section: str  = ""
        current_date           = None
        sections_seen          = 0

        for child in letterstyle.children:
            if not isinstance(child, Tag):
                continue
            if len(items) >= MAX_TOTAL:
                break

            classes = child.get("class") or []

            if "sect4" in classes:
                if sections_seen >= MAX_SECTIONS:
                    break
                heading = child.find("h3") or child.find("h2")
                if not heading:
                    continue
                current_section = _clean(heading.get_text())
                current_date    = _parse_date(current_section)
                # Description lives in a <div> or <p> sibling of the heading
                desc_parts = [
                    _clean(el.get_text())
                    for el in child.find_all(["p", "div"], recursive=False)
                    if _clean(el.get_text())
                ]
                _add_section(current_section,
                             " ".join(desc_parts)[:2000])
                sections_seen += 1

            elif "sect5" in classes and current_section:
                # Feature sub-section belonging to current_section
                for table in child.find_all("table"):
                    rows = table.find_all("tr")[1:]   # skip header
                    for row in rows[:MAX_ROWS_PER_TABLE]:
                        if len(items) >= MAX_TOTAL:
                            break
                        cells = row.find_all(["td", "th"])
                        if not cells:
                            continue
                        feat_name = _clean(cells[0].get_text())
                        feat_desc = (
                            _clean(" ".join(c.get_text() for c in cells[1:]))
                            if len(cells) > 1 else ""
                        )
                        _add_feature(current_section, feat_name,
                                     feat_desc, current_date)

        if items:
            return items

    # ── Fallback: h3-based flat parse (if letterstyle not found) ────────────
    current_section = ""
    current_date    = None
    sections_seen   = 0

    for tag in soup.find_all(["h3", "table"]):
        if len(items) >= MAX_TOTAL:
            break
        if tag.name == "h3":
            if sections_seen >= MAX_SECTIONS:
                break
            current_section = _clean(tag.get_text())
            current_date    = _parse_date(current_section)
            desc_div = tag.find_next_sibling(["p", "div"])
            desc = _clean(desc_div.get_text()) if desc_div else ""
            _add_section(current_section, desc)
            sections_seen += 1
        elif tag.name == "table" and current_section:
            rows = tag.find_all("tr")[1:]
            for row in rows[:MAX_ROWS_PER_TABLE]:
                if len(items) >= MAX_TOTAL:
                    break
                cells = row.find_all(["td", "th"])
                if not cells:
                    continue
                feat_name = _clean(cells[0].get_text())
                feat_desc = (
                    _clean(" ".join(c.get_text() for c in cells[1:]))
                    if len(cells) > 1 else ""
                )
                _add_feature(current_section, feat_name,
                             feat_desc, current_date)

    return items


# ── HCM-specific parsers ───────────────────────────────────────────────────────

def _try_hcm_api_usage(soup: BeautifulSoup) -> list[dict]:
    """
    Parse the Oracle HCM REST API index page
    (https://docs.oracle.com/en/cloud/saas/human-resources/index.html).

    The page lists available REST API resource groups. Each entry becomes one
    record whose content describes what the resource does and which HTTP
    operations (GET / POST / PATCH / DELETE) are supported.

    Strategy:
    1. Look for <table> rows listing resource names + descriptions (common Oracle
       API index layout).
    2. Fall back to <dt>/<dd> definition lists.
    3. Fall back to <h3>/<h4> heading + following paragraph.
    """
    items: list[dict] = []
    seen: set[str] = set()

    _method_words = {"get", "post", "patch", "put", "delete"}

    def _extract_methods(text: str) -> str:
        found = [m.upper() for m in _method_words if m in text.lower()]
        return ", ".join(found) if found else ""

    def _make_usage_content(title: str, description: str, methods: str) -> str:
        parts = []
        if methods:
            parts.append(f"Supported operations: {methods}")
        if description:
            parts.append(description)
        if not parts:
            parts.append(title)
        return " | ".join(parts)

    def _add(title: str, description: str) -> None:
        key = title.lower().strip()
        if len(title) < 4 or key in seen:
            return
        seen.add(key)
        methods = _extract_methods(description)
        content = _make_usage_content(title, description, methods)
        # GET-only resources are informational (Low); resources with write
        # operations warrant more attention (Medium/High)
        write_ops = {"POST", "PATCH", "PUT", "DELETE"}
        has_write = any(m in (methods or "") for m in write_ops)
        impact = "Medium" if has_write else "Low"
        summary = f"REST API resource — {title}" + (f" ({methods})" if methods else "")
        items.append({
            "title":        title,
            "content":      content,
            "release_date": None,
            "impact_level": impact,
            "summary":      summary,
        })

    # Strategy 1 — table rows (resource name | description | operations)
    for row in soup.find_all("tr")[1:500]:
        cells = row.find_all(["td", "th"])
        if len(cells) >= 2:
            title = _clean(cells[0].get_text())
            desc  = _clean(" ".join(c.get_text() for c in cells[1:]))
            _add(title, desc)

    if items:
        return items

    # Strategy 2 — definition list <dt>/<dd>
    for dt in soup.find_all("dt")[:500]:
        title = _clean(dt.get_text())
        dd    = dt.find_next_sibling("dd")
        desc  = _clean(dd.get_text(separator=" ")) if dd else ""
        _add(title, desc)

    if items:
        return items

    # Strategy 3 — heading + following paragraph
    for heading in soup.find_all(["h2", "h3", "h4"])[:200]:
        title = _clean(heading.get_text())
        parts: list[str] = []
        for sib in heading.next_siblings:
            if not isinstance(sib, Tag):
                continue
            if sib.name in ("h2", "h3", "h4"):
                break
            text = _clean(sib.get_text())
            if text:
                parts.append(text)
        _add(title, " ".join(parts)[:800])

    return items

def _try_hcm_rest_endpoints(soup: BeautifulSoup) -> list[dict]:
    """
    Parse Oracle HCM REST API endpoint pages.
    Structure: <dl> containing <dt><a>Operation name</a></dt><dd>Method + Path</dd>

    impact_level and summary are derived here (no LLM needed — content is
    already fully structured as Method + Path).
    """
    _skip = {"get action not supported", "post action not supported",
             "patch action not supported", "delete action not supported"}
    _method_impact = {"get": "Low", "delete": "High"}   # default Medium for others

    items: list[dict] = []
    seen: set[str] = set()
    for dt in soup.find_all("dt")[:500]:
        a = dt.find("a")
        title = _clean(a.get_text() if a else dt.get_text())
        if len(title) < 3 or title.lower() in _skip:
            continue
        dd = dt.find_next_sibling("dd")
        content = _clean(dd.get_text(separator=" ")) if dd else ""
        key = title.lower()
        if key in seen:
            continue
        seen.add(key)

        # Derive HTTP method and impact without calling an LLM
        method_match = re.search(r"Method:\s*(\w+)", content, re.I)
        method = method_match.group(1).lower() if method_match else ""
        impact = _method_impact.get(method, "Medium")
        summary = f"{method.upper()} endpoint — {title}" if method else title

        items.append({
            "title":        title,
            "content":      content or title,
            "release_date": None,
            "impact_level": impact,
            "summary":      summary,
        })
    return items


def _try_hcm_readiness(soup: BeautifulSoup) -> list[dict]:
    """
    Parse Oracle HCM Readiness hub pages.
    Structure: <h3>Module What's New XX</h3> followed by <p><a href="..."> links.
    The hub page is JS-rendered so actual section content may be sparse;
    we extract every heading + its following description paragraph as one entry.
    """
    items: list[dict] = []
    for heading in soup.find_all(["h2", "h3", "h4"])[:150]:
        title = _clean(heading.get_text())
        # Skip navigation / boilerplate headings
        if len(title) < 8 or title.lower() in ("contents", "overview", "search"):
            continue
        parts: list[str] = []
        links: list[str] = []
        for sib in heading.next_siblings:
            if not isinstance(sib, Tag):
                continue
            if sib.name in ("h2", "h3", "h4"):
                break
            text = _clean(sib.get_text())
            if text:
                parts.append(text)
            for a in sib.find_all("a", href=True):
                href = a["href"]
                if href.startswith("http") or href.endswith(".html"):
                    links.append(href)
        content = " ".join(parts)
        if links:
            content = (content + " — Links: " + ", ".join(links[:3])).strip(" —")
        date = _parse_date(content) or _parse_date(title)
        items.append({"title": title, "content": content or title, "release_date": date})
    return items


def parse_readiness_hub_modules(html: str, path_prefix: str = "hcm") -> list[dict]:
    """
    Extract the module list from an Oracle Fusion readiness hub page.

    Works for both hcm.html (path_prefix="hcm") and common.html
    (path_prefix="common").  The server inlines a JavaScript variable
    containing a JSON-like array of module entries, e.g.:
        {"title": "Payroll What's New 26B", "html": "hcm/26b/payr-26b/index.html", "position": 23}
        {"title": "Common Technologies ... 26B", "html": "common/26b/common26b/index.html", "position": 1}

    Returns a list of {"title": ..., "path": ...} dicts.
    """
    import json as _json

    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    modules: list[dict] = []
    seen: set[str]      = set()
    key = f'"{path_prefix}/'

    for script in soup.find_all("script"):
        text = script.string or ""
        if key not in text:
            continue

        # Each module object looks like: {"title":"...","html":"PREFIX/...","position":N}
        pattern = (
            r'\{[^{}]*?"html"\s*:\s*"('
            + re.escape(path_prefix)
            + r'/[^"]+\.html)"[^{}]*?\}'
        )
        for m in re.finditer(pattern, text, re.DOTALL):
            obj_str = m.group(0)
            path    = m.group(1)
            if path in seen:
                continue
            try:
                entry = _json.loads(obj_str)
                title = entry.get("title", "")
            except _json.JSONDecodeError:
                title_m = re.search(r'"title"\s*:\s*"([^"]+)"', obj_str)
                title   = title_m.group(1) if title_m else ""

            if title and path:
                seen.add(path)
                modules.append({"title": title, "path": path})

    log.info("Readiness hub (%s): found %d modules", path_prefix, len(modules))
    return modules


def parse_hcm_hub_modules(html: str) -> list[dict]:
    """Extract HCM module list from hcm.html. Wrapper for parse_readiness_hub_modules."""
    return parse_readiness_hub_modules(html, path_prefix="hcm")


def parse_common_hub_modules(html: str) -> list[dict]:
    """Extract Common Technologies module list from common.html."""
    return parse_readiness_hub_modules(html, path_prefix="common")


def parse_hcm_toc(html: str, toc_url: str) -> list[str]:
    """
    Parse an HCM module toc.htm and return feature page URLs.

    toc.htm contains <a href="..."> links pointing to individual feature pages
    (e.g. "26B-payroll-wn-f12345.htm").  Relative URLs are resolved against
    *toc_url* (the URL used to fetch this page).
    """
    from urllib.parse import urljoin

    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    urls: list[str] = []
    seen: set[str]  = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        # Strip fragment (#anchor) — toc.htm links use "file.htm#anchor-id"
        if "#" in href:
            href = href.split("#", 1)[0]
        if not href:
            continue
        # Only feature .htm links, not the toc itself or index
        if not href.endswith(".htm"):
            continue
        if href.endswith("toc.htm") or href.endswith("index.htm"):
            continue
        full = urljoin(toc_url, href)
        if full not in seen:
            seen.add(full)
            urls.append(full)

    log.info("HCM toc: %d feature URLs from %s", len(urls), toc_url)
    return urls


def parse_hcm_feature_page(
    html: str,
    parent_title: str,
    source_url: str,
    source_name: str,
    category: str,
    service: str,
    doc_type: str,
) -> Optional[dict]:
    """
    Parse one Oracle HCM feature readiness page.

    Oracle readiness pages embed the feature title in a Schema.org JSON-LD
    block (<script type="application/ld+json">), e.g.:
        {"@type":"WebPage","name":"Prior Salary and Graph Section...","datePublished":"2026-02-26"}

    Fallback chain for title extraction:
      1. Schema.org JSON-LD  "name"  field
      2. <meta name="dcterms.title"> content
      3. <title> HTML tag
      4. <h1> text

    Release code is extracted from dcterms.release meta → parent_title → URL.

    The record is titled "{parent_title} — {feature_title}" so the UI
    "Features in this Release" tree picks it up automatically.

    Returns a record dict or None if the page cannot be parsed.
    """
    import json as _json

    if not html:
        return None

    soup = BeautifulSoup(html, "lxml")

    def _meta(name: str) -> str:
        tag = soup.find("meta", attrs={"name": name})
        return (tag.get("content") or "").strip() if tag else ""

    # ── Title extraction (priority order) ─────────────────────────────────
    feat_title  = ""
    date_from_ld = None

    # 1. Schema.org JSON-LD — most reliable on Oracle readiness pages
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = _json.loads(script.string or "")
            name = data.get("name", "").strip()
            if name and len(name) > 4:
                feat_title = name
                # Also grab datePublished as a date hint
                dp = data.get("datePublished", "")
                if dp:
                    try:
                        date_from_ld = datetime.strptime(dp[:10], "%Y-%m-%d")
                    except ValueError:
                        pass
                break
        except Exception:
            pass

    # 2. dcterms.title meta
    if not feat_title:
        feat_title = _meta("dcterms.title")

    # 3. <title> HTML tag
    if not feat_title:
        title_tag = soup.find("title")
        if title_tag:
            feat_title = _clean(title_tag.get_text())

    # 4. <h1> text
    if not feat_title:
        h1 = soup.find("h1")
        feat_title = _clean(h1.get_text()) if h1 else ""

    if not feat_title:
        return None

    # ── Release code + date ────────────────────────────────────────────────
    release_raw  = _meta("dcterms.release")   # e.g. "26A"
    created_str  = _meta("dcterms.created")   # e.g. "2026-02-26 17:08:11"

    release_date, release_code = _parse_oracle_release(release_raw)
    # Derive from parent_title if not in meta (e.g. "HCM — Payroll What's New 26A")
    if not release_code:
        _, release_code = _parse_oracle_release(parent_title)
    # Derive from URL as last resort (e.g. ".../26a/comp-26a/...")
    if not release_code:
        url_m = re.search(r"/(\d{2}[A-D])/", source_url, re.IGNORECASE)
        if url_m:
            _, release_code = _parse_oracle_release(url_m.group(1))
    if release_code and not release_date:
        release_date, _ = _parse_oracle_release(release_code)

    # Date fallbacks: JSON-LD datePublished → dcterms.created
    if not release_date and date_from_ld:
        release_date = date_from_ld
    if not release_date and created_str:
        try:
            release_date = datetime.strptime(created_str[:10], "%Y-%m-%d")
        except ValueError:
            pass

    # Build content from h2 sections
    for noise in soup(["script", "style", "nav", "footer", "header"]):
        noise.decompose()

    sections: list[str] = []
    for h2 in soup.find_all("h2")[:10]:
        h_text = _clean(h2.get_text())
        parts: list[str] = []
        for sib in h2.next_siblings:
            if not isinstance(sib, Tag):
                continue
            if sib.name == "h2":
                break
            t = _clean(sib.get_text())
            if t:
                parts.append(t)
        body = " ".join(parts)[:600]
        if h_text and body:
            sections.append(f"{h_text}: {body}")

    content = " | ".join(sections) if sections else _clean(soup.get_text())[:2000]
    if not content:
        content = feat_title

    full_title = f"{parent_title} — {feat_title}"

    return {
        "source_name":  source_name,
        "source_url":   source_url,
        "category":     category,
        "service":      service,
        "doc_type":     doc_type,
        "title":        full_title[:480],
        "content":      content,
        "summary":      None,
        "_tags":        "[]",
        "impact_level": None,
        "release_date": release_date,
        "release_code": release_code,
        "content_hash": _make_hash(full_title, content, source_url),
        "is_new":       True,
        "vector_id":    None,
    }


def parse_hcm_detail_page(
    html: str,
    parent_title: str,
    source_url: str,
    source_name: str,
    category: str,
    service: str,
    doc_type: str,
) -> list[dict]:
    """
    Parse an Oracle HCM module What's New detail page (linked from the hub).

    Each h3/h4 heading becomes a child record titled
    "{parent_title} — {feature_name}" so the UI's "Features in this Release"
    block can pick them up automatically.

    Caps: 60 feature headings per page.
    """
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    items: list[dict] = []
    seen:  set[str]   = set()

    for heading in soup.find_all(["h3", "h4"])[:60]:
        feat_name = _clean(heading.get_text())
        if len(feat_name) < 5:
            continue
        key = feat_name.lower()
        if key in seen:
            continue
        seen.add(key)

        parts: list[str] = []
        for sib in heading.next_siblings:
            if not isinstance(sib, Tag):
                continue
            if sib.name in ("h2", "h3", "h4"):
                break
            text = _clean(sib.get_text())
            if text:
                parts.append(text)
        content = " ".join(parts)[:2000] or feat_name
        date = _parse_date(feat_name) or _parse_date(content)

        full_title = f"{parent_title} — {feat_name}"
        _, rc = _parse_oracle_release(parent_title)
        items.append({
            "source_name":  source_name,
            "source_url":   source_url,
            "category":     category,
            "service":      service,
            "doc_type":     doc_type,
            "title":        full_title[:480],
            "content":      content,
            "summary":      None,
            "_tags":        "[]",
            "impact_level": None,
            "release_date": date,
            "release_code": rc,
            "content_hash": _make_hash(full_title, content, source_url),
            "is_new":       True,
            "vector_id":    None,
        })

    log.info("HCM detail parse: %d features from %s (parent: %s)",
             len(items), source_url, parent_title)
    return items


def parse_oracle_page(
    html: str,
    source_name: str,
    source_url: str,
    category: str,
    service: str,
    doc_type: str,
    page_date: Optional[datetime] = None,
) -> list[dict]:
    """
    Parse raw HTML into a list of update records ready for database insertion.
    Each record is a dict matching the OracleUpdate column names (minus id).

    page_date : HTTP Last-Modified datetime for the page (used as release_date
                fallback for records that contain no date in their text).
    """
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")

    # Remove noise
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    items: list[dict] = []

    # OIC What's New — dedicated parser that captures both section headings
    # (e.g. "End of Life" notices) and individual feature rows within each section
    if category == "OIC" and doc_type == "whats_new":
        items = _try_oic_whats_new(soup)

    # HCM pages have a distinct structure — use dedicated parsers first
    if not items and category == "HCM":
        if service == "REST API Usage":
            items = _try_hcm_api_usage(soup)
        elif service == "REST API":
            items = _try_hcm_rest_endpoints(soup)
        if not items:
            items = _try_hcm_readiness(soup)

    # Standard OCI / OIC parser chain
    if not items:
        if doc_type == "release_notes":
            items = _try_oracle_release_notes(soup)
    if not items:
        items = _try_whats_new_list(soup)
    if not items:
        items = _generic_heading_parse(soup)

    # Last resort: entire page text as one item
    if not items:
        body_text = _clean(soup.get_text())[:3000]
        if body_text:
            items = [{"title": f"{source_name} — Page Content",
                      "content": body_text, "release_date": None}]

    log.info("Parsed %d items from %s", len(items), source_name)

    records: list[dict] = []
    for item in items:
        title   = item["title"]
        content = item["content"] or title

        # Derive Oracle release code from title + content (e.g. "26A" → Jan 2026)
        release_date = item.get("release_date")
        release_code = item.get("release_code")
        if not release_code:
            _, release_code = _parse_oracle_release(title)
        if not release_code:
            _, release_code = _parse_oracle_release(content)
        # If the code gives us a better date than what the parser found, use it
        if release_code and not release_date:
            release_date, _ = _parse_oracle_release(title + " " + content)
        # Last resort: use the page's HTTP Last-Modified date
        if not release_date and page_date:
            release_date = page_date

        records.append({
            "source_name":  source_name,
            "source_url":   source_url,
            "category":     category,
            "service":      service,
            "doc_type":     doc_type,
            "title":        title[:480],
            "content":      content,
            "summary":      item.get("summary"),      # pre-filled by some parsers
            "_tags":        "[]",
            "impact_level": item.get("impact_level"), # pre-filled by some parsers
            "release_date": release_date,
            "release_code": release_code,
            "content_hash": _make_hash(title, content, source_url),
            "is_new":       True,
            "vector_id":    None,
        })
    return records


# ── Mock / seed data ───────────────────────────────────────────────────────────
MOCK_UPDATES: list[dict] = [
    {
        "source_name":  "OCI — Compute",
        "source_url":   "https://docs.oracle.com/en-us/iaas/releasenotes/changes/compute/",
        "category":     "OCI",
        "service":      "Compute",
        "doc_type":     "release_notes",
        "title":        "Flexible Shapes Support for E5 Instances",
        "content":      (
            "March 2024 — Oracle Cloud Infrastructure now supports E5 flexible shapes for "
            "compute instances. E5 instances are powered by 4th-generation AMD EPYC processors "
            "and offer higher memory-to-OCPU ratios, up to 1024 GB of RAM. Flexible shapes allow "
            "you to customize the number of OCPUs and the amount of memory when creating or "
            "resizing instances. This enables precise right-sizing of workloads and can reduce "
            "compute costs by up to 30% compared to fixed shapes."
        ),
        "release_date": datetime(2024, 3, 15),
        "impact_level": "Medium",
        "_tags":        '["Compute", "Performance", "Cost"]',
    },
    {
        "source_name":  "OCI — Networking",
        "source_url":   "https://docs.oracle.com/en-us/iaas/releasenotes/changes/network/",
        "category":     "OCI",
        "service":      "Networking",
        "doc_type":     "release_notes",
        "title":        "Network Path Analyzer Now Generally Available",
        "content":      (
            "February 2024 — Network Path Analyzer is now generally available in all commercial "
            "regions. Network Path Analyzer helps you troubleshoot connectivity issues by "
            "analyzing the virtual network path between a source and a destination. "
            "It tests the reachability of resources and identifies network misconfigurations, "
            "such as misconfigured security lists, route tables, or network security groups. "
            "The tool provides a detailed visual representation of the network path and "
            "highlights any issues found along the path."
        ),
        "release_date": datetime(2024, 2, 20),
        "impact_level": "Medium",
        "_tags":        '["Networking", "Troubleshooting", "GA"]',
    },
    {
        "source_name":  "OCI — Database",
        "source_url":   "https://docs.oracle.com/en-us/iaas/releasenotes/changes/database/",
        "category":     "OCI",
        "service":      "Database",
        "doc_type":     "release_notes",
        "title":        "Autonomous Database Serverless Now Supports Oracle Database 23ai",
        "content":      (
            "March 2024 — Oracle Autonomous Database Serverless now supports Oracle Database 23ai, "
            "the latest release of Oracle Database. Oracle Database 23ai includes over 300 new "
            "features, including AI Vector Search, JSON Relational Duality, JavaScript stored "
            "procedures, and True Cache. With AI Vector Search, you can store vector embeddings "
            "directly in Oracle Database and run similarity searches using SQL. Existing Autonomous "
            "Database instances can be upgraded to 23ai through the Console."
        ),
        "release_date": datetime(2024, 3, 1),
        "impact_level": "High",
        "_tags":        '["Database", "AI/ML", "Autonomous Database", "New Feature"]',
    },
    {
        "source_name":  "OCI — Security",
        "source_url":   "https://docs.oracle.com/en-us/iaas/releasenotes/changes/security/",
        "category":     "OCI",
        "service":      "Security",
        "doc_type":     "release_notes",
        "title":        "Zero Trust Packet Routing (ZPR) Generally Available",
        "content":      (
            "January 2024 — Zero Trust Packet Routing (ZPR) is now generally available. "
            "ZPR is a new security architecture that allows you to control network traffic "
            "at the packet level based on the identity of the workload rather than its network "
            "location. ZPR uses security attributes attached to resources and evaluates policies "
            "before allowing packets to traverse the network. This eliminates the need for complex "
            "security lists and NSGs for many scenarios and provides stronger isolation. "
            "ZPR is available in all commercial OCI regions."
        ),
        "release_date": datetime(2024, 1, 10),
        "impact_level": "High",
        "_tags":        '["Security", "Networking", "GA", "ZPR"]',
    },
    {
        "source_name":  "OCI — Storage",
        "source_url":   "https://docs.oracle.com/en-us/iaas/releasenotes/changes/storage/",
        "category":     "OCI",
        "service":      "Storage",
        "doc_type":     "release_notes",
        "title":        "Object Storage Lifecycle Policy Now Supports Intelligent Tiering",
        "content":      (
            "February 2024 — Object Storage lifecycle policies now support automatic movement of "
            "objects between Standard and Infrequent Access tiers based on access patterns. "
            "With Intelligent Tiering, Oracle monitors object access patterns and automatically "
            "moves objects that have not been accessed for 30 days to the lower-cost Infrequent "
            "Access tier. Objects are moved back to Standard tier when accessed. There is no "
            "retrieval fee for tier transitions. Intelligent Tiering is suitable for data with "
            "unpredictable or changing access patterns."
        ),
        "release_date": datetime(2024, 2, 5),
        "impact_level": "Medium",
        "_tags":        '["Storage", "Cost", "Object Storage"]',
    },
    {
        "source_name":  "OIC — What's New",
        "source_url":   "https://docs.oracle.com/en/cloud/paas/integration-cloud/whats-new/",
        "category":     "OIC",
        "service":      "Integration",
        "doc_type":     "whats_new",
        "title":        "OIC 3 — AI-Powered Integration Recommendations",
        "content":      (
            "March 2024 — Oracle Integration Cloud (OIC) 3 now includes AI-powered integration "
            "recommendations. When building integrations, the AI engine analyzes your source and "
            "target schemas and suggests field mappings, transformations, and patterns based on "
            "millions of anonymized integration patterns. Recommendations include confidence "
            "scores and explanations. This feature is available in OIC 3 Generation 2 instances "
            "and can reduce integration build time by up to 60% for common patterns such as "
            "Order-to-Cash, Hire-to-Retire, and Procure-to-Pay."
        ),
        "release_date": datetime(2024, 3, 20),
        "impact_level": "High",
        "_tags":        '["OIC", "AI/ML", "Integration", "New Feature"]',
    },
    {
        "source_name":  "OIC — What's New",
        "source_url":   "https://docs.oracle.com/en/cloud/paas/integration-cloud/whats-new/",
        "category":     "OIC",
        "service":      "Integration",
        "doc_type":     "whats_new",
        "title":        "OIC — Process Automation New BPMN 2.0 Designer",
        "content":      (
            "February 2024 — Oracle Integration Cloud Process Automation now includes a redesigned "
            "BPMN 2.0 process designer. The new designer offers a modern drag-and-drop interface, "
            "real-time collaboration for multiple users, an improved properties panel, and "
            "Git-based version control integration. The designer supports all standard BPMN 2.0 "
            "elements including events, gateways, tasks, sub-processes, and boundary events. "
            "Existing processes can be migrated to the new designer with one click."
        ),
        "release_date": datetime(2024, 2, 14),
        "impact_level": "Medium",
        "_tags":        '["OIC", "Process Automation", "BPMN", "Enhancement"]',
    },
    {
        "source_name":  "OCI — Containers & Kubernetes",
        "source_url":   "https://docs.oracle.com/en-us/iaas/releasenotes/changes/containers/",
        "category":     "OCI",
        "service":      "Containers",
        "doc_type":     "release_notes",
        "title":        "OKE Now Supports Kubernetes 1.29",
        "content":      (
            "March 2024 — Oracle Container Engine for Kubernetes (OKE) now supports "
            "Kubernetes 1.29. Kubernetes 1.29 includes improvements to the kube-proxy, "
            "support for ReadWriteOncePod PersistentVolumeClaims, and KMS v2 improvements for "
            "encryption. OKE automatically handles the Kubernetes control plane upgrade. Node "
            "pool upgrades can be done in-place with zero downtime using the rolling upgrade "
            "strategy. Kubernetes 1.26 is now deprecated and will reach end of support on "
            "June 1, 2024."
        ),
        "release_date": datetime(2024, 3, 10),
        "impact_level": "Medium",
        "_tags":        '["Containers", "Kubernetes", "OKE", "Upgrade"]',
    },
    {
        "source_name":  "OCI — Analytics",
        "source_url":   "https://docs.oracle.com/en-us/iaas/releasenotes/changes/analytics/",
        "category":     "OCI",
        "service":      "Analytics",
        "doc_type":     "release_notes",
        "title":        "Oracle Analytics Cloud — GenAI Narrative Explanations",
        "content":      (
            "January 2024 — Oracle Analytics Cloud (OAC) now supports Generative AI narrative "
            "explanations. With this feature, OAC automatically generates natural language "
            "summaries of dashboard insights and data visualizations. The AI model analyzes "
            "trends, anomalies, and patterns in your data and writes human-readable explanations "
            "that appear alongside your charts and tables. Narratives can be customized in tone "
            "(formal/casual) and length. The feature uses OCI Generative AI service and requires "
            "an OAC Professional or Enterprise Edition license."
        ),
        "release_date": datetime(2024, 1, 25),
        "impact_level": "Medium",
        "_tags":        '["Analytics", "GenAI", "OAC", "New Feature"]',
    },
    {
        "source_name":  "HCM — REST API Endpoints",
        "source_url":   "https://docs.oracle.com/en/cloud/saas/human-resources/farws/rest-endpoints.html",
        "category":     "HCM",
        "service":      "REST API",
        "doc_type":     "release_notes",
        "title":        "Get all absence records",
        "content":      (
            "Method: GET  Path: /hcmRestApi/resources/11.13.18.05/absences — "
            "Returns a collection of absence records. Supports query parameters for filtering "
            "by worker, absence type, start date, and end date. "
            "Response includes absence dates, duration, approval status, and associated payroll information."
        ),
        "release_date": datetime(2024, 1, 1),
        "impact_level": "Low",
        "_tags":        '["HCM", "REST API", "Absences", "GET"]',
    },
    {
        "source_name":  "HCM — REST API Endpoints",
        "source_url":   "https://docs.oracle.com/en/cloud/saas/human-resources/farws/rest-endpoints.html",
        "category":     "HCM",
        "service":      "REST API",
        "doc_type":     "release_notes",
        "title":        "Get a worker",
        "content":      (
            "Method: GET  Path: /hcmRestApi/resources/11.13.18.05/workers/{WorkerNumber} — "
            "Returns details for a specific worker including person information, assignment details, "
            "employment terms, salary, and legislative data. "
            "Supports expand parameters for related resources such as assignments, contracts, and roles."
        ),
        "release_date": datetime(2024, 1, 1),
        "impact_level": "Low",
        "_tags":        '["HCM", "REST API", "Workers", "GET"]',
    },
    {
        "source_name":  "HCM — What's New",
        "source_url":   "https://docs.oracle.com/en/cloud/saas/readiness/hcm.html",
        "category":     "HCM",
        "service":      "Human Capital Management",
        "doc_type":     "whats_new",
        "title":        "HCM — Payroll What's New 26A",
        "content":      (
            "Oracle Fusion Cloud Payroll 26A introduces enhancements to payroll processing, "
            "including improved balance calculation performance, new payroll flow pattern templates, "
            "and enhanced retroactive pay handling. "
            "The release also adds support for additional legislative data groups and "
            "improved integration with Oracle Time and Labor."
        ),
        "release_date": datetime(2026, 1, 1),
        "release_code": "26A",
        "impact_level": "Medium",
        "_tags":        '["HCM", "Payroll", "Whats New"]',
    },
    # ── Child feature records for "HCM — Payroll What's New 26A" ─────────────
    # Title must start with the exact parent title + " — " for the
    # "Features in this Release" block to link them.
    {
        "source_name":  "HCM — What's New",
        "source_url":   "https://docs.oracle.com/en/cloud/saas/readiness/hcm.html",
        "category":     "HCM",
        "service":      "Human Capital Management",
        "doc_type":     "whats_new",
        "title":        "HCM — Payroll What's New 26A — New Position Fields: Working Hours and Frequency",
        "content":      (
            "Two new fields are added to the Position page: Working Hours and Frequency. "
            "These fields let you record the standard working hours and the frequency (e.g. Weekly, "
            "Bi-Weekly, Monthly) directly on a position. The values default to the assignment when "
            "the position is selected, reducing manual data entry and ensuring consistency across "
            "all workers assigned to the same position. "
            "Affected pages: Manage Positions, Position Details. "
            "Integration impact: Position REST API v2 returns the new fields workingHours and "
            "frequency; downstream integrations that consume position data should be updated."
        ),
        "release_date": datetime(2026, 1, 1),
        "release_code": "26A",
        "impact_level": "Medium",
        "_tags":        '["HCM", "Payroll", "Position", "REST API"]',
        "summary":      "Adds WorkingHours and Frequency fields to Position; defaults to assignment on selection.",
    },
    {
        "source_name":  "HCM — What's New",
        "source_url":   "https://docs.oracle.com/en/cloud/saas/readiness/hcm.html",
        "category":     "HCM",
        "service":      "Human Capital Management",
        "doc_type":     "whats_new",
        "title":        "HCM — Payroll What's New 26A — Improved Balance Calculation Performance",
        "content":      (
            "Payroll balance calculations have been optimised in 26A to reduce run times for "
            "large legislative data groups. Internal caching now reuses already-computed element "
            "results across multiple balance calls within the same payroll run, resulting in up to "
            "40% faster calculation for customers with more than 50,000 payees."
        ),
        "release_date": datetime(2026, 1, 1),
        "release_code": "26A",
        "impact_level": "Low",
        "_tags":        '["HCM", "Payroll", "Performance"]',
        "summary":      "Payroll balance calculations up to 40% faster for large legislative data groups.",
    },
    {
        "source_name":  "HCM — What's New",
        "source_url":   "https://docs.oracle.com/en/cloud/saas/readiness/hcm.html",
        "category":     "HCM",
        "service":      "Human Capital Management",
        "doc_type":     "whats_new",
        "title":        "HCM — Payroll What's New 26A — New Payroll Flow Pattern Templates",
        "content":      (
            "Several new predefined payroll flow pattern templates are available in 26A: "
            "Quick Pay with Costing, Retroactive Pay Run, and End-of-Year Processing. "
            "These templates reduce the configuration required when setting up recurring payroll "
            "flows and include the most commonly used tasks in the correct sequence. "
            "Existing custom flow patterns are unaffected."
        ),
        "release_date": datetime(2026, 1, 1),
        "release_code": "26A",
        "impact_level": "Medium",
        "_tags":        '["HCM", "Payroll", "Flow Patterns"]',
        "summary":      "Three new predefined payroll flow pattern templates added: Quick Pay with Costing, Retroactive Pay Run, End-of-Year Processing.",
    },
    {
        "source_name":  "HCM — What's New",
        "source_url":   "https://docs.oracle.com/en/cloud/saas/readiness/hcm.html",
        "category":     "HCM",
        "service":      "Human Capital Management",
        "doc_type":     "whats_new",
        "title":        "HCM — Payroll What's New 26A — Enhanced Retroactive Pay Handling",
        "content":      (
            "Retroactive pay now supports component-level recalculation. When a salary or element "
            "entry is backdated, 26A recalculates only the affected earnings components rather than "
            "the full payroll run. The Retroactive Notifications report has been updated to show "
            "the delta amount per component alongside the employee name and assignment details."
        ),
        "release_date": datetime(2026, 1, 1),
        "release_code": "26A",
        "impact_level": "Medium",
        "_tags":        '["HCM", "Payroll", "Retroactive Pay"]',
        "summary":      "Retroactive pay supports component-level recalculation; updated notifications report shows delta per component.",
    },
    {
        "source_name":  "HCM — What's New",
        "source_url":   "https://docs.oracle.com/en/cloud/saas/readiness/hcm.html",
        "category":     "HCM",
        "service":      "Human Capital Management",
        "doc_type":     "whats_new",
        "title":        "HCM — Talent Management What's New 26A",
        "content":      (
            "Oracle Fusion Cloud Talent Management 26A adds AI-powered skills recommendations, "
            "enhanced goal alignment across teams, and a redesigned performance document experience. "
            "New REST APIs are available for skills inventory, development goals, and talent profiles. "
            "The check-in feature now supports structured templates and manager dashboards."
        ),
        "release_date": datetime(2026, 1, 1),
        "release_code": "26A",
        "impact_level": "Medium",
        "_tags":        '["HCM", "Talent Management", "Whats New", "AI"]',
    },
    {
        "source_name":  "OCI — What's New",
        "source_url":   "https://docs.oracle.com/en-us/iaas/Content/servicechanges.htm",
        "category":     "OCI",
        "service":      "General",
        "doc_type":     "whats_new",
        "title":        "OCI Free Tier Expanded — Always Free Resources Updated",
        "content":      (
            "March 2024 — Oracle has expanded the OCI Free Tier Always Free resources. "
            "The Always Free tier now includes: 2 AMD-based Compute VMs (1 OCPU, 1 GB RAM each), "
            "4 Arm-based Ampere A1 Compute instances with 3,000 OCPU-hours and 18,000 GB-hours "
            "per month, 200 GB total Block Volume storage, 20 GB Object Storage, 10 GB Archive "
            "Storage, 1 Autonomous Database (ATP or ADW), and Load Balancer. The Ampere A1 "
            "allocation is shared across all instances in your tenancy. These resources never "
            "expire as long as your account remains active."
        ),
        "release_date": datetime(2024, 3, 5),
        "impact_level": "Low",
        "_tags":        '["General", "Free Tier", "Pricing"]',
    },
]


def make_hash_for_mock(item: dict) -> str:
    return hashlib.sha256(
        f"{item['source_url']}|{item['title']}|{item['content'][:500]}".encode()
    ).hexdigest()


def get_mock_records() -> list[dict]:
    """Return mock records ready for db insertion."""
    records = []
    for item in MOCK_UPDATES:
        rec = dict(item)
        rec["content_hash"] = make_hash_for_mock(item)
        rec["summary"]      = None
        rec["vector_id"]    = None
        rec["is_new"]       = True
        records.append(rec)
    return records
