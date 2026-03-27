"""
crawler/fetcher.py — HTTP page fetcher with retry, rate-limiting, and
                     realistic browser headers to avoid 403s from Oracle.
"""

import logging
import time
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import MAX_RETRIES, REQUEST_DELAY, REQUEST_TIMEOUT

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


def _build_session() -> requests.Session:
    session = requests.Session()
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
    return session


_session = _build_session()


def fetch_page(url: str) -> Optional[str]:
    """
    Fetch a URL and return its HTML content as a string.
    Returns None on failure.  Enforces REQUEST_DELAY between requests.
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
            log.info("OK %d  (%d bytes)  %s", resp.status_code, len(resp.content), url)
            return resp.text

        log.warning("HTTP %d for %s", resp.status_code, url)
        return None

    except requests.exceptions.ConnectionError as exc:
        log.error("Connection error for %s: %s", url, exc)
    except requests.exceptions.Timeout:
        log.error("Timeout for %s", url)
    except Exception as exc:
        log.error("Unexpected error fetching %s: %s", url, exc)

    return None
