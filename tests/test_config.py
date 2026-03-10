"""
Unit tests for model_router config loading, resolution, and classification logic.

Imports directly from hooks/model_router.py — the single source of truth.
"""

import json
import os
import pathlib
import sys
import tempfile
import unittest

# Add hooks/ to import path so we can import model_router directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "plugins", "claude-model-router-hook", "hooks"))
from model_router import load_config, resolve_list, safe_regex_match


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


# ── Tests: thresholds + classification ────────────────────────────────────

class TestThresholds(unittest.TestCase):
    """Verify threshold values and boundary semantics (>, <) in routing logic."""

    def _classify(self, prompt, config):
        prompt_lower = prompt.lower()
        word_count = len(prompt.split())
        thresholds = config.get("thresholds", {})
        opus_wc = thresholds.get("opus_word_count", 200)
        opus_q_wc = thresholds.get("opus_question_word_count", 100)
        haiku_max = thresholds.get("haiku_max_word_count", 60)

        default_opus_kw = ["analyze", "architecture"]
        default_haiku_pat = [r"\blint\b", r"\bformat\b"]
        default_sonnet_pat = [r"\bfix\b", r"\bbuild\b"]

        opus_keywords = resolve_list(config, "opus", "keywords", default_opus_kw)
        opus_patterns = resolve_list(config, "opus", "patterns", [])
        haiku_patterns = resolve_list(config, "haiku", "patterns", default_haiku_pat)
        sonnet_patterns = resolve_list(config, "sonnet", "patterns", default_sonnet_pat)

        has_opus_keyword = any(kw in prompt_lower for kw in opus_keywords)
        has_opus_pattern = safe_regex_match(opus_patterns, prompt_lower)
        has_opus_signal = has_opus_keyword or has_opus_pattern

        if has_opus_signal or \
           (word_count > opus_q_wc and "?" in prompt) or \
           word_count > opus_wc:
            return "opus"
        if word_count < haiku_max and safe_regex_match(haiku_patterns, prompt_lower):
            return "haiku"
        if safe_regex_match(sonnet_patterns, prompt_lower):
            return "sonnet"
        return None

    # --- opus_word_count: uses > (strictly greater than) ---

    def test_default_opus_word_count_above(self):
        """201 words > 200 → opus"""
        self.assertEqual(self._classify(" ".join(["word"] * 201), {}), "opus")

    def test_default_opus_word_count_at_boundary(self):
        """200 words == 200, not > 200 → NOT opus"""
        self.assertNotEqual(self._classify(" ".join(["word"] * 200), {}), "opus")

    def test_custom_opus_word_count_above(self):
        config = {"thresholds": {"opus_word_count": 50}}
        self.assertEqual(self._classify(" ".join(["word"] * 51), config), "opus")

    def test_custom_opus_word_count_at_boundary(self):
        config = {"thresholds": {"opus_word_count": 50}}
        self.assertNotEqual(self._classify(" ".join(["word"] * 50), config), "opus")

    # --- opus_question_word_count: uses > (strictly greater than) ---

    def test_default_question_word_count_above(self):
        """101 words with ? > 100 → opus"""
        self.assertEqual(self._classify(" ".join(["word"] * 101) + "?", {}), "opus")

    def test_default_question_word_count_at_boundary(self):
        """100 words with ? == 100, not > 100 → NOT opus"""
        self.assertNotEqual(self._classify(" ".join(["word"] * 100) + "?", {}), "opus")

    def test_custom_question_word_count_above(self):
        config = {"thresholds": {"opus_question_word_count": 50}}
        self.assertEqual(self._classify(" ".join(["word"] * 51) + "?", config), "opus")

    def test_custom_question_word_count_at_boundary(self):
        config = {"thresholds": {"opus_question_word_count": 50}}
        self.assertNotEqual(self._classify(" ".join(["word"] * 50) + "?", config), "opus")

    # --- haiku_max_word_count: uses < (strictly less than) ---

    def test_default_haiku_max_word_count_below(self):
        """59 words < 60 with lint → haiku"""
        prompt = " ".join(["word"] * 58) + " lint"
        self.assertEqual(self._classify(prompt, {}), "haiku")

    def test_default_haiku_max_word_count_at_boundary(self):
        """60 words == 60, not < 60 → NOT haiku (lint still present)"""
        prompt = " ".join(["word"] * 59) + " lint"
        self.assertNotEqual(self._classify(prompt, {}), "haiku")

    def test_custom_haiku_max_word_count_above(self):
        """25 words >= 20 with lint → NOT haiku"""
        config = {"thresholds": {"haiku_max_word_count": 20}}
        prompt = " ".join(["word"] * 24) + " lint"
        self.assertNotEqual(self._classify(prompt, config), "haiku")

    def test_custom_haiku_max_word_count_at_boundary(self):
        """20 words == 20, not < 20 → NOT haiku"""
        config = {"thresholds": {"haiku_max_word_count": 20}}
        prompt = " ".join(["word"] * 19) + " lint"
        self.assertNotEqual(self._classify(prompt, config), "haiku")

    def test_custom_haiku_max_word_count_below(self):
        """19 words < 20 with lint → haiku"""
        config = {"thresholds": {"haiku_max_word_count": 20}}
        prompt = " ".join(["word"] * 18) + " lint"
        self.assertEqual(self._classify(prompt, config), "haiku")

    # --- Other classification tests ---

    def test_opus_pattern_triggers_routing(self):
        config = {"opus": {"patterns": [r"\bmy-opus-trigger\b"]}}
        self.assertEqual(self._classify("run my-opus-trigger now", config), "opus")

    def test_malformed_regex_does_not_crash(self):
        config = {"haiku": {"mode": "replace", "patterns": [r"[bad-regex"]}}
        result = self._classify("lint", config)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
