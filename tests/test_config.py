"""
Unit tests for model_router config loading, resolution, and classification logic.

Imports directly from hooks/model_router.py — the single source of truth.
"""

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

# Add hooks/ to import path so we can import model_router directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "plugins", "claude-model-router-hook", "hooks"))
from model_router import load_config, resolve_list, safe_regex_match, classify_with_haiku_fallback


# ── Helpers ────────────────────────────────────────────────────────────────

DEFAULTS_KW = ["analyze", "architecture", "deep dive"]
DEFAULTS_PAT = [r"\blint\b", r"\bformat\b"]


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)


# ── Tests: resolve_list ───────────────────────────────────────────────────

class TestResolveList(unittest.TestCase):

    def test_no_config_returns_defaults(self):
        result = resolve_list({}, "opus", "keywords", DEFAULTS_KW)
        self.assertEqual(result, DEFAULTS_KW)

    def test_extend_mode_adds_keywords(self):
        config = {"opus": {"mode": "extend", "keywords": ["custom-kw"]}}
        result = resolve_list(config, "opus", "keywords", DEFAULTS_KW)
        self.assertEqual(result, DEFAULTS_KW + ["custom-kw"])

    def test_extend_is_default_mode(self):
        config = {"opus": {"keywords": ["extra"]}}
        result = resolve_list(config, "opus", "keywords", DEFAULTS_KW)
        self.assertIn("extra", result)
        for kw in DEFAULTS_KW:
            self.assertIn(kw, result)

    def test_replace_mode_discards_defaults(self):
        config = {"opus": {"mode": "replace", "keywords": ["only-this"]}}
        result = resolve_list(config, "opus", "keywords", DEFAULTS_KW)
        self.assertEqual(result, ["only-this"])

    def test_replace_mode_empty_list_returns_empty(self):
        config = {"opus": {"mode": "replace", "keywords": []}}
        result = resolve_list(config, "opus", "keywords", DEFAULTS_KW)
        self.assertEqual(result, [])

    def test_replace_mode_missing_field_returns_empty(self):
        """Replace mode with no field specified should return empty, not defaults."""
        config = {"opus": {"mode": "replace"}}
        result = resolve_list(config, "opus", "keywords", DEFAULTS_KW)
        self.assertEqual(result, [])

    def test_remove_keywords_in_extend_mode(self):
        config = {"opus": {"mode": "extend", "remove_keywords": ["analyze"]}}
        result = resolve_list(config, "opus", "keywords", DEFAULTS_KW)
        self.assertNotIn("analyze", result)
        self.assertIn("architecture", result)
        self.assertIn("deep dive", result)

    def test_remove_patterns_in_extend_mode(self):
        config = {"haiku": {"mode": "extend", "remove_patterns": [r"\blint\b"]}}
        result = resolve_list(config, "haiku", "patterns", DEFAULTS_PAT)
        self.assertNotIn(r"\blint\b", result)
        self.assertIn(r"\bformat\b", result)

    def test_remove_nonexistent_entry_is_noop(self):
        config = {"opus": {"remove_keywords": ["not-in-defaults"]}}
        result = resolve_list(config, "opus", "keywords", DEFAULTS_KW)
        self.assertEqual(result, DEFAULTS_KW)

    def test_remove_ignored_in_replace_mode(self):
        config = {"opus": {"mode": "replace", "keywords": ["a"], "remove_keywords": ["analyze"]}}
        result = resolve_list(config, "opus", "keywords", DEFAULTS_KW)
        self.assertEqual(result, ["a"])

    def test_missing_tier_returns_defaults(self):
        result = resolve_list({}, "haiku", "patterns", DEFAULTS_PAT)
        self.assertEqual(result, DEFAULTS_PAT)


# ── Tests: load_config ────────────────────────────────────────────────────

class TestLoadConfig(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_no_config_returns_empty(self):
        nonexistent = os.path.join(self.tmpdir, "missing.json")
        config = load_config(global_path=nonexistent, cwd=self.tmpdir)
        self.assertEqual(config, {})

    def test_global_config_loaded(self):
        global_f = os.path.join(self.tmpdir, "global.json")
        write_json(global_f, {"opus": {"keywords": ["global-kw"]}})
        config = load_config(global_path=global_f, cwd=self.tmpdir)
        self.assertEqual(config["opus"]["keywords"], ["global-kw"])

    def test_project_config_overrides_global(self):
        global_f = os.path.join(self.tmpdir, "global.json")
        write_json(global_f, {"opus": {"keywords": ["global-kw"]}})

        project_dir = os.path.join(self.tmpdir, "project")
        project_f = os.path.join(project_dir, ".claude", "model-router.json")
        write_json(project_f, {"opus": {"keywords": ["project-kw"]}})

        config = load_config(global_path=global_f, cwd=project_dir)
        self.assertEqual(config["opus"]["keywords"], ["project-kw"])

    def test_tier_dict_deep_merged(self):
        """Project tier config should deep-merge with global, not replace it."""
        global_f = os.path.join(self.tmpdir, "global.json")
        write_json(global_f, {"opus": {"keywords": ["gk"], "patterns": ["gp"]}})

        project_dir = os.path.join(self.tmpdir, "project")
        project_f = os.path.join(project_dir, ".claude", "model-router.json")
        write_json(project_f, {"opus": {"keywords": ["pk"]}})

        config = load_config(global_path=global_f, cwd=project_dir)
        # keywords overridden by project
        self.assertEqual(config["opus"]["keywords"], ["pk"])
        # patterns preserved from global
        self.assertEqual(config["opus"]["patterns"], ["gp"])

    def test_thresholds_deep_merged(self):
        global_f = os.path.join(self.tmpdir, "global.json")
        write_json(global_f, {"thresholds": {"opus_word_count": 300}})

        project_dir = os.path.join(self.tmpdir, "project")
        project_f = os.path.join(project_dir, ".claude", "model-router.json")
        write_json(project_f, {"thresholds": {"haiku_max_word_count": 20}})

        config = load_config(global_path=global_f, cwd=project_dir)
        self.assertEqual(config["thresholds"]["opus_word_count"], 300)
        self.assertEqual(config["thresholds"]["haiku_max_word_count"], 20)

    def test_project_thresholds_override_global(self):
        global_f = os.path.join(self.tmpdir, "global.json")
        write_json(global_f, {"thresholds": {"opus_word_count": 300}})

        project_dir = os.path.join(self.tmpdir, "project")
        project_f = os.path.join(project_dir, ".claude", "model-router.json")
        write_json(project_f, {"thresholds": {"opus_word_count": 150}})

        config = load_config(global_path=global_f, cwd=project_dir)
        self.assertEqual(config["thresholds"]["opus_word_count"], 150)

    def test_invalid_json_falls_back_gracefully(self):
        bad_f = os.path.join(self.tmpdir, "bad.json")
        with open(bad_f, "w") as f:
            f.write("{invalid json!!")
        config = load_config(global_path=bad_f, cwd=self.tmpdir)
        self.assertEqual(config, {})

    def test_schema_key_skipped_during_merge(self):
        global_f = os.path.join(self.tmpdir, "global.json")
        write_json(global_f, {"opus": {"keywords": ["kw"]}})

        project_dir = os.path.join(self.tmpdir, "project")
        project_f = os.path.join(project_dir, ".claude", "model-router.json")
        write_json(project_f, {"$schema": "./schema/model-router.schema.json", "opus": {"keywords": ["pkw"]}})

        config = load_config(global_path=global_f, cwd=project_dir)
        self.assertNotIn("$schema", config)
        self.assertEqual(config["opus"]["keywords"], ["pkw"])

    def test_project_discovered_from_parent_directory(self):
        """Config in a parent .claude/ directory should be found when CWD is deeper."""
        project_dir = os.path.join(self.tmpdir, "project")
        deep_dir = os.path.join(project_dir, "src", "components")
        os.makedirs(deep_dir, exist_ok=True)

        project_f = os.path.join(project_dir, ".claude", "model-router.json")
        write_json(project_f, {"opus": {"keywords": ["from-parent"]}})

        nonexistent_global = os.path.join(self.tmpdir, "nope.json")
        config = load_config(global_path=nonexistent_global, cwd=deep_dir)
        self.assertEqual(config["opus"]["keywords"], ["from-parent"])


# ── Tests: safe_regex_match ───────────────────────────────────────────────

class TestSafeRegexMatch(unittest.TestCase):

    def test_valid_pattern_matches(self):
        self.assertTrue(safe_regex_match([r"\blint\b"], "please lint the code"))

    def test_valid_pattern_no_match(self):
        self.assertFalse(safe_regex_match([r"\blint\b"], "build the project"))

    def test_invalid_regex_skipped(self):
        """Malformed regex should not crash, just be skipped."""
        self.assertFalse(safe_regex_match([r"[invalid", r"(unclosed"], "test"))

    def test_mixed_valid_and_invalid(self):
        """Valid pattern should still match even if another is malformed."""
        self.assertTrue(safe_regex_match([r"[bad", r"\blint\b"], "lint"))

    def test_empty_list(self):
        self.assertFalse(safe_regex_match([], "anything"))


# ── Tests: opus patterns ──────────────────────────────────────────────────

class TestOpusPatterns(unittest.TestCase):
    """Verify opus supports both keywords and regex patterns."""

    def test_opus_patterns_resolved(self):
        config = {"opus": {"patterns": [r"\bmy-opus-trigger\b"]}}
        result = resolve_list(config, "opus", "patterns", [])
        self.assertEqual(result, [r"\bmy-opus-trigger\b"])

    def test_opus_patterns_default_empty(self):
        result = resolve_list({}, "opus", "patterns", [])
        self.assertEqual(result, [])


# ── Tests: classification logic ───────────────────────────────────────────

class TestClassification(unittest.TestCase):
    """Verify classification routing logic."""

    def _classify(self, prompt, config):
        prompt_lower = prompt.lower()

        default_opus_kw = ["architecture", "deep dive"]
        default_haiku_pat = [r"\blint\b", r"\bformat\b"]
        default_sonnet_pat = [r"\bfix\b", r"\bimplement\b"]

        opus_keywords = resolve_list(config, "opus", "keywords", default_opus_kw)
        opus_patterns = resolve_list(config, "opus", "patterns", [])
        haiku_patterns = resolve_list(config, "haiku", "patterns", default_haiku_pat)
        sonnet_patterns = resolve_list(config, "sonnet", "patterns", default_sonnet_pat)

        has_opus_keyword = any(kw in prompt_lower for kw in opus_keywords)
        has_opus_pattern = safe_regex_match(opus_patterns, prompt_lower)
        has_opus_signal = has_opus_keyword or has_opus_pattern

        if has_opus_signal:
            return "opus"
        if safe_regex_match(haiku_patterns, prompt_lower):
            return "haiku"
        if safe_regex_match(sonnet_patterns, prompt_lower):
            return "sonnet"
        return None

    def test_opus_keyword_routes(self):
        self.assertEqual(self._classify("deep dive into this", {}), "opus")

    def test_haiku_pattern_routes(self):
        self.assertEqual(self._classify("lint the code", {}), "haiku")

    def test_sonnet_pattern_routes(self):
        self.assertEqual(self._classify("fix the login bug", {}), "sonnet")

    def test_no_match_returns_none(self):
        self.assertIsNone(self._classify("hello world", {}))

    def test_opus_pattern_triggers_routing(self):
        config = {"opus": {"patterns": [r"\bmy-opus-trigger\b"]}}
        self.assertEqual(self._classify("run my-opus-trigger now", config), "opus")

    def test_malformed_regex_does_not_crash(self):
        config = {"haiku": {"mode": "replace", "patterns": [r"[bad-regex"]}}
        result = self._classify("lint", config)
        self.assertIsNone(result)

    def test_long_prompt_without_keyword_returns_none(self):
        """Word count alone should NOT trigger opus routing."""
        self.assertIsNone(self._classify(" ".join(["word"] * 300), {}))


# ── Tests: fallback config ───────────────────────────────────────────────

class TestFallbackConfig(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_fallback_disabled_by_default(self):
        nonexistent = os.path.join(self.tmpdir, "missing.json")
        config = load_config(global_path=nonexistent, cwd=self.tmpdir)
        fallback = config.get("fallback", {})
        self.assertFalse(fallback.get("enabled", False))

    def test_fallback_enabled_from_config(self):
        global_f = os.path.join(self.tmpdir, "global.json")
        write_json(global_f, {"fallback": {"enabled": True}})
        config = load_config(global_path=global_f, cwd=self.tmpdir)
        self.assertTrue(config["fallback"]["enabled"])

    def test_fallback_disabled_from_config(self):
        global_f = os.path.join(self.tmpdir, "global.json")
        write_json(global_f, {"fallback": {"enabled": False}})
        config = load_config(global_path=global_f, cwd=self.tmpdir)
        self.assertFalse(config["fallback"]["enabled"])

    def test_project_fallback_overrides_global(self):
        global_f = os.path.join(self.tmpdir, "global.json")
        write_json(global_f, {"fallback": {"enabled": False}})

        project_dir = os.path.join(self.tmpdir, "project")
        project_f = os.path.join(project_dir, ".claude", "model-router.json")
        write_json(project_f, {"fallback": {"enabled": True}})

        config = load_config(global_path=global_f, cwd=project_dir)
        self.assertTrue(config["fallback"]["enabled"])


# ── Tests: classify_with_haiku_fallback ──────────────────────────────────

class TestClassifyWithHaikuFallback(unittest.TestCase):

    @mock.patch("model_router.shutil.which", return_value=None)
    def test_returns_none_when_cli_not_found(self, mock_which):
        result = classify_with_haiku_fallback("some prompt")
        self.assertIsNone(result)

    @mock.patch("model_router.subprocess.run")
    @mock.patch("model_router.shutil.which", return_value="/usr/local/bin/claude")
    def test_returns_tier_on_valid_response(self, mock_which, mock_run):
        mock_run.return_value = mock.Mock(returncode=0, stdout="sonnet\n")
        result = classify_with_haiku_fallback("build a dashboard")
        self.assertEqual(result, "sonnet")

    @mock.patch("model_router.subprocess.run", side_effect=subprocess.TimeoutExpired("claude", 4))
    @mock.patch("model_router.shutil.which", return_value="/usr/local/bin/claude")
    def test_returns_none_on_timeout(self, mock_which, mock_run):
        result = classify_with_haiku_fallback("some prompt")
        self.assertIsNone(result)

    @mock.patch("model_router.subprocess.run")
    @mock.patch("model_router.shutil.which", return_value="/usr/local/bin/claude")
    def test_returns_none_on_unexpected_output(self, mock_which, mock_run):
        mock_run.return_value = mock.Mock(returncode=0, stdout="I think this is complex\n")
        result = classify_with_haiku_fallback("some prompt")
        self.assertIsNone(result)

    @mock.patch("model_router.subprocess.run")
    @mock.patch("model_router.shutil.which", return_value="/usr/local/bin/claude")
    def test_extracts_tier_from_verbose_response(self, mock_which, mock_run):
        mock_run.return_value = mock.Mock(returncode=0, stdout="I would classify this as opus.\n")
        result = classify_with_haiku_fallback("architect the entire system")
        self.assertEqual(result, "opus")

    @mock.patch("model_router.subprocess.run")
    @mock.patch("model_router.shutil.which", return_value="/usr/local/bin/claude")
    def test_returns_none_on_nonzero_exit(self, mock_which, mock_run):
        mock_run.return_value = mock.Mock(returncode=1, stdout="")
        result = classify_with_haiku_fallback("some prompt")
        self.assertIsNone(result)


# ── Tests: tightened patterns ────────────────────────────────────────────

class TestTightenedPatterns(unittest.TestCase):
    """Verify broad patterns were removed and specific patterns work."""

    SONNET_PATTERNS = [
        r"\bimplement\b", r"\bfix\b", r"\bdebug\b",
        r"\badd\s+feature\b", r"\bdeploy\b", r"\brefactor\b",
        r"\bwrite\s+(a\s+)?(function|component|service|test|module|script|class|hook|middleware)\b",
        r"\bcreate\s+(a\s+)?(function|component|service|endpoint|module|database|schema|migration)\b",
        r"\b(add|write)\s+(unit\s+|integration\s+|e2e\s+)?tests?\s+(for|to|covering)\b",
    ]

    OPUS_KEYWORDS = [
        "architecture", "trade-off", "deep dive",
        "redesign", "across the codebase", "multi-system",
        "complex refactor", "plan mode",
    ]

    def test_bare_write_no_longer_matches_sonnet(self):
        self.assertFalse(safe_regex_match(self.SONNET_PATTERNS, "write me a poem"))

    def test_write_function_matches_sonnet(self):
        self.assertTrue(safe_regex_match(self.SONNET_PATTERNS, "write a function to parse json"))

    def test_bare_create_no_longer_matches_sonnet(self):
        self.assertFalse(safe_regex_match(self.SONNET_PATTERNS, "create a folder"))

    def test_create_component_matches_sonnet(self):
        self.assertTrue(safe_regex_match(self.SONNET_PATTERNS, "create a component for the sidebar"))

    def test_add_tests_for_matches_sonnet(self):
        self.assertTrue(safe_regex_match(self.SONNET_PATTERNS, "add tests for the auth module"))

    def test_broad_keywords_removed_from_opus(self):
        for kw in ["analyze", "evaluate", "why does", "architect", "strategy",
                    "strategic", "investor", "rethink", "high-stakes", "critical decision"]:
            self.assertNotIn(kw, self.OPUS_KEYWORDS)

    def test_architecture_still_triggers_opus(self):
        self.assertIn("architecture", self.OPUS_KEYWORDS)

    def test_deep_dive_still_triggers_opus(self):
        self.assertIn("deep dive", self.OPUS_KEYWORDS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
