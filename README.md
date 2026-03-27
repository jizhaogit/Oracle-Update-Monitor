# Oracle OCI / OIC Monitor

An intelligent, self-contained tool for tracking Oracle Cloud Infrastructure (OCI) and Oracle Integration Cloud (OIC) documentation updates — release notes, what's-new entries, and feature announcements — with AI-powered summarisation, semantic search, and side-by-side version comparison.

---

## Table of Contents

1. [Introduction](#introduction)
2. [Key Features](#key-features)
3. [Architecture Overview](#architecture-overview)
4. [Quick Start](#quick-start)
5. [Configuration](#configuration)
6. [Using the UI](#using-the-ui)
   - [Toolbar](#toolbar)
   - [Sidebar](#sidebar)
   - [Detail View](#detail-view)
   - [All Updates Tab](#all-updates-tab)
   - [Statistics Tab](#statistics-tab)
   - [Conclusion (Comparison) Modal](#conclusion-comparison-modal)
   - [Appearance Settings](#appearance-settings)
7. [REST API Reference](#rest-api-reference)
8. [Command-Line Options](#command-line-options)
9. [Project Structure](#project-structure)
10. [Dependencies](#dependencies)
11. [Troubleshooting](#troubleshooting)

---

## Introduction

Oracle regularly publishes updates to its cloud services across dozens of product pages. Keeping track of what changed, when, and how it affects your environment is time-consuming when done manually.

**Oracle OCI/OIC Monitor** automates this by:

- Crawling 11 official Oracle documentation pages on a configurable schedule (default: every 24 hours)
- Detecting new entries and content changes between crawls
- Archiving previous versions of any changed document
- Classifying each update by impact level (High / Medium / Low) and extracting relevant tags
- Generating AI summaries (with optional LLM integration)
- Exposing everything through a browser-based UI and a REST API

The tool is distributed as a **portable green package** — copy the folder to any Windows machine and double-click `run.bat`. No pre-installed Python or dependencies are required.

---

## Key Features

| Feature | Description |
|---|---|
| **Automated crawling** | Polls 11 Oracle OCI/OIC documentation URLs; configurable interval |
| **Change detection** | SHA-256 content hashing detects new entries and content updates |
| **Version history** | Keeps full snapshots of every previous version of a changed document |
| **Impact classification** | Rule-based classifier tags each update as High / Medium / Low impact |
| **Auto-tagging** | Keyword extraction assigns service tags (Compute, Networking, Database, etc.) |
| **AI summarisation** | Optional OpenAI or local Ollama LLM summarises long entries |
| **Semantic search** | HuggingFace embeddings + ChromaDB vector store (optional, ~2.5 GB) |
| **Full-text search** | Always-available keyword search across title, content, and summary |
| **Q&A** | Ask natural-language questions over stored documents |
| **Conclusion view** | Select multiple items and compare them side-by-side with version diffs |
| **Appearance control** | Per-user font-size selector and background colour picker (saved in browser) |
| **Portable runtime** | Ships as a self-contained folder; `run.bat` downloads Python automatically |
| **REST API** | Full FastAPI backend with interactive Swagger docs at `/docs` |

---

## Architecture Overview

```
oracle_monitor/
├── run.bat               ← launcher (downloads Python runtime automatically)
├── main.py               ← entry point
├── config.py             ← all settings (env vars / .env file)
│
├── crawler/
│   ├── fetcher.py        ← HTTP client with retry and rate limiting
│   ├── parser.py         ← three-strategy HTML parser + mock data
│   └── scheduler.py      ← APScheduler orchestration
│
├── processor/
│   ├── classifier.py     ← rule-based + optional LLM classifier
│   └── summarizer.py     ← LangChain summarisation, vector store, Q&A
│
├── storage/
│   ├── models.py         ← SQLAlchemy ORM (OracleUpdate, UpdateVersion, CrawlRun)
│   ├── database.py       ← CRUD helpers, schema migration
│   └── file_store.py     ← raw HTML archiving
│
├── api/
│   └── app.py            ← FastAPI REST endpoints
│
└── ui/
    └── index.html        ← single-page browser UI (served by FastAPI)
```

**Data flow:**

```
Oracle Docs → fetcher → parser → classifier → summarizer → database
                                                              ↓
                                               FastAPI REST API
                                                              ↓
                                               Browser UI (index.html)
```

---

## Quick Start

### Option A — Portable (Recommended, Windows)

No Python installation required.

1. **Download or copy** the `oracle_monitor` folder to any location on your Windows machine.
2. **Double-click `run.bat`**.
   - On first run it downloads the Python 3.11 embeddable runtime (~8 MB) and installs packages (~300 MB). This takes a few minutes.
   - On subsequent runs it starts in seconds.
3. Your default browser opens automatically at `http://127.0.0.1:8000`.

### Option B — System Python

If you already have Python 3.10+ installed:

```bat
cd oracle_monitor
python -m pip install -r requirements-core.txt
python main.py
```

### Option C — Full AI mode (semantic search + local embeddings)

Installs sentence-transformers and ChromaDB (~2.5 GB including PyTorch):

```bat
python -m pip install -r requirements-full.txt
python main.py
```

---

## Configuration

All settings live in `.env` (copy from `.env.example`):

```bat
copy .env.example .env
```

Then edit `.env` with a text editor:

```ini
# ── LLM for AI summarisation ────────────────────────────
# "none"   — rule-based only (default, no API key needed)
# "openai" — requires OPENAI_API_KEY
# "ollama" — requires a running Ollama server
LLM_PROVIDER=none

OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-3.5-turbo

OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama2

# ── Crawl schedule ──────────────────────────────────────
CRAWL_INTERVAL_HOURS=24     # how often to check for updates
CRAWL_ON_STARTUP=true       # run a crawl immediately at launch

# ── API server ──────────────────────────────────────────
API_HOST=127.0.0.1          # use 0.0.0.0 to expose on the network
API_PORT=8000

# ── Logging ─────────────────────────────────────────────
LOG_LEVEL=INFO              # DEBUG | INFO | WARNING | ERROR
```

> **Note:** The application works fully without any API key. Set `LLM_PROVIDER=none` to use the built-in rule-based classifier and summary generator.

---

## Using the UI

Open `http://127.0.0.1:8000` in your browser after launching `run.bat`.

### Toolbar

The toolbar at the top provides global controls:

| Control | Description |
|---|---|
| **Search box** | Type and press Enter (or click Search) to filter updates by keyword |
| **Category** dropdown | Filter by OCI or OIC |
| **Impact** dropdown | Filter by High / Medium / Low impact level |
| **↺ Refresh** | Reload updates from the server |
| **✓ Mark Seen** | Mark all currently-new items as seen (removes NEW badge) |
| **▶ Crawl Now** | Trigger an immediate crawl in the background |
| **🔍 Conclusion** | Open the side-by-side comparison view for selected items (enabled when ≥1 item is checked) |
| **✕ Clear** | Deselect all checked items |
| **Font Size** | Choose your preferred text size (12px – 20px); saved across sessions |
| **BG Color** | Pick a background colour; text automatically flips dark/light for readability; saved across sessions |

### Sidebar

The left sidebar shows a collapsible tree organised by **Category → Service → Item**.

- Click a **category** (e.g. OCI) to expand/collapse it.
- Click a **service** (e.g. Database) to expand/collapse its items.
- Click an **item** to load its details in the main panel.
- **Colour coding** reflects impact: red = High, orange = Medium, green = Low.
- **✦ blue** items are newly discovered since last "Mark Seen".
- The **checkbox** on each item adds it to the Conclusion comparison.
- Use the **Filter** box at the top of the sidebar to search within the tree.

### Detail View

Clicking any item shows its full detail:

- **Title** with impact badge, category badge, service badge, date, and NEW/version badges.
- Clicking the **version badge** (e.g. `v3`) opens the Conclusion modal pre-loaded with that item's history.
- **Summary** — AI-generated or rule-based summary of the update.
- **Full Content** — the original text from Oracle's documentation page (scrollable).
- **Tags** — automatically extracted service tags.
- **View Source** — direct link to the Oracle documentation page.

### All Updates Tab

A sortable table listing every update with columns:

| Column | Description |
|---|---|
| Checkbox | Select for Conclusion comparison |
| Title | Update title (click to open Detail View) |
| Category | OCI or OIC |
| Service | Service name |
| Impact | High / Medium / Low |
| Ver | Version count; click if > 1 to open comparison |
| New? | ✦ if newly discovered |
| Crawled | Date/time the update was last seen |

Use the **select-all checkbox** in the header to select all visible rows at once.

### Statistics Tab

Shows aggregated counts:

- Total updates in the database
- Breakdown by category (OCI / OIC)
- Breakdown by service
- Breakdown by impact level
- Last successful crawl time and results

### Conclusion (Comparison) Modal

The Conclusion feature lets you compare multiple updates side-by-side and review what changed between versions.

**How to use:**

1. Check the checkbox on any items you want to compare (sidebar or All Updates tab).
2. The **🔍 Conclusion** button activates and shows a count badge.
3. Click **🔍 Conclusion** to open the modal.

**What you see:**

- A **side-by-side comparison table** with one column per selected item. Fields that differ between items are highlighted in amber with a △ indicator.
- Below each item, a **version history table** appears if that item has been updated before. It shows the previous version versus the current version, with changed fields clearly marked.

**Tip:** You can use Conclusion to review a single item's version history — just check it and click Conclusion.

### Appearance Settings

Both settings are saved in your browser's local storage and restored on every visit.

**Font Size** — select from the dropdown in the toolbar:

| Option | Size |
|---|---|
| Small | 12px |
| Small+ | 13px |
| Medium | 14px |
| Normal (default) | 15px |
| Large | 16px |
| Larger | 18px |
| X-Large | 20px |

**Background Colour** — click the colour swatch in the toolbar to open the browser colour picker. The tool automatically detects whether the chosen colour is light or dark and switches the text colour accordingly, so content remains readable at all times.

---

## REST API Reference

The API is available at `http://127.0.0.1:8000`. Interactive documentation (Swagger UI) is at `/docs`.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Serves the browser UI |
| `GET` | `/health` | Health check |
| `GET` | `/stats` | Summary statistics |
| `GET` | `/updates` | List updates (supports `category`, `service`, `impact_level`, `is_new`, `search`, `limit`, `offset` query params) |
| `GET` | `/updates/{id}` | Single update detail |
| `GET` | `/updates/{id}/versions` | Version history for one update |
| `GET` | `/search?q=...&mode=all` | Search — `mode`: `all` \| `text` \| `semantic` |
| `GET` | `/categories` | Distinct category list |
| `GET` | `/services` | Distinct service list |
| `GET` | `/crawl-runs` | Crawl audit log |
| `GET` | `/conclusion?ids=1,2,3` | Enriched records with version history for given IDs |
| `POST` | `/crawl` | Trigger a manual crawl |
| `POST` | `/mark-seen` | Mark all new updates as seen |
| `POST` | `/ask` | Q&A — body: `{"question": "..."}` |

**Example:**

```bash
# List high-impact OCI updates
curl "http://127.0.0.1:8000/updates?category=OCI&impact_level=High&limit=20"

# Ask a question
curl -X POST http://127.0.0.1:8000/ask \
     -H "Content-Type: application/json" \
     -d '{"question": "What changed in OCI Networking this month?"}'
```

---

## Command-Line Options

```
python main.py                  Full app: API + scheduler + browser UI (default)
python main.py --api-only       Headless: API + scheduler, no browser (server mode)
python main.py --crawl-once     Run one crawl cycle and exit
python main.py --seed           Insert sample mock data and exit
python main.py --no-api         Start scheduler only, skip the API server
```

**Running as a background service (headless):**

```bat
python main.py --api-only
```

The server stays running until you press `Ctrl+C`. Access the UI from any browser at `http://<server-ip>:8000` (set `API_HOST=0.0.0.0` in `.env` to allow remote access).

---

## Project Structure

```
oracle_monitor/
├── .env.example            ← configuration template (safe to commit)
├── .gitignore
├── README.md
├── requirements-core.txt   ← lightweight deps, no PyTorch (~300 MB)
├── requirements-full.txt   ← adds sentence-transformers + ChromaDB (~2.5 GB)
├── config.py               ← all settings
├── main.py                 ← entry point
├── run.bat                 ← Windows portable launcher
├── pack.bat                ← builds OracleMonitor_portable.zip for distribution
│
├── api/
│   └── app.py              ← FastAPI endpoints
│
├── crawler/
│   ├── fetcher.py          ← HTTP client (retry, rate limiting)
│   ├── parser.py           ← HTML parser + mock data seed
│   └── scheduler.py        ← crawl pipeline orchestration
│
├── processor/
│   ├── classifier.py       ← impact/tag classification
│   └── summarizer.py       ← AI summary, vector store, Q&A
│
├── storage/
│   ├── models.py           ← SQLAlchemy ORM models
│   ├── database.py         ← CRUD + schema migration
│   └── file_store.py       ← raw HTML storage
│
├── ui/
│   └── index.html          ← single-page browser UI
│
├── data/                   ← runtime data (not committed)
│   ├── db/                 ← SQLite database
│   ├── raw/                ← archived raw HTML pages
│   └── vectors/            ← ChromaDB vector store
│
├── logs/                   ← log files (not committed)
└── runtime/                ← portable Python runtime (not committed)
```

---

## Dependencies

### Core (requirements-core.txt) — ~300 MB

| Package | Purpose |
|---|---|
| `fastapi` + `uvicorn` | REST API and web server |
| `sqlalchemy` | ORM and database access |
| `beautifulsoup4` + `lxml` | HTML parsing |
| `requests` + `urllib3` | HTTP crawling |
| `apscheduler` | Periodic crawl scheduling |
| `langchain` + `langchain-community` | LLM integration, Q&A chain |
| `python-dotenv` | `.env` file loading |

### Full (requirements-full.txt) — additional ~2.2 GB

| Package | Purpose |
|---|---|
| `sentence-transformers` | Local HuggingFace text embeddings |
| `chromadb` | Vector store for semantic search |
| `torch` | Required by sentence-transformers |

> The application runs fully without the full dependencies. Semantic search and vector-based Q&A gracefully degrade to keyword search when `sentence-transformers` is not installed.

---

## Troubleshooting

**Browser shows "This site can't be reached"**
- Wait 10–15 seconds after launching `run.bat` for the server to bind.
- Check `logs/oracle_monitor.log` for startup errors.

**No updates appear after first launch**
- The first crawl runs automatically on startup. It may take 1–2 minutes.
- If Oracle's servers are unreachable, mock/sample data is seeded automatically so the UI is never empty.

**"Dependency install failed" during run.bat**
- Check your internet connection.
- Corporate proxy users: set `HTTP_PROXY` / `HTTPS_PROXY` environment variables before running `run.bat`.

**Crawl returns 0 results from live Oracle pages**
- Oracle's pages may have changed their HTML structure. The parser tries three strategies; if all fail, mock data is used.
- Check `logs/oracle_monitor.log` for parser warnings.

**LLM features not working**
- Set `LLM_PROVIDER=none` in `.env` to disable LLM and use the built-in rule-based classifier, which always works without any API key.
- For OpenAI: verify `OPENAI_API_KEY` is set correctly.
- For Ollama: verify Ollama is running (`ollama serve`) and `OLLAMA_BASE_URL` points to it.

**Want to reset all data**
- Stop the server.
- Delete `data/db/oracle_monitor.db` and `data/vectors/` (if present).
- Restart — the database and vector store are rebuilt from scratch on the next crawl.
