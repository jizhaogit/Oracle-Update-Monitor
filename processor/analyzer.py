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
        flag_note = (u.get("flag_note") or "").strip()
        user_comment = (u.get("user_comment") or "").strip()
        extra = ""
        if flag_note:
            extra += f"Team Flag Note: {flag_note}\n"
        if user_comment:
            extra += f"Team Comment: {user_comment}\n"
        parts.append(
            f"[Update {i}]\n"
            f"Title: {u.get('title', 'N/A')}\n"
            f"Category: {u.get('category', '')} | Service: {u.get('service', '')}\n"
            f"Impact Level: {u.get('impact_level', 'Unknown')}\n"
            f"Summary: {u.get('summary') or '(none)'}\n"
            f"Tags: {', '.join(u.get('tags') or []) or '(none)'}\n"
            f"{extra}"
            f"Content:\n{content_excerpt}"
        )
    return "\n\n---\n\n".join(parts)


def _fmt_jira_context(jira_issues: list[dict]) -> str:
    """Render fetched Jira issues into a context block for the LLM prompt.
    Issues that could not be fetched are skipped (caller handles them separately)."""
    parts = []
    for issue in jira_issues:
        if issue.get("fetch_error"):
            continue   # exclude failed fetches from LLM context
        comments_block = ""
        for c in issue.get("comments") or []:
            comments_block += f"  [{c['author']}]: {c['body']}\n"
        parts.append(
            f"[Jira {issue['key']}] {issue['summary']}\n"
            f"URL: {issue['url']}\n"
            f"Type: {issue.get('issue_type','')} | "
            f"Status: {issue.get('status','')} | "
            f"Priority: {issue.get('priority','')}\n"
            f"Description:\n{issue.get('description') or '(no description)'}\n"
            + (f"Recent Comments:\n{comments_block}" if comments_block else "")
        )
    return "\n\n---\n\n".join(parts) if parts else ""


def _llm_analyze(updates: list[dict], jira_issues: list[dict] | None = None) -> str | None:
    """Call the configured LLM to produce structured upgrade guidance.
    Runs as a blocking call — callers must run this in a background thread if needed."""
    try:
        from processor.classifier import _get_llm
        from langchain_core.messages import HumanMessage, SystemMessage

        llm = _get_llm()
        if llm is None:
            return None

        # Only count tickets we actually have content for
        good_jira = [j for j in (jira_issues or []) if not j.get("fetch_error")]
        has_jira  = bool(good_jira)

        jira_instruction = ""
        if has_jira:
            jira_instruction = (
                "\n\nYou have also been provided with one or more **Jira tickets** that "
                "your team has linked to these Oracle updates. These tickets describe "
                "the team's internal concern, question, or investigation about the update.\n\n"
                "**IMPORTANT:** Tailor your analysis specifically to answer what the "
                "Jira ticket is asking. For each ticket:\n"
                "  - Directly address the concern or question raised in the ticket.\n"
                "  - Explain whether the Oracle update resolves, worsens, or is unrelated "
                "to the ticket's concern.\n"
                "  - If the ticket proposes a solution, evaluate whether that solution is "
                "still valid given the Oracle update.\n"
                "  - Reference the Jira ticket key (e.g. BGCO-1234) explicitly in your "
                "response where relevant.\n"
            )

        system = (
            "You are a senior Oracle Cloud architect advising development teams on how "
            "to react to Oracle OCI/OIC documentation updates."
            + jira_instruction +
            "\n\nFor each Oracle update provided, produce a structured analysis with "
            "ALL of the following numbered sections:\n\n"
            "1. **Impact Summary** — one sentence describing what changed in Oracle's "
            "documentation.\n"
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
            "4. **Affected Areas** — APIs / SDKs / Console / CLI / Terraform / HCM "
            "configuration / etc.\n"
            "5. **AI Suggestion** — based solely on Oracle's documentation, provide your "
            "independent recommendation for what the team should do. This section must:\n"
            "   - Stand on its own regardless of any internal tickets or team decisions.\n"
            "   - Suggest concrete next steps, best practices, or configuration guidance "
            "derived from the Oracle update content.\n"
            "   - Flag any risks or opportunities that the team may not have considered "
            "based on what Oracle's documentation says.\n"
            "   - Be written as if you are advising the team for the first time, with no "
            "knowledge of any internal discussions.\n"
            + ("6. **Jira Ticket Response** — for each linked Jira ticket, directly "
               "answer the concern raised and recommend a course of action. Reference "
               "section 5 (AI Suggestion) where relevant, and note whether the team's "
               "current approach aligns with Oracle's documented intent.\n"
               if has_jira else "") +
            "\nIf multiple updates are provided, analyse each one separately with a clear "
            "heading, then add a combined **Summary Table** at the end.\n\n"
            "Use Markdown formatting. Be specific and actionable. "
            "Do NOT skip section 5 — it must always be present.\n\n"
            "IMPORTANT — output the very first line of your response as exactly one of:\n"
            "INTEGRATION_IMPACT: YES\n"
            "INTEGRATION_IMPACT: NO\n"
            "Choose YES if the update may require reviewing or updating Oracle Integration "
            "Cloud (OIC) connections, REST/SOAP adapters, API endpoint calls, data flows, "
            "triggers, scheduled orchestrations, or integration payloads/schemas. "
            "Choose NO if the change is unrelated to OIC integrations (e.g. a pure HCM UI "
            "change, documentation clarification, OCI infrastructure, or new opt-in feature "
            "that does not alter existing behaviour). "
            "Output ONLY that line first — no blank line before the rest of the content."
        )

        updates_block = _fmt_updates(updates)
        jira_block = (
            f"\n\n---\n\n## Linked Jira Tickets\n\n{_fmt_jira_context(good_jira)}"
            if has_jira else ""
        )

        user = (
            "Please analyse the following Oracle Cloud update(s) and produce upgrade "
            f"guidance my team can act on today:\n\n{updates_block}{jira_block}"
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


# Keywords that indicate the change may affect OIC integrations
_INTEGRATION_KEYWORDS = [
    "rest api", "rest endpoint", "soap", "wsdl", "adapter", "connector",
    "integration", "orchestration", "trigger", "webhook", "payload",
    "schema change", "api version", "endpoint url", "oauth", "access token",
    "authentication change", "api deprecat", "endpoint deprecat",
    "api removed", "api changed", "response format", "request format",
    "field removed", "field renamed", "field added to response",
    "breaking change", "migration required",
]


def _is_integration_related(updates: list[dict]) -> bool:
    """Return True if any of the updates has content suggesting OIC integration impact."""
    blob = " ".join(
        f"{u.get('title','')} {u.get('summary','')} {u.get('content','')}"
        for u in updates
    ).lower()
    return any(kw in blob for kw in _INTEGRATION_KEYWORDS)


def _rule_based_analyze(updates: list[dict], jira_issues: list[dict] | None = None) -> str:
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
            action_body = (
                f"**Action Required: Yes**\n\n"
                f"{signal_line}"
                f"{tag_line}"
                f"{excerpt_block}\n"
                f"{link_line}"
                f"**Upgrade Steps:**\n\n"
                f"1. Review the full update at the reference link above.\n"
                f"2. Search your codebase for references to **{service}** "
                f"{'APIs, SDK calls, or endpoints' if 'api' in blob or 'endpoint' in blob or 'sdk' in blob else 'configuration or integration points'} "
                f"related to `{title}`.\n"
                f"3. Test your {category} integration in a non-production environment.\n"
                f"4. Apply any schema, endpoint, or configuration changes described in the update.\n"
                f"5. {'Deploy before any stated deadline.' if any(w in blob for w in ['deadline', 'by ', 'before ', 'migrate by']) else 'Monitor for issues after deployment.'}\n"
            )
            ai_suggestion = (
                f"**AI Suggestion:**\n\n"
                f"Based on Oracle's documentation, this change carries a high impact signal "
                f"(`{'`, `'.join(action_hits[:3]) if action_hits else impact}`). "
                f"Prioritise reviewing this update against your current {service} configuration. "
                f"Engage your {category} team to assess whether any live integrations, "
                f"scheduled jobs, or API consumers depend on the affected behaviour. "
                f"Consider raising an internal change request if modifications are needed.\n"
            )

        elif info_hits or impact in ("low", "medium"):
            action_body = (
                f"**No action needed.**\n\n"
                f"{tag_line}"
                f"{excerpt_block}\n"
                f"{link_line}"
                f"This `{service}` update is backward-compatible "
                f"({'a new feature' if any(w in blob for w in ['new feature', 'new service', 'added']) else 'an enhancement or informational notice'}). "
                f"Existing {category} integrations should continue working without modification.\n\n"
                f"You may optionally explore the new capability at your own pace.\n"
            )
            ai_suggestion = (
                f"**AI Suggestion:**\n\n"
                f"Oracle has introduced a new capability in `{service}`. "
                f"While no immediate action is required, consider the following:\n\n"
                f"- Review the feature at the reference link to understand how it may benefit "
                f"your current {category} workflows.\n"
                f"- If this is a UI or Redwood update, assess whether end-user training or "
                f"documentation updates are appropriate.\n"
                f"- If your team manages related configurations, confirm the defaults are "
                f"acceptable or adjust them proactively.\n"
            )

        else:
            action_body = (
                f"**Review Required**\n\n"
                f"{tag_line}"
                f"{excerpt_block}\n"
                f"{link_line}"
                f"Unable to determine impact automatically for `{title}`. "
                f"Please review the full content to decide whether changes are needed "
                f"in your {category} integration.\n"
            )
            ai_suggestion = (
                f"**AI Suggestion:**\n\n"
                f"This update could not be classified automatically. "
                f"Assign a team member to read the full Oracle documentation at the "
                f"reference link and determine whether it affects any active {service} "
                f"integrations, scheduled processes, or user-facing features. "
                f"Update the impact level in the monitor once reviewed.\n"
            )

        sections.append(
            f"### {i}. {title}\n"
            f"**{category} — {service}** | Impact: {u.get('impact_level') or 'Unknown'}\n\n"
            f"{action_body}\n"
            f"---\n\n"
            f"{ai_suggestion}"
        )

    header = (
        "## Impact Analysis & Upgrade Guide\n\n"
        "> *Rule-based analysis — content-specific per update. "
        "Configure an LLM provider in `.env` for AI-generated, code-level guidance "
        "with richer AI Suggestions and Jira Ticket Responses.*\n\n"
        "---\n\n"
    )
    jira_section = ""
    if jira_issues:
        good   = [j for j in jira_issues if not j.get("fetch_error")]
        failed = [j for j in jira_issues if j.get("fetch_error")]
        jira_lines = []
        for issue in good:
            status = f" [{issue.get('status')}]" if issue.get("status") else ""
            jira_lines.append(
                f"- **[{issue['key']}]({issue['url']})**{status}: "
                f"{issue.get('summary') or '(no summary)'}"
            )
            if issue.get("description"):
                jira_lines.append(
                    f"  > {issue['description'][:300].replace(chr(10), ' ')}"
                )
        for issue in failed:
            jira_lines.append(
                f"- ⚠ **[{issue['key']}]({issue['url']})** — "
                f"could not be fetched: `{issue['fetch_error']}`"
            )
        note = (
            "> *Full ticket content was used to tailor the analysis above.*"
            if good else
            "> ⚠ *Jira ticket(s) could not be fetched — see errors below. "
            "Ensure you are on VPN, have Jira read access, and "
            "`requests-negotiate-sspi` is installed.*"
        )
        jira_section = (
            "\n\n---\n\n## 🎫 Linked Jira Tickets\n\n"
            + note + "\n\n"
            + "\n".join(jira_lines)
        )

    footer = f"\n\n---\n\n{llm_note}" if llm_note.strip() else ""
    integration_marker = (
        "INTEGRATION_IMPACT: YES\n" if _is_integration_related(updates)
        else "INTEGRATION_IMPACT: NO\n"
    )
    return integration_marker + header + "\n\n---\n\n".join(sections) + jira_section + footer


def analyze_impact(updates: list[dict], jira_issues: list[dict] | None = None) -> str:
    """
    Analyse a list of Oracle update records and return Markdown upgrade guidance.

    Tries the configured LLM first; falls back to rule-based analysis.
    Jira issues (pre-fetched by the caller) are woven into the prompt / output.
    """
    if not updates:
        return "No updates provided for analysis."

    if LLM_PROVIDER in ("openai", "anthropic", "bedrock", "ollama"):
        result = _llm_analyze(updates, jira_issues=jira_issues)
        if result:
            return result

    return _rule_based_analyze(updates, jira_issues=jira_issues)
