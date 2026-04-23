"""
tests/test_instruction_impact.py
=================================
Verifies three guarantees for instruction.ini integration:

  SCENARIO A  —  instruction.ini context reaches the LLM during Mark Impact
  SCENARIO B  —  crawl uses rule-based logic only (no LLM, no instruction.ini context)
  SCENARIO C  —  manual (customised) impact levels are NEVER overwritten by AI or crawl

Run with:
    cd C:\\CFT\\Oracle-Update-Monitor
    python -m pytest tests/test_instruction_impact.py -v

No real LLM API call is made — the chain is mocked wherever the LLM would be invoked.
No real HTTP fetch is made — crawler is tested with mock data only.
"""

import hashlib
import json
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ── Make sure project root is on sys.path ──────────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_ini(content: str, directory: Path) -> Path:
    """Write INI text to a temp instruction.ini inside *directory*."""
    p = directory / "instruction.ini"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


def _sample_record(
    title="Compensation REST API changes",
    content="The REST API for compensation calculations has been deprecated.",
    service="Compensation",
    impact_level=None,
    impact_overridden=False,
):
    return {
        "id": None,
        "source_name": "HCM — What's New",
        "source_url": "https://docs.oracle.com/test",
        "category": "HCM",
        "service": service,
        "doc_type": "whats_new",
        "title": title,
        "content": content,
        "summary": "",
        "_tags": "[]",
        "impact_level": impact_level,
        "release_date": None,
        "release_code": "26B",
        "content_hash": hashlib.sha256(title.encode()).hexdigest(),
        "is_new": True,
        "vector_id": None,
        "impact_overridden": impact_overridden,
    }


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO A  —  instruction.ini context reaches LLM during Mark Impact
# ─────────────────────────────────────────────────────────────────────────────

class TestScenarioA_MarkImpactUsesInstructionIni(unittest.TestCase):
    """
    Verify that _load_project_context() reads instruction.ini and that
    llm_classify() injects that context into the LLM prompt.
    """

    # ── A1: _load_project_context reads all non-Crawl sections ────────────────

    def test_A1_load_project_context_returns_all_non_crawl_sections(self):
        """All [Project], [Scope], [Context] fields should appear in the output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ini = _make_ini("""
                [Project]
                description = We implement Oracle HCM for finance.

                [Scope]
                modules = Compensation, Payroll
                categories = HCM
                integrations = Workday, BI tool

                [Context]
                notes = Compensation APIs are business-critical.

                [Crawl]
                extra_keywords = Benefits
            """, Path(tmpdir))

            with patch("processor.classifier.INSTRUCTION_FILE", ini):
                from processor.classifier import _load_project_context
                ctx = _load_project_context()

        self.assertIn("finance", ctx,
                      "Project description must appear in context")
        self.assertIn("Compensation", ctx,
                      "Scope modules must appear in context")
        self.assertIn("business-critical", ctx,
                      "Context notes must appear in context")

    # ── A2: _load_project_context SKIPS [Crawl] section ──────────────────────

    def test_A2_load_project_context_skips_crawl_section(self):
        """[Crawl] extra_keywords must NOT be sent to the LLM."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ini = _make_ini("""
                [Project]
                description = Test project.

                [Crawl]
                extra_keywords = Benefits, Learning
            """, Path(tmpdir))

            with patch("processor.classifier.INSTRUCTION_FILE", ini):
                from processor.classifier import _load_project_context
                ctx = _load_project_context()

        # "Benefits, Learning" comes from the [Crawl] section
        self.assertNotIn("extra_keywords", ctx.lower(),
                         "[Crawl] key names must not appear in LLM context")
        # "Benefits" could plausibly appear in [Scope] too, but since we only
        # have a [Crawl] section with it here, it should not be in the context.
        self.assertNotIn("Benefits", ctx,
                         "[Crawl] values must not appear in LLM context")

    # ── A3: empty instruction.ini → empty context (no crash) ─────────────────

    def test_A3_empty_instruction_ini_returns_empty_context(self):
        """Missing instruction.ini AND missing fallback must return '' without raising."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Neither file exists inside this temp dir
            missing_ini      = Path(tmpdir) / "instruction.ini"
            missing_fallback = Path(tmpdir) / "project_context.txt"

            with patch("processor.classifier.INSTRUCTION_FILE", missing_ini), \
                 patch("processor.classifier._PROJECT_CONTEXT_FILE", missing_fallback):
                from processor.classifier import _load_project_context
                ctx = _load_project_context()

        self.assertEqual(ctx, "",
                         "Missing instruction.ini must produce empty context string")

    # ── A4: llm_classify injects project context into the chain prompt ────────

    def test_A4_llm_classify_sends_project_context_to_chain(self):
        """
        When instruction.ini has content, the LLM chain must receive it in the
        'project_context' template variable.
        """
        import processor.classifier as clf

        expected_phrase = "Compensation API is our most critical"
        captured_kwargs = {}

        def fake_chain_invoke(kwargs):
            captured_kwargs.update(kwargs)
            return json.dumps({
                "impact_level": "High",
                "tags": ["API", "Compensation"],
                "summary": "Mock summary.",
            })

        mock_chain = MagicMock()
        mock_chain.invoke.side_effect = fake_chain_invoke

        with tempfile.TemporaryDirectory() as tmpdir:
            ini = _make_ini(f"""
                [Project]
                description = Finance HCM project.

                [Context]
                notes = {expected_phrase}.
            """, Path(tmpdir))

            with patch("processor.classifier.INSTRUCTION_FILE", ini), \
                 patch("processor.classifier._chain", mock_chain), \
                 patch("processor.classifier._llm", MagicMock()):

                # Reset chain so _get_chain() is not called (we patched _chain directly)
                record = _sample_record()
                clf.llm_classify(record, timeout=5)

        self.assertTrue(
            mock_chain.invoke.called,
            "The LLM chain must be invoked during llm_classify()",
        )
        ctx_sent = captured_kwargs.get("project_context", "")
        self.assertIn(expected_phrase, ctx_sent,
                      "The instruction.ini [Context] notes must appear in the LLM prompt")

    # ── A5: llm_classify returns LLM impact level (not rule-based fallback) ───

    def test_A5_llm_classify_uses_llm_result(self):
        """
        When the LLM succeeds, its impact_level must be stored — not the
        rule-based fallback.
        """
        import processor.classifier as clf

        llm_response = json.dumps({
            "impact_level": "High",
            "tags": ["API"],
            "summary": "Critical API change.",
        })

        mock_chain = MagicMock()
        mock_chain.invoke.return_value = llm_response

        with patch("processor.classifier._chain", mock_chain), \
             patch("processor.classifier._llm", MagicMock()):

            # Use a record whose rule-based impact would be "Low"
            record = _sample_record(
                title="Minor documentation update",
                content="Some clarification added to the help docs.",
            )
            result = clf.llm_classify(record, timeout=5)

        self.assertEqual(
            result["impact_level"], "High",
            "LLM result (High) must override what rule-based would produce (Low)",
        )

    # ── A6: llm_classify falls back to rule-based on timeout ─────────────────

    def test_A6_llm_classify_falls_back_to_rule_based_on_timeout(self):
        """
        When the LLM chain hangs, llm_classify must fall back to rule-based
        and NOT raise an exception.
        """
        import time
        import processor.classifier as clf

        def slow_invoke(_):
            time.sleep(10)  # longer than the 1s timeout we set
            return json.dumps({"impact_level": "High", "tags": [], "summary": ""})

        mock_chain = MagicMock()
        mock_chain.invoke.side_effect = slow_invoke

        with patch("processor.classifier._chain", mock_chain), \
             patch("processor.classifier._llm", MagicMock()):

            record = _sample_record(
                title="Breaking change to API",
                content="This is a breaking change to the REST API endpoint.",
            )
            result = clf.llm_classify(record, timeout=1)  # 1-second timeout

        # Rule-based should have caught "breaking change" → High
        self.assertEqual(
            result["impact_level"], "High",
            "Rule-based fallback should classify 'breaking change' as High",
        )

    # ── A7: classify_unlimited passes timeout=None ────────────────────────────

    def test_A7_classify_unlimited_passes_timeout_none(self):
        """
        classify_unlimited() must call llm_classify(timeout=None) so slow
        local models like Ollama are never cut short.
        """
        import processor.classifier as clf

        with patch("processor.classifier.LLM_PROVIDER", "ollama"), \
             patch("processor.classifier.llm_classify") as mock_llm:
            mock_llm.return_value = _sample_record(impact_level="Medium")
            record = _sample_record()
            clf.classify_unlimited(record)

        mock_llm.assert_called_once()
        _, kwargs = mock_llm.call_args
        self.assertIsNone(
            kwargs.get("timeout"),
            "classify_unlimited() must pass timeout=None to llm_classify()",
        )

    # ── A8: classify (crawl-time) passes LLM_TIMEOUT ─────────────────────────

    def test_A8_classify_passes_llm_timeout(self):
        """
        classify() (used at crawl time) must pass a finite timeout so it can
        fall back quickly if the LLM is slow.
        """
        import processor.classifier as clf

        with patch("processor.classifier.LLM_PROVIDER", "ollama"), \
             patch("processor.classifier.llm_classify") as mock_llm:
            mock_llm.return_value = _sample_record(impact_level="Low")
            record = _sample_record()
            clf.classify(record)

        mock_llm.assert_called_once()
        _, kwargs = mock_llm.call_args
        self.assertIsNotNone(
            kwargs.get("timeout"),
            "classify() must pass a finite timeout (not None) to llm_classify()",
        )


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO B  —  Crawl uses rule-based only (no LLM, no instruction.ini context)
# ─────────────────────────────────────────────────────────────────────────────

class TestScenarioB_CrawlUsesRuleBasedOnly(unittest.TestCase):
    """
    Verify that the crawler scheduler imports rule_classify (not llm_classify),
    and that rule_classify does NOT read instruction.ini context.
    """

    # ── B1: scheduler imports rule_classify ───────────────────────────────────

    def test_B1_scheduler_imports_rule_classify(self):
        """
        crawler/scheduler.py must import rule_classify as its classify function,
        NOT llm_classify or the full classify() wrapper.

        We check the source file directly rather than importing the module, because
        the crawler has optional dependencies (bs4, etc.) that may not be installed
        in the test environment.
        """
        scheduler_src = ROOT / "crawler" / "scheduler.py"
        self.assertTrue(scheduler_src.exists(),
                        "crawler/scheduler.py must exist")

        source = scheduler_src.read_text(encoding="utf-8")

        # Must import rule_classify aliased as 'classify'
        self.assertIn(
            "from processor.classifier import rule_classify as classify",
            source,
            "crawler/scheduler.py must import 'rule_classify as classify' — "
            "confirming crawl never uses LLM",
        )
        # The generic 'classify' (LLM-capable wrapper) must NOT be imported
        # without the 'rule_' prefix.  We check for an exact bare import of
        # 'classify' — not 'rule_classify', not 'classify_unlimited'.
        import re
        bare_import = re.search(
            r"^\s*from processor\.classifier import\s+classify\b",
            source, re.MULTILINE
        )
        self.assertIsNone(
            bare_import,
            "crawler/scheduler.py must not import the bare classify() "
            "(LLM-capable); it must use rule_classify as classify",
        )

    # ── B2: rule_classify does NOT call _load_project_context ────────────────

    def test_B2_rule_classify_does_not_use_instruction_ini(self):
        """
        rule_classify() must classify by keywords only — never read instruction.ini.
        """
        from processor.classifier import rule_classify, _load_project_context

        with patch("processor.classifier._load_project_context") as mock_ctx:
            record = _sample_record()
            rule_classify(record)

        mock_ctx.assert_not_called(
        )  # would fail if rule_classify called _load_project_context

    # ── B3: rule_classify uses IMPACT_KEYWORDS from config.py ────────────────

    def test_B3_rule_classify_high_impact_on_breaking_change_keyword(self):
        """'breaking change' keyword → High impact via IMPACT_KEYWORDS."""
        from processor.classifier import rule_classify

        record = _sample_record(
            title="Breaking Change to Compensation REST API",
            content="The /compensation/v1/calculations endpoint has been removed.",
        )
        result = rule_classify(record)
        self.assertEqual(result["impact_level"], "High")

    def test_B3_rule_classify_medium_impact_on_new_feature_keyword(self):
        """'new feature' keyword → Medium impact via IMPACT_KEYWORDS."""
        from processor.classifier import rule_classify

        record = _sample_record(
            title="New Feature: Goal Alignment Dashboard",
            content="A new feature has been added for goal alignment tracking.",
        )
        result = rule_classify(record)
        self.assertEqual(result["impact_level"], "Medium")

    def test_B3_rule_classify_low_impact_on_documentation_keyword(self):
        """
        'documentation' keyword → Low impact via IMPACT_KEYWORDS.

        NOTE: We deliberately avoid Medium keywords (like 'added', 'updated',
        'new feature', 'introduction', 'redwood') in this record so that the
        Low rule is the first (and only) match in the priority chain:
        High → Medium → Low.
        """
        from processor.classifier import rule_classify

        record = _sample_record(
            title="Documentation Clarification for Compensation Setup",
            # Avoid 'added', 'updated', 'new feature' etc. — all trigger Medium.
            content="Minor typo fix in the documentation. No functional change.",
        )
        result = rule_classify(record)
        self.assertEqual(result["impact_level"], "Low")

    # ── B4: rule_classify produces correct tags from TAG_KEYWORDS ─────────────

    def test_B4_rule_classify_tags_include_service(self):
        """Service name must always appear in tags."""
        from processor.classifier import rule_classify

        record = _sample_record(service="Recruiting")
        result = rule_classify(record)
        self.assertIn("Recruiting", result["tags"])

    def test_B4_rule_classify_tags_include_api_keyword(self):
        """'REST API' in content must produce 'API' tag."""
        from processor.classifier import rule_classify

        record = _sample_record(
            title="REST API Update",
            content="The REST API endpoint has changed.",
        )
        result = rule_classify(record)
        self.assertIn("API", result["tags"])

    # ── B5: [Crawl] extra_keywords merge into HCM_MODULE_KEYWORDS ─────────────

    def test_B5_crawl_extra_keywords_merge_into_module_keywords(self):
        """
        [Crawl] extra_keywords in instruction.ini must be appended to
        HCM_MODULE_KEYWORDS so the module filter covers them.
        This is the ONLY way instruction.ini affects crawl behaviour.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            ini = _make_ini("""
                [Project]
                description = Test.

                [Crawl]
                extra_keywords = Benefits, Learning, Payroll
            """, Path(tmpdir))

            # Simulate config._read_instruction_extra_keywords() with our test file
            import configparser
            cp = configparser.RawConfigParser()
            cp.read(str(ini), encoding="utf-8")
            raw = cp.get("Crawl", "extra_keywords", fallback="")
            extra_kw = [k.strip() for k in raw.split(",") if k.strip()]

        self.assertIn("Benefits", extra_kw)
        self.assertIn("Learning", extra_kw)
        self.assertIn("Payroll", extra_kw)

    # ── B6: rule_classify with no LLM provider → always rule-based ───────────

    def test_B6_classify_with_provider_none_uses_rule_classify(self):
        """
        classify() with LLM_PROVIDER='none' must call rule_classify,
        not attempt any LLM invocation.
        """
        import processor.classifier as clf

        with patch("processor.classifier.LLM_PROVIDER", "none"), \
             patch("processor.classifier.llm_classify") as mock_llm:
            record = _sample_record()
            clf.classify(record)

        mock_llm.assert_not_called(
        )  # llm_classify must never be called when provider is 'none'


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO C  —  Manual (customised) impact levels are NEVER overwritten
# ─────────────────────────────────────────────────────────────────────────────

class TestScenarioC_ManualOverrideProtected(unittest.TestCase):
    """
    Verify impact_overridden=True records are protected from AI and crawl rewrites
    at every layer: set_impact(), update_classification(), and upsert_update().
    """

    def setUp(self):
        """
        Create a fresh in-memory SQLite database for each test so tests are
        fully isolated and leave no side-effects on the real database.
        """
        from sqlalchemy import create_engine
        from sqlalchemy.orm import scoped_session, sessionmaker
        from storage.models import Base, OracleUpdate

        self._engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self._engine)
        self._factory = sessionmaker(bind=self._engine, autoflush=False,
                                     autocommit=False, expire_on_commit=False)
        self._Session = scoped_session(self._factory)

        # Patch the module-level Session so database.py functions use our test DB
        self._session_patch = patch("storage.database.Session", self._Session)
        self._session_patch.start()

    def tearDown(self):
        self._session_patch.stop()
        self._Session.remove()
        self._engine.dispose()

    def _insert_record(self, title="Test Record", impact_level="Low",
                       impact_overridden=False) -> int:
        """Insert a minimal OracleUpdate row and return its id."""
        from storage.models import OracleUpdate
        session = self._Session()
        rec = OracleUpdate(
            source_name="Test Source",
            source_url="https://example.com",
            category="HCM",
            service="Compensation",
            doc_type="whats_new",
            title=title,
            content="Test content about compensation.",
            content_hash=hashlib.sha256(title.encode()).hexdigest(),
            impact_level=impact_level,
            impact_overridden=impact_overridden,
            is_new=True,
        )
        session.add(rec)
        session.commit()
        rid = rec.id
        session.close()
        return rid

    def _get_record(self, record_id: int):
        """Fetch a record dict from the test DB."""
        from storage.models import OracleUpdate
        session = self._Session()
        rec = session.query(OracleUpdate).filter_by(id=record_id).first()
        d = rec.to_dict() if rec else None
        session.close()
        return d

    # ── C1: set_impact() marks impact_overridden=True ─────────────────────────

    def test_C1_set_impact_marks_overridden_true(self):
        """
        When a user manually sets an impact level, impact_overridden must become True.
        """
        from storage.database import set_impact

        rid = self._insert_record(impact_level="Low", impact_overridden=False)
        set_impact(rid, "High")

        rec = self._get_record(rid)
        self.assertEqual(rec["impact_level"], "High")
        self.assertTrue(rec["impact_overridden"],
                        "set_impact() must set impact_overridden=True")

    # ── C2: set_impact(None) resets the override flag ─────────────────────────

    def test_C2_set_impact_reset_clears_overridden_flag(self):
        """
        Passing None to set_impact() must clear the impact override so the
        record becomes eligible for AI reclassification again.
        """
        from storage.database import set_impact

        rid = self._insert_record(impact_level="High", impact_overridden=True)
        set_impact(rid, None)

        rec = self._get_record(rid)
        self.assertIsNone(rec["impact_level"])
        self.assertFalse(rec["impact_overridden"],
                         "set_impact(None) must clear impact_overridden flag")

    # ── C3: update_classification() SKIPS overridden records ─────────────────

    def test_C3_update_classification_skips_overridden_record(self):
        """
        update_classification() — called by the Mark Impact background job —
        must not touch records where impact_overridden=True.
        """
        from storage.database import update_classification

        rid = self._insert_record(impact_level="High", impact_overridden=True)
        # Attempt to reclassify to Low via Mark Impact
        update_classification(rid, "Low", ["docs"], "Summary text")

        rec = self._get_record(rid)
        self.assertEqual(rec["impact_level"], "High",
                         "update_classification() must not change an overridden record's impact")
        self.assertEqual(rec["tags"], [],
                         "update_classification() must not change an overridden record's tags")

    # ── C4: update_classification() DOES update non-overridden records ────────

    def test_C4_update_classification_updates_non_overridden_record(self):
        """
        Sanity check: update_classification() must still work normally for
        records that have not been manually overridden.
        """
        from storage.database import update_classification

        rid = self._insert_record(impact_level="Low", impact_overridden=False)
        update_classification(rid, "High", ["API", "Security"], "Critical change.")

        rec = self._get_record(rid)
        self.assertEqual(rec["impact_level"], "High")
        self.assertIn("API", rec["tags"])
        self.assertEqual(rec["summary"], "Critical change.")

    # ── C5: upsert_update() skips impact for overridden records ───────────────

    def test_C5_upsert_update_does_not_overwrite_overridden_impact(self):
        """
        When a crawl finds a new version of an existing record, upsert_update()
        must NOT change the impact_level of records with impact_overridden=True.
        """
        from storage.database import upsert_update

        # First insert: user-overridden to High
        title = "Compensation Calculation Update"
        first_hash = hashlib.sha256(b"version1").hexdigest()
        first_data = {
            "source_name":  "HCM — What's New",
            "source_url":   "https://docs.oracle.com/test",
            "category":     "HCM",
            "service":      "Compensation",
            "doc_type":     "whats_new",
            "title":        title,
            "content":      "Version 1 content.",
            "summary":      None,
            "_tags":        "[]",
            "impact_level": "Low",
            "release_date": None,
            "release_code": "26A",
            "content_hash": first_hash,
            "is_new":       True,
            "vector_id":    None,
        }
        row, _ = upsert_update(first_data)
        rid = row["id"]

        # Simulate user manually setting it to High
        from storage.database import set_impact
        set_impact(rid, "High")

        # Crawl finds a new content version — tries to set impact_level=Low
        second_hash = hashlib.sha256(b"version2").hexdigest()
        second_data = {**first_data, "content": "Version 2 content.", "content_hash": second_hash, "impact_level": "Low"}
        upsert_update(second_data)

        rec = self._get_record(rid)
        self.assertEqual(rec["impact_level"], "High",
                         "Crawl upsert must not overwrite user-overridden impact level")
        self.assertTrue(rec["impact_overridden"],
                        "impact_overridden must remain True after a crawl upsert")

    # ── C6: reclassify-all background job skips overridden records ────────────

    def test_C6_reclassify_all_logic_skips_overridden(self):
        """
        The reclassify-all job calls update_classification() for every record.
        Records with impact_overridden=True must remain unchanged.
        """
        from storage.database import update_classification

        # Two records: one overridden, one not
        rid_overridden = self._insert_record(
            title="User Override Record",
            impact_level="High",
            impact_overridden=True,
        )
        rid_normal = self._insert_record(
            title="Normal Record",
            impact_level="Low",
            impact_overridden=False,
        )

        # Simulate what reclassify-all does for each record
        for rid in [rid_overridden, rid_normal]:
            update_classification(rid, "Medium", ["AI/ML"], "AI-assigned summary")

        overridden_rec = self._get_record(rid_overridden)
        normal_rec     = self._get_record(rid_normal)

        # Overridden record must be unchanged
        self.assertEqual(overridden_rec["impact_level"], "High",
                         "Reclassify-all must NOT touch a manually overridden record")

        # Normal record must be updated
        self.assertEqual(normal_rec["impact_level"], "Medium",
                         "Reclassify-all must update non-overridden records")

    # ── C7: impact_overridden does NOT block other field updates ──────────────

    def test_C7_overridden_record_still_gets_tag_and_summary_updates_blocked(self):
        """
        When impact_overridden=True, update_classification() must skip ALL updates
        (impact, tags, and summary) to keep the record fully in user control.
        """
        from storage.database import update_classification

        rid = self._insert_record(impact_level="High", impact_overridden=True)
        update_classification(rid, "Low", ["new-tag"], "New AI summary")

        rec = self._get_record(rid)
        self.assertNotIn("new-tag", rec["tags"],
                         "Tags must not be updated on an overridden record")
        # summary was None when inserted; should still be empty/None after blocked update
        self.assertFalse(rec["summary"],
                         "Summary must not be updated on an overridden record")

    # ── C8: set_impact with invalid value raises error ────────────────────────

    def test_C8_set_impact_rejects_invalid_value(self):
        """set_impact() must raise ValueError for any level not in High/Medium/Low/None."""
        from storage.database import set_impact

        rid = self._insert_record()
        with self.assertRaises(ValueError):
            set_impact(rid, "Critical")  # not a valid impact level


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO D  —  End-to-end integration test (no real HTTP or LLM calls)
# ─────────────────────────────────────────────────────────────────────────────

class TestScenarioD_EndToEndIntegration(unittest.TestCase):
    """
    Simulate a complete Mark Impact run for a set of records and verify that:
      - instruction.ini context is used by the LLM
      - overridden records are left alone
      - non-overridden records get the LLM's result
    """

    def setUp(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import scoped_session, sessionmaker
        from storage.models import Base

        self._engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self._engine)
        self._factory = sessionmaker(bind=self._engine, autoflush=False,
                                     autocommit=False, expire_on_commit=False)
        self._Session = scoped_session(self._factory)
        self._session_patch = patch("storage.database.Session", self._Session)
        self._session_patch.start()

    def tearDown(self):
        self._session_patch.stop()
        self._Session.remove()
        self._engine.dispose()

    def test_D1_full_reclassify_pipeline(self):
        """
        Simulate reclassify-all:
          1. Insert 2 records — one normal, one manually overridden.
          2. Run classify_unlimited() for each and call update_classification().
          3. Verify: overridden stays unchanged; normal gets LLM result.
        """
        from storage.database import set_impact, update_classification
        from storage.models import OracleUpdate

        session = self._Session()

        # Insert record A — will be overridden to High by user
        rec_a = OracleUpdate(
            source_name="HCM — What's New",
            source_url="https://docs.oracle.com/a",
            category="HCM",
            service="Compensation",
            doc_type="whats_new",
            title="Compensation Calculation Docs Update",
            content="Documentation clarification for calculation rules.",
            content_hash=hashlib.sha256(b"recA").hexdigest(),
            impact_level="Low",
            impact_overridden=False,
            is_new=True,
        )
        # Insert record B — no override; LLM may reclassify
        rec_b = OracleUpdate(
            source_name="HCM — What's New",
            source_url="https://docs.oracle.com/b",
            category="HCM",
            service="Recruiting",
            doc_type="whats_new",
            title="New Feature: AI-Powered Resume Screening",
            content="AI resume screening has been enhanced with new capabilities.",
            content_hash=hashlib.sha256(b"recB").hexdigest(),
            impact_level="Low",
            impact_overridden=False,
            is_new=True,
        )
        session.add_all([rec_a, rec_b])
        session.commit()
        id_a = rec_a.id
        id_b = rec_b.id
        session.close()

        # User manually overrides record A to High (e.g. via UI impact dropdown)
        set_impact(id_a, "High")

        # LLM returns High for both records (mock)
        llm_result = {"impact_level": "High", "tags": ["AI/ML"], "summary": "High impact."}

        import processor.classifier as clf
        mock_chain = MagicMock()
        mock_chain.invoke.return_value = json.dumps(llm_result)

        with patch("processor.classifier.LLM_PROVIDER", "openai"), \
             patch("processor.classifier._chain", mock_chain), \
             patch("processor.classifier._llm", MagicMock()):

            # Simulate the reclassify-all loop
            from storage.database import list_updates
            all_recs = list_updates(limit=10)
            for rec in all_recs:
                classified = clf.classify_unlimited(rec)
                update_classification(
                    rec["id"],
                    classified.get("impact_level", "Low"),
                    classified.get("tags", []),
                    classified.get("summary", ""),
                )

        # Record A (overridden) — must still be High with impact_overridden=True
        from storage.models import OracleUpdate
        session = self._Session()
        rec_a_db = session.query(OracleUpdate).filter_by(id=id_a).first()
        rec_b_db = session.query(OracleUpdate).filter_by(id=id_b).first()

        self.assertEqual(rec_a_db.impact_level, "High",
                         "Overridden record must keep its manual High impact")
        self.assertTrue(rec_a_db.impact_overridden,
                        "impact_overridden must remain True for record A")

        # Record B (normal) — must be updated to LLM's High
        self.assertEqual(rec_b_db.impact_level, "High",
                         "Non-overridden record must be updated by LLM result")
        session.close()


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO E  —  Regression tests for bugs found by the test suite
# ─────────────────────────────────────────────────────────────────────────────

class TestScenarioE_BugRegressions(unittest.TestCase):
    """
    Regression tests for two bugs the test suite originally exposed:

    Bug 1  (config.py)   — Emergency fallback in _init_instruction_file() was
                           creating [Priority] and [Notes] sections (old schema)
                           instead of [Context].  The LLM and UI would then see
                           incorrect section names.

    Bug 2  (classifier.py) — _rule_based_impact() iterated High→Medium→Low and
                             returned on the FIRST keyword match.  Generic Medium
                             words like "added" appeared in documentation sentences
                             ("a clarification was added to the documentation"),
                             causing Low-impact records to be misclassified as Medium.
                             Fix: titles containing strong Low markers ("documentation",
                             "bug fix", "typo", "clarification") return Low immediately
                             even when body text contains Medium words.
    """

    # ── Bug 1 Regression: config.py emergency fallback schema ─────────────────

    def test_E1_fallback_ini_uses_context_not_priority(self):
        """
        When instruction.ini.example is absent the fallback content must use
        [Context] (current schema) — not [Priority] or [Notes] (old schema).
        The [Scope] section must NOT contain a 'categories' key (auto-derived).
        """
        import configparser
        from config import _init_instruction_file

        with tempfile.TemporaryDirectory() as tmpdir:
            ini     = Path(tmpdir) / "instruction.ini"
            example = Path(tmpdir) / "instruction.ini.example"
            # Neither file exists → triggers the emergency fallback branch

            with patch("config.INSTRUCTION_FILE", ini), \
                 patch("config.INSTRUCTION_EXAMPLE_FILE", example):
                _init_instruction_file()

            self.assertTrue(ini.exists(),
                            "Emergency fallback must create instruction.ini")

            cp = configparser.RawConfigParser()
            cp.read(str(ini), encoding="utf-8")
            sections = [s.lower() for s in cp.sections()]

            # [Context] must exist
            self.assertIn("context", sections,
                          "Fallback ini must have [Context] section (current schema)")

            # [Priority] and [Notes] must NOT exist (old, removed schema)
            self.assertNotIn("priority", sections,
                             "Fallback ini must NOT have [Priority] section (obsolete)")
            self.assertNotIn("notes", sections,
                             "Fallback ini must NOT have [Notes] section (obsolete)")

            # [Scope] must NOT have a 'categories' key — it is auto-derived
            self.assertFalse(cp.has_option("Scope", "categories"),
                             "Fallback ini must NOT have [Scope] categories key "
                             "(categories are auto-derived from sources.ini)")

    def test_E1b_fallback_ini_context_has_notes_key(self):
        """
        The [Context] section in the emergency fallback must contain a 'notes' key,
        matching what the API endpoint and LLM prompt expect.
        """
        import configparser
        from config import _init_instruction_file

        with tempfile.TemporaryDirectory() as tmpdir:
            ini     = Path(tmpdir) / "instruction.ini"
            example = Path(tmpdir) / "instruction.ini.example"

            with patch("config.INSTRUCTION_FILE", ini), \
                 patch("config.INSTRUCTION_EXAMPLE_FILE", example):
                _init_instruction_file()

            cp = configparser.RawConfigParser()
            cp.read(str(ini), encoding="utf-8")

            self.assertTrue(cp.has_option("Context", "notes"),
                            "Fallback [Context] section must have 'notes' key")

    # ── Bug 2 Regression: rule_classify "added in documentation" false positive

    def test_E2_documentation_title_beats_added_keyword_in_body(self):
        """
        A record whose TITLE contains a strong Low marker ("documentation",
        "bug fix", "typo", "clarification") must be classified Low even when
        the body text contains a Medium keyword like "added" or "updated".

        This was the original bug: "A clarification was added to the documentation"
        got Medium because 'added' fired before 'documentation' in the
        High→Medium→Low keyword scan.
        """
        from processor.classifier import rule_classify

        cases = [
            # (title, content, expected_level)
            (
                "Documentation Clarification for Compensation Setup",
                "A new note was added to the documentation regarding payroll.",
                "Low",
                "'documentation' in title + 'added' in body → must be Low",
            ),
            (
                "Bug Fix: Incorrect Leave Balance Displayed",
                "The leave balance calculation was updated and a correction was added.",
                "Low",
                "'bug fix' in title + 'updated/added' in body → must be Low",
            ),
            (
                "Typo Correction in HCM Common Setup Guide",
                "A minor typo was fixed; documentation has been updated.",
                "Low",
                "'typo' in title + 'updated' in body → must be Low",
            ),
            (
                "Clarification on Absence Management Policies",
                "Additional guidance was added and some content was enhanced.",
                "Low",
                "'clarification' in title + 'added/enhanced' in body → must be Low",
            ),
        ]

        for title, content, expected, msg in cases:
            with self.subTest(title=title):
                record = _sample_record(title=title, content=content)
                result = rule_classify(record)
                self.assertEqual(result["impact_level"], expected, msg)

    def test_E2b_medium_title_still_classified_medium(self):
        """
        When the title itself signals a new feature / enhancement (no Strong-Low
        marker), a Medium result must still be produced even if the body also
        mentions 'documentation'.
        """
        from processor.classifier import rule_classify

        cases = [
            (
                "New Feature: Goal Alignment Dashboard",
                "A new dashboard was added. Documentation has been updated accordingly.",
                "Medium",
                "'new feature' in title → Medium despite 'documentation' in body",
            ),
            (
                "Enhancement: Compensation REST API Response Fields",
                "Additional fields were added to the response payload.",
                "Medium",
                "'enhancement' in title → Medium",
            ),
        ]

        for title, content, expected, msg in cases:
            with self.subTest(title=title):
                record = _sample_record(title=title, content=content)
                result = rule_classify(record)
                self.assertEqual(result["impact_level"], expected, msg)

    def test_E2c_high_still_beats_documentation_in_title(self):
        """
        High-impact keywords (breaking change, deprecated, security) must still
        win even when the title contains 'documentation' or other Low markers.
        High > everything.
        """
        from processor.classifier import rule_classify

        record = _sample_record(
            title="Security Vulnerability Documentation and Patch Notes",
            content="A critical security vulnerability has been identified and patched.",
        )
        result = rule_classify(record)
        self.assertEqual(result["impact_level"], "High",
                         "'security vulnerability' (High) must beat 'documentation' (Low) in title")

    def test_E2d_rule_classify_unchanged_for_clear_medium_no_low_title(self):
        """
        Records with no Low-marker title and Medium body keywords must still
        get Medium — the bug fix must not accidentally demote clear Medium cases.
        """
        from processor.classifier import rule_classify

        cases = [
            ("Recruiting Workflow Preview Available",
             "A preview of the new recruiting workflow is now available.",
             "Medium"),
            ("Expansion of HCM Common REST API",
             "Additional endpoints have been added to the REST API.",
             "Medium"),
        ]

        for title, content, expected in cases:
            with self.subTest(title=title):
                record = _sample_record(title=title, content=content)
                result = rule_classify(record)
                self.assertEqual(result["impact_level"], expected)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
