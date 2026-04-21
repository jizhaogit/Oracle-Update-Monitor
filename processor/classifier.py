"""
processor/classifier.py — Classify and tag Oracle update records.

Two modes:
  - "none"   — rule-based classifier (no LLM required, works offline)
  - "openai" — LangChain + OpenAI for richer classification
  - "ollama" — LangChain + local Ollama model
"""

import json
import logging
import re
from typing import Optional

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import (
    IMPACT_KEYWORDS, LLM_PROVIDER, TAG_KEYWORDS, DATA_DIR,
    OPENAI_API_KEY, OPENAI_MODEL,
    ANTHROPIC_API_KEY, ANTHROPIC_MODEL,
    BEDROCK_MODEL_ID, BEDROCK_REGION, BEDROCK_PROFILE,
    OLLAMA_BASE_URL, OLLAMA_MODEL,
    LLM_TIMEOUT,
)

log = logging.getLogger(__name__)

# Path where the user's project instructions are stored
_PROJECT_CONTEXT_FILE = DATA_DIR / "project_context.txt"


def _load_project_context() -> str:
    """Return the saved project instructions, or empty string if none saved."""
    try:
        if _PROJECT_CONTEXT_FILE.exists():
            text = _PROJECT_CONTEXT_FILE.read_text(encoding="utf-8").strip()
            return text
    except Exception as exc:
        log.warning("Could not read project context: %s", exc)
    return ""


def save_project_context(text: str) -> None:
    """Persist project instructions to disk."""
    _PROJECT_CONTEXT_FILE.write_text(text.strip(), encoding="utf-8")
    log.info("Project context saved (%d chars)", len(text.strip()))


# ── Rule-based classifier (always available) ───────────────────────────────────

def _rule_based_impact(title: str, content: str) -> str:
    combined = (title + " " + content).lower()
    for level, keywords in IMPACT_KEYWORDS.items():
        for kw in keywords:
            if kw in combined:
                return level
    return "Low"


def _rule_based_tags(title: str, content: str, service: str) -> list[str]:
    combined = (title + " " + content).lower()
    found = set()
    for kw, tag in TAG_KEYWORDS.items():
        if kw in combined:
            found.add(tag)
    # Always include the service as a tag
    if service:
        found.add(service)
    return sorted(found)


def rule_classify(record: dict) -> dict:
    """
    Enrich a record dict with impact_level and tags using rule-based logic.
    Returns the modified record dict.
    """
    title   = record.get("title", "")
    content = record.get("content", "")
    service = record.get("service", "")

    record["impact_level"] = _rule_based_impact(title, content)
    record["tags"]         = _rule_based_tags(title, content, service)
    return record


# ── LangChain LLM classifier ───────────────────────────────────────────────────

_llm = None
_chain = None


def _get_llm():
    global _llm
    if _llm is not None:
        return _llm

    try:
        if LLM_PROVIDER == "openai" and OPENAI_API_KEY:
            from langchain_openai import ChatOpenAI
            _llm = ChatOpenAI(
                model=OPENAI_MODEL,
                openai_api_key=OPENAI_API_KEY,
                temperature=0,
            )
            log.info("LLM: OpenAI %s", OPENAI_MODEL)

        elif LLM_PROVIDER == "anthropic" and ANTHROPIC_API_KEY:
            from langchain_anthropic import ChatAnthropic
            _llm = ChatAnthropic(
                model=ANTHROPIC_MODEL,
                anthropic_api_key=ANTHROPIC_API_KEY,
                temperature=0,
                max_tokens=4096,
            )
            log.info("LLM: Anthropic %s", ANTHROPIC_MODEL)

        elif LLM_PROVIDER == "bedrock":
            import boto3
            from langchain_aws import ChatBedrock
            # Honour a named SSO profile if provided; otherwise use the default
            # credential chain (env vars, ~/.aws/credentials, instance role, SSO)
            session = (boto3.Session(profile_name=BEDROCK_PROFILE)
                       if BEDROCK_PROFILE else boto3.Session())
            client = session.client("bedrock-runtime", region_name=BEDROCK_REGION)
            _llm = ChatBedrock(
                model_id=BEDROCK_MODEL_ID,
                client=client,
                model_kwargs={"temperature": 0, "max_tokens": 4096},
            )
            log.info("LLM: AWS Bedrock %s (%s)", BEDROCK_MODEL_ID, BEDROCK_REGION)

        elif LLM_PROVIDER == "ollama":
            from langchain_community.chat_models import ChatOllama
            _llm = ChatOllama(base_url=OLLAMA_BASE_URL, model=OLLAMA_MODEL, temperature=0)
            log.info("LLM: Ollama (chat) %s @ %s", OLLAMA_MODEL, OLLAMA_BASE_URL)

    except Exception as exc:
        log.warning("LLM init failed (%s), falling back to rule-based: %s", LLM_PROVIDER, exc)
        _llm = None

    return _llm


def _get_chain():
    global _chain
    if _chain is not None:
        return _chain

    llm = _get_llm()
    if llm is None:
        return None

    try:
        from langchain_core.output_parsers import StrOutputParser
        from langchain_core.prompts import ChatPromptTemplate

        template = ChatPromptTemplate.from_messages([
            ("system", (
                "You are an expert Oracle Cloud HCM and OIC analyst. "
                "Analyse the following release-note entry and respond "
                "with a JSON object containing exactly these fields:\n"
                "  impact_level: one of High | Medium | Low\n"
                "  tags: list of short keyword strings (max 6)\n"
                "  summary: one-paragraph plain-English summary (max 80 words)\n\n"
                "{project_context}"
                "Respond with valid JSON only — no markdown, no extra text."
            )),
            ("human", (
                "Title: {title}\n"
                "Service: {service}  Category: {category}\n\n"
                "Content:\n{content}"
            )),
        ])
        _chain = template | llm | StrOutputParser()
        log.info("LangChain classification chain initialised")
    except Exception as exc:
        log.warning("Chain init failed: %s", exc)
        _chain = None

    return _chain


def llm_classify(record: dict) -> dict:
    """
    Use LangChain LLM to enrich a record with impact_level, tags, and summary.
    Falls back to rule-based if LLM_TIMEOUT seconds elapse or any error occurs.
    Uses a daemon thread so a slow LLM never blocks the crawl indefinitely.
    """
    import threading

    chain = _get_chain()
    if chain is None:
        return rule_classify(record)

    bucket: dict = {}

    # Load project context and format it for the prompt
    _ctx = _load_project_context()
    _project_context_str = (
        f"Team project context (use this to judge relevance and impact):\n"
        f"─────────────────────────────────────────────\n"
        f"{_ctx}\n"
        f"─────────────────────────────────────────────\n\n"
    ) if _ctx else ""

    def _invoke():
        try:
            raw = chain.invoke({
                "title":           record.get("title", ""),
                "service":         record.get("service", ""),
                "category":        record.get("category", ""),
                "content":         record.get("content", "")[:1500],
                "project_context": _project_context_str,
            })
            raw = re.sub(r"```json|```", "", raw).strip()
            bucket["parsed"] = json.loads(raw)
        except Exception as exc:
            bucket["error"] = str(exc)

    t = threading.Thread(target=_invoke, daemon=True)
    t.start()
    t.join(timeout=LLM_TIMEOUT)

    if "parsed" in bucket:
        parsed = bucket["parsed"]
        record["impact_level"] = parsed.get("impact_level", "Low")
        record["tags"]         = parsed.get("tags", [])
        if parsed.get("summary"):
            record["summary"]  = parsed["summary"]
        log.debug("LLM classified: %s → %s", record["title"][:60], record["impact_level"])
        return record

    if "error" in bucket:
        log.warning("LLM classification failed (%s), using rule-based", bucket["error"])
    else:
        log.warning("LLM classify timeout (%ds) for '%s' — using rule-based",
                    LLM_TIMEOUT, record.get("title", "")[:50])
    return rule_classify(record)


def classify(record: dict) -> dict:
    """
    Main entry point: classify a record dict.
    Uses LLM if configured, otherwise rule-based.
    """
    if LLM_PROVIDER in ("openai", "anthropic", "bedrock", "ollama"):
        return llm_classify(record)
    return rule_classify(record)


def classify_batch(records: list[dict]) -> list[dict]:
    """Classify a list of records in-place."""
    for i, rec in enumerate(records):
        records[i] = classify(rec)
    return records
