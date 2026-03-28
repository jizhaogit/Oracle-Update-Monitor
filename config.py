"""
config.py — Central configuration for Oracle OCI/OIC Monitor.

All settings are read from environment variables (or .env file).
Sensible defaults allow the app to run out-of-the-box.
"""

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

for _d in [DATA_DIR, DB_DIR, FILES_DIR, VECTOR_DIR, RAW_DIR, LOGS_DIR]:
    _d.mkdir(parents=True, exist_ok=True)

# ── Database ───────────────────────────────────────────────────────────────────
DATABASE_URL = f"sqlite:///{DB_DIR}/oracle_monitor.db"

# ── Oracle URLs to monitor ─────────────────────────────────────────────────────
# Each entry: display_name → {url, category, service, type}
ORACLE_SOURCES: dict[str, dict] = {
    "OCI — What's New": {
        "url": "https://docs.oracle.com/en-us/iaas/Content/servicechanges.htm",
        "category": "OCI",
        "service": "General",
        "doc_type": "whats_new",
    },
    "OCI — Release Notes (All)": {
        "url": "https://docs.oracle.com/en-us/iaas/releasenotes/",
        "category": "OCI",
        "service": "General",
        "doc_type": "release_notes",
    },
    "OCI — Compute": {
        "url": "https://docs.oracle.com/en-us/iaas/releasenotes/changes/compute/",
        "category": "OCI",
        "service": "Compute",
        "doc_type": "release_notes",
    },
    "OCI — Networking": {
        "url": "https://docs.oracle.com/en-us/iaas/releasenotes/changes/network/",
        "category": "OCI",
        "service": "Networking",
        "doc_type": "release_notes",
    },
    "OCI — Database": {
        "url": "https://docs.oracle.com/en-us/iaas/releasenotes/changes/database/",
        "category": "OCI",
        "service": "Database",
        "doc_type": "release_notes",
    },
    "OCI — Storage": {
        "url": "https://docs.oracle.com/en-us/iaas/releasenotes/changes/storage/",
        "category": "OCI",
        "service": "Storage",
        "doc_type": "release_notes",
    },
    "OCI — Security": {
        "url": "https://docs.oracle.com/en-us/iaas/releasenotes/changes/security/",
        "category": "OCI",
        "service": "Security",
        "doc_type": "release_notes",
    },
    "OCI — Analytics": {
        "url": "https://docs.oracle.com/en-us/iaas/releasenotes/changes/analytics/",
        "category": "OCI",
        "service": "Analytics",
        "doc_type": "release_notes",
    },
    "OCI — Containers & Kubernetes": {
        "url": "https://docs.oracle.com/en-us/iaas/releasenotes/changes/containers/",
        "category": "OCI",
        "service": "Containers",
        "doc_type": "release_notes",
    },
    "OIC — What's New": {
        "url": "https://docs.oracle.com/en/cloud/paas/integration-cloud/whats-new/",
        "category": "OIC",
        "service": "Integration",
        "doc_type": "whats_new",
    },
    "OIC — Release Notes": {
        "url": "https://docs.oracle.com/en/cloud/paas/integration-cloud/release-notes/",
        "category": "OIC",
        "service": "Integration",
        "doc_type": "release_notes",
    },
}

# Impact-level keywords used by the rule-based classifier
IMPACT_KEYWORDS: dict[str, list[str]] = {
    "High":   ["breaking change", "deprecated", "removed", "critical", "security",
               "vulnerability", "end of life", "eol", "migration required"],
    "Medium": ["new feature", "enhancement", "improvement", "added", "updated",
               "expanded", "new service", "preview"],
    "Low":    ["documentation", "bug fix", "minor", "typo", "clarification",
               "updated docs", "note"],
}

# Tag extraction keyword → tag
TAG_KEYWORDS: dict[str, str] = {
    "compute":      "Compute",
    "instance":     "Compute",
    "networking":   "Networking",
    "vcn":          "Networking",
    "subnet":       "Networking",
    "database":     "Database",
    "autonomous":   "Database",
    "storage":      "Storage",
    "object storage": "Storage",
    "block volume": "Storage",
    "security":     "Security",
    "iam":          "IAM",
    "policy":       "IAM",
    "kubernetes":   "Kubernetes",
    "container":    "Containers",
    "analytics":    "Analytics",
    "integration":  "Integration",
    "api":          "API",
    "sdk":          "SDK",
    "cli":          "CLI",
    "terraform":    "Terraform",
    "monitoring":   "Monitoring",
    "logging":      "Logging",
    "notification": "Notifications",
    "ai":           "AI/ML",
    "machine learning": "AI/ML",
    "generative":   "GenAI",
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

EMBEDDINGS_PROVIDER = os.getenv("EMBEDDINGS_PROVIDER", "huggingface")
EMBEDDINGS_MODEL    = os.getenv("EMBEDDINGS_MODEL", "all-MiniLM-L6-v2")

# ── Scheduler ──────────────────────────────────────────────────────────────────
CRAWL_INTERVAL_HOURS = int(os.getenv("CRAWL_INTERVAL_HOURS", "24"))
CRAWL_ON_STARTUP     = os.getenv("CRAWL_ON_STARTUP", "true").lower() == "true"

# ── API ────────────────────────────────────────────────────────────────────────
API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", "8000"))

# ── HTTP crawler ───────────────────────────────────────────────────────────────
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))
REQUEST_DELAY   = float(os.getenv("REQUEST_DELAY", "2.0"))
MAX_RETRIES     = int(os.getenv("MAX_RETRIES", "3"))

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
