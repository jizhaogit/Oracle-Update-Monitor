# Oracle OCI / OIC Monitor

An intelligent, self-contained tool for tracking Oracle Cloud Infrastructure (OCI), Oracle Integration Cloud (OIC), and Oracle HCM documentation updates — release notes, what's-new entries, and feature announcements — with AI-powered impact analysis, side-by-side version comparison, and Jira-aware conclusions.

---

## Table of Contents

1. [Introduction](#introduction)
2. [Monitored Sources](#monitored-sources)
3. [Key Features](#key-features)
4. [How Topics and Impact Levels Work](#how-topics-and-impact-levels-work)
5. [Architecture Overview](#architecture-overview)
6. [Quick Start](#quick-start)
7. [Configuration](#configuration)
8. [Using the UI](#using-the-ui)
   - [Toolbar](#toolbar)
   - [Sidebar](#sidebar)
   - [Detail View](#detail-view)
   - [Override Impact Level](#override-impact-level)
   - [Flag for Review](#flag-for-review)
   - [My Notes](#my-notes)
   - [All Updates Tab](#all-updates-tab)
   - [Statistics Tab](#statistics-tab)
   - [Conclusion (Comparison) Modal](#conclusion-comparison-modal)
   - [AI Impact Analysis](#ai-impact-analysis)
   - [Jira-Aware Analysis](#jira-aware-analysis)
   - [Appearance Settings](#appearance-settings)
9. [User Customisations Survive Crawls](#user-customisations-survive-crawls)
10. [REST API Reference](#rest-api-reference)
11. [Command-Line Options](#command-line-options)
12. [Project Structure](#project-structure)
13. [Dependencies](#dependencies)
14. [Troubleshooting](#troubleshooting)

---

## Introduction

Oracle regularly publishes updates to its cloud services across dozens of product pages. Keeping track of what changed, when, and how it affects your environment is time-consuming when done manually.

**Oracle OCI/OIC/HCM Monitor** automates this by:

- Crawling 14 official Oracle documentation pages on a configurable schedule (default: on-demand via Crawl Now button)
- Detecting new entries and content changes between crawls
- Archiving previous versions of any changed document
- Classifying each update by impact level (High / Medium / Low) and extracting relevant tags using rule-based analysis
- Letting users manually override impact levels, flag items for review, and add personal notes — all of which **survive future crawls**
- Producing on-demand AI impact analysis and upgrade guidance, optionally enriched with live Jira ticket content
- Exposing everything through a browser-based UI and a REST API

The tool is distributed as a **portable green package** — copy the folder to any Windows machine and double-click `run.bat`. No pre-installed Python or dependencies are required.

---

## Monitored Sources

| # | Category | Source Name | Type | URL |
|---|---|---|---|---|
| 1 | 👤 HCM | REST API Usage | Reference | [human-resources/index.html](https://docs.oracle.com/en/cloud/saas/human-resources/index.html) |
| 2 | 👤 HCM | What's New | What's New | [saas/readiness/hcm.html](https://docs.oracle.com/en/cloud/saas/readiness/hcm.html) |
| 3 | 👤 HCM | REST API Endpoints | Release Notes | [human-resources/farws/rest-endpoints.html](https://docs.oracle.com/en/cloud/saas/human-resources/farws/rest-endpoints.html) |
| 4 | ☁ OCI | What's New | What's New | [servicechanges.htm](https://docs.oracle.com/en-us/iaas/Content/servicechanges.htm) |
| 5 | ☁ OCI | Release Notes (All) | Release Notes | [releasenotes/](https://docs.oracle.com/en-us/iaas/releasenotes/) |
| 6 | ☁ OCI | Compute | Release Notes | [releasenotes/changes/compute/](https://docs.oracle.com/en-us/iaas/releasenotes/changes/compute/) |
| 7 | ☁ OCI | Networking | Release Notes | [releasenotes/changes/network/](https://docs.oracle.com/en-us/iaas/releasenotes/changes/network/) |
| 8 | ☁ OCI | Database | Release Notes | [releasenotes/changes/database/](https://docs.oracle.com/en-us/iaas/releasenotes/changes/database/) |
| 9 | ☁ OCI | Storage | Release Notes | [releasenotes/changes/storage/](https://docs.oracle.com/en-us/iaas/releasenotes/changes/storage/) |
| 10 | ☁ OCI | Security | Release Notes | [releasenotes/changes/security/](https://docs.oracle.com/en-us/iaas/releasenotes/changes/security/) |
| 11 | ☁ OCI | Analytics | Release Notes | [releasenotes/changes/analytics/](https://docs.oracle.com/en-us/iaas/releasenotes/changes/analytics/) |
| 12 | ☁ OCI | Containers & Kubernetes | Release Notes | [releasenotes/changes/containers/](https://docs.oracle.com/en-us/iaas/releasenotes/changes/containers/) |
| 13 | 🔗 OIC | What's New | What's New | [integration-cloud/whats-new/](https://docs.oracle.com/en/cloud/paas/integration-cloud/whats-new/) |
| 14 | 🔗 OIC | Release Notes | Release Notes | [integration-cloud/release-notes/](https://docs.oracle.com/en/cloud/paas/integration-cloud/release-notes/) |

> Sources are defined in `config.py` (`ORACLE_SOURCES`) and can be extended with additional Oracle documentation URLs without any code changes.
>
> **HCM What's New** uses a multi-step crawl: the hub page (`hcm.html`) embeds a JSON list of all current-release modules; the app fetches each module's `toc.htm`, then every individual feature page — storing one parent record per module and one child record per feature. Because the hub only lists the **current release**, older releases (e.g. 26A) must be listed in `HCM_EXTRA_RELEASES` in `.env` to be included.

---

## Key Features

| Feature | Description |
|---|---|
| **Automated crawling** | Polls 14 Oracle OCI/OIC/HCM documentation URLs; manual (Crawl Now) or scheduled |
| **Change detection** | SHA-256 content hashing detects new entries and content updates |
| **Version history** | Keeps full snapshots of every previous version of a changed document |
| **Impact classification** | Rule-based classifier tags each update as High / Medium / Low impact |
| **Impact override** | Users can manually set the impact level; the override survives all future crawls |
| **Auto-tagging** | Keyword extraction assigns service tags (Compute, Networking, Database, etc.) |
| **🖥 UI/Redwood badge** | Items with Redwood UI keywords are automatically promoted to Medium and badged |
| **🚩 Flag for Review** | Flag any item for team attention; attach a Jira ticket URL or free-text note |
| **💬 My Notes** | Personal free-text notes per item; independent of the flag; persist across crawls |
| **Review filter** | Toolbar filter to show only flagged items |
| **AI impact analysis** | On-demand upgrade guidance generated by LLM; results cached for instant replay |
| **Jira-aware analysis** | When a flagged item has a Jira URL, the ticket content is fetched and fed to the LLM so the conclusion directly addresses the team's concern |
| **Conclusion view** | Pick a single item via radio button and compare versions side-by-side |
| **By Version grouping** | Sidebar groups items by Oracle release code (26A, 26B, …) by default |
| **Appearance control** | Per-user font-size selector and background colour picker (saved in browser) |
| **🤖 AI Search** | Natural-language sidebar search — the LLM expands your query into focused keywords, searches the database, and returns results ranked by relevance |
| **Keyword highlighting** | When AI Search is active, the exact words you typed are highlighted in amber in the Detail View; AI-expanded terms appear in a subtle blue |
| **Portable runtime** | Ships as a self-contained folder; `run.bat` downloads Python automatically |
| **REST API** | Full FastAPI backend with interactive Swagger docs at `/docs` |

---

## How Topics and Impact Levels Work

### Topic Generation

When a crawl runs, the app fetches each source URL as raw HTML — **before any JavaScript executes**. Many Oracle pages (like OIC What's New) build their visible content dynamically in the browser, so the JS-rendered topic list is not available. The parser works through a three-strategy fallback chain on the static HTML:

| Priority | HTML looked for | Title comes from | Content comes from |
|---|---|---|---|
| 1st | `<dt>` / `<dd>` definition lists | `<dt>` text | `<dd>` text |
| 2nd | `<tr>` table rows | First `<td>` cell | Remaining `<td>` cells joined |
| 3rd (fallback) | `<h2>` / `<h3>` headings | Heading text | All siblings until the next heading |

This means the topics shown in the app come from the **static headings and list structures** in Oracle's raw page source — which may differ from the fully-rendered view you see in a browser. A maximum of **50 items per page** are captured.

HCM REST API pages use dedicated parsers that directly extract operation names and HTTP methods from Oracle's structured `<dl>` format, so those results are more complete and accurate.

---

### Impact Level Classification

Every parsed record is automatically assigned an impact level by scanning the full title + content text for keyword matches. The check runs **in order — first match wins**:

| Level | Triggers when the text contains any of these keywords |
|---|---|
| 🔴 **High** | `breaking change` · `deprecated` · `removed` · `critical` · `security` · `vulnerability` · `end of life` · `eol` · `migration required` |
| 🟡 **Medium** | `new feature` · `enhancement` · `improvement` · `added` · `updated` · `expanded` · `new service` · `preview` · `introduction` · `redwood` · `new experience` · `redesigned` · `new section` |
| 🟢 **Low** | `documentation` · `bug fix` · `minor` · `typo` · `clarification` · `updated docs` · `note` |
| 🟢 **Low** | *(default — no keywords matched)* |

**Example:** "Oracle Integration Generation 2 End of Life" → contains `end of life` → **High**

**Example:** "Prior Salary and Graph Section Introduction in Redwood Salary History" → contains `introduction` and `redwood` → **Medium**

**Example:** "April 2025" *(a bare month heading)* → no keywords match → **Low** (default)

> **Tip:** The keyword lists are defined in `config.py → IMPACT_KEYWORDS`. You can add, remove, or change keywords there without touching any other code — just restart the app and re-crawl.

Users can also **manually override** the impact level per item from the Detail View. Manually set levels are marked with ✎ and are never overwritten by future crawls.

---

### Auto-Tagging

Tags are extracted from the same title + content scan using a separate keyword → tag mapping (`config.py → TAG_KEYWORDS`). The service name is always included as a tag.

| Keyword found in text | Tag assigned |
|---|---|
| `security` | Security |
| `api` | API |
| `integration` | Integration |
| `ai` · `machine learning` | AI/ML |
| `generative` | GenAI |
| `kubernetes` · `container` | Kubernetes / Containers |
| `compute` · `instance` | Compute |
| `database` · `autonomous` | Database |
| `terraform` | Terraform |
| `redwood` · `new experience` · `user interface` | Redwood UI |

---

## Architecture Overview

```
<project-folder>/
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
│   ├── analyzer.py       ← AI impact analysis + rule-based fallback
│   ├── classifier.py     ← rule-based + optional LLM classifier
│   ├── jira_client.py    ← Jira ticket fetcher (PAT / Windows SSPI auth)
│   └── summarizer.py     ← LangChain summarisation + Q&A
│
├── storage/
│   ├── models.py         ← SQLAlchemy ORM (OracleUpdate, UpdateVersion, AnalysisCache, CrawlRun)
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
Oracle Docs → fetcher → parser → classifier → database
                                                  ↓
                                     FastAPI REST API
                                                  ↓
                                     Browser UI (index.html)
                                                  ↓ (on Analyze click)
                                     Jira REST API (if flag_note has URL)
                                                  ↓
                                     LLM (analyze_impact with Jira context)
```

---

## Quick Start

### Option A — Portable (Recommended, Windows)

No Python installation required.

1. **Download or copy** the project folder to any location on your Windows machine.
2. **Double-click `run.bat`**.
   - On first run it downloads the Python 3.11 embeddable runtime (~8 MB) and installs packages (~300 MB). This takes a few minutes.
   - On subsequent runs it starts in seconds.
3. Your default browser opens automatically at `http://127.0.0.1:8000`.

### Option B — System Python

If you already have Python 3.10+ installed:

```bat
cd <project-folder>
python -m pip install -r requirements-core.txt
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
# ── LLM for AI impact analysis ───────────────────────────
# "none"      — rule-based only (default, no API key needed)
# "openai"    — requires OPENAI_API_KEY
# "anthropic" — requires ANTHROPIC_API_KEY
# "bedrock"   — requires AWS credentials (aws sso login)
# "ollama"    — requires a running Ollama server
LLM_PROVIDER=none

OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-3.5-turbo

ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-3-5-sonnet-20241022

BEDROCK_REGION=us-east-1
BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0
BEDROCK_PROFILE=                    # optional AWS SSO profile name

OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3

# ── Crawl LLM timeout ───────────────────────────────────
# Hard cut-off (seconds) for per-record LLM calls during crawl.
# If the LLM takes longer, rule-based classification is used instead.
LLM_TIMEOUT=15

# ── Crawl schedule ──────────────────────────────────────
# Set CRAWL_SCHEDULE=false to disable ALL automatic crawling.
# Crawls will only run when you click "Crawl Now" in the UI.
CRAWL_SCHEDULE=false

CRAWL_INTERVAL_HOURS=24     # interval when CRAWL_SCHEDULE=true
CRAWL_ON_STARTUP=false      # run a crawl on app startup (ignored when CRAWL_SCHEDULE=false)

# ── API server ──────────────────────────────────────────
API_HOST=127.0.0.1          # use 0.0.0.0 to expose on the network
API_PORT=8000

# ── HTTP crawler ────────────────────────────────────────
REQUEST_TIMEOUT=30          # seconds per request before giving up
REQUEST_DELAY=2.0           # minimum seconds between requests (rate limit)
MAX_RETRIES=3               # retry attempts on 5xx / timeout

# ── Corporate VPN / Proxy ───────────────────────────────
# Set if the crawler times out while on VPN.
#
# If you have a PAC file URL (ends in .pac or .dat) the app resolves
# it automatically via pypac — paste the PAC URL directly:
#   HTTPS_PROXY=http://proxy.company.com/proxy.pac
#
# If you know the real proxy address, use it directly:
#   HTTPS_PROXY=http://proxy.company.com:8080
#
# To find your proxy: open PowerShell and run:
#   netsh winhttp show proxy
HTTPS_PROXY=
HTTP_PROXY=

# Set to false if you see "CERTIFICATE_VERIFY_FAILED" errors in the log
# (occurs when corporate VPN performs SSL inspection).
VERIFY_SSL=true

# ── HCM readiness crawl scope ───────────────────────────
# The Oracle HCM hub page (hcm.html) only lists the CURRENT release
# (e.g. 26B).  List any older releases you also want crawled here.
# The app auto-generates the module URLs for each listed release.
# Comma-separated release codes, e.g.:  HCM_EXTRA_RELEASES=26A,25D
HCM_EXTRA_RELEASES=26A

# ── Jira integration ────────────────────────────────────
# When a flagged item has a Jira ticket URL in its flag note, the AI
# analysis fetches the ticket and tailors its conclusion to the
# team's specific concern.
#
# Generate a Personal Access Token (PAT):
#   1. Open Jira in your browser
#   2. Click your avatar (top-right) → Profile → Personal Access Tokens
#   3. Click "Create token", give it a name, set expiry, click Create
#   4. Copy the token (shown once) and paste it below
#
# Leave blank to attempt Windows SSPI auth (automatic, no config needed,
# but may not work with all corporate Jira configurations).
JIRA_PAT=

# ── Logging ─────────────────────────────────────────────
LOG_LEVEL=INFO              # DEBUG | INFO | WARNING | ERROR
```

> **Note:** The application works fully without any API key. Set `LLM_PROVIDER=none` to use the built-in rule-based classifier. The LLM is only called when you click the **🧠 Analyze Impact & Upgrade Guide** button — crawling always uses rule-based classification.

---

## Using the UI

Open `http://127.0.0.1:8000` in your browser after launching `run.bat`.

### Toolbar

| Control | Description |
|---|---|
| **Category** | Filter sidebar and table to one Oracle category (OCI / OIC / HCM) |
| **Impact** | Filter by impact level (High / Medium / Low) |
| **Review** | `🚩 Flagged` — show only items you have flagged for review |
| **↺ Refresh** | Reload all updates from the server |
| **✓ Mark Seen** | Mark all currently-new items as seen (removes NEW badge) |
| **▶ Crawl Now** | Trigger an immediate crawl in the background |
| **🔍 Conclusion** | Open the version comparison view for the currently selected item |
| **Font Size** | Choose your preferred text size (12px – 20px); saved across sessions |
| **BG Color** | Pick a background colour; text automatically flips dark/light; saved across sessions |

### Sidebar

The left sidebar shows a collapsible tree. The default grouping is **By Version** (Oracle release code), with **By Category** available via the toggle buttons.

- **By Version** groups items under release codes (26B, 26A, …) with date hints (e.g. "2026 · Q2 Apr"). New-count badges appear per version.
- **By Category** groups items under Category → Service.
- Colour coding reflects impact: red = High, orange = Medium, green = Low.
- **✦ blue** items are newly discovered since last "Mark Seen".
- **🖥** icon — item involves a Redwood UI change.
- **🚩** icon — item has been flagged for review.
- **💬** icon — item has a personal note.
- The **radio button** on each item marks it for the Conclusion / Analyze workflow.
- Use the **Filter** box to search by title or summary within the tree.

#### 🤖 AI Search

Type a natural-language description into the search box and press **Enter** (or click **🤖 AI**) to trigger an AI-powered search.

- The LLM converts your query into 4–7 specific keywords focused on what you are actually looking for — product names and generic module terms are deliberately excluded to avoid noise.
- The database is searched for records matching **any** of those keywords (OR logic), and results are ranked by how many keywords matched.
- Your raw query is also always searched as-is (including space-inserted variants of run-together words like `workinghours` → `working hours`).
- Results respect the active **By Version / By Category** toggle and appear with all groups pre-expanded so every item is immediately clickable.
- A row of keyword chips below the search box shows exactly which terms were used. Click **✕** to clear the AI search and return to the normal filter.
- **Without an LLM configured** (`LLM_PROVIDER=none`), AI Search falls back to a plain word-split of your query — it still searches and ranks results, just without LLM keyword expansion.

### Detail View

Clicking any item shows its full detail in the right panel:

- **Header badges** — category, service, impact level (with ✎ if manually overridden), date, release code, 🖥 UI badge, 🚩 Flagged badge, 💬 Has Notes badge, NEW, and version count.
- Clicking the **version badge** (e.g. `v3 — Compare Versions`) opens the Conclusion modal.
- **Summary** — rule-based or AI-generated summary. When AI Search is active, matched keywords are highlighted (see below).
- **Full Content** — original text from Oracle's documentation page (scrollable). When AI Search is active, matched keywords are highlighted.
- **What's in this Update** — content broken into individual sentences for quick scanning.
- **Tags** — automatically extracted service tags.
- **View Source** — direct link to the Oracle documentation page.
- **⚡ Override Impact Level** — manually set the impact level (see below).
- **🚩 Flag for Review** — flag the item and link a Jira ticket (see below).
- **💬 My Notes** — personal free-text notes (see below).

### Keyword Highlighting (AI Search mode)

When an AI Search is active and you open any result in the Detail View, the **Summary** and **Full Content** fields highlight matched terms with two distinct styles:

| Highlight | Colour | What it marks |
|---|---|---|
| **Primary** | Amber / bold | The exact words you typed in the search box (your raw query) |
| **Secondary** | Subtle blue | AI-expanded keywords that differ from what you typed |

This makes it immediately clear **why** a result was included and where the relevant content is in the document. Generic product names (`Oracle`, `HCM`, `OIC`) are excluded from secondary highlights to avoid visual noise.

### Override Impact Level

Every item has an **⚡ Override Impact Level** panel in the detail view.

- Select **High**, **Medium**, or **Low** from the dropdown.
- Click **💾 Save** — the change is saved to the database immediately.
- The impact badge in the header updates and shows a **✎** marker to indicate it was manually set.
- The sidebar row colour and any active Impact filter update instantly.
- **The override survives all future crawls** — the crawler will never overwrite a manually-set impact level.

### Flag for Review

The **🚩 Flag for Review** panel lets you mark any item as needing team attention.

- Type a **Jira ticket URL**, a reason, or any free-text note in the textarea.
- Click **🚩 Flag this item** to save the flag.
- Once flagged:
  - A 🚩 icon appears next to the item in the sidebar.
  - A red **🚩 Flagged for Review** badge appears in the detail header.
  - The item appears when the **Review → 🚩 Flagged** toolbar filter is active.
  - The button label changes to **🚩 Update Flag** so you can edit the note.
  - A **✕ Clear Flag** button removes the flag and note.
- If the note contains a Jira URL (e.g. `https://jira.tssi.ca/browse/BGCO-4817`), a **🎫 Test Jira** button appears. Click it to verify the ticket can be fetched before running the full analysis.
- **Flags and notes survive all future crawls.**

### My Notes

The **💬 My Notes** panel (green, below the flag panel) is for personal free-text notes that are independent of the review flag.

- Write anything — observations, links, decisions, follow-up actions.
- Click **💾 Save Note** — saved permanently to the database.
- A 💬 icon appears in the sidebar and a green **💬 Has Notes** badge appears in the detail header.
- **Notes survive all future crawls.**

### All Updates Tab

A table listing every update with columns:

| Column | Description |
|---|---|
| Radio | Select this item as the active Conclusion / Analyze target |
| Title | Update title (click row to open Detail View) |
| Category | OCI, OIC, or HCM |
| Service | Service name |
| Impact | High / Medium / Low (✎ if manually overridden) |
| Date | Release date with release code |
| Ver | Version count; click if > 1 to open comparison |

### Statistics Tab

Shows aggregated counts: total updates, breakdown by category/service/impact level, and details of the last crawl run.

### Conclusion (Comparison) Modal

The Conclusion feature lets you inspect a single update and review what changed between versions.

**How to use:**

1. Click any item in the sidebar or All Updates tab to select it.
2. Click **🔍 Conclusion** in the toolbar, or click the **version badge** in the Detail View.

**What you see:**

- A **side-by-side comparison table** — fields that differ from a previous version are highlighted in amber with a △ indicator.
- A **version history table** (if the item has been updated) showing each archived version versus the current content.

### AI Impact Analysis

Inside the Conclusion modal, **🧠 Analyze Impact & Upgrade Guide** runs an AI analysis.

- **First run** — calls the configured LLM (or rule-based fallback) and caches the result.
- **Subsequent opens** — the cached analysis loads instantly; a `📋 Cached analysis` badge shows when it was generated.
- Click **🔄 Regenerate** to force a fresh LLM call.

**Analysis structure (with LLM configured):**

1. **Impact Summary** — one sentence describing what changed.
2. **Action Required** — Yes / No / N/A with explanation.
3. **Upgrade Steps** (when action is required) — numbered, concrete steps with API/SDK/CLI specifics.
4. **Affected Areas** — APIs, SDKs, Console, CLI, Terraform, HCM config, etc.
5. **AI Suggestion** — independent recommendation based solely on Oracle's documentation: concrete next steps, best practices, risks, or opportunities the team may not have considered. Always present, regardless of Jira tickets.
6. **Jira Ticket Response** — present only when a Jira ticket was successfully fetched. Directly answers the concern raised in the ticket and notes whether the team's current approach aligns with Oracle's documented intent.
7. **Summary Table** — at the end when multiple items are analysed together.

**Without an LLM** (`LLM_PROVIDER=none`), a keyword-based fallback analysis is produced with a note explaining how to enable full AI guidance.

### Jira-Aware Analysis

When the selected item has a **Jira ticket URL in its flag note**, the Analyze workflow automatically fetches the ticket content before calling the LLM.

**What the LLM receives (in addition to the Oracle update):**

- Ticket key, summary, status, priority, type
- Full description
- Last 5 comments (including any "leave it be" or resolution decisions)

**The LLM is explicitly instructed to:**

- Directly answer the concern or question raised in the ticket
- Explain whether the Oracle update resolves, worsens, or is unrelated to the ticket's concern
- Evaluate whether any solution proposed in the ticket is still valid
- Reference the Jira ticket key (e.g. BGCO-4817) explicitly in its response

**UI indicators:**

- A blue `🎫 Jira context loaded: BGCO-4817` badge appears in the modal footer when the fetch succeeded.
- A red `⚠ BGCO-4817: <error>` badge appears if the fetch failed, with the exact error reason.
- The loading spinner shows `Analyzing with Jira context (BGCO-4817)…` while the LLM runs.

**Testing Jira connectivity:**

Click **🎫 Test Jira** (appears in the Flag panel when a Jira URL is present) to verify connectivity without running a full analysis. The result box shows:
- ✓ green — ticket fetched successfully, with a content preview and latest comment
- ⚠ red — exact error with a checklist of what to fix

### Appearance Settings

Both settings are saved in your browser's local storage and restored on every visit.

**Font Size** — select from the dropdown (12px – 20px).

**Background Colour** — click the colour swatch. The tool automatically switches text colour for readability on any background.

---

## User Customisations Survive Crawls

Three types of data are set by users and **never overwritten by the crawler**:

| Field | Where to set | Survives crawl? |
|---|---|---|
| **Impact level override** | ⚡ Override Impact Level panel | ✅ Yes — marked with ✎ |
| **Flag + flag note** | 🚩 Flag for Review panel | ✅ Yes |
| **Personal note** | 💬 My Notes panel | ✅ Yes |

When an item's Oracle documentation content changes between crawls, the crawler archives the old version and updates the content — but it reads the `impact_overridden` flag in the database and skips the impact level update if you've manually set it.

To reset a manually-set impact back to auto-classification, choose the desired level and save, or delete the database record and let it be re-crawled.

---

## REST API Reference

The API is available at `http://127.0.0.1:8000`. Interactive documentation (Swagger UI) is at `/docs`.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Serves the browser UI |
| `GET` | `/health` | Health check |
| `GET` | `/stats` | Summary statistics |
| `GET` | `/updates` | List updates (`category`, `service`, `impact_level`, `is_new`, `search`, `limit`, `offset`) |
| `GET` | `/updates/{id}` | Single update detail |
| `GET` | `/updates/{id}/versions` | Version history for one update |
| `POST` | `/updates/{id}/impact` | Override impact level — body: `{"impact_level": "High"}` |
| `POST` | `/updates/{id}/flag` | Set/clear review flag — body: `{"is_flagged": true, "note": "..."}` |
| `POST` | `/updates/{id}/comment` | Save personal note — body: `{"comment": "..."}` |
| `GET` | `/categories` | Distinct category list |
| `GET` | `/services` | Distinct service list |
| `GET` | `/crawl-runs` | Crawl audit log |
| `GET` | `/conclusion?ids=1,2` | Enriched records with version history for given IDs |
| `GET` | `/jira-test?url=...` | Test whether a Jira ticket URL can be fetched (diagnostic) |
| `POST` | `/crawl` | Trigger a manual crawl |
| `POST` | `/mark-seen` | Mark all new updates as seen |
| `POST` | `/analyze` | Start async AI impact analysis — body: `{"ids": [1], "force": false}` |
| `GET` | `/analyze/{job_id}` | Poll for the result of an async analyze job |
| `POST` | `/search/ai` | AI-powered keyword search — body: `{"query": "..."}` — returns ranked results with expanded keywords |
| `POST` | `/ask` | Q&A over stored documents — body: `{"question": "..."}` |

**`/analyze` response includes Jira status:**

```json
{
  "job_id": "abc123",
  "status": "running",
  "jira_keys": ["BGCO-4817"],
  "jira_failed": []
}
```

`jira_keys` — tickets successfully fetched and included in the LLM prompt.
`jira_failed` — tickets that could not be fetched, each with `key`, `url`, `error`.

**`/updates/{id}/impact` body:**

```json
{ "impact_level": "High" }
```

Valid values: `"High"` / `"Medium"` / `"Low"`. Setting `null` clears the override.

**`/updates/{id}/flag` body:**

```json
{ "is_flagged": true, "note": "https://jira.tssi.ca/browse/BGCO-4817" }
```

**Example curl calls:**

```bash
# List flagged OCI items
curl "http://127.0.0.1:8000/updates?category=OCI&limit=20"

# Override impact on item 42
curl -X POST http://127.0.0.1:8000/updates/42/impact \
     -H "Content-Type: application/json" \
     -d '{"impact_level": "High"}'

# Flag item 42 with a Jira link
curl -X POST http://127.0.0.1:8000/updates/42/flag \
     -H "Content-Type: application/json" \
     -d '{"is_flagged": true, "note": "https://jira.tssi.ca/browse/BGCO-4817"}'

# Test Jira connectivity
curl "http://127.0.0.1:8000/jira-test?url=https://jira.tssi.ca/browse/BGCO-4817"

# Run AI analysis (with Jira context if flag note has a Jira URL)
curl -X POST http://127.0.0.1:8000/analyze \
     -H "Content-Type: application/json" \
     -d '{"ids": [42], "force": false}'
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

---

## Project Structure

```
<project-folder>/
├── .env                    ← your local configuration (not committed)
├── .env.example            ← configuration template (safe to commit)
├── .gitignore
├── README.md
├── requirements-core.txt   ← all required dependencies
├── config.py               ← all settings
├── main.py                 ← entry point
├── run.bat                 ← Windows portable launcher
├── pack.bat                ← builds OracleMonitor_portable.zip for distribution
│
├── api/
│   └── app.py              ← FastAPI endpoints
│
├── crawler/
│   ├── fetcher.py          ← HTTP client (retry, rate limiting, PAC proxy)
│   ├── parser.py           ← HTML parser + mock data seed
│   └── scheduler.py        ← crawl pipeline orchestration
│
├── processor/
│   ├── analyzer.py         ← AI impact analysis + rule-based fallback
│   ├── classifier.py       ← impact/tag classification
│   ├── jira_client.py      ← Jira ticket fetcher (PAT / Windows SSPI / anonymous)
│   └── summarizer.py       ← AI summary + Q&A
│
├── storage/
│   ├── models.py           ← SQLAlchemy ORM (OracleUpdate, UpdateVersion, AnalysisCache, CrawlRun)
│   ├── database.py         ← CRUD + schema migration
│   └── file_store.py       ← raw HTML storage
│
├── ui/
│   └── index.html          ← single-page browser UI
│
├── data/                   ← runtime data (not committed)
│   ├── db/                 ← SQLite database
│   └── raw/                ← archived raw HTML pages
│
├── logs/                   ← log files (not committed)
└── runtime/                ← portable Python runtime (not committed)
```

---

## Dependencies

### Core (requirements-core.txt)

| Package | Purpose |
|---|---|
| `fastapi` + `uvicorn` | REST API and web server |
| `sqlalchemy` | ORM and database access |
| `beautifulsoup4` + `lxml` | HTML parsing |
| `requests` + `urllib3` | HTTP crawling |
| `pypac` | PAC file resolution for corporate VPN proxy auto-config |
| `requests-negotiate-sspi` | Windows SSPI (NTLM/Kerberos) auth for Jira — uses current Windows login |
| `apscheduler` | Periodic crawl scheduling |
| `langchain` + `langchain-community` | LLM integration |
| `python-dotenv` | `.env` file loading |
| `pydantic` | Request/response validation |

---

## Troubleshooting

**Browser shows "This site can't be reached"**
- Wait 10–15 seconds after launching `run.bat` for the server to bind.
- Check `logs/oracle_monitor.log` for startup errors.

**No updates appear after first launch**
- Click **▶ Crawl Now** — automatic crawling is disabled by default (`CRAWL_SCHEDULE=false`).
- If Oracle's servers are unreachable, mock/sample data is seeded automatically so the UI is never empty.

**"Dependency install failed" during run.bat**
- Check your internet connection.
- Corporate proxy users: set `HTTPS_PROXY` in `.env`.

**Crawl times out or returns "Connection timed out" errors on VPN**
- Set `HTTPS_PROXY` in `.env` to your corporate proxy address (plain URL or PAC file URL).
- To find your proxy: run `netsh winhttp show proxy` in PowerShell, or check Edge → Settings → System → Proxy.
- If you still see `CERTIFICATE_VERIFY_FAILED` errors, add `VERIFY_SSL=false` to `.env`.

**Crawl returns 0 results from live Oracle pages**
- Oracle's pages may have changed their HTML structure. Check `logs/oracle_monitor.log` for parser warnings.

**LLM features not working**
- Set `LLM_PROVIDER=none` to fall back to rule-based analysis (always works, no API key needed).
- For OpenAI: verify `OPENAI_API_KEY` is set.
- For Anthropic: verify `ANTHROPIC_API_KEY` starts with `sk-ant-`.
- For Bedrock: run `aws sso login` first, then verify `BEDROCK_REGION` and `BEDROCK_MODEL_ID`.
- For Ollama: verify Ollama is running (`ollama serve`) and the model is downloaded (`ollama pull llama3`).

**AI Impact Analysis returns HTTP 500**
- Restart `run.bat` — `init_db` automatically adds any missing columns on startup.
- Check `logs/oracle_monitor.log` for `Cache read/write failed` warnings.

**Jira Test Jira button shows ⚠ HTTP 401 / Authentication required**

The app tries two auth methods in order:

1. **Jira PAT (recommended)** — set `JIRA_PAT` in `.env`:
   - Open Jira in your browser
   - Click your avatar → **Profile** → **Personal Access Tokens**
   - Click **Create token** → name it → set expiry → copy it (shown once)
   - Add to `.env`: `JIRA_PAT=<your token>`
   - Restart the app

2. **Windows SSPI** (fallback, no config needed) — requires the SSO package:
   ```
   runtime\python.exe -m pip install requests-negotiate-sspi
   ```
   Then restart the app. Note: SSPI may still fail if your corporate Jira uses reverse-proxy SSO that doesn't accept NTLM from non-browser clients. The PAT approach is more reliable.

**Jira Test Jira shows ⚠ REST API path not found (HTTP 404 on all candidates)**
- The app tried several REST API paths but none returned valid JSON. This is unusual — check that the Jira URL in the flag note is a valid browse URL (e.g. `https://jira.tssi.ca/browse/BGCO-4817`).
- Check `logs/oracle_monitor.log` for the exact paths that were tried.

**Jira analysis conclusion says "content unavailable"**
- The ticket fetch failed silently before a recent fix. Restart the app to pick up the latest `jira_client.py`, then click **🎫 Test Jira** in the flag panel to get the exact error.

**Want to reset all data**
- Stop the server.
- Delete `data/db/oracle_monitor.db`.
- Restart — the database is rebuilt from scratch on the next crawl.

**AI Search returns irrelevant results / highlights generic terms**
- The LLM prompt explicitly forbids product names and module names — ensure you are running the latest `api/app.py`.
- If `LLM_PROVIDER=none`, the search falls back to plain word-splitting (no AI expansion), which may return fewer focused results.
- Run-together words like `workinghours` are automatically split into `working hours` and searched as an additional seed keyword — no spaces needed.

**AI Search returns HTTP 500**
- Restart the app — the `multi_keyword_search` function requires the latest `storage/database.py`.
- Check `logs/oracle_monitor.log` for details.

**Impact level I manually set was reset after a crawl**
- This should not happen with the current code. Impact overrides set via the ⚡ panel set `impact_overridden=true` in the database, which the crawler checks before updating. If you see this, check that you are running the latest version and restart the app so the schema migration runs (`impact_overridden` column is added on startup).
