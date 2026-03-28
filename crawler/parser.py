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


def _parse_date(text: str) -> Optional[datetime]:
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


def parse_oracle_page(
    html: str,
    source_name: str,
    source_url: str,
    category: str,
    service: str,
    doc_type: str,
) -> list[dict]:
    """
    Parse raw HTML into a list of update records ready for database insertion.
    Each record is a dict matching the OracleUpdate column names (minus id).
    """
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")

    # Remove noise
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    items: list[dict] = []

    # HCM pages have a distinct structure — use dedicated parsers first
    if category == "HCM":
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
            "release_date": item.get("release_date"),
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
        "impact_level": "Medium",
        "_tags":        '["HCM", "Payroll", "Whats New"]',
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
