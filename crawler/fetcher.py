"""
crawler/fetcher.py — HTTP page fetcher with retry, rate-limiting, and
                     realistic browser headers to avoid 403s from Oracle.
"""

import logging
import time
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import HTTP_PROXY, HTTPS_PROXY, MAX_RETRIES, REQUEST_DELAY, REQUEST_TIMEOUT, VERIFY_SSL

log = logging.getLogger(__name__)

# Realistic browser headers
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection":      "keep-alive",
    "Cache-Control":   "no-cache",
}

_last_request_time: float = 0.0


def _is_pac_url(url: str) -> bool:
    lower = url.lower()
    last_segment = lower.rstrip("/").split("/")[-1]
    return last_segment.endswith(".pac") or last_segment.endswith(".dat")


def _build_session() -> requests.Session:
    raw_proxy = HTTPS_PROXY or HTTP_PROXY

    # ── Session creation ───────────────────────────────────────────────────
    if raw_proxy and _is_pac_url(raw_proxy):
        # PAC file — use PACSession so each request is routed correctly,
        # exactly as a browser would (PAC files can return different proxies
        # for different target URLs).
        try:
            from pypac import PACSession, get_pac
            log.info("Fetching PAC file: %s", raw_proxy)
            pac = get_pac(url=raw_proxy)
            if pac:
                session = PACSession(pac)
                log.info("Using PAC-aware session — proxy resolved per request")
            else:
                log.warning(
                    "PAC file at %s could not be fetched — falling back to direct connection. "
                    "If crawl times out, check that the PAC server is reachable on your VPN.",
                    raw_proxy,
                )
                session = requests.Session()
                session.trust_env = False
        except ImportError:
            log.warning(
                "pypac is not installed — PAC file proxy will be ignored. "
                "Run: runtime\\python.exe -m pip install pypac"
            )
            session = requests.Session()
            session.trust_env = False

    elif raw_proxy:
        # Plain proxy URL (e.g. http://proxy.corp.com:8080)
        session = requests.Session()
        session.trust_env = False
        session.proxies.update({"http": raw_proxy, "https": raw_proxy})
        log.info("Using proxy: %s", raw_proxy)

    else:
        # No proxy configured — direct connection
        session = requests.Session()
        session.trust_env = False
        log.debug("No proxy configured — connecting directly")

    # ── Retry adapter ──────────────────────────────────────────────────────
    retry = Retry(
        total=MAX_RETRIES,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://",  adapter)
    session.headers.update(_HEADERS)

    # ── SSL verification ──────────────────────────────────────────────────
    if not VERIFY_SSL:
        session.verify = False
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        log.warning("SSL verification DISABLED (VERIFY_SSL=false)")

    return session


_session = _build_session()


def _parse_last_modified(header_value: str) -> Optional[datetime]:
    """Parse an HTTP Last-Modified header string into a datetime (UTC, tz-naive)."""
    try:
        dt = parsedate_to_datetime(header_value)
        return dt.replace(tzinfo=None)
    except Exception:
        return None


def fetch_page(url: str) -> tuple[Optional[str], Optional[datetime]]:
    """
    Fetch a URL and return (html, last_modified).

    - html          : page content as a string, or None on failure
    - last_modified : datetime parsed from the HTTP Last-Modified header,
                      or None if the header is absent / unparseable
    """
    global _last_request_time

    # Rate limiting
    elapsed = time.time() - _last_request_time
    if elapsed < REQUEST_DELAY:
        time.sleep(REQUEST_DELAY - elapsed)

    log.info("Fetching: %s", url)
    try:
        resp = _session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        _last_request_time = time.time()

        if resp.status_code == 200:
            last_mod = _parse_last_modified(resp.headers.get("Last-Modified", ""))
            log.info("OK %d  (%d bytes)  last-modified=%s  %s",
                     resp.status_code, len(resp.content),
                     last_mod.date() if last_mod else "none", url)
            return resp.text, last_mod

        log.warning("HTTP %d for %s", resp.status_code, url)
        return None, None

    except requests.exceptions.ConnectionError as exc:
        log.error("Connection error for %s: %s", url, exc)
    except requests.exceptions.Timeout:
        log.error("Timeout for %s", url)
    except Exception as exc:
        log.error("Unexpected error fetching %s: %s", url, exc)

    return None, None
