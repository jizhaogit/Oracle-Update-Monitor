"""
processor/coverage.py — Detect Oracle modules mentioned in instruction.ini
that are not currently covered by the crawl configuration.
"""

import configparser
import logging
import re
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

log = logging.getLogger(__name__)

# ── Comprehensive list of known Oracle HCM module names (normalised lowercase) ──
_KNOWN_HCM_MODULES = [
    "absence management", "absence",
    "benefits",
    "compensation", "total compensation",
    "common technologies", "common technologies and user experience",
    "hcm common",
    "human resources", "global human resources", "workforce",
    "hr helpdesk",
    "learning",
    "opportunity marketplace", "internal mobility",
    "payroll",
    "performance management", "performance",
    "recruiting", "talent acquisition",
    "skills", "dynamic skills",
    "succession", "succession planning",
    "talent management",
    "time and labor", "time & labor",
    "workforce management",
    "workforce modeling",
    "workforce rewards",
    "healthcare and insurance",
    "journeys",
    "connections",
    "sales force",
]

# Canonical display names for known modules (used in UI suggestions)
_MODULE_DISPLAY = {
    "absence management": "Absence Management",
    "absence": "Absence Management",
    "benefits": "Benefits",
    "compensation": "Compensation",
    "total compensation": "Compensation",
    "common technologies": "Common Technologies and User Experience",
    "common technologies and user experience": "Common Technologies and User Experience",
    "hcm common": "HCM Common",
    "human resources": "Human Resources",
    "global human resources": "Human Resources",
    "workforce": "Human Resources",
    "hr helpdesk": "HR Helpdesk",
    "learning": "Learning",
    "opportunity marketplace": "Opportunity Marketplace",
    "internal mobility": "Opportunity Marketplace",
    "payroll": "Payroll",
    "performance management": "Performance Management",
    "performance": "Performance Management",
    "recruiting": "Recruiting",
    "talent acquisition": "Recruiting",
    "skills": "Skills",
    "dynamic skills": "Skills",
    "succession": "Succession Planning",
    "succession planning": "Succession Planning",
    "talent management": "Talent Management",
    "time and labor": "Time and Labor",
    "time & labor": "Time and Labor",
    "workforce management": "Workforce Management",
    "workforce modeling": "Workforce Modeling",
    "workforce rewards": "Workforce Rewards",
    "healthcare and insurance": "Healthcare and Insurance",
    "journeys": "Journeys",
    "connections": "Connections",
}


def _parse_instruction_ini(ini_path) -> dict:
    """Read instruction.ini and return a dict of {section: {key: value}}."""
    cp = configparser.RawConfigParser()
    cp.read(str(ini_path), encoding="utf-8")
    result = {}
    for section in cp.sections():
        result[section.lower()] = dict(cp.items(section))
    return result


def extract_mentioned_modules(ini_path) -> list[str]:
    """
    Extract Oracle module names mentioned in instruction.ini.
    Scans [Scope] modules, [Project] description, and [Priority] sections.
    Returns a list of canonical display names (deduplicated).
    """
    try:
        data = _parse_instruction_ini(ini_path)
    except Exception as exc:
        log.warning("Could not parse instruction.ini: %s", exc)
        return []

    # Collect all text to scan
    texts = []
    scope = data.get("scope", {})
    if scope.get("modules"):
        texts.append(scope["modules"])
    project = data.get("project", {})
    if project.get("description"):
        texts.append(project["description"])
    priority = data.get("priority", {})
    for key in ("high", "medium", "low"):
        if priority.get(key):
            texts.append(priority[key])

    combined = " ".join(texts).lower()

    found = set()
    for kw in _KNOWN_HCM_MODULES:
        if kw in combined:
            canonical = _MODULE_DISPLAY.get(kw, kw.title())
            found.add(canonical)

    return sorted(found)


def get_crawled_keywords() -> list[str]:
    """Return the current HCM_MODULE_KEYWORDS list (normalised lowercase)."""
    from config import HCM_MODULE_KEYWORDS
    return [k.lower() for k in HCM_MODULE_KEYWORDS if k.strip()]


def find_uncovered_rule_based(ini_path) -> list[dict]:
    """
    Rule-based coverage check: compare instruction.ini mentions against
    the current HCM_MODULE_KEYWORDS crawl filter.
    Returns a list of dicts: {module, reason, type}
    """
    mentioned  = extract_mentioned_modules(ini_path)
    crawled_kw = get_crawled_keywords()

    uncovered = []
    for mod in mentioned:
        mod_lower = mod.lower()
        # Check if any current keyword is a substring of or matches this module
        covered = any(
            kw in mod_lower or mod_lower in kw
            for kw in crawled_kw
        )
        if not covered:
            uncovered.append({
                "module": mod,
                "type":   "HCM",
                "reason": f"Mentioned in your instructions but not in the current crawl filter",
                "source": "rule-based",
            })

    return uncovered


def find_uncovered_ai(ini_path) -> list[dict]:
    """
    AI-based coverage check: ask the LLM to identify gaps between
    instruction.ini and the current crawl configuration.
    Returns a list of dicts: {module, reason, type}
    Falls back to rule-based if LLM unavailable.
    """
    from config import LLM_PROVIDER, INSTRUCTION_FILE
    if LLM_PROVIDER not in ("openai", "anthropic", "bedrock", "ollama"):
        return find_uncovered_rule_based(ini_path)

    try:
        instruction_text = INSTRUCTION_FILE.read_text(encoding="utf-8")
    except Exception:
        return find_uncovered_rule_based(ini_path)

    from config import HCM_MODULE_KEYWORDS
    crawl_list = ", ".join(HCM_MODULE_KEYWORDS) or "(none configured)"

    try:
        from processor.classifier import _get_llm
        from langchain_core.messages import HumanMessage, SystemMessage
        import json as _json

        llm = _get_llm()
        if llm is None:
            return find_uncovered_rule_based(ini_path)

        system = (
            "You are an Oracle Cloud HCM/OIC expert. "
            "Given a project instruction file and a list of Oracle modules currently being crawled, "
            "identify Oracle HCM or OIC modules/topics explicitly mentioned in the instructions "
            "that are NOT covered by the current crawl list.\n\n"
            "Respond with a JSON array only (no markdown). Each item: "
            '{"module": "<Oracle module name>", "reason": "<one sentence why it should be added>", "type": "HCM"}'
            "\n\nIf everything is covered, return an empty array []."
        )
        user = (
            f"Current crawl keywords:\n{crawl_list}\n\n"
            f"Project instructions (instruction.ini):\n{instruction_text[:3000]}\n\n"
            "Return JSON array of uncovered modules."
        )

        resp = llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])
        raw = resp.content.strip()
        raw = re.sub(r"```json|```", "", raw).strip()
        items = _json.loads(raw)
        if isinstance(items, list):
            for item in items:
                item["source"] = "ai"
            return items
    except Exception as exc:
        log.warning("AI coverage check failed, falling back to rule-based: %s", exc)

    return find_uncovered_rule_based(ini_path)


def add_keywords_to_instruction(ini_path, new_keywords: list[str]) -> None:
    """
    Append confirmed module keywords to [Crawl] extra_keywords in instruction.ini.
    Deduplicates against existing entries.
    """
    cp = configparser.RawConfigParser()
    cp.read(str(ini_path), encoding="utf-8")

    if not cp.has_section("Crawl"):
        cp.add_section("Crawl")

    existing_raw = cp.get("Crawl", "extra_keywords", fallback="")
    existing = [k.strip() for k in existing_raw.split(",") if k.strip()]
    combined = list(dict.fromkeys(existing + new_keywords))  # dedup, preserve order

    cp.set("Crawl", "extra_keywords", ", ".join(combined))

    with open(str(ini_path), "w", encoding="utf-8") as f:
        cp.write(f)

    log.info("Added %d keyword(s) to instruction.ini [Crawl]: %s", len(new_keywords), new_keywords)
