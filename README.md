# Oracle OCI / OIC Monitor

An intelligent, self-contained tool for tracking Oracle Cloud Infrastructure (OCI), Oracle Integration Cloud (OIC), and Oracle HCM documentation updates — release notes, what's-new entries, and feature announcements — with AI-powered impact analysis, side-by-side version comparison, Jira-aware conclusions, and per-item PSA/TES project tracking fields.

---

## Table of Contents

1. [Introduction](#introduction)
2. [Monitored Sources](#monitored-sources)
3. [Key Features](#key-features)
4. [How Topics and Impact Levels Work](#how-topics-and-impact-levels-work)
5. [Architecture Overview](#architecture-overview)
6. [Quick Start](#quick-start)
7. [Running as a Web App (Server Mode)](#running-as-a-web-app-server-mode)
8. [Deploying on Google Cloud Platform (GCP)](#deploying-on-google-cloud-platform-gcp)
   - [About proxies on GCP](#about-proxies-on-gcp)
   - [Step-by-step: Compute Engine VM](#step-by-step-compute-engine-vm-deployment)
   - [Step-by-step: Docker on Compute Engine](#step-by-step-docker-deployment-on-compute-engine)
   - [Cost summary](#cost-summary)
9. [Configuration](#configuration)
10. [Using the UI](#using-the-ui)
    - [Toolbar](#toolbar)
    - [Sidebar](#sidebar)
    - [Detail View](#detail-view)
    - [Override Impact Level](#override-impact-level)
    - [Flag for Review](#flag-for-review)
    - [My Notes](#my-notes)
    - [PSA / TES Project Tracking](#psa--tes-project-tracking)
    - [All Updates Tab](#all-updates-tab)
    - [Statistics Tab & Export](#statistics-tab--export)
    - [Conclusion (Comparison) Modal](#conclusion-comparison-modal)
    - [AI Impact Analysis](#ai-impact-analysis)
    - [Jira-Aware Analysis](#jira-aware-analysis)
    - [Project Instructions](#project-instructions)
    - [Appearance Settings](#appearance-settings)
11. [User Customisations Survive Crawls](#user-customisations-survive-crawls)
12. [REST API Reference](#rest-api-reference)
13. [Command-Line Options](#command-line-options)
14. [Project Structure](#project-structure)
15. [Dependencies](#dependencies)
16. [Troubleshooting](#troubleshooting)

---

## Introduction

Oracle regularly publishes updates to its cloud services across dozens of product pages. Keeping track of what changed, when, and how it affects your environment is time-consuming when done manually.

**Oracle OCI/OIC/HCM Monitor** automates this by:

- Crawling official Oracle documentation pages on a configurable schedule (default: on-demand via Crawl Now button)
- Detecting new entries and content changes between crawls
- Archiving previous versions of any changed document
- Classifying each update by impact level (High / Medium / Low) using rule-based analysis or an LLM if configured
- Letting users manually override impact levels, flag items for review, add personal notes, and fill in PSA/TES project tracking fields — all of which **survive future crawls**
- Producing on-demand AI impact analysis and upgrade guidance, optionally enriched with live Jira ticket content
- Exposing everything through a browser-based UI and a REST API

The tool is distributed as a **portable green package** — copy the folder to any Windows machine and double-click `run.bat`. No pre-installed Python or dependencies are required.

---

## Monitored Sources

Sources are defined in `sources.ini` (auto-created on first run) and can be edited with any text editor — no code changes needed.

| Category | Source Name | Type |
|---|---|---|
| 👤 HCM | What's New (all modules) | What's New hub — crawls module list automatically |
| 👤 HCM | Common Technologies — What's New | What's New |
| 🔗 OIC | What's New | What's New |
| 🔗 OIC | Release Notes | Release Notes |

> **HCM What's New** uses a multi-step crawl: the hub page (`hcm.html`) embeds a JSON list of all current-release modules; the app fetches each module's `toc.htm`, then every individual feature page — storing one parent record per module and one child record per feature.
>
> Because the hub only lists the **current release**, older releases must be listed in `HCM_EXTRA_RELEASES` in `.env` to be included.
>
> To add, remove, or disable a source, edit `sources.ini` and restart the app — no code changes required.

---

## Key Features

| Feature | Description |
|---|---|
| **Automated crawling** | Polls Oracle OIC/HCM documentation URLs; manual (Crawl Now) or scheduled |
| **Change detection** | SHA-256 content hashing detects new entries and content updates |
| **Version history** | Keeps full snapshots of every previous version of a changed document |
| **Impact classification** | Rule-based classifier tags each update as High / Medium / Low impact |
| **LLM classification** | Optional — when an LLM is configured, it classifies each new crawled item with richer context |
| **Impact override** | Users can manually set the impact level; the override survives all future crawls |
| **Auto-tagging** | Keyword extraction assigns service tags (Compensation, Recruiting, API, etc.) |
| **🖥 UI/Redwood badge** | Items with Redwood UI keywords are automatically promoted to Medium and badged |
| **🚩 Flag for Review** | Flag any item for team attention; attach a Jira ticket URL or free-text note |
| **💬 My Notes** | Personal free-text notes per item; independent of the flag; persist across crawls |
| **📋 PSA / TES Tracking** | Per-item project tracking fields: TES Owner, PSA Owner, Function Category, TES Status, Next Action, Profile Options, PSA Comments — all exported to CSV |
| **Review filter** | Toolbar filter to show only flagged items |
| **AI impact analysis** | On-demand upgrade guidance generated by LLM; results cached for instant replay |
| **Jira-aware analysis** | When a flagged item has a Jira URL, the ticket content is fetched and fed to the LLM so the conclusion directly addresses the team's concern |
| **Conclusion view** | Pick a single item via radio button and compare versions side-by-side |
| **By Version grouping** | Sidebar groups items by Oracle release code (26A, 26B, …) by default |
| **Project Instructions** | Paste or upload a project description; when an LLM is configured the classifier uses it to judge relevance and impact for newly crawled items |
| **⚡ Mark Impact** | Re-runs LLM classification on every existing record using the saved project instructions |
| **Appearance control** | Per-user font-size selector and background colour picker (saved in browser) |
| **🤖 AI Search** | Natural-language sidebar search — the LLM expands your query into focused keywords, searches the database, and returns results ranked by relevance |
| **Keyword highlighting** | When AI Search is active, the exact words you typed are highlighted in amber; AI-expanded terms appear in subtle blue |
| **Export CSV** | Statistics tab exports all visible items including PSA/TES tracking fields to a `.csv` file |
| **Portable runtime** | Ships as a self-contained folder; `run.bat` downloads Python automatically; auto-detects corporate proxy |
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

HCM What's New pages use a dedicated three-step crawl (hub → toc.htm → feature pages) that directly extracts individual features with full content.

---

### Impact Level Classification

Every parsed record is automatically assigned an impact level by scanning the full title + content text for keyword matches. The check runs **in order — first match wins**:

| Level | Triggers when the text contains any of these keywords |
|---|---|
| 🔴 **High** | `breaking change` · `deprecated` · `removed` · `critical` · `security` · `vulnerability` · `end of life` · `eol` · `migration required` |
| 🟡 **Medium** | `new feature` · `enhancement` · `improvement` · `added` · `updated` · `expanded` · `new service` · `preview` · `introduction` · `redwood` · `new experience` · `redesigned` · `new section` |
| 🟢 **Low** | `documentation` · `bug fix` · `minor` · `typo` · `clarification` · `updated docs` · `note` |
| 🟢 **Low** | *(default — no keywords matched)* |

> **Tip:** The keyword lists are defined in `config.py → IMPACT_KEYWORDS`. You can add, remove, or change keywords there without touching any other code — just restart the app and re-crawl.

When an LLM is configured, it classifies each **newly crawled** item using the full content plus any saved Project Instructions. Users can also **manually override** the impact level per item from the Detail View; manually-set levels are marked with ✎ and never overwritten by crawls or the Mark Impact function.

---

### Auto-Tagging

Tags are extracted from the same title + content scan using a separate keyword → tag mapping (`config.py → TAG_KEYWORDS`). The service name is always included as a tag.

| Keyword found in text | Tag assigned |
|---|---|
| `security` | Security |
| `api` / `rest api` | API |
| `ai` · `machine learning` | AI/ML |
| `generative` · `agentic` | GenAI |
| `redwood` · `new experience` · `user interface` | Redwood UI |
| `compensation` · `salary` | Compensation |
| `recruiting` · `talent acquisition` | Recruiting |
| `payroll` | Payroll |
| `absence` | Absence Management |

---

## Architecture Overview

```
<project-folder>/
├── run.bat               ← launcher (downloads Python runtime, auto-detects proxy)
├── main.py               ← entry point
├── config.py             ← all settings (env vars / .env file)
├── sources.ini           ← crawl source URLs (edit with Notepad, no code changes)
│
├── crawler/
│   ├── fetcher.py        ← HTTP client with retry and rate limiting
│   ├── parser.py         ← HTML parser + HCM hub parser + mock data
│   └── scheduler.py      ← APScheduler orchestration
│
├── processor/
│   ├── analyzer.py       ← AI impact analysis + rule-based fallback
│   ├── classifier.py     ← rule-based + optional LLM classifier (uses project instructions)
│   ├── jira_client.py    ← Jira ticket fetcher (PAT / Windows SSPI auth)
│   └── summarizer.py     ← LangChain summarisation + Q&A
│
├── storage/
│   ├── models.py         ← SQLAlchemy ORM (OracleUpdate, UpdateVersion, AnalysisCache, CrawlRun)
│   ├── database.py       ← CRUD helpers, auto schema migration
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
Oracle Docs → fetcher → parser → classifier (+ project instructions) → database
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
   - On first run it auto-detects your corporate proxy, downloads the Python 3.11 embeddable runtime (~8 MB), and installs packages. This takes a few minutes.
   - On subsequent runs it starts in seconds.
3. Your default browser opens automatically at `http://127.0.0.1:8000`.

> **On corporate VPN:** `run.bat` automatically detects your proxy using three methods in order: Windows system/WPAD proxy, PAC file resolution (if `HTTPS_PROXY` in `.env` is a `.pac` URL), or a direct `host:port` URL. No manual configuration is needed in most corporate environments.

### Option B — System Python

If you already have Python 3.10+ installed:

```bat
cd <project-folder>
python -m pip install -r requirements-core.txt
python main.py
```

---

## Running as a Web App (Server Mode)

The backend is FastAPI + Uvicorn — a production-grade web server that runs entirely in Python. No Apache, Nginx, or IIS is *required*, though any of them can be placed in front as a reverse proxy.

---

### Option 1 — Uvicorn direct (simplest, internal team)

This is the easiest path. The app binds directly to a port and teammates access it over the network.

**Step 1 — Change the bind address in `.env`:**

```ini
API_HOST=0.0.0.0      # listen on all network interfaces, not just localhost
API_PORT=8000
```

**Step 2 — Start in headless mode (no browser auto-open):**

```bat
runtime\python.exe main.py --api-only
```

Or with system Python:

```bash
python main.py --api-only
```

**Step 3 — Teammates open their browser to:**

```
http://<your-machine-name-or-ip>:8000
```

That's it. No other software needed. Works well for a small team (5–15 people) accessing over VPN or LAN.

---

### Option 2 — Nginx reverse proxy (recommended for production)

Nginx sits in front of Uvicorn and handles SSL, compression, and port 80/443. Uvicorn stays on an internal port.

**1. Install Nginx** (Linux):

```bash
sudo apt install nginx        # Ubuntu/Debian
sudo yum install nginx        # RHEL/CentOS
```

**2. Create a site config** (`/etc/nginx/sites-available/oracle-monitor`):

```nginx
server {
    listen 80;
    server_name your-server-name.company.com;

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 120s;
    }
}
```

**3. Enable and restart:**

```bash
sudo ln -s /etc/nginx/sites-available/oracle-monitor /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl restart nginx
```

**4. Start the app** (keep `.env` with `API_HOST=127.0.0.1` — Nginx handles the public side):

```bash
python main.py --api-only
```

Teammates access: `http://your-server-name.company.com`

To add HTTPS, use **Let's Encrypt** (`certbot --nginx`) or install your corporate SSL certificate.

---

### Option 3 — IIS reverse proxy (Windows corporate server)

IIS can proxy to Uvicorn using the **Application Request Routing (ARR)** module.

**Prerequisites:**
- IIS installed (Windows Server)
- [ARR module](https://www.iis.net/downloads/microsoft/application-request-routing) installed
- URL Rewrite module installed

**Steps:**

1. Start the app on the server:
   ```bat
   runtime\python.exe main.py --api-only
   ```

2. In IIS Manager → select your site → **URL Rewrite** → Add Rule → **Reverse Proxy**:
   - Server name: `127.0.0.1:8000`
   - Enable SSL offloading if needed

3. Teammates access the app via the IIS site URL (e.g. `http://intranet.company.com/oracle-monitor`).

> **Note:** IIS reverse proxy is more complex to configure than Nginx but is the preferred approach in Windows-only corporate environments where IT only permits IIS.

---

### Option 4 — Docker (any server, any OS)

Containerise the whole app so IT can deploy it without touching Python.

**`Dockerfile`** (create in the project root):

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements-core.txt .
RUN pip install --no-cache-dir -r requirements-core.txt

COPY . .

EXPOSE 8000
ENV API_HOST=0.0.0.0
ENV CRAWL_SCHEDULE=false

CMD ["python", "main.py", "--api-only"]
```

**`docker-compose.yml`:**

```yaml
version: "3.9"
services:
  oracle-monitor:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data      # persist database and project context
      - ./logs:/app/logs
    env_file:
      - .env
    restart: unless-stopped
```

**Run:**

```bash
docker compose up -d
```

Teammates access: `http://server-ip:8000`

The `data/` volume mount ensures the SQLite database, crawled data, and project instructions survive container restarts and upgrades.

---

### Keeping the app running (as a background service)

On **Linux**, use `systemd`:

```ini
# /etc/systemd/system/oracle-monitor.service
[Unit]
Description=Oracle OCI/OIC Monitor
After=network.target

[Service]
WorkingDirectory=/opt/oracle-monitor
ExecStart=/opt/oracle-monitor/runtime/python.exe main.py --api-only
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now oracle-monitor
```

On **Windows Server**, use the **Task Scheduler** or **NSSM** (Non-Sucking Service Manager):

```bat
nssm install OracleMonitor "C:\oracle-monitor\runtime\python.exe" "main.py --api-only"
nssm set OracleMonitor AppDirectory "C:\oracle-monitor"
nssm start OracleMonitor
```

---

### Summary

| Scenario | Setup effort | Best for |
|---|---|---|
| Uvicorn direct on a shared PC | Minimal — change 1 `.env` line | Small team, VPN-only access |
| Nginx reverse proxy | Low — 1 config file | Linux server, internal intranet |
| IIS reverse proxy | Medium — ARR module config | Windows Server, corporate IT |
| Docker | Low — `docker compose up` | Any server, easiest for IT handoff |
| GCP Compute Engine | Low — same as Linux server | Cloud-hosted, always-on |

> **No code changes are needed** between any of these options. The Python app is identical — only the deployment wrapper differs.

---

## Deploying on Google Cloud Platform (GCP)

### Prerequisites

- A GCP account with billing enabled
- [Google Cloud SDK (`gcloud`)](https://cloud.google.com/sdk/docs/install) installed on your local machine
- A GCP project created (`gcloud projects create my-project` or via the Console)

### About proxies on GCP

> **No proxy configuration is needed on GCP.**
>
> Your corporate VPN proxy is only required when running on a machine inside your company network. A GCP VM sits directly on the public internet and can reach PyPI, Oracle docs, and all other external URLs without any proxy.
>
> | | Corporate laptop (on VPN) | GCP VM |
> |---|---|---|
> | PyPI (`pypi.org`) | Needs proxy | ✅ Direct access |
> | Oracle docs (`docs.oracle.com`) | Needs proxy | ✅ Direct access |
> | Corporate PAC server | ✅ Reachable (internal only) | ❌ Not reachable |
> | SSL inspection | VPN may intercept traffic | ✅ No interception |
>
> In your GCP `.env`, leave the proxy lines blank:
> ```ini
> HTTPS_PROXY=
> HTTP_PROXY=
> VERIFY_SSL=true
> ```

---

### Which GCP service to use

The app has two constraints that shape the right service:

| Constraint | Why it matters |
|---|---|
| **SQLite** | Needs a persistent local filesystem — ephemeral containers lose data on restart |
| **APScheduler** | Runs inside the Python process — must stay alive between requests |

These rule out **Cloud Run** and **App Engine Standard** without significant code changes. **Compute Engine (VM)** is the recommended path — no code changes required.

---

### Step-by-step: Compute Engine VM deployment

#### Step 1 — Set your GCP project

```bash
gcloud config set project YOUR_PROJECT_ID
```

#### Step 2 — Create the VM

```bash
# e2-micro = free tier (light use)
# e2-small = ~$13/month (recommended for daily use)
gcloud compute instances create oracle-monitor \
  --machine-type=e2-small \
  --image-family=debian-12 \
  --image-project=debian-cloud \
  --boot-disk-size=20GB \
  --zone=us-central1-a \
  --tags=oracle-monitor-server
```

#### Step 3 — Open the firewall

```bash
# Allow traffic on port 8000 (direct access, no Nginx)
gcloud compute firewall-rules create allow-oracle-monitor \
  --allow=tcp:8000 \
  --target-tags=oracle-monitor-server \
  --description="Oracle Monitor web UI"
```

#### Step 4 — SSH into the VM

```bash
gcloud compute ssh oracle-monitor --zone=us-central1-a
```

All following commands run **inside the VM**.

#### Step 5 — Install Python and Git

```bash
sudo apt update && sudo apt install -y python3 python3-pip git
```

#### Step 6 — Copy the app to the VM

**Option A — from Git (recommended):**

```bash
git clone <your-repo-url> /opt/oracle-monitor
cd /opt/oracle-monitor
```

**Option B — upload from your local machine** (run this from your laptop, not the VM):

```bash
gcloud compute scp --recurse ./Oracle-Update-Monitor oracle-monitor:/opt/ --zone=us-central1-a
```

#### Step 7 — Install Python dependencies

No proxy needed — pip connects to PyPI directly:

```bash
cd /opt/oracle-monitor
pip3 install -r requirements-core.txt
```

#### Step 8 — Configure `.env`

```bash
cp .env.example .env
nano .env
```

Key settings to change for GCP:

```ini
# ── Required changes for GCP ──────────────────────────
API_HOST=0.0.0.0          # listen on all interfaces (not just localhost)
CRAWL_SCHEDULE=false      # use Crawl Now button; or set true for auto

# ── Proxy: leave blank on GCP ─────────────────────────
HTTPS_PROXY=              # NOT needed on GCP — clear this
HTTP_PROXY=               # NOT needed on GCP — clear this
VERIFY_SSL=true

# ── Optional: LLM for AI features ─────────────────────
LLM_PROVIDER=none         # or anthropic / openai / bedrock / ollama
ANTHROPIC_API_KEY=sk-ant-...
```

Save and exit (`Ctrl+X`, `Y`, `Enter` in nano).

#### Step 9 — Test run

```bash
python3 main.py --api-only
```

Open a browser and go to:
```
http://<VM-EXTERNAL-IP>:8000
```

Find the external IP with:
```bash
gcloud compute instances describe oracle-monitor \
  --zone=us-central1-a \
  --format='get(networkInterfaces[0].accessConfigs[0].natIP)'
```

Press `Ctrl+C` to stop the test run.

#### Step 10 — Run as a background service (survives logout and reboots)

Create a systemd service:

```bash
sudo nano /etc/systemd/system/oracle-monitor.service
```

Paste this content:

```ini
[Unit]
Description=Oracle OCI/OIC Monitor
After=network.target

[Service]
WorkingDirectory=/opt/oracle-monitor
ExecStart=/usr/bin/python3 main.py --api-only
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable oracle-monitor
sudo systemctl start oracle-monitor
```

Verify it is running:

```bash
sudo systemctl status oracle-monitor
```

View live logs:

```bash
sudo journalctl -u oracle-monitor -f
```

The app now starts automatically on every reboot.

---

### Step 11 (optional) — Add Nginx + HTTPS

Skip this step if HTTP on port 8000 is acceptable for your team. Add it if you want a clean URL on port 80/443 with SSL.

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
```

Create the Nginx site config:

```bash
sudo nano /etc/nginx/sites-available/oracle-monitor
```

```nginx
server {
    listen 80;
    server_name YOUR_DOMAIN_OR_IP;

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 120s;
    }
}
```

Enable the site and open port 80:

```bash
sudo ln -s /etc/nginx/sites-available/oracle-monitor /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl restart nginx

gcloud compute firewall-rules create allow-http \
  --allow=tcp:80,tcp:443 \
  --target-tags=oracle-monitor-server
```

Add a free SSL certificate (requires a public domain name):

```bash
sudo certbot --nginx -d your-domain.company.com
```

After certbot completes, the app is available at `https://your-domain.company.com`.

> **No public domain?** Use your VM's external IP directly on port 8000. For a self-signed certificate (internal use), run:
> ```bash
> sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
>   -keyout /etc/ssl/private/oracle-monitor.key \
>   -out /etc/ssl/certs/oracle-monitor.crt
> ```
> Then update the Nginx config to reference these files.

---

### Step-by-step: Docker deployment on Compute Engine

Use this approach if you prefer clean upgrades via `git pull && docker compose up -d`.

After completing Steps 1–4 above (VM created, SSH'd in):

#### Step 5D — Install Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker
```

#### Step 6D — Copy the app (same as Step 6 above)

#### Step 7D — Configure `.env` (same as Step 8 above)

#### Step 8D — Start with Docker Compose

```bash
cd /opt/oracle-monitor
docker compose up -d
```

The `./data` volume persists the database and project instructions across container restarts and rebuilds.

**Useful commands:**

```bash
docker compose logs -f          # live logs
docker compose ps               # check running containers
docker compose restart          # restart without rebuild

# Upgrade to a new version:
git pull
docker compose up -d --build
```

---

### Other GCP options (reference)

| Option | What changes | Effort |
|---|---|---|
| **Cloud Run** | SQLite → Cloud SQL; scheduler → Cloud Scheduler; files → Cloud Storage | 1–2 weeks |
| **Cloud Run + Cloud SQL** | Full serverless, auto-scaling, ~$15–30/month | 1–2 weeks |
| **App Engine Flexible** | Similar to Cloud Run — same code changes required | 1–2 weeks |

---

### Cost summary

| Machine | vCPU / RAM | Est. monthly | Best for |
|---|---|---|---|
| `e2-micro` | 1 / 1 GB | **Free** (always-free tier) | Occasional use |
| `e2-small` | 2 / 2 GB | **~$13** | Daily team use |
| `e2-medium` | 2 / 4 GB | **~$27** | If running Ollama LLM locally |
| Cloud Run + Cloud SQL | Serverless | **~$15–30** | Requires code changes |

Persistent disk: ~$0.80/month per 20 GB (stores database, logs, crawled pages).

> **Save money when not in use:**
> ```bash
> # Stop the VM (disk is preserved, no compute charge)
> gcloud compute instances stop oracle-monitor --zone=us-central1-a
>
> # Start it again
> gcloud compute instances start oracle-monitor --zone=us-central1-a
> ```

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
CRAWL_ON_STARTUP=false      # run a crawl on app startup

# ── API server ──────────────────────────────────────────
API_HOST=127.0.0.1          # use 0.0.0.0 to expose on the network
API_PORT=8000

# ── HTTP crawler ────────────────────────────────────────
REQUEST_TIMEOUT=30          # seconds per request before giving up
REQUEST_DELAY=2.0           # minimum seconds between requests (rate limit)
MAX_RETRIES=3               # retry attempts on 5xx / timeout

# ── Corporate VPN / Proxy ───────────────────────────────
# run.bat auto-detects your proxy via Windows system settings.
# Only set this manually if auto-detection fails.
#
# PAC file URL:   HTTPS_PROXY=http://proxy.company.com/proxy.pac
# Direct proxy:   HTTPS_PROXY=http://proxy.company.com:8080
HTTPS_PROXY=
HTTP_PROXY=

# Set to false if you see "CERTIFICATE_VERIFY_FAILED" errors in the log
# (occurs when corporate VPN performs SSL inspection).
VERIFY_SSL=true

# ── HCM readiness crawl scope ───────────────────────────
# The Oracle HCM hub page only lists the CURRENT release (e.g. 26B).
# List any older releases you also want crawled here.
# Comma-separated, e.g.:  HCM_EXTRA_RELEASES=26A,25D
HCM_EXTRA_RELEASES=26A

# ── Jira integration ────────────────────────────────────
# Generate a Personal Access Token (PAT):
#   1. Open Jira → Click avatar → Profile → Personal Access Tokens
#   2. Create token → copy it (shown once) → paste below
# Leave blank to attempt Windows SSPI auth automatically.
JIRA_PAT=

# ── Logging ─────────────────────────────────────────────
LOG_LEVEL=INFO              # DEBUG | INFO | WARNING | ERROR
```

> **Note:** The application works fully without any API key. Set `LLM_PROVIDER=none` to use the built-in rule-based classifier. The LLM is only called when you click **🧠 Analyze Impact & Upgrade Guide** or run **⚡ Mark Impact** — routine crawling always uses rule-based classification unless an LLM is configured.

---

## Using the UI

Open `http://127.0.0.1:8000` in your browser after launching `run.bat`.

### Toolbar

| Control | Description |
|---|---|
| **Module** | Filter sidebar and table by HCM module or OIC |
| **Impact** | Filter by impact level (High / Medium / Low) |
| **Review** | `🚩 Flagged` — show only items flagged for review |
| **✓ Mark Seen** | Mark all currently-new items as seen (removes NEW badge) |
| **▶ Crawl Now** | Trigger an immediate crawl in the background |
| **🔍 Conclusion** | Open the version comparison view for the currently selected item |
| **⚙ Project Config** | Open the project configuration panel (Project Instructions + Excel upload) |
| **Font Size** | Choose your preferred text size (12px – 20px); saved across sessions |
| **BG Color** | Pick a background colour; saved across sessions |

### Sidebar

The left sidebar shows a collapsible tree. The default grouping is **By Version** (Oracle release code), with **By Category** available via the toggle buttons.

- **By Version** groups items under release codes (26B, 26A, …) with date hints. New-count badges appear per version.
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

- The LLM converts your query into 4–7 specific keywords focused on what you are actually looking for.
- The database is searched for records matching **any** of those keywords (OR logic), and results are ranked by how many keywords matched.
- **Without an LLM configured** (`LLM_PROVIDER=none`), AI Search falls back to plain word-splitting of your query.

### Detail View

Clicking any item shows its full detail in the right panel:

- **Header badges** — category, service, impact level (with ✎ if manually overridden), date, release code, 🖥 UI badge, 🚩 Flagged badge, 💬 Has Notes badge, NEW, and version count.
- Clicking the **version badge** (e.g. `v3 — Compare Versions`) opens the Conclusion modal.
- **Summary** — rule-based or AI-generated summary.
- **Full Content** — original text from Oracle's documentation page.
- **Tags** — automatically extracted service tags.
- **View Source** — direct link to the Oracle documentation page.
- **⚡ Override Impact Level** — manually set the impact level.
- **🚩 Flag for Review** — flag the item and link a Jira ticket.
- **💬 My Notes** — personal free-text notes.
- **📋 PSA / TES Project Tracking** — project tracking fields (see below).

### Override Impact Level

Every item has an **⚡ Override Impact Level** panel in the detail view.

- Select **High**, **Medium**, or **Low** from the dropdown and click **💾 Save**.
- The impact badge in the header updates and shows a **✎** marker.
- **The override survives all future crawls and the Mark Impact bulk re-classification.**

### Flag for Review

The **🚩 Flag for Review** panel lets you mark any item as needing team attention.

- Type a **Jira ticket URL**, a reason, or any free-text note in the textarea.
- Click **🚩 Flag this item** to save. Once flagged:
  - A 🚩 icon appears in the sidebar and detail header.
  - The item appears when the **Review → 🚩 Flagged** toolbar filter is active.
  - A **🎫 Test Jira** button appears if the note contains a Jira URL.
- **Flags and notes survive all future crawls.**

### My Notes

The **💬 My Notes** panel (green) is for personal free-text notes independent of the review flag.

- Click **💾 Save Note** — saved permanently to the database.
- A 💬 icon appears in the sidebar and detail header.
- **Notes survive all future crawls.**

### PSA / TES Project Tracking

The **📋 PSA / TES Project Tracking** panel (blue) is at the bottom of the detail view. It stores internal project management data alongside each Oracle update.

| Field | Type | Description |
|---|---|---|
| **TES Owner** | Text | Name or email of the TES owner |
| **PSA Owner** | Text | Name or email of the PSA owner |
| **Function Category** | Text | Functional area (e.g. Compensation, Recruiting) |
| **TES Status** | Dropdown | Not Started · In Progress · To Review · Complete · On Hold · N/A |
| **Next Action Required for PSA Project** | Textarea | Description of the next steps required |
| **Profile Options Already On** | Textarea | List of relevant profile options currently enabled |
| **PSA Comments** | Textarea | Additional free-text comments |

- Click **💾 Save PSA / TES Fields** — all 7 fields are saved to the database immediately.
- Fields persist across crawls and are never overwritten by the crawler.
- All 7 fields are included as columns in the **Export to CSV** output from the Statistics tab.

### All Updates Tab

A table listing every update. Columns: radio select, Title, Category, Service, Impact, Date, Version. Click any row to open the Detail View.

### Statistics Tab & Export

Shows aggregated counts: total updates, breakdown by category/service/impact level, and the last crawl run summary.

**⬇ Export to CSV** downloads all currently-visible items (respecting the active filters) as a `.csv` file with the following columns:

```
Topic, Category, Version, Impact Level, Auto, Jira Link, Customize Note,
TES Owner, PSA Owner, Function Category, TES Status,
Next Action Required for PSA Project, Profile Options Already On, PSA Comments
```

### Conclusion (Comparison) Modal

1. Click any item to select it, then click **🔍 Conclusion** in the toolbar or the version badge in the Detail View.
2. A **side-by-side comparison table** shows fields that differ from a previous version (highlighted in amber with △).
3. A **version history table** lists all archived snapshots.

### AI Impact Analysis

Inside the Conclusion modal, **🧠 Analyze Impact & Upgrade Guide** runs an AI analysis.

- **First run** — calls the configured LLM and caches the result.
- **Subsequent opens** — cached analysis loads instantly.
- Click **🔄 Regenerate** to force a fresh LLM call.

**Analysis structure (with LLM configured):**

1. **Impact Summary** — what changed in one sentence.
2. **Action Required** — Yes / No / N/A with explanation.
3. **Upgrade Steps** — numbered concrete steps when action is required.
4. **Affected Areas** — APIs, SDKs, Console, CLI, HCM config, etc.
5. **AI Suggestion** — independent recommendation based solely on Oracle's documentation.
6. **Jira Ticket Response** — present only when a Jira ticket was successfully fetched.
7. **Summary Table** — when multiple items are analysed together.

**Without an LLM** (`LLM_PROVIDER=none`), a keyword-based fallback analysis is produced.

### Jira-Aware Analysis

When the selected item has a **Jira ticket URL in its flag note**, the Analyze workflow automatically fetches the ticket and feeds its content to the LLM — ticket key, summary, status, priority, description, and last 5 comments.

- A blue `🎫 Jira context loaded: PROJ-1234` badge appears when the fetch succeeded.
- A red `⚠ PROJ-1234: <error>` badge appears if it failed.
- Click **🎫 Test Jira** in the Flag panel to verify connectivity without running the full analysis.

### Project Instructions

The **⚙ Project Config** button (toolbar) opens the project configuration panel. The **Project Instructions** section lets you describe your project so the LLM can judge relevance and impact in the context of your specific deployment.

**How to set instructions:**

- **Type directly** into the textarea — describe modules in scope, key integrations, business priorities.
- **Upload a `.txt` file** — clicking Upload disables the textarea (file content takes over). Click **✕** on the file badge to remove it and re-enable the textarea. File upload and manual typing are mutually exclusive.

**Buttons:**

| Button | Action |
|---|---|
| **💾 Save** | Saves the current instructions to `data/project_context.txt`. A status badge shows **ACTIVE** when instructions are set. |
| **⚡ Mark Impact** | Saves instructions first, then re-classifies every record in the database using the current LLM and instructions. A progress bar shows `X / total` as records are processed. When complete, the item list refreshes automatically. Records with a manual impact override (✎) are skipped. |

**How it works with crawling:**

When instructions are saved and an LLM is configured, every **newly crawled** item is automatically classified using the instructions as context — no manual action needed after a crawl. The Mark Impact button is used to retroactively re-classify **existing** records.

**Without an LLM** (`LLM_PROVIDER=none`), instructions have no effect — rule-based classification is always used.

### Appearance Settings

Both settings are saved in browser local storage and restored on every visit.

**Font Size** — select from 12px – 20px.

**Background Colour** — click the colour swatch. Text automatically flips dark/light for readability.

---

## User Customisations Survive Crawls

These fields are set by users and **never overwritten by the crawler or Mark Impact**:

| Field | Where to set | Survives crawl? | Survives Mark Impact? |
|---|---|---|---|
| **Impact level override** | ⚡ Override Impact Level panel | ✅ Yes — marked ✎ | ✅ Yes — always skipped |
| **Flag + flag note** | 🚩 Flag for Review panel | ✅ Yes | ✅ Yes |
| **Personal note** | 💬 My Notes panel | ✅ Yes | ✅ Yes |
| **TES Owner** | 📋 PSA/TES panel | ✅ Yes | ✅ Yes |
| **PSA Owner** | 📋 PSA/TES panel | ✅ Yes | ✅ Yes |
| **Function Category** | 📋 PSA/TES panel | ✅ Yes | ✅ Yes |
| **TES Status** | 📋 PSA/TES panel | ✅ Yes | ✅ Yes |
| **Next Action** | 📋 PSA/TES panel | ✅ Yes | ✅ Yes |
| **Profile Options** | 📋 PSA/TES panel | ✅ Yes | ✅ Yes |
| **PSA Comments** | 📋 PSA/TES panel | ✅ Yes | ✅ Yes |

> **Database migration is automatic.** When upgrading from an older version, simply restart the app — `init_db()` detects and adds any missing columns via `ALTER TABLE` on startup. No manual SQL or database file deletion is required.

---

## REST API Reference

The API is available at `http://127.0.0.1:8000`. Interactive documentation (Swagger UI) is at `/docs`.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Serves the browser UI |
| `GET` | `/health` | Health check |
| `GET` | `/stats` | Summary statistics |
| `GET` | `/updates` | List updates (`category`, `service`, `impact_level`, `is_new`, `search`, `limit`, `offset`) |
| `GET` | `/updates/{id}` | Single update detail (includes all PSA/TES fields) |
| `GET` | `/updates/{id}/versions` | Version history for one update |
| `POST` | `/updates/{id}/impact` | Override impact level — body: `{"impact_level": "High"}` |
| `POST` | `/updates/{id}/flag` | Set/clear review flag — body: `{"is_flagged": true, "note": "..."}` |
| `POST` | `/updates/{id}/comment` | Save personal note — body: `{"comment": "..."}` |
| `POST` | `/updates/{id}/psa-fields` | Save PSA/TES tracking fields — body: see below |
| `GET` | `/categories` | Distinct category list |
| `GET` | `/services` | Distinct service list |
| `GET` | `/crawl-runs` | Crawl audit log |
| `GET` | `/conclusion?ids=1,2` | Enriched records with version history for given IDs |
| `GET` | `/jira-test?url=...` | Test whether a Jira ticket URL can be fetched (diagnostic) |
| `POST` | `/crawl` | Trigger a manual crawl |
| `POST` | `/mark-seen` | Mark all new updates as seen |
| `GET` | `/project-context` | Get saved project instructions — returns `{text, active}` |
| `POST` | `/project-context` | Save project instructions — body: `{"text": "..."}` |
| `POST` | `/reclassify-all` | Start background re-classification of every record using current LLM + instructions |
| `GET` | `/reclassify-status` | Poll progress of reclassify-all — returns `{running, done, total, error}` |
| `POST` | `/analyze` | Start async AI impact analysis — body: `{"ids": [1], "force": false}` |
| `GET` | `/analyze/{job_id}` | Poll for the result of an async analyze job |
| `POST` | `/search/ai` | AI-powered keyword search — body: `{"query": "..."}` |
| `POST` | `/ask` | Q&A over stored documents — body: `{"question": "..."}` |
| `POST` | `/purge-non-hcm` | Delete legacy OCI records and stale HCM mock data (hidden in UI) |

**`/updates/{id}/psa-fields` body (all fields optional):**

```json
{
  "tes_owner":         "Jane Smith",
  "psa_owner":         "John Doe",
  "function_category": "Compensation",
  "tes_status":        "In Progress",
  "next_action":       "Review impact on annual compensation cycle",
  "profile_options":   "ORA_HCM_COMP_ENABLED",
  "psa_comments":      "Blocked pending IT sign-off"
}
```

**`/updates/{id}/impact` body:**

```json
{ "impact_level": "High" }
```

Valid values: `"High"` / `"Medium"` / `"Low"`. Setting `null` clears the override.

**Example curl calls:**

```bash
# List all HCM updates
curl "http://127.0.0.1:8000/updates?category=HCM&limit=50"

# Override impact on item 42
curl -X POST http://127.0.0.1:8000/updates/42/impact \
     -H "Content-Type: application/json" \
     -d '{"impact_level": "High"}'

# Save PSA/TES fields for item 42
curl -X POST http://127.0.0.1:8000/updates/42/psa-fields \
     -H "Content-Type: application/json" \
     -d '{"tes_owner": "Jane", "tes_status": "In Progress"}'

# Save project instructions
curl -X POST http://127.0.0.1:8000/project-context \
     -H "Content-Type: application/json" \
     -d '{"text": "We are implementing HCM Compensation and Recruiting..."}'

# Start bulk re-classification
curl -X POST http://127.0.0.1:8000/reclassify-all

# Poll progress
curl http://127.0.0.1:8000/reclassify-status

# Test Jira connectivity
curl "http://127.0.0.1:8000/jira-test?url=https://jira.your-company.com/browse/PROJ-1234"
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
├── sources.ini             ← crawl source URLs (edit with Notepad)
├── config.py               ← all settings
├── main.py                 ← entry point
├── run.bat                 ← Windows portable launcher (auto-detects proxy)
├── install.bat             ← alternative installer using system Python + venv
├── pack.bat                ← builds OracleMonitor_portable.zip for distribution
│
├── api/
│   └── app.py              ← FastAPI endpoints
│
├── crawler/
│   ├── fetcher.py          ← HTTP client (retry, rate limiting, PAC proxy)
│   ├── parser.py           ← HTML parser + HCM hub crawler + mock data seed
│   └── scheduler.py        ← crawl pipeline orchestration
│
├── processor/
│   ├── analyzer.py         ← AI impact analysis + rule-based fallback
│   ├── classifier.py       ← impact/tag classification + project instructions
│   ├── jira_client.py      ← Jira ticket fetcher (PAT / Windows SSPI / anonymous)
│   └── summarizer.py       ← AI summary + Q&A
│
├── storage/
│   ├── models.py           ← SQLAlchemy ORM (OracleUpdate, UpdateVersion, AnalysisCache, CrawlRun)
│   ├── database.py         ← CRUD + auto schema migration (v1–v7)
│   └── file_store.py       ← raw HTML storage
│
├── ui/
│   └── index.html          ← single-page browser UI
│
├── data/                   ← runtime data (not committed)
│   ├── db/                 ← SQLite database
│   ├── raw/                ← archived raw HTML pages
│   └── project_context.txt ← saved project instructions (if set)
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
| `requests-negotiate-sspi` | Windows SSPI (NTLM/Kerberos) auth for Jira |
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

**"Dependency install failed" during run.bat on VPN**
- `run.bat` auto-detects your corporate proxy using Windows system settings and/or the `HTTPS_PROXY` value in `.env` (including PAC file URLs ending in `.pac`).
- If auto-detection fails, find your proxy manually: run `netsh winhttp show proxy` in PowerShell, then set `HTTPS_PROXY=http://host:port` in `.env`.
- If you see `CERTIFICATE_VERIFY_FAILED` errors, add `VERIFY_SSL=false` to `.env`.

**Crawl times out or returns "Connection timed out" on VPN**
- Same proxy steps as above — `HTTPS_PROXY` also applies to the crawler.
- The app uses `pypac` to resolve PAC file URLs automatically during crawling.

**Crawl returns 0 results from live Oracle pages**
- Oracle's pages may have changed their HTML structure. Check `logs/oracle_monitor.log` for parser warnings.

**LLM features not working**
- Set `LLM_PROVIDER=none` to fall back to rule-based analysis (always works, no API key needed).
- For OpenAI: verify `OPENAI_API_KEY` is set.
- For Anthropic: verify `ANTHROPIC_API_KEY` starts with `sk-ant-`.
- For Bedrock: run `aws sso login` first, verify `BEDROCK_REGION` and `BEDROCK_MODEL_ID`.
- For Ollama: verify Ollama is running (`ollama serve`) and the model is pulled (`ollama pull llama3`).

**Mark Impact does nothing / shows 0 / 0**
- Ensure project instructions are saved (the ACTIVE badge should be visible in ⚙ Project Config).
- Ensure `LLM_PROVIDER` is set to something other than `none`.
- Check `logs/oracle_monitor.log` for reclassify errors.

**PSA/TES fields are missing after upgrading**
- Just restart the app — `init_db()` automatically adds the new columns via `ALTER TABLE` on startup. No database deletion needed.

**AI Impact Analysis returns HTTP 500**
- Restart the app — `init_db()` automatically adds any missing columns on startup.
- Check `logs/oracle_monitor.log` for `Cache read/write failed` warnings.

**Jira Test Jira button shows ⚠ HTTP 401 / Authentication required**

The app tries two auth methods in order:

1. **Jira PAT (recommended)** — set `JIRA_PAT` in `.env`:
   - Open Jira → Click avatar → **Profile** → **Personal Access Tokens** → **Create token** → copy it
   - Add to `.env`: `JIRA_PAT=<your token>` and restart the app

2. **Windows SSPI** (fallback, no config needed):
   ```
   runtime\python.exe -m pip install requests-negotiate-sspi
   ```
   Restart the app. Note: SSPI may fail if your corporate Jira uses reverse-proxy SSO that doesn't accept NTLM from non-browser clients. The PAT approach is more reliable.

**Want to reset all data**
- Stop the server.
- Delete `data/db/oracle_monitor.db`.
- Restart — the database is rebuilt from scratch on the next crawl.

**Impact level I manually set was reset after a crawl**
- This should not happen. Impact overrides set via ⚡ set `impact_overridden=true` in the database, which the crawler and Mark Impact both check before updating.
- Verify you are running the latest version and restart so the schema migration runs.
