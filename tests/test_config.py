"""
Unit tests for router.config loading, resolution, and regex safety.

Imports directly from the v2 router.config module, the single source of truth.
"""

import json
import os
import sys
import tempfile
import unittest

# Add hooks/ to import path so we can import the router package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "plugins", "claude-model-router-hook", "hooks"))
from router.config import DEFAULTS, load_config, migrate_v1, resolve_list, safe_regex_match


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
        result = resolve_list({}, "keywords", DEFAULTS_KW)
        self.assertEqual(result, DEFAULTS_KW)

    def test_extend_mode_adds_keywords(self):
        class_cfg = {"mode": "extend", "keywords": ["custom-kw"]}
        result = resolve_list(class_cfg, "keywords", DEFAULTS_KW)
        self.assertEqual(result, DEFAULTS_KW + ["custom-kw"])

    def test_extend_is_default_mode(self):
        class_cfg = {"keywords": ["extra"]}
        result = resolve_list(class_cfg, "keywords", DEFAULTS_KW)
        self.assertIn("extra", result)
        for kw in DEFAULTS_KW:
            self.assertIn(kw, result)

    def test_replace_mode_discards_defaults(self):
        class_cfg = {"mode": "replace", "keywords": ["only-this"]}
        result = resolve_list(class_cfg, "keywords", DEFAULTS_KW)
        self.assertEqual(result, ["only-this"])

    def test_replace_mode_empty_list_returns_empty(self):
        class_cfg = {"mode": "replace", "keywords": []}
        result = resolve_list(class_cfg, "keywords", DEFAULTS_KW)
        self.assertEqual(result, [])

    def test_replace_mode_missing_field_returns_empty(self):
        """Replace mode with no field specified should return empty, not defaults."""
        class_cfg = {"mode": "replace"}
        result = resolve_list(class_cfg, "keywords", DEFAULTS_KW)
        self.assertEqual(result, [])

    def test_remove_keywords_in_extend_mode(self):
        class_cfg = {"mode": "extend", "remove_keywords": ["analyze"]}
        result = resolve_list(class_cfg, "keywords", DEFAULTS_KW)
        self.assertNotIn("analyze", result)
        self.assertIn("architecture", result)
        self.assertIn("deep dive", result)

    def test_remove_patterns_in_extend_mode(self):
        class_cfg = {"mode": "extend", "remove_patterns": [r"\blint\b"]}
        result = resolve_list(class_cfg, "patterns", DEFAULTS_PAT)
        self.assertNotIn(r"\blint\b", result)
        self.assertIn(r"\bformat\b", result)

    def test_remove_nonexistent_entry_is_noop(self):
        class_cfg = {"remove_keywords": ["not-in-defaults"]}
        result = resolve_list(class_cfg, "keywords", DEFAULTS_KW)
        self.assertEqual(result, DEFAULTS_KW)

    def test_remove_ignored_in_replace_mode(self):
        class_cfg = {"mode": "replace", "keywords": ["a"], "remove_keywords": ["analyze"]}
        result = resolve_list(class_cfg, "keywords", DEFAULTS_KW)
        self.assertEqual(result, ["a"])

    def test_missing_class_returns_defaults(self):
        result = resolve_list({}, "patterns", DEFAULTS_PAT)
        self.assertEqual(result, DEFAULTS_PAT)


# ── Tests: load_config ────────────────────────────────────────────────────

class TestLoadConfig(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_no_config_returns_defaults(self):
        nonexistent = os.path.join(self.tmpdir, "missing.json")
        config = load_config(global_path=nonexistent, cwd=self.tmpdir)
        self.assertEqual(config, DEFAULTS)

    def test_global_config_loaded(self):
        global_f = os.path.join(self.tmpdir, "global.json")
        write_json(global_f, {"opus": {"keywords": ["global-kw"]}})
        config = load_config(global_path=global_f, cwd=self.tmpdir)
        self.assertEqual(config["classes"]["architecture"]["keywords"], ["global-kw"])

    def test_project_config_overrides_global(self):
        global_f = os.path.join(self.tmpdir, "global.json")
        write_json(global_f, {"opus": {"keywords": ["global-kw"]}})

        project_dir = os.path.join(self.tmpdir, "project")
        project_f = os.path.join(project_dir, ".claude", "model-router.json")
        write_json(project_f, {"opus": {"keywords": ["project-kw"]}})

        config = load_config(global_path=global_f, cwd=project_dir)
        self.assertEqual(config["classes"]["architecture"]["keywords"], ["project-kw"])

    def test_tier_dict_deep_merged(self):
        """Project class config should deep-merge with global, not replace it."""
        global_f = os.path.join(self.tmpdir, "global.json")
        write_json(global_f, {"opus": {"keywords": ["gk"], "patterns": ["gp"]}})

        project_dir = os.path.join(self.tmpdir, "project")
        project_f = os.path.join(project_dir, ".claude", "model-router.json")
        write_json(project_f, {"opus": {"keywords": ["pk"]}})

        config = load_config(global_path=global_f, cwd=project_dir)
        # keywords overridden by project
        self.assertEqual(config["classes"]["architecture"]["keywords"], ["pk"])
        # patterns preserved from global
        self.assertEqual(config["classes"]["architecture"]["patterns"], ["gp"])

    def test_thresholds_deep_merged(self):
        global_f = os.path.join(self.tmpdir, "global.json")
        write_json(global_f, {"thresholds": {"opus_word_count": 300}})

        project_dir = os.path.join(self.tmpdir, "project")
        project_f = os.path.join(project_dir, ".claude", "model-router.json")
        write_json(project_f, {"thresholds": {"haiku_max_word_count": 20}})

        config = load_config(global_path=global_f, cwd=project_dir)
        self.assertEqual(config["thresholds"]["long_prompt_words"], 300)
        self.assertEqual(config["thresholds"]["mechanical_max_words"], 20)

    def test_project_thresholds_override_global(self):
        global_f = os.path.join(self.tmpdir, "global.json")
        write_json(global_f, {"thresholds": {"opus_word_count": 300}})

        project_dir = os.path.join(self.tmpdir, "project")
        project_f = os.path.join(project_dir, ".claude", "model-router.json")
        write_json(project_f, {"thresholds": {"opus_word_count": 150}})

        config = load_config(global_path=global_f, cwd=project_dir)
        self.assertEqual(config["thresholds"]["long_prompt_words"], 150)

    def test_invalid_json_falls_back_gracefully(self):
        bad_f = os.path.join(self.tmpdir, "bad.json")
        with open(bad_f, "w") as f:
            f.write("{invalid json!!")
        config = load_config(global_path=bad_f, cwd=self.tmpdir)
        self.assertEqual(config, DEFAULTS)

    def test_schema_key_skipped_during_merge(self):
        global_f = os.path.join(self.tmpdir, "global.json")
        write_json(global_f, {"opus": {"keywords": ["kw"]}})

        project_dir = os.path.join(self.tmpdir, "project")
        project_f = os.path.join(project_dir, ".claude", "model-router.json")
        write_json(project_f, {"$schema": "./schema/model-router.schema.json", "opus": {"keywords": ["pkw"]}})

        config = load_config(global_path=global_f, cwd=project_dir)
        self.assertNotIn("$schema", config)
        self.assertEqual(config["classes"]["architecture"]["keywords"], ["pkw"])

    def test_project_discovered_from_parent_directory(self):
        """Config in a parent .claude/ directory should be found when CWD is deeper."""
        project_dir = os.path.join(self.tmpdir, "project")
        deep_dir = os.path.join(project_dir, "src", "components")
        os.makedirs(deep_dir, exist_ok=True)

        project_f = os.path.join(project_dir, ".claude", "model-router.json")
        write_json(project_f, {"opus": {"keywords": ["from-parent"]}})

        nonexistent_global = os.path.join(self.tmpdir, "nope.json")
        config = load_config(global_path=nonexistent_global, cwd=deep_dir)
        self.assertEqual(config["classes"]["architecture"]["keywords"], ["from-parent"])


# ── Tests: migrate_v1 (v1-semantics coverage) ─────────────────────────────

class TestMigrateV1(unittest.TestCase):
    """v1-shaped config migrates to v2 shape (tier->class, threshold renames)."""

    def test_tiers_map_to_classes(self):
        migrated = migrate_v1({"opus": {"keywords": ["a"]}, "haiku": {"patterns": ["p"]}})
        self.assertEqual(migrated["classes"]["architecture"]["keywords"], ["a"])
        self.assertEqual(migrated["classes"]["mechanical"]["patterns"], ["p"])

    def test_threshold_keys_renamed(self):
        migrated = migrate_v1({"thresholds": {"opus_word_count": 300, "haiku_max_word_count": 20}})
        self.assertEqual(migrated["thresholds"]["long_prompt_words"], 300)
        self.assertEqual(migrated["thresholds"]["mechanical_max_words"], 20)

    def test_sets_v2_version_and_warn_mode(self):
        migrated = migrate_v1({"opus": {"keywords": ["a"]}})
        self.assertEqual(migrated["version"], 2)
        self.assertEqual(migrated["apply_mode"], "warn")


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

    def test_non_string_pattern_skipped(self):
        """Non-string pattern entries (e.g. 123, null) are skipped, not raised (F3)."""
        self.assertFalse(safe_regex_match([123, None], "test"))

    def test_non_string_mixed_with_valid_still_matches(self):
        """A valid pattern still matches even when non-string entries are present (F3)."""
        self.assertTrue(safe_regex_match([123, r"\blint\b", None], "please lint the code"))


# ── Tests: opus patterns ──────────────────────────────────────────────────

class TestOpusPatterns(unittest.TestCase):
    """Verify the architecture class supports both keywords and regex patterns."""

    def test_patterns_resolved(self):
        class_cfg = {"patterns": [r"\bmy-opus-trigger\b"]}
        result = resolve_list(class_cfg, "patterns", [])
        self.assertEqual(result, [r"\bmy-opus-trigger\b"])

    def test_patterns_default_empty(self):
        result = resolve_list({}, "patterns", [])
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
