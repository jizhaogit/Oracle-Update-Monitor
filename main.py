"""
main.py — Entry point for Oracle OCI/OIC Monitor.

Starts three concurrent components:
  1. FastAPI REST API      (background thread, uvicorn)
  2. APScheduler crawls   (background thread, periodic)
  3. Tkinter Desktop UI   (main thread — MUST be last)

Usage
-----
    python main.py                  # full app (UI + API + scheduler)
    python main.py --api-only       # headless API + scheduler only
    python main.py --crawl-once     # run one crawl then exit
    python main.py --seed           # seed mock data and exit
"""

# Ensure the project root is on sys.path so sub-packages (storage, crawler,
# processor, api, ui) are importable regardless of how Python was launched.
# This is required when using an embeddable/portable Python runtime.
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import argparse
import logging
import sys
import threading
import time

log = logging.getLogger(__name__)


def _start_api(host: str, port: int) -> None:
    """Launch FastAPI/uvicorn in a daemon thread."""
    def _run():
        try:
            import uvicorn
            from api.app import app
            uvicorn.run(
                app,
                host=host,
                port=port,
                log_level="warning",
                access_log=False,
            )
        except Exception as exc:
            log.error("API server error: %s", exc)

    t = threading.Thread(target=_run, name="api-server", daemon=True)
    t.start()
    log.info("API server starting on http://%s:%d  (docs: /docs)", host, port)
    time.sleep(1)   # give uvicorn a moment to bind


def main() -> None:
    parser = argparse.ArgumentParser(description="Oracle OCI/OIC Monitor")
    parser.add_argument("--api-only",   action="store_true",
                        help="Run API + scheduler without desktop UI")
    parser.add_argument("--crawl-once", action="store_true",
                        help="Run one crawl cycle and exit")
    parser.add_argument("--seed",       action="store_true",
                        help="Seed mock data into the database and exit")
    parser.add_argument("--no-api",     action="store_true",
                        help="Skip starting the API server")
    args = parser.parse_args()

    # ── 1. Initialise database ─────────────────────────────────────────────
    print("\n" + "═" * 64)
    print("  Oracle OCI/OIC Monitor — starting up")
    print("═" * 64)

    from storage.database import init_db
    init_db()
    print("[OK] Database initialised")

    # ── 2. Seed mode ───────────────────────────────────────────────────────
    if args.seed:
        from crawler.parser import get_mock_records
        from processor.classifier import classify
        from processor.summarizer import generate_summary
        from storage.database import upsert_update

        records = get_mock_records()
        new_count = 0
        for rec in records:
            rec = classify(rec)
            if not rec.get("summary"):
                rec["summary"] = generate_summary(rec["title"], rec["content"])
            _, is_new = upsert_update(rec)
            if is_new:
                new_count += 1
        print(f"[OK] Seeded {new_count} mock records")
        return

    # ── 3. Single crawl mode ───────────────────────────────────────────────
    if args.crawl_once:
        from crawler.scheduler import run_crawl
        result = run_crawl(seed_mock=True)
        print(f"[OK] Crawl complete — found {result['updates_found']}, "
              f"new {result['updates_new']}")
        return

    # ── 4. API server ──────────────────────────────────────────────────────
    from config import API_HOST, API_PORT

    if not args.no_api:
        try:
            _start_api(API_HOST, API_PORT)
            print(f"[OK] API running at http://{API_HOST}:{API_PORT}/docs")
        except Exception as exc:
            print(f"[WARN] API failed to start: {exc}")

    # ── 5. Scheduler ──────────────────────────────────────────────────────
    try:
        from crawler.scheduler import register_update_callback, start_scheduler
        # We'll connect the callback once the UI is ready
        start_scheduler()
        print("[OK] Scheduler started")
    except Exception as exc:
        print(f"[WARN] Scheduler failed to start: {exc}")

    # ── 6. Open browser UI (or headless) ──────────────────────────────────
    url = f"http://{API_HOST}:{API_PORT}"

    if args.api_only:
        print(f"[OK] Running in headless mode  →  {url}")
        print("     Press Ctrl+C to stop.\n")
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            print("\nShutting down…")
        return

    # Open the browser UI automatically
    import webbrowser
    time.sleep(1.5)   # give uvicorn a moment to bind
    print(f"[OK] Opening browser UI at {url}\n")
    webbrowser.open(url)

    print("     Server is running. Close this window to stop.\n")
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("\nShutting down…")


if __name__ == "__main__":
    main()
