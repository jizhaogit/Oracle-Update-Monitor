"""
config.py — Central configuration for Oracle OCI/OIC Monitor.

All settings are read from environment variables (or .env file).
Sensible defaults allow the app to run out-of-the-box.
"""

import configparser
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── Directory layout ───────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
DATA_DIR   = BASE_DIR / "data"
DB_DIR     = DATA_DIR / "db"
FILES_DIR  = DATA_DIR / "files"
VECTOR_DIR = DATA_DIR / "vectors"
RAW_DIR    = DATA_DIR / "raw"
LOGS_DIR   = BASE_DIR / "logs"

for _d in [DATA_DIR, DB_DIR, FILES_DIR, RAW_DIR, LOGS_DIR]:
    _d.mkdir(parents=True, exist_ok=True)

# ── Database ───────────────────────────────────────────────────────────────────
DATABASE_URL = f"sqlite:///{DB_DIR}/oracle_monitor.db"

# ── Oracle URLs to monitor ─────────────────────────────────────────────────────
# Loaded from sources.ini (auto-created on first run).
# Users can edit that file with Notepad — no code changes needed.

SOURCES_FILE = BASE_DIR / "sources.ini"
INSTRUCTION_FILE = BASE_DIR / "instruction.ini"
INSTRUCTION_EXAMPLE_FILE = BASE_DIR / "instruction.ini.example"

_DEFAULT_SOURCES_INI = """\
# Oracle Update Monitor — Source URLs
# ─────────────────────────────────────────────────────────────────────────────
# Edit this file to add, remove, or disable the URLs the app crawls.
# Restart the app after saving changes.
#
# Each [Section Name] becomes the display name shown in the UI.
# Required fields:  url, category, service
# Optional fields:
#   type    = whats_new | release_notes | reference   (default: release_notes)
#   enabled = true | false                            (default: true)
#
# To stop crawling a source without deleting it, set:  enabled = false
# Lines starting with # are comments and are ignored.
# ─────────────────────────────────────────────────────────────────────────────

# ── HCM Readiness (hub crawls all keyword-filtered modules automatically) ────

[HCM — What's New]
url      = https://docs.oracle.com/en/cloud/saas/readiness/hcm.html
category = HCM
service  = Human Capital Management
type     = whats_new

# ── Common Technologies & User Experience Readiness ───────────────────────────

[Common Technologies — What's New]
url      = https://docs.oracle.com/en/cloud/saas/readiness/common.html
category = HCM
service  = Common Technologies and User Experience
type     = whats_new

# ── OIC (Oracle Integration Cloud) ───────────────────────────────────────────

[OIC — What's New]
url      = https://docs.oracle.com/en/cloud/paas/integration-cloud/whats-new/
category = OIC
service  = Integration
type     = whats_new

[OIC — Release Notes]
url      = https://docs.oracle.com/en/cloud/paas/integration-cloud/release-notes/
category = OIC
service  = Integration
type     = release_notes

# ── Add your own sources below ───────────────────────────────────────────────
# Example:
#
# [My Custom Source]
# url      = https://docs.oracle.com/en/cloud/saas/readiness/hcm.html
# category = HCM
# service  = My Service
# type     = whats_new
"""


def _load_sources() -> dict[str, dict]:
    """
    Read SOURCES_FILE (sources.ini) and return the ORACLE_SOURCES dict.
    If the file does not exist, write it from the built-in defaults first.
    Sections with  enabled = false  are silently skipped.
    """
    if not SOURCES_FILE.exists():
        SOURCES_FILE.write_text(_DEFAULT_SOURCES_INI, encoding="utf-8")

    cp = configparser.RawConfigParser()
    cp.optionxform = str          # preserve key case as written
    cp.read(SOURCES_FILE, encoding="utf-8")

    sources: dict[str, dict] = {}
    for name in cp.sections():
        sec = cp[name]
        if sec.get("enabled", "true").strip().lower() in ("false", "0", "no"):
            continue
        url = sec.get("url", "").strip()
        if not url:
            continue
        sources[name] = {
            "url":      url,
            "category": sec.get("category", "OCI").strip(),
            "service":  sec.get("service",  "General").strip(),
            "doc_type": sec.get("type",     "release_notes").strip(),
        }
    return sources


ORACLE_SOURCES: dict[str, dict] = _load_sources()


def _init_instruction_file() -> None:
    """
    If instruction.ini does not exist yet, seed it from instruction.ini.example.
    This mirrors the pattern used for sources.ini auto-creation.
    """
    if not INSTRUCTION_FILE.exists():
        if INSTRUCTION_EXAMPLE_FILE.exists():
            content = INSTRUCTION_EXAMPLE_FILE.read_text(encoding="utf-8")
            INSTRUCTION_FILE.write_text(content, encoding="utf-8")
        else:
            # Minimal fallback if the example file is also missing.
            # Must match the current schema: [Project], [Scope], [Context], [Crawl].
            # [Priority] and [Notes] are obsolete — do NOT include them here.
            INSTRUCTION_FILE.write_text(
                "# Oracle Update Monitor — Project Instructions\n"
                "[Project]\ndescription =\n\n"
                "[Scope]\nmodules =\nintegrations =\n\n"
                "[Context]\nnotes =\n\n"
                "[Crawl]\nextra_keywords =\n",
                encoding="utf-8",
            )


_init_instruction_file()

# Impact-level keywords used by the rule-based classifier
IMPACT_KEYWORDS: dict[str, list[str]] = {
    "High":   ["breaking change", "deprecated", "removed", "critical", "security",
               "vulnerability", "end of life", "eol", "migration required"],
    "Medium": ["new feature", "enhancement", "improvement", "added", "updated",
               "expanded", "new service", "preview",
               # UI / new-experience keywords — Oracle readiness naming conventions:
               # "X Introduction in Redwood Y" always means a new UI feature
               "introduction",      # Oracle uses "X Introduction" for new UI features
               "redwood",           # Oracle's Redwood UI framework
               "new experience",    # "Redwood Experience for ..."
               "redesigned",        # redesigned pages / workflows
               "new section",       # new UI section added to an existing page
               ],
    "Low":    ["documentation", "bug fix", "minor", "typo", "clarification",
               "updated docs", "note"],
}

# Tag extraction keyword → tag
TAG_KEYWORDS: dict[str, str] = {
    # ── HCM modules ──────────────────────────────────────────────────────────
    "human resources":              "Human Resources",
    "global human resources":       "Human Resources",
    "workforce":                    "Human Resources",
    "recruiting":                   "Recruiting",
    "talent acquisition":           "Recruiting",
    "opportunity marketplace":      "Opportunity Marketplace",
    "internal mobility":            "Opportunity Marketplace",
    "talent management":            "Talent Management",
    "performance":                  "Talent Management",
    "succession":                   "Talent Management",
    "compensation":                 "Compensation",
    "total compensation":           "Compensation",
    "salary":                       "Compensation",
    "hcm common":                   "HCM Common",
    "absence":                      "Absence Management",
    "time and labor":               "Time & Labor",
    "payroll":                      "Payroll",
    "benefits":                     "Benefits",
    "learning":                     "Learning",
    "dynamic skills":               "Skills",
    "skills":                       "Skills",
    # ── Cross-cutting ─────────────────────────────────────────────────────────
    "security":                     "Security",
    "api":                          "API",
    "rest api":                     "API",
    "analytics":                    "Analytics",
    "ai":                           "AI/ML",
    "machine learning":             "AI/ML",
    "generative":                   "GenAI",
    "agentic":                      "GenAI",
    # ── UI / new-experience tags ──────────────────────────────────────────────
    "redwood":                      "Redwood UI",
    "new experience":               "Redwood UI",
    "user interface":               "Redwood UI",
    "common technologies":          "Common Technologies",
    "user experience":              "Common Technologies",
}

# ── LLM / AI settings ──────────────────────────────────────────────────────────
# Options: "openai" | "anthropic" | "bedrock" | "ollama" | "none"
LLM_PROVIDER        = os.getenv("LLM_PROVIDER", "none")

# OpenAI
OPENAI_API_KEY      = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL        = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")

# Anthropic direct API (sk-ant-... key from IT or platform.anthropic.com)
ANTHROPIC_API_KEY   = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL     = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")

# AWS Bedrock (uses AWS SSO / IAM credentials — no Anthropic key needed)
BEDROCK_MODEL_ID    = os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0")
BEDROCK_REGION      = os.getenv("BEDROCK_REGION", "us-east-1")
BEDROCK_PROFILE     = os.getenv("BEDROCK_PROFILE", "")   # AWS SSO profile name (optional)

# Ollama local LLM
OLLAMA_BASE_URL     = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL        = os.getenv("OLLAMA_MODEL", "llama2")

# Embeddings (kept for summarizer.py compatibility — vector search is disabled)
EMBEDDINGS_PROVIDER = os.getenv("EMBEDDINGS_PROVIDER", "huggingface")
EMBEDDINGS_MODEL    = os.getenv("EMBEDDINGS_MODEL", "all-MiniLM-L6-v2")

# Max seconds for a single LLM classification call (crawl) before falling back to rule-based
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "15"))

# ── Scheduler ──────────────────────────────────────────────────────────────────
CRAWL_INTERVAL_HOURS = int(os.getenv("CRAWL_INTERVAL_HOURS", "24"))
CRAWL_ON_STARTUP     = os.getenv("CRAWL_ON_STARTUP", "true").lower() == "true"

# Set CRAWL_SCHEDULE=false to disable ALL automatic crawling (startup + interval).
# When false, crawls only run when you click the "Crawl Now" button in the UI.
CRAWL_SCHEDULE_ENABLED = os.getenv("CRAWL_SCHEDULE", "true").lower() in ("true", "1", "yes")

# ── Jira integration ───────────────────────────────────────────────────────────
# Personal Access Token — the most reliable way to access corporate Jira.
# Leave blank to fall back to Windows SSPI (silent, no config needed).
#
# How to generate:
#   1. Open Jira in your browser
#   2. Click your avatar (top-right) → Profile → Personal Access Tokens
#   3. Click "Create token", give it a name, set expiry, click Create
#   4. Copy the token and paste it below — it is only shown once
JIRA_PAT = os.getenv("JIRA_PAT", "")

# ── API ────────────────────────────────────────────────────────────────────────
API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", "8000"))

# ── HTTP crawler ───────────────────────────────────────────────────────────────
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))
REQUEST_DELAY   = float(os.getenv("REQUEST_DELAY", "2.0"))
MAX_RETRIES     = int(os.getenv("MAX_RETRIES", "3"))

# Additional HCM release codes to crawl alongside whatever the hub page lists.
# The hub only shows the CURRENT release; older releases must be listed here.
# Comma-separated, e.g.  HCM_EXTRA_RELEASES=26A,25D,25C
# Default: include 26A so Compensation/Payroll/etc. 26A features are discovered.
HCM_EXTRA_RELEASES: list[str] = [
    r.strip().upper()
    for r in os.getenv("HCM_EXTRA_RELEASES", "26A").split(",")
    if r.strip()
]

# HCM module keyword filter — only crawl readiness modules whose title contains
# at least one of these keywords (case-insensitive substring match).
# Covers both the HCM hub (hcm.html) and Fusion Common hub (common.html).
# Leave blank (HCM_MODULE_KEYWORDS=) to crawl ALL modules from every hub.
# Comma-separated, e.g.  HCM_MODULE_KEYWORDS=Compensation,Recruiting
HCM_MODULE_KEYWORDS: list[str] = [
    k.strip()
    for k in os.getenv(
        "HCM_MODULE_KEYWORDS",
        "Human Resources,"
        "Human Capital Management,"
        "Recruiting,"
        "Opportunity Marketplace,"
        "Talent Management,"
        "Compensation,"
        "HCM Common,"
        "Common Technologies",
    ).split(",")
    if k.strip()
]

def _read_instruction_extra_keywords() -> list[str]:
    """Read [Crawl] extra_keywords from instruction.ini and return as a list."""
    try:
        if INSTRUCTION_FILE.exists():
            cp = configparser.RawConfigParser()
            cp.read(str(INSTRUCTION_FILE), encoding="utf-8")
            raw = cp.get("Crawl", "extra_keywords", fallback="")
            return [k.strip() for k in raw.split(",") if k.strip()]
    except Exception:
        pass
    return []


# Merge extra keywords from instruction.ini into HCM_MODULE_KEYWORDS
_extra_kw = _read_instruction_extra_keywords()
for _kw in _extra_kw:
    if _kw not in HCM_MODULE_KEYWORDS:
        HCM_MODULE_KEYWORDS.append(_kw)

# Corporate proxy support — set these in .env when running behind a VPN.
# Example:  HTTPS_PROXY=http://proxy.company.com:8080
# Leave blank to fall back to system/OS proxy detection.
HTTP_PROXY  = os.getenv("HTTP_PROXY",  "")
HTTPS_PROXY = os.getenv("HTTPS_PROXY", "")

# SSL certificate verification.
# Corporate VPN / proxy SSL inspection causes "certificate verify failed" errors.
# Option A (recommended): export your corporate CA cert as a .pem/.crt file and set:
#   SSL_CERT_FILE=C:\path\to\corporate-ca.pem
# Option B (quick fix):  set VERIFY_SSL=false to skip verification entirely.
VERIFY_SSL    = os.getenv("VERIFY_SSL", "true").lower() not in ("false", "0", "no")
SSL_CERT_FILE = os.getenv("SSL_CERT_FILE", "").strip() or None

# ── Logging ────────────────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE  = LOGS_DIR / "oracle_monitor.log"

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
