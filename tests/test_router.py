"""
Unit tests for the v2 router modules. Imports the real router package
(no logic reimplementation) and asserts behavior directly.

Phase 3.1 covers router.ladder: Decision invariants and model-string utilities.
"""

import json
import os
import sys
import tempfile
import unittest

# Add hooks/ to import path so we can import the router package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "plugins", "claude-model-router-hook", "hooks"))
from router.ladder import (  # noqa: E402
    TIERS,
    MODEL_IDS,
    EFFORTS,
    Decision,
    detect_tier,
    split_suffix,
    effort_distance,
)
from router.config import (  # noqa: E402
    DEFAULTS,
    detect_version,
    migrate_v1,
    merge,
    resolve_list,
    load_config,
    v1_hint_due,
)
from router import taxonomy  # noqa: E402
from router.taxonomy import (  # noqa: E402
    CLASSES,
    TEXT_CAP,
    EXTREME_CAP,
    EXTREME_ESCALATION_MIN,
    score,
    classify_heuristic,
)


def _det_cfg():
    """DEFAULTS copy with CLI fallback off: fully deterministic, offline."""
    import copy
    cfg = copy.deepcopy(DEFAULTS)
    cfg["classifier"]["cli_fallback"] = False
    return cfg


# ── Tests: Decision invariants ─────────────────────────────────────────────

class TestDecisionInvariants(unittest.TestCase):

    def test_haiku_without_effort_constructs(self):
        d = Decision("haiku", None, "mechanical", "heuristic")
        self.assertEqual(d.model, "haiku")
        self.assertIsNone(d.effort)

    def test_haiku_with_effort_raises(self):
        with self.assertRaises(ValueError):
            Decision("haiku", "high", "mechanical", "heuristic")

    def test_non_ladder_model_raises(self):
        with self.assertRaises(ValueError):
            Decision("gpt-5", "high", "architecture", "heuristic")

    def test_mythos_model_raises(self):
        with self.assertRaises(ValueError):
            Decision("claude-mythos-5", "high", "extreme", "heuristic")

    def test_invalid_effort_raises(self):
        with self.assertRaises(ValueError):
            Decision("sonnet", "extreme", "implementation", "heuristic")

    def test_valid_effort_tiers_construct(self):
        for effort in EFFORTS:
            d = Decision("opus", effort, "architecture", "cli")
            self.assertEqual(d.effort, effort)


# ── Tests: mythos never present (FR-2, test-asserted) ──────────────────────

class TestMythosAbsent(unittest.TestCase):

    def test_mythos_not_in_tiers(self):
        for tier in TIERS:
            self.assertNotIn("mythos", tier)

    def test_mythos_not_in_model_id_values(self):
        for model_id in MODEL_IDS.values():
            self.assertNotIn("mythos", model_id)

    def test_mythos_not_a_tier_key(self):
        self.assertNotIn("mythos", MODEL_IDS)

    def test_every_tier_has_model_id(self):
        self.assertEqual(set(TIERS), set(MODEL_IDS))


# ── Tests: detect_tier ─────────────────────────────────────────────────────

class TestDetectTier(unittest.TestCase):

    def test_aliases(self):
        for tier in TIERS:
            self.assertEqual(detect_tier(tier), tier)

    def test_full_ids(self):
        for tier, model_id in MODEL_IDS.items():
            self.assertEqual(detect_tier(model_id), tier)

    def test_fable_substring(self):
        self.assertEqual(detect_tier("claude-fable-5"), "fable")

    def test_suffixed_id(self):
        self.assertEqual(detect_tier("claude-opus-4-8[1m]"), "opus")

    def test_unknown_returns_none(self):
        self.assertIsNone(detect_tier("gpt-5"))

    def test_mythos_returns_none(self):
        self.assertIsNone(detect_tier("claude-mythos-5"))


# ── Tests: split_suffix ────────────────────────────────────────────────────

class TestSplitSuffix(unittest.TestCase):

    def test_suffix_present(self):
        self.assertEqual(split_suffix("opus[1m]"), ("opus", "[1m]"))

    def test_full_id_suffix(self):
        self.assertEqual(split_suffix("claude-opus-4-8[1m]"), ("claude-opus-4-8", "[1m]"))

    def test_no_suffix(self):
        self.assertEqual(split_suffix("sonnet"), ("sonnet", ""))

    def test_no_suffix_full_id(self):
        self.assertEqual(split_suffix("claude-sonnet-5"), ("claude-sonnet-5", ""))


# ── Tests: effort_distance ─────────────────────────────────────────────────

class TestEffortDistance(unittest.TestCase):

    def test_zero_distance(self):
        self.assertEqual(effort_distance("high", "high"), 0)

    def test_adjacent(self):
        self.assertEqual(effort_distance("low", "medium"), 1)

    def test_symmetric(self):
        self.assertEqual(effort_distance("low", "max"), effort_distance("max", "low"))

    def test_full_span(self):
        self.assertEqual(effort_distance("low", "max"), len(EFFORTS) - 1)


# ── Tests: detect_version (FR-31 structural detection) ─────────────────────

class TestDetectVersion(unittest.TestCase):

    def test_version_two_is_v2(self):
        self.assertEqual(detect_version({"version": 2, "opus": {}}), 2)

    def test_empty_config_is_v2(self):
        self.assertEqual(detect_version({}), 2)

    def test_opus_key_triggers_v1(self):
        self.assertEqual(detect_version({"opus": {"keywords": []}}), 1)

    def test_sonnet_key_triggers_v1(self):
        self.assertEqual(detect_version({"sonnet": {"keywords": []}}), 1)

    def test_haiku_key_triggers_v1(self):
        self.assertEqual(detect_version({"haiku": {"keywords": []}}), 1)

    def test_thresholds_key_triggers_v1(self):
        self.assertEqual(detect_version({"thresholds": {"opus_word_count": 300}}), 1)

    def test_explicit_version_two_beats_v1_keys(self):
        self.assertEqual(detect_version({"version": 2, "thresholds": {}}), 2)

    def test_unknown_keys_only_is_v2(self):
        self.assertEqual(detect_version({"apply_mode": "warn"}), 2)


# ── Tests: migrate_v1 full mapping table (FR-32, design table) ─────────────

class TestMigrateV1Table(unittest.TestCase):
    """Every row of the design v1->v2 mapping table."""

    def test_opus_maps_to_architecture(self):
        migrated = migrate_v1({"opus": {"mode": "replace", "keywords": ["a"], "patterns": ["p"]}})
        arch = migrated["classes"]["architecture"]
        self.assertEqual(arch["mode"], "replace")
        self.assertEqual(arch["keywords"], ["a"])
        self.assertEqual(arch["patterns"], ["p"])

    def test_sonnet_maps_to_implementation(self):
        migrated = migrate_v1({"sonnet": {"keywords": ["s"], "remove_keywords": ["x"]}})
        impl = migrated["classes"]["implementation"]
        self.assertEqual(impl["keywords"], ["s"])
        self.assertEqual(impl["remove_keywords"], ["x"])

    def test_haiku_maps_to_mechanical(self):
        migrated = migrate_v1({"haiku": {"patterns": ["hp"], "remove_patterns": ["rp"]}})
        mech = migrated["classes"]["mechanical"]
        self.assertEqual(mech["patterns"], ["hp"])
        self.assertEqual(mech["remove_patterns"], ["rp"])

    def test_opus_word_count_renamed(self):
        migrated = migrate_v1({"thresholds": {"opus_word_count": 300}})
        self.assertEqual(migrated["thresholds"]["long_prompt_words"], 300)

    def test_opus_question_word_count_renamed(self):
        migrated = migrate_v1({"thresholds": {"opus_question_word_count": 120}})
        self.assertEqual(migrated["thresholds"]["question_words"], 120)

    def test_haiku_max_word_count_renamed(self):
        migrated = migrate_v1({"thresholds": {"haiku_max_word_count": 20}})
        self.assertEqual(migrated["thresholds"]["mechanical_max_words"], 20)

    def test_unknown_threshold_key_passthrough(self):
        migrated = migrate_v1({"thresholds": {"confident_margin": 5}})
        self.assertEqual(migrated["thresholds"]["confident_margin"], 5)

    def test_implicit_warn_mode_and_version(self):
        migrated = migrate_v1({"opus": {"keywords": ["a"]}})
        self.assertEqual(migrated["version"], 2)
        self.assertEqual(migrated["apply_mode"], "warn")

    def test_only_known_tier_fields_carried(self):
        """Unknown keys inside a v1 tier config are dropped."""
        migrated = migrate_v1({"opus": {"keywords": ["a"], "bogus": 1}})
        self.assertNotIn("bogus", migrated["classes"]["architecture"])

    def test_non_dict_tier_config_skipped(self):
        migrated = migrate_v1({"opus": "not-a-dict"})
        self.assertNotIn("classes", migrated)

    def test_empty_config_migrates_to_minimal(self):
        migrated = migrate_v1({})
        self.assertEqual(migrated, {"version": 2, "apply_mode": "warn"})


# ── Tests: merge semantics (FR-32, AC-8.4) ─────────────────────────────────

class TestMerge(unittest.TestCase):

    def test_overlay_key_wins(self):
        result = merge({"apply_mode": "warn"}, {"apply_mode": "enforce"})
        self.assertEqual(result["apply_mode"], "enforce")

    def test_schema_key_skipped(self):
        result = merge({}, {"$schema": "./x.json", "apply_mode": "warn"})
        self.assertNotIn("$schema", result)
        self.assertEqual(result["apply_mode"], "warn")

    def test_dict_values_spread_merged(self):
        base = {"thresholds": {"a": 1, "b": 2}}
        result = merge(base, {"thresholds": {"b": 20, "c": 3}})
        self.assertEqual(result["thresholds"], {"a": 1, "b": 20, "c": 3})

    def test_classes_merged_per_class(self):
        base = {"classes": {"architecture": {"keywords": ["a"]}, "mechanical": {"keywords": ["m"]}}}
        overlay = {"classes": {"architecture": {"patterns": ["p"]}}}
        result = merge(base, overlay)
        # architecture gains patterns, keeps keywords; mechanical untouched
        self.assertEqual(result["classes"]["architecture"]["keywords"], ["a"])
        self.assertEqual(result["classes"]["architecture"]["patterns"], ["p"])
        self.assertEqual(result["classes"]["mechanical"]["keywords"], ["m"])

    def test_new_class_added(self):
        base = {"classes": {"architecture": {"keywords": ["a"]}}}
        overlay = {"classes": {"debugging": {"keywords": ["d"]}}}
        result = merge(base, overlay)
        self.assertEqual(result["classes"]["debugging"]["keywords"], ["d"])

    def test_inputs_not_mutated(self):
        base = {"thresholds": {"a": 1}}
        overlay = {"thresholds": {"a": 2}}
        merge(base, overlay)
        self.assertEqual(base["thresholds"]["a"], 1)
        self.assertEqual(overlay["thresholds"]["a"], 2)

    def test_scalar_over_dict_replaces(self):
        result = merge({"x": {"a": 1}}, {"x": "scalar"})
        self.assertEqual(result["x"], "scalar")


# ── Tests: resolve_list extend/replace/remove (FR-33) ──────────────────────

class TestResolveListMatrix(unittest.TestCase):

    DEFAULTS_KW = ["alpha", "beta"]

    def test_extend_appends_to_defaults(self):
        cfg = {"mode": "extend", "keywords": ["gamma"]}
        self.assertEqual(resolve_list(cfg, "keywords", self.DEFAULTS_KW), ["alpha", "beta", "gamma"])

    def test_extend_is_default_mode(self):
        cfg = {"keywords": ["gamma"]}
        self.assertEqual(resolve_list(cfg, "keywords", self.DEFAULTS_KW), ["alpha", "beta", "gamma"])

    def test_replace_discards_defaults(self):
        cfg = {"mode": "replace", "keywords": ["only"]}
        self.assertEqual(resolve_list(cfg, "keywords", self.DEFAULTS_KW), ["only"])

    def test_remove_drops_default_entry(self):
        cfg = {"mode": "extend", "remove_keywords": ["alpha"]}
        self.assertEqual(resolve_list(cfg, "keywords", self.DEFAULTS_KW), ["beta"])

    def test_remove_ignored_in_replace_mode(self):
        cfg = {"mode": "replace", "keywords": ["only"], "remove_keywords": ["only"]}
        self.assertEqual(resolve_list(cfg, "keywords", self.DEFAULTS_KW), ["only"])

    def test_non_dict_class_cfg_returns_defaults(self):
        self.assertEqual(resolve_list(None, "keywords", self.DEFAULTS_KW), self.DEFAULTS_KW)


# ── Tests: v1_hint_due one-time gate (AC-8.3) ──────────────────────────────

class TestV1HintDue(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_fires_once_then_never(self):
        self.assertTrue(v1_hint_due(self.tmpdir))
        self.assertFalse(v1_hint_due(self.tmpdir))
        self.assertFalse(v1_hint_due(self.tmpdir))

    def test_writes_marker_file(self):
        v1_hint_due(self.tmpdir)
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir, "v1-hint-shown")))

    def test_empty_data_dir_returns_false(self):
        self.assertFalse(v1_hint_due(None))
        self.assertFalse(v1_hint_due(""))


# ── Tests: load_config fail-open + no file writes (AC-8.5, AC-8.2) ─────────

class TestLoadConfigSafety(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_unparseable_file_falls_back_to_defaults(self):
        bad = os.path.join(self.tmpdir, "bad.json")
        with open(bad, "w") as f:
            f.write("{ this is not json ")
        config = load_config(global_path=bad, cwd=self.tmpdir)
        self.assertEqual(config, DEFAULTS)

    def test_missing_file_returns_defaults(self):
        config = load_config(global_path=os.path.join(self.tmpdir, "nope.json"), cwd=self.tmpdir)
        self.assertEqual(config, DEFAULTS)

    def test_migration_never_writes_user_file(self):
        """Loading a v1 file must not modify it (AC-8.2): content + mtime unchanged."""
        v1_path = os.path.join(self.tmpdir, "v1.json")
        v1_body = {"opus": {"keywords": ["a"]}, "thresholds": {"opus_word_count": 300}}
        with open(v1_path, "w") as f:
            json.dump(v1_body, f)
        before_mtime = os.path.getmtime(v1_path)
        with open(v1_path) as f:
            before_content = f.read()

        config = load_config(global_path=v1_path, cwd=self.tmpdir)
        # migration happened in memory
        self.assertEqual(config["classes"]["architecture"]["keywords"], ["a"])
        self.assertEqual(config["thresholds"]["long_prompt_words"], 300)
        # source file untouched
        self.assertEqual(os.path.getmtime(v1_path), before_mtime)
        with open(v1_path) as f:
            self.assertEqual(f.read(), before_content)


# ── Tests: taxonomy per-class scoring and margin (design table) ────────────

class TestTaxonomyScoring(unittest.TestCase):

    def setUp(self):
        self.cfg = _det_cfg()

    def test_mechanical_prompt_tops_mechanical(self):
        result = score("git commit all my changes and push to origin", self.cfg)
        self.assertEqual(result.top, "mechanical")
        self.assertGreater(result.scores["mechanical"], 0)

    def test_implementation_prompt_tops_implementation(self):
        result = score("build a new React component for the login page", self.cfg)
        self.assertEqual(result.top, "implementation")

    def test_debugging_prompt_tops_debugging(self):
        result = score("debug why the test is failing with a traceback", self.cfg)
        self.assertEqual(result.top, "debugging")

    def test_architecture_prompt_tops_architecture(self):
        result = score(
            "architect a strategy to redesign the auth system tradeoff analysis deep dive",
            self.cfg,
        )
        self.assertEqual(result.top, "architecture")

    def test_margin_is_top_minus_second(self):
        result = score("git commit all my changes and push to origin", self.cfg)
        self.assertEqual(
            result.margin, result.scores[result.top] - result.scores[result.second]
        )
        self.assertGreaterEqual(result.margin, 0)


# ── Tests: signal caps, no single signal forces a tier (FR-7) ──────────────

class TestSignalCaps(unittest.TestCase):

    def setUp(self):
        self.cfg = _det_cfg()

    def test_keyword_stuffing_capped_at_text_cap(self):
        """Many implementation keywords cannot exceed the per-class text cap."""
        stuffed = (
            "build implement create fix write component service page deploy "
            "test refactor style css route api function"
        )
        result = score(stuffed, self.cfg)
        self.assertEqual(result.scores["implementation"], TEXT_CAP)

    def test_keyword_stuffing_cannot_force_extreme(self):
        """Stuffing non-architecture keywords never reaches the top (extreme) tier."""
        stuffed = (
            "build implement create fix write component service page deploy test"
        )
        result = score(stuffed, self.cfg)
        self.assertEqual(result.scores["extreme"], 0.0)
        self.assertNotEqual(result.top, "extreme")

    def test_degenerate_long_prompt_length_capped(self):
        """A 500-word content-free prompt: length signal capped, extreme stays 0."""
        result = score("word " * 500, self.cfg)
        self.assertLessEqual(result.scores["architecture"], 2.0)
        self.assertEqual(result.scores["extreme"], 0.0)

    def test_architecture_text_capped(self):
        stuffed = (
            "architect architecture evaluate tradeoff strategy strategic "
            "redesign analyze analysis rethink high-stakes"
        )
        result = score(stuffed, self.cfg)
        self.assertEqual(result.scores["architecture"], TEXT_CAP)


# ── Tests: extreme escalation only from architecture top ───────────────────

class TestExtremeEscalation(unittest.TestCase):

    def setUp(self):
        self.cfg = _det_cfg()

    def test_escalates_when_architecture_top(self):
        prompt = (
            "migration plan across the entire codebase multi-system rewrite the "
            "platform long-horizon architecture strategy redesign"
        )
        result = score(prompt, self.cfg)
        self.assertEqual(result.top, "extreme")
        self.assertGreater(result.scores["extreme"], result.scores["architecture"])

    def test_no_escalation_when_architecture_not_top(self):
        """Extreme markers present but implementation dominates: extreme stays 0."""
        prompt = (
            "build implement create fix write component migration plan "
            "multi-system epic"
        )
        result = score(prompt, self.cfg)
        self.assertEqual(result.top, "implementation")
        self.assertEqual(result.scores["extreme"], 0.0)

    def test_single_extreme_marker_below_min_no_escalation(self):
        """Architecture top with fewer than EXTREME_ESCALATION_MIN markers: no bump."""
        self.assertGreaterEqual(EXTREME_ESCALATION_MIN, 2)
        prompt = "architect a redesign strategy tradeoff analysis with a migration plan"
        result = score(prompt, self.cfg)
        self.assertEqual(result.top, "architecture")
        self.assertEqual(result.scores["extreme"], 0.0)

    def test_extreme_bump_capped(self):
        prompt = (
            "migration plan across the entire codebase multi-system rewrite the "
            "platform long-horizon epic architecture strategy redesign"
        )
        result = score(prompt, self.cfg)
        bump = result.scores["extreme"] - result.scores["architecture"]
        self.assertLessEqual(bump, EXTREME_CAP)


# ── Tests: abstain and mechanical length gate (FR-24, AC-7.1) ──────────────

class TestTaxonomyAbstain(unittest.TestCase):

    def setUp(self):
        self.cfg = _det_cfg()

    def test_empty_prompt_abstains(self):
        klass, result = classify_heuristic("", self.cfg)
        self.assertIsNone(klass)
        self.assertEqual(result.word_count, 0)

    def test_whitespace_prompt_abstains(self):
        klass, result = classify_heuristic("   \n\t  ", self.cfg)
        self.assertIsNone(klass)
        self.assertEqual(result.word_count, 0)

    def test_none_prompt_abstains(self):
        klass, _ = classify_heuristic(None, self.cfg)
        self.assertIsNone(klass)

    def test_low_signal_prompt_abstains(self):
        """A greeting with no class signal falls below the low-confidence floor."""
        klass, _ = classify_heuristic("hello there friend", self.cfg)
        self.assertIsNone(klass)

    def test_mechanical_zeroed_above_max_words(self):
        """A git op padded past mechanical_max_words loses its mechanical score."""
        max_words = self.cfg["thresholds"]["mechanical_max_words"]
        prompt = "git commit " + ("extra " * (max_words + 12))
        result = score(prompt, self.cfg)
        self.assertGreater(result.word_count, max_words)
        self.assertEqual(result.scores["mechanical"], 0.0)


# ── Tests: determinism, same prompt + config -> identical (NFR-10) ─────────

class TestTaxonomyDeterminism(unittest.TestCase):

    def setUp(self):
        self.cfg = _det_cfg()

    def test_score_identical_across_three_runs(self):
        prompt = "architect a strategy to redesign the auth system tradeoff analysis"
        runs = [score(prompt, self.cfg) for _ in range(3)]
        self.assertEqual(runs[0], runs[1])
        self.assertEqual(runs[1], runs[2])

    def test_classify_identical_across_three_runs(self):
        prompt = "debug why the integration test is failing with a stack trace"
        results = [classify_heuristic(prompt, self.cfg)[0] for _ in range(3)]
        self.assertEqual(len(set(results)), 1)

    def test_classes_tuple_matches_module_scores(self):
        result = score("build a service", self.cfg)
        self.assertEqual(set(result.scores), set(CLASSES))
        self.assertEqual(set(CLASSES), set(taxonomy.DEFAULT_KEYWORDS))


if __name__ == "__main__":
    unittest.main()
