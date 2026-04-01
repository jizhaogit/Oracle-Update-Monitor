"""
processor/jira_client.py — Fetch Jira ticket content for impact analysis.

Zero-config: uses Windows SSPI (NTLM/Kerberos) — same silent auth as your
browser on VPN.  Falls back to anonymous.  No credentials in .env required.

Pre-requisite (one-time):
    runtime\\python.exe -m pip install requests-negotiate-sspi
"""

import logging
import re
from typing import Optional
from urllib.parse import urlparse

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

log = logging.getLogger(__name__)

# Matches  https://jira.example.com/browse/PROJ-1234
_JIRA_URL_RE = re.compile(
    r'https?://[^\s/]+/browse/([A-Z][A-Z0-9_]+-\d+)',
    re.IGNORECASE,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _extract_urls(text: str) -> list[tuple[str, str]]:
    """Return [(base_url, issue_key), ...] for every Jira browse-URL in text."""
    results, seen = [], set()
    for m in _JIRA_URL_RE.finditer(text or ""):
        key = m.group(1).upper()
        if key in seen:
            continue
        seen.add(key)
        parsed = urlparse(m.group(0))
        results.append((f"{parsed.scheme}://{parsed.netloc}", key))
    return results


def _flatten_adf(node, depth: int = 0) -> str:
    """Recursively flatten Atlassian Document Format JSON → plain text."""
    if depth > 20 or not isinstance(node, dict):
        return node if isinstance(node, str) else ""
    parts = [node.get("text", "")] if node.get("type") == "text" else []
    for child in node.get("content") or []:
        parts.append(_flatten_adf(child, depth + 1))
    return " ".join(p for p in parts if p)


def _build_session(auth_method: str = "auto"):
    """
    Build a requests.Session for Jira.
    auth_method:
      "pat"   — Bearer token from JIRA_PAT config  (most reliable)
      "sspi"  — Windows SSPI / Negotiate            (silent, no config needed)
      "anon"  — no auth                             (last resort)
      "auto"  — PAT if configured, else SSPI, else anon
    Returns (session, auth_label: str).
    """
    import requests
    from config import HTTPS_PROXY, HTTP_PROXY, VERIFY_SSL, JIRA_PAT

    session = requests.Session()
    session.trust_env = False
    session.verify    = VERIFY_SSL
    session.headers.update({
        "Accept":     "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Oracle-Monitor/1.0",
    })

    # ── Proxy (PAC file or static) ─────────────────────────────────────────────
    raw_proxy = HTTPS_PROXY or HTTP_PROXY
    if raw_proxy:
        if raw_proxy.lower().endswith(('.pac', '.dat')):
            try:
                from pypac import PACSession, get_pac
                pac = get_pac(url=raw_proxy)
                if pac:
                    session = PACSession(pac)
                    session.verify    = VERIFY_SSL
                    session.trust_env = False
                    session.headers.update({
                        "Accept":     "application/json",
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Oracle-Monitor/1.0",
                    })
            except ImportError:
                pass
        else:
            session.proxies = {"http": raw_proxy, "https": raw_proxy}

    # ── Auth ───────────────────────────────────────────────────────────────────
    if auth_method == "auto":
        auth_method = "pat" if JIRA_PAT else "sspi"

    if auth_method == "pat":
        if JIRA_PAT:
            session.headers["Authorization"] = f"Bearer {JIRA_PAT}"
            return session, "PAT"
        # PAT requested but not configured — fall through to SSPI
        auth_method = "sspi"

    if auth_method == "sspi":
        try:
            from requests_negotiate_sspi import HttpNegotiateAuth
            session.auth = HttpNegotiateAuth()
            return session, "SSPI"
        except ImportError:
            pass   # fall through to anon
        except Exception as exc:
            log.debug("SSPI setup error: %s", exc)

    return session, "anon"


# ── REST fetch with full diagnostics ──────────────────────────────────────────

def _parse_issue_json(data: dict, key: str, base_url: str) -> dict:
    """Convert a raw Jira REST API response dict into our simplified format."""
    fields = data.get("fields", {})

    desc = fields.get("description") or ""
    if isinstance(desc, dict):
        desc = _flatten_adf(desc)
    desc = (desc or "").strip()[:3000]

    comments = []
    for c in (fields.get("comment") or {}).get("comments", [])[-5:]:
        body = c.get("body") or ""
        if isinstance(body, dict):
            body = _flatten_adf(body)
        author = (c.get("author") or {}).get("displayName", "unknown")
        comments.append({"author": author, "body": (body or "").strip()[:800]})

    return {
        "key":         key,
        "url":         f"{base_url}/browse/{key}",
        "summary":     (fields.get("summary")   or "").strip(),
        "status":      (fields.get("status")    or {}).get("name", ""),
        "priority":    (fields.get("priority")  or {}).get("name", ""),
        "issue_type":  (fields.get("issuetype") or {}).get("name", ""),
        "description": desc,
        "comments":    comments,
        "fetch_error": None,
    }


def _try_rest(base_url: str, key: str, session) -> tuple[Optional[dict], Optional[str]]:
    """
    Attempt to fetch one issue via Jira REST API.
    Tries multiple context-path variants so it works regardless of how
    Jira is deployed (root, /jira/, /issues/, etc.).

    Returns (issue_dict, None) on success, (None, error_msg) on failure.
    """
    qs = "?fields=summary,description,status,priority,issuetype,comment"

    # Candidate REST base paths — covers most Jira Server / Data Center / Cloud deployments
    candidates = [
        f"{base_url}/rest/api/2/issue/{key}{qs}",
        f"{base_url}/rest/api/latest/issue/{key}{qs}",
    ]
    # Also try any sub-path hinted by the base_url itself
    # (e.g. if browse URL is https://jira.co/jira/browse/X, base is https://jira.co/jira)
    parsed = urlparse(base_url)
    if parsed.path and parsed.path not in ('', '/'):
        root = f"{parsed.scheme}://{parsed.netloc}"
        candidates += [
            f"{root}/rest/api/2/issue/{key}{qs}",
            f"{root}/rest/api/latest/issue/{key}{qs}",
        ]

    last_err = "no candidates tried"
    for api_url in candidates:
        try:
            resp = session.get(api_url, timeout=15, allow_redirects=True)
        except Exception as exc:
            last_err = f"Network error on {api_url}: {exc}"
            log.debug("Jira REST attempt failed (%s): %s", api_url, exc)
            continue

        # If redirected to a login / SSO page, the response will be HTML not JSON
        ct = resp.headers.get("Content-Type", "")
        if resp.ok and "html" in ct:
            last_err = (
                f"HTTP {resp.status_code} but got HTML response (redirected to login page). "
                f"Tried: {api_url}. "
                "This usually means authentication is required — "
                "install requests-negotiate-sspi for Windows SSO: "
                "runtime\\python.exe -m pip install requests-negotiate-sspi"
            )
            log.info("Jira REST %s returned HTML (likely login redirect)", api_url)
            continue

        if resp.status_code == 401:
            last_err = (
                f"HTTP 401 Unauthorized at {api_url}. "
                "Jira requires authentication. "
                "Install requests-negotiate-sspi: "
                "runtime\\python.exe -m pip install requests-negotiate-sspi"
            )
            continue

        if resp.status_code == 403:
            last_err = f"HTTP 403 Forbidden — no read permission for {key} at {api_url}"
            continue

        if resp.status_code == 404:
            # 404 on this path — try the next candidate
            last_err = f"HTTP 404 at {api_url}"
            log.debug("Jira REST 404 at %s — trying next candidate", api_url)
            continue

        if not resp.ok:
            last_err = f"HTTP {resp.status_code} at {api_url}"
            continue

        try:
            data = resp.json()
        except Exception as exc:
            last_err = f"JSON parse error from {api_url}: {exc}"
            continue

        if "fields" not in data:
            last_err = f"Unexpected JSON structure from {api_url} (no 'fields' key)"
            continue

        log.info("Jira REST success: %s", api_url)
        return _parse_issue_json(data, key, base_url), None

    return None, last_err


def fetch_jira_issue(base_url: str, key: str) -> dict:
    """
    Fetch one Jira issue.  Always returns a dict — on failure, fetch_error
    contains a human-readable explanation of exactly what went wrong.

    Auth strategy (tried in order):
      1. PAT (Bearer token) — if JIRA_PAT is set in .env  [most reliable]
      2. Windows SSPI       — silent Windows login          [no config needed]
      3. Anonymous          — last resort
    """
    from config import JIRA_PAT

    errors = []

    # Build the attempt list based on what's available
    attempts: list[str] = []
    if JIRA_PAT:
        attempts.append("pat")
    attempts += ["sspi", "anon"]

    for method in attempts:
        session, label = _build_session(auth_method=method)
        result, err = _try_rest(base_url, key, session)
        if result:
            log.info("Jira %s fetched OK (%s)", key, label)
            return result

        errors.append(f"[{label}] {err}")
        log.info("Jira %s [%s] failed: %s", key, label, err)

        # If we get a definitive 403 (wrong permissions, not auth), stop trying
        if "403" in (err or ""):
            break

    # ── Build a helpful error message ──────────────────────────────────────────
    has_pat    = bool(JIRA_PAT)
    pat_hint   = "" if has_pat else (
        "\n\nFix: generate a Jira Personal Access Token and add it to .env:\n"
        "  1. Open Jira in your browser\n"
        "  2. Click your avatar → Profile → Personal Access Tokens\n"
        "  3. Create token (Read scope is enough)\n"
        "  4. Add to .env:  JIRA_PAT=<paste token here>\n"
        "  5. Restart the app"
    )
    error_summary = " | ".join(errors) + pat_hint
    log.warning("Could not fetch Jira %s: %s", key, " | ".join(errors))

    return {
        "key":         key,
        "url":         f"{base_url}/browse/{key}",
        "summary":     "",
        "status":      "",
        "priority":    "",
        "issue_type":  "",
        "description": "",
        "comments":    [],
        "fetch_error": error_summary,
    }


def fetch_jira_issues_from_notes(records: list[dict]) -> list[dict]:
    """
    Scan every record's flag_note for Jira browse URLs, deduplicate,
    fetch each ticket, and return the list (always includes an entry
    per unique key, with fetch_error set if retrieval failed).
    """
    issues: list[dict] = []
    seen:   set[str]   = set()

    for rec in records:
        for base_url, key in _extract_urls(rec.get("flag_note") or ""):
            if key in seen:
                continue
            seen.add(key)
            log.info("Fetching Jira ticket %s for analysis context", key)
            issues.append(fetch_jira_issue(base_url, key))

    return issues
