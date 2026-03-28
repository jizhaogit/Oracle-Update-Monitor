"""
processor/analyzer.py — Impact analysis and upgrade guidance for Oracle updates.

Uses the configured LLM when available; falls back to rule-based keyword
analysis so the feature always works even without an API key.
"""

import logging

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import LLM_PROVIDER, OLLAMA_BASE_URL, OLLAMA_MODEL

log = logging.getLogger(__name__)

# Keywords that strongly suggest action is required
_ACTION_KEYWORDS = [
    "breaking change", "deprecated", "deprecation", "removed", "end of life",
    "eol", "migration required", "mandatory", "no longer supported",
    "will be discontinued", "sunset", "shutdown", "must update", "must upgrade",
    "required action", "action required", "retire", "retiring",
]

# Keywords that suggest informational / no action
_INFO_KEYWORDS = [
    "new feature", "enhancement", "added support", "new capability",
    "improved", "bug fix", "minor update", "documentation", "preview",
    "generally available", "now available", "clarification",
]


def _fmt_updates(updates: list[dict]) -> str:
    """Render update records into a readable block for the LLM prompt."""
    parts = []
    for i, u in enumerate(updates, 1):
        content_excerpt = (u.get("content") or "")[:2500]
        parts.append(
            f"[Update {i}]\n"
            f"Title: {u.get('title', 'N/A')}\n"
            f"Category: {u.get('category', '')} | Service: {u.get('service', '')}\n"
            f"Impact Level: {u.get('impact_level', 'Unknown')}\n"
            f"Summary: {u.get('summary') or '(none)'}\n"
            f"Tags: {', '.join(u.get('tags') or []) or '(none)'}\n"
            f"Content:\n{content_excerpt}"
        )
    return "\n\n---\n\n".join(parts)


def _llm_analyze(updates: list[dict]) -> str | None:
    """Call the configured LLM to produce structured upgrade guidance.
    Runs as a blocking call — callers must run this in a background thread if needed."""
    try:
        from processor.classifier import _get_llm
        from langchain_core.messages import HumanMessage, SystemMessage

        llm = _get_llm()
        if llm is None:
            return None

        system = (
            "You are a senior Oracle Cloud architect advising development teams on how "
            "to react to Oracle OCI/OIC documentation updates.\n\n"
            "For each update provided, produce a structured analysis:\n\n"
            "1. **Impact Summary** — one sentence describing what changed.\n"
            "2. **Action Required** — Yes / No / N/A\n"
            "   - Yes  → the update may break or require changes to existing code, "
            "config, API calls, or endpoints.\n"
            "   - No   → backward-compatible new feature, informational notice, or "
            "documentation fix. Write **No action needed.** and briefly explain why.\n"
            "   - N/A  → not applicable to existing integrations (preview feature, "
            "unrelated service, pure docs). Write **N/A** and briefly explain.\n"
            "3. **Upgrade Steps** (only if Action Required = Yes) — numbered, concrete, "
            "specific steps a developer can follow immediately. Include:\n"
            "   - Which API endpoints, SDK methods, or CLI commands changed\n"
            "   - Old behaviour vs new behaviour\n"
            "   - Example code or configuration snippets where helpful\n"
            "   - Deadline or migration window if mentioned\n"
            "4. **Affected Areas** — APIs / SDKs / Console / CLI / Terraform / etc.\n\n"
            "If multiple updates are provided, analyse each one separately with a clear "
            "heading, then add a combined **Summary Table** at the end.\n\n"
            "Use Markdown formatting. Be specific and actionable."
        )

        user = (
            "Please analyse the following Oracle Cloud update(s) and produce upgrade "
            f"guidance my team can act on today:\n\n{_fmt_updates(updates)}"
        )

        resp = llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])
        return resp.content.strip()

    except Exception as exc:
        log.warning("LLM impact analysis failed (%s): %s", LLM_PROVIDER, exc)
        return None


def _llm_status_note() -> str:
    """Return a human-readable note explaining why rule-based is being used."""
    if LLM_PROVIDER == "none":
        return (
            "> **Note:** No LLM configured (`LLM_PROVIDER=none`). "
            "Set `LLM_PROVIDER=ollama` (or `anthropic` / `openai`) in `.env` "
            "and restart the app for AI-generated, code-level guidance."
        )
    if LLM_PROVIDER == "ollama":
        return (
            f"> **Note:** Ollama is configured (`{OLLAMA_MODEL}` at `{OLLAMA_BASE_URL}`) "
            "but the analysis timed out or could not be reached. "
            "Make sure Ollama is running (`ollama serve`) and the model is downloaded "
            f"(`ollama pull {OLLAMA_MODEL}`). "
            "You can also increase `LLM_TIMEOUT` in `.env` for slower machines."
        )
    if LLM_PROVIDER == "anthropic":
        return (
            "> **Note:** Anthropic provider is configured but the API call failed. "
            "Check that `ANTHROPIC_API_KEY` in `.env` is a valid `sk-ant-...` key."
        )
    if LLM_PROVIDER == "bedrock":
        return (
            "> **Note:** AWS Bedrock is configured but the API call failed. "
            "Run `aws sso login` first, then check `BEDROCK_REGION` and "
            "`BEDROCK_MODEL_ID` are correct in `.env`."
        )
    return "> **Note:** LLM call failed. Check `logs/oracle_monitor.log` for details."


def _rule_based_analyze(updates: list[dict]) -> str:
    """
    Keyword-driven fallback analysis — always available without an LLM.
    Produces a Markdown report specific to each update's actual content.
    """
    llm_note = _llm_status_note()
    sections = []

    for i, u in enumerate(updates, 1):
        title      = u.get("title") or "Unknown"
        category   = u.get("category") or ""
        service    = u.get("service") or ""
        impact     = (u.get("impact_level") or "").lower()
        summary    = u.get("summary") or ""
        content    = u.get("content") or ""
        tags       = u.get("tags") or []
        source_url = u.get("source_url") or ""

        blob = f"{title} {summary} {content}".lower()

        action_hits = [kw for kw in _ACTION_KEYWORDS if kw in blob]
        info_hits   = [kw for kw in _INFO_KEYWORDS   if kw in blob]

        # Content excerpt — first 400 chars of meaningful content
        excerpt = (summary or content)[:400].strip()
        if excerpt:
            excerpt_block = f"\n> {excerpt}\n"
        else:
            excerpt_block = ""

        tag_line = f"**Tags:** {', '.join(tags)}\n\n" if tags else ""
        link_line = f"**Reference:** [{source_url}]({source_url})\n\n" if source_url else ""

        if action_hits or impact == "high":
            kw_list = ", ".join(f"`{k}`" for k in action_hits[:4])
            signal_line = f"**Detected signals:** {kw_list}\n\n" if kw_list else ""
            body = (
                f"**Action Required: Yes**\n\n"
                f"{signal_line}"
                f"{tag_line}"
                f"{excerpt_block}\n"
                f"{link_line}"
                f"**Recommended steps for `{title}`:**\n\n"
                f"1. Review the full update at the reference link above.\n"
                f"2. Search your codebase for references to **{service}** "
                f"{'APIs, SDK calls, or endpoints' if 'api' in blob or 'endpoint' in blob or 'sdk' in blob else 'configuration or integration points'} "
                f"related to `{title}`.\n"
                f"3. Test your {category} integration in a non-production environment.\n"
                f"4. Apply any schema, endpoint, or configuration changes described in the update.\n"
                f"5. {'Deploy before any stated deadline.' if any(w in blob for w in ['deadline', 'by ', 'before ', 'migrate by']) else 'Monitor for issues after deployment.'}\n"
            )

        elif info_hits or impact in ("low", "medium"):
            body = (
                f"**No action needed.**\n\n"
                f"{tag_line}"
                f"{excerpt_block}\n"
                f"{link_line}"
                f"This `{service}` update is backward-compatible "
                f"({'a new feature' if any(w in blob for w in ['new feature', 'new service', 'added']) else 'an enhancement or informational notice'}). "
                f"Existing {category} integrations should continue working without modification.\n\n"
                f"You may optionally explore the new capability at your own pace.\n"
            )

        else:
            body = (
                f"**Review Required**\n\n"
                f"{tag_line}"
                f"{excerpt_block}\n"
                f"{link_line}"
                f"Unable to determine impact automatically for `{title}`. "
                f"Please review the full content to decide whether changes are needed in your {category} integration.\n"
            )

        sections.append(
            f"### {i}. {title}\n"
            f"**{category} — {service}** | Impact: {u.get('impact_level') or 'Unknown'}\n\n"
            f"{body}"
        )

    header = (
        "## Impact Analysis & Upgrade Guide\n\n"
        "> *Rule-based analysis — content-specific per update. "
        "Configure an LLM provider in `.env` for AI-generated code-level guidance.*\n\n"
        "---\n\n"
    )
    footer = f"\n\n---\n\n{llm_note}" if llm_note.strip() else ""
    return header + "\n\n---\n\n".join(sections) + footer


def analyze_impact(updates: list[dict]) -> str:
    """
    Analyse a list of Oracle update records and return Markdown upgrade guidance.

    Tries the configured LLM first; falls back to rule-based analysis.
    """
    if not updates:
        return "No updates provided for analysis."

    if LLM_PROVIDER in ("openai", "anthropic", "bedrock", "ollama"):
        result = _llm_analyze(updates)
        if result:
            return result

    return _rule_based_analyze(updates)
