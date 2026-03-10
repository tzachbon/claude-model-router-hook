"""
Unit tests for model-router-hook config loading and resolution logic.

These functions are extracted from hooks/model-router-hook.sh (the embedded
Python block) so they can be tested independently.
"""

import json
import os
import pathlib
import tempfile
import unittest


# ── Functions under test (mirrors hooks/model-router-hook.sh) ──────────────

def load_config(global_path=None, cwd=None):
    """Load and merge global + project configs.

    Parameters override the real filesystem paths for testing.
    """
    config = {}

    if global_path is None:
        global_path = pathlib.Path.home() / ".claude" / "model-router.json"
    else:
        global_path = pathlib.Path(global_path)

    if global_path.exists():
        try:
            with open(global_path) as f:
                config = json.load(f)
        except Exception:
            pass

    search_root = pathlib.Path(cwd) if cwd else pathlib.Path.cwd()
    for parent in [search_root, *search_root.parents]:
        project_path = parent / ".claude" / "model-router.json"
        if project_path.exists():
            try:
                with open(project_path) as f:
                    project_config = json.load(f)
                for key in project_config:
                    if key == "$schema":
                        continue
                    if key == "thresholds" and key in config:
                        config[key] = {**config.get(key, {}), **project_config[key]}
                    else:
                        config[key] = project_config[key]
            except Exception:
                pass
            break

    return config


def resolve_list(config, tier, field, defaults):
    """Resolve final keyword/pattern list for a tier based on mode."""
    tier_config = config.get(tier, {})
    mode = tier_config.get("mode", "extend")

    if mode == "replace":
        return tier_config.get(field, defaults)

    result = list(defaults)
    result.extend(tier_config.get(field, []))

    remove_key = f"remove_{field}"
    for item in tier_config.get(remove_key, []):
        if item in result:
            result.remove(item)

    return result


# ── Helpers ────────────────────────────────────────────────────────────────

DEFAULTS_KW = ["analyze", "architecture", "deep dive"]
DEFAULTS_PAT = [r"\blint\b", r"\bformat\b"]


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)


# ── Tests ──────────────────────────────────────────────────────────────────

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
        # replace mode: remove_keywords has no effect on already-excluded defaults
        self.assertEqual(result, ["a"])

    def test_missing_tier_returns_defaults(self):
        result = resolve_list({}, "haiku", "patterns", DEFAULTS_PAT)
        self.assertEqual(result, DEFAULTS_PAT)


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


class TestThresholds(unittest.TestCase):
    """Verify threshold values propagate correctly to routing logic."""

    def _classify(self, prompt, config):
        prompt_lower = prompt.lower()
        word_count = len(prompt.split())
        thresholds = config.get("thresholds", {})
        opus_wc = thresholds.get("opus_word_count", 200)
        opus_q_wc = thresholds.get("opus_question_word_count", 100)
        haiku_max = thresholds.get("haiku_max_word_count", 60)

        import re
        default_opus_kw = ["analyze", "architecture"]
        default_haiku_pat = [r"\blint\b", r"\bformat\b"]
        default_sonnet_pat = [r"\bfix\b", r"\bbuild\b"]

        opus_keywords = resolve_list(config, "opus", "keywords", default_opus_kw)
        haiku_patterns = resolve_list(config, "haiku", "patterns", default_haiku_pat)
        sonnet_patterns = resolve_list(config, "sonnet", "patterns", default_sonnet_pat)

        if any(kw in prompt_lower for kw in opus_keywords) or \
           (word_count > opus_q_wc and "?" in prompt) or \
           word_count > opus_wc:
            return "opus"
        if word_count < haiku_max and any(re.search(p, prompt_lower) for p in haiku_patterns):
            return "haiku"
        if any(re.search(p, prompt_lower) for p in sonnet_patterns):
            return "sonnet"
        return None

    def test_default_opus_word_count(self):
        long_prompt = " ".join(["word"] * 201)
        self.assertEqual(self._classify(long_prompt, {}), "opus")

    def test_custom_opus_word_count(self):
        config = {"thresholds": {"opus_word_count": 50}}
        long_prompt = " ".join(["word"] * 51)
        self.assertEqual(self._classify(long_prompt, config), "opus")

    def test_default_haiku_max_word_count(self):
        # 59 words + "lint" → haiku
        prompt = " ".join(["word"] * 58) + " lint"
        self.assertEqual(self._classify(prompt, {}), "haiku")

    def test_custom_haiku_max_word_count_blocks_match(self):
        config = {"thresholds": {"haiku_max_word_count": 20}}
        # 25 words + "lint" → should NOT match haiku (25 >= 20)
        prompt = " ".join(["word"] * 24) + " lint"
        result = self._classify(prompt, config)
        self.assertNotEqual(result, "haiku")

    def test_default_question_word_count(self):
        # 101 words with "?" → opus (threshold is > 100)
        prompt = " ".join(["word"] * 101) + "?"
        self.assertEqual(self._classify(prompt, {}), "opus")

    def test_custom_question_word_count(self):
        config = {"thresholds": {"opus_question_word_count": 50}}
        prompt = " ".join(["word"] * 51) + "?"
        self.assertEqual(self._classify(prompt, config), "opus")


if __name__ == "__main__":
    unittest.main(verbosity=2)
