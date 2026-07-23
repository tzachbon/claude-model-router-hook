"""
Unit tests for the v2 router modules. Imports the real router package
(no logic reimplementation) and asserts behavior directly.

Phase 3.1 covers router.ladder: Decision invariants and model-string utilities.
"""

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

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
    ScoreResult,
    score,
    classify_heuristic,
)
from router.policy import (  # noqa: E402
    target_for_class,
    main_prompt_decision,
    apply_gates,
    DEFAULT_GATE_PATTERNS,
    DEFAULT_FLOOR_PATTERNS,
)
from router import cli_fallback  # noqa: E402
from router.cli_fallback import classify_cli  # noqa: E402


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

    def test_action_key_triggers_v1(self):
        self.assertEqual(detect_version({"action": "warn"}), 1)


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

    def test_action_autoswitch_maps_to_apply_mode(self):
        migrated = migrate_v1({"action": "autoswitch", "opus": {"keywords": ["x"]}})
        self.assertEqual(migrated["apply_mode"], "autoswitch")
        self.assertEqual(migrated["classes"]["architecture"]["keywords"], ["x"])

    def test_action_warn_stays_warn(self):
        self.assertEqual(migrate_v1({"action": "warn"})["apply_mode"], "warn")


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

    def test_partial_target_override_deep_merged(self):
        """F1: an effort-only target override keeps the inherited model."""
        base = {"classes": {"debugging": {"target": {"model": "sonnet", "effort": "high"}}}}
        overlay = {"classes": {"debugging": {"target": {"effort": "low"}}}}
        result = merge(base, overlay)
        self.assertEqual(
            result["classes"]["debugging"]["target"],
            {"model": "sonnet", "effort": "low"},
        )

    def test_model_only_target_override_keeps_deep_merge(self):
        """F1: a model-only override deep-merges over the inherited effort."""
        base = {"classes": {"debugging": {"target": {"model": "sonnet", "effort": "high"}}}}
        overlay = {"classes": {"debugging": {"target": {"model": "haiku"}}}}
        result = merge(base, overlay)
        self.assertEqual(
            result["classes"]["debugging"]["target"],
            {"model": "haiku", "effort": "high"},
        )


class TestClassTargetResolution(unittest.TestCase):
    """F1: target_for_class is robust to deep-merged and invalid targets."""

    def _cfg_with_target(self, klass, target_override):
        cfg = copy.deepcopy(DEFAULTS)
        overlay = {"classes": {klass: {"target": target_override}}}
        return merge(cfg, overlay)

    def test_effort_only_override_keeps_model(self):
        cfg = self._cfg_with_target("debugging", {"effort": "low"})
        decision = target_for_class("debugging", cfg)
        self.assertIsNotNone(decision)
        self.assertEqual(decision.model, "sonnet")
        self.assertEqual(decision.effort, "low")

    def test_model_switch_to_haiku_drops_inherited_effort(self):
        """A haiku target must not raise even if a stale effort was inherited."""
        cfg = self._cfg_with_target("debugging", {"model": "haiku"})
        decision = target_for_class("debugging", cfg)  # must not raise
        self.assertIsNotNone(decision)
        self.assertEqual(decision.model, "haiku")
        self.assertIsNone(decision.effort)

    def test_invalid_model_returns_none(self):
        cfg = copy.deepcopy(DEFAULTS)
        cfg["classes"]["debugging"]["target"] = {"model": "gpt-5"}
        self.assertIsNone(target_for_class("debugging", cfg))

    def test_missing_model_returns_none(self):
        cfg = copy.deepcopy(DEFAULTS)
        cfg["classes"]["debugging"]["target"] = {"effort": "high"}
        self.assertIsNone(target_for_class("debugging", cfg))

    def test_main_prompt_decision_skips_invalid_target(self):
        """A None target is treated as pass-through (no routing), not a crash."""
        cfg = copy.deepcopy(DEFAULTS)
        cfg["classes"]["debugging"]["target"] = {"model": "not-a-tier"}
        result = main_prompt_decision("debugging", "sonnet", "high", cfg, _score(5))
        self.assertIsNone(result)

    def test_invalid_effort_falls_back_to_default(self):
        """F3: an invalid effort string ("ultra") must not raise inside Decision;
        it falls back to the shipped default effort for the class."""
        cfg = self._cfg_with_target("debugging", {"effort": "ultra"})
        decision = target_for_class("debugging", cfg)  # must not raise
        self.assertIsNotNone(decision)
        self.assertEqual(decision.model, "sonnet")
        self.assertEqual(decision.effort, "high")  # debugging default


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
        """Extreme markers present but architecture below top: extreme stays 0.

        The markers here ("company-wide", "phased rollout") are not also
        architecture keywords, so architecture stays at 0 while implementation
        dominates; escalation only fires when architecture is among the top
        scorers (F5 narrow fix).
        """
        prompt = (
            "build implement create fix write component company-wide phased rollout"
        )
        result = score(prompt, self.cfg)
        self.assertEqual(result.top, "implementation")
        self.assertEqual(result.scores["architecture"], 0.0)
        self.assertEqual(result.scores["extreme"], 0.0)

    def test_tie_primary_pick_unchanged_without_markers(self):
        """F5: architecture==debugging tie keeps the strict-order pick (debugging)
        when extreme markers do not clear the escalation threshold."""
        prompt = "the deadlock tradeoff company-wide"  # one marker, below MIN
        result = score(prompt, self.cfg)
        self.assertEqual(result.scores["debugging"], result.scores["architecture"])
        self.assertEqual(result.top, "debugging")
        self.assertEqual(result.scores["extreme"], 0.0)

    def test_tie_with_markers_escalates_to_extreme(self):
        """F5: an architecture-tied (with debugging) prompt still escalates to
        extreme when >= EXTREME_ESCALATION_MIN extreme markers are present.

        Before the fix, escalation was gated on the tie-break-earlier pick being
        exactly architecture, so this tie routed to debugging (sonnet) and never
        reached extreme."""
        prompt = "the deadlock tradeoff company-wide phased rollout"
        result = score(prompt, self.cfg)
        self.assertEqual(result.scores["debugging"], result.scores["architecture"])
        self.assertEqual(result.top, "extreme")
        self.assertGreater(result.scores["extreme"], result.scores["architecture"])

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


# ── Tests: non-string signal entries are ignored, never raise (F3) ─────────

class TestNonStringSignals(unittest.TestCase):
    """A numeric/boolean/null keyword or pattern in config must not crash scoring."""

    def setUp(self):
        self.cfg = _det_cfg()

    def test_non_string_keywords_and_patterns_scored_without_raising(self):
        self.cfg["classes"]["architecture"]["keywords"] = [5, True, "tradeoff"]
        self.cfg["classes"]["architecture"]["patterns"] = [123, None, r"\bredesign\b"]
        # Must not raise; the valid entries still contribute to the score.
        result = score("evaluate the tradeoff and redesign the system", self.cfg)
        self.assertGreater(result.scores["architecture"], 0.0)

    def test_all_non_string_signals_score_zero(self):
        self.cfg["classes"]["debugging"]["mode"] = "replace"
        self.cfg["classes"]["debugging"]["keywords"] = [5, True]
        self.cfg["classes"]["debugging"]["patterns"] = [123, None]
        result = score("a plain sentence with no signals", self.cfg)
        self.assertEqual(result.scores["debugging"], 0.0)


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


# ── Tests: full 5x4 main-prompt matrix (FR-4, AC-2.1, design matrix) ────────

def _score(margin):
    """Minimal ScoreResult carrying just a margin (only field policy reads)."""
    return ScoreResult(scores={}, top="", second="", margin=margin, word_count=0)


class TestMainPromptMatrix(unittest.TestCase):
    """All 20 cells of the (class x current tier) suggestion matrix."""

    def setUp(self):
        self.cfg = _det_cfg()

    def _cell(self, klass, current_model, current_effort, margin=5):
        return main_prompt_decision(
            klass, current_model, current_effort, self.cfg, _score(margin)
        )

    def _assert_decision(self, decision, model, effort):
        self.assertIsNotNone(decision)
        self.assertEqual(decision.model, model)
        self.assertEqual(decision.effort, effort)

    # mechanical row (target haiku): match on haiku, guarded downroute elsewhere
    def test_mechanical_on_haiku_matches(self):
        self.assertIsNone(self._cell("mechanical", "haiku", None))

    def test_mechanical_on_sonnet_downroutes_haiku(self):
        self._assert_decision(self._cell("mechanical", "sonnet", "high"), "haiku", None)

    def test_mechanical_on_opus_downroutes_haiku(self):
        self._assert_decision(self._cell("mechanical", "opus", "high"), "haiku", None)

    def test_mechanical_on_fable_downroutes_haiku(self):
        self._assert_decision(self._cell("mechanical", "fable", "high"), "haiku", None)

    # implementation row (target sonnet/medium)
    def test_implementation_on_haiku_uproutes_sonnet(self):
        self._assert_decision(self._cell("implementation", "haiku", "high"), "sonnet", "medium")

    def test_implementation_on_sonnet_stays_medium(self):
        self._assert_decision(self._cell("implementation", "sonnet", "max"), "sonnet", "medium")

    def test_implementation_on_opus_stays_medium(self):
        self._assert_decision(self._cell("implementation", "opus", "max"), "opus", "medium")

    def test_implementation_on_fable_stays_medium(self):
        self._assert_decision(self._cell("implementation", "fable", "max"), "fable", "medium")

    # debugging row (target sonnet/high)
    def test_debugging_on_haiku_uproutes_sonnet_high(self):
        self._assert_decision(self._cell("debugging", "haiku", "high"), "sonnet", "high")

    def test_debugging_on_sonnet_stays_high(self):
        self._assert_decision(self._cell("debugging", "sonnet", "low"), "sonnet", "high")

    def test_debugging_on_opus_stays_high(self):
        self._assert_decision(self._cell("debugging", "opus", "low"), "opus", "high")

    def test_debugging_on_fable_stays_high(self):
        self._assert_decision(self._cell("debugging", "fable", "low"), "fable", "high")

    # architecture row (target opus/high; xhigh when already on opus)
    def test_architecture_on_haiku_uproutes_opus_high(self):
        self._assert_decision(self._cell("architecture", "haiku", "high"), "opus", "high")

    def test_architecture_on_sonnet_uproutes_opus_high(self):
        self._assert_decision(self._cell("architecture", "sonnet", "high"), "opus", "high")

    def test_architecture_on_opus_stays_xhigh(self):
        self._assert_decision(self._cell("architecture", "opus", "low"), "opus", "xhigh")

    def test_architecture_on_fable_stays_high(self):
        self._assert_decision(self._cell("architecture", "fable", "low"), "fable", "high")

    # extreme row (target fable/high; xhigh when already on fable)
    def test_extreme_on_haiku_uproutes_fable_high(self):
        self._assert_decision(self._cell("extreme", "haiku", "high"), "fable", "high")

    def test_extreme_on_sonnet_uproutes_fable_high(self):
        self._assert_decision(self._cell("extreme", "sonnet", "high"), "fable", "high")

    def test_extreme_on_opus_uproutes_fable_high(self):
        self._assert_decision(self._cell("extreme", "opus", "high"), "fable", "high")

    def test_extreme_on_fable_stays_xhigh(self):
        self._assert_decision(self._cell("extreme", "fable", "low"), "fable", "xhigh")

    def test_haiku_decisions_never_carry_effort(self):
        """Every haiku result across the matrix (and target) has effort None."""
        for current in TIERS:
            eff = None if current == "haiku" else "high"
            d = self._cell("mechanical", current, eff)
            if d is not None and d.model == "haiku":
                self.assertIsNone(d.effort)
        self.assertIsNone(target_for_class("mechanical", self.cfg).effort)


# ── Tests: downroute guard (FR-5, asymmetric threshold) ────────────────────

class TestDownrouteGuard(unittest.TestCase):

    def setUp(self):
        self.cfg = _det_cfg()  # downroute_margin = 4

    def test_high_margin_allows_downroute_to_haiku(self):
        d = main_prompt_decision("mechanical", "opus", "high", self.cfg, _score(4))
        self._assert_haiku(d)

    def test_margin_above_threshold_downroutes(self):
        d = main_prompt_decision("mechanical", "sonnet", "high", self.cfg, _score(7))
        self._assert_haiku(d)

    def test_low_margin_blocks_downroute(self):
        d = main_prompt_decision("mechanical", "opus", "high", self.cfg, _score(3))
        self.assertIsNone(d)

    def test_none_score_blocks_downroute(self):
        d = main_prompt_decision("mechanical", "sonnet", "high", self.cfg, None)
        self.assertIsNone(d)

    def test_guard_does_not_gate_nonhaiku_stay(self):
        """Non-haiku target above current tier stays regardless of margin."""
        d = main_prompt_decision("implementation", "opus", "max", self.cfg, _score(0))
        self.assertEqual(d.model, "opus")
        self.assertEqual(d.effort, "medium")

    def _assert_haiku(self, d):
        self.assertIsNotNone(d)
        self.assertEqual(d.model, "haiku")
        self.assertIsNone(d.effort)


# ── Tests: capability gates (FR-21, AC-6.3) ────────────────────────────────

class TestCapabilityGates(unittest.TestCase):

    def setUp(self):
        self.cfg = _det_cfg()

    def test_handoff_never_haiku(self):
        decision = target_for_class("mechanical", self.cfg)  # haiku, no effort
        gated = apply_gates("coordinate agents to split this work", decision, self.cfg)
        self.assertEqual(gated.model, "sonnet")
        self.assertEqual(gated.effort, "medium")

    def test_sendmessage_gate_bumps_haiku(self):
        decision = target_for_class("mechanical", self.cfg)
        gated = apply_gates("use SendMessage to hand off", decision, self.cfg)
        self.assertEqual(gated.model, "sonnet")

    def test_multi_agent_gate_bumps_haiku(self):
        decision = target_for_class("mechanical", self.cfg)
        gated = apply_gates("run a multi-agent workflow", decision, self.cfg)
        self.assertEqual(gated.model, "sonnet")

    def test_no_gate_leaves_haiku(self):
        decision = target_for_class("mechanical", self.cfg)
        gated = apply_gates("rename this variable everywhere", decision, self.cfg)
        self.assertEqual(gated.model, "haiku")
        self.assertIsNone(gated.effort)
        self.assertIs(gated, decision)

    def test_gate_leaves_higher_tier_untouched(self):
        decision = Decision("opus", "high", "architecture", "heuristic")
        gated = apply_gates("coordinate agents for the redesign", decision, self.cfg)
        self.assertEqual(gated.model, "opus")
        self.assertEqual(gated.effort, "high")


# ── Tests: effort floors (FR-22, AC-6.5, data-handling) ────────────────────

class TestEffortFloors(unittest.TestCase):

    def setUp(self):
        self.cfg = _det_cfg()

    def test_debugging_floor_raises_low_to_high(self):
        decision = Decision("sonnet", "low", "debugging", "heuristic")
        gated = apply_gates("plain prompt", decision, self.cfg)
        self.assertEqual(gated.effort, "high")

    def test_debugging_floor_leaves_high_alone(self):
        decision = Decision("sonnet", "high", "debugging", "heuristic")
        gated = apply_gates("plain prompt", decision, self.cfg)
        self.assertIs(gated, decision)

    def test_data_handling_floor_raises_effort(self):
        decision = Decision("sonnet", "low", "implementation", "heuristic")
        gated = apply_gates("run the database migration on prod", decision, self.cfg)
        self.assertEqual(gated.effort, "high")

    def test_data_handling_floor_implies_min_sonnet(self):
        """A data-handling prompt on a haiku decision -> min tier sonnet + floor."""
        decision = Decision("haiku", None, "mechanical", "heuristic")
        gated = apply_gates("backfill the database and delete data", decision, self.cfg)
        self.assertEqual(gated.model, "sonnet")
        self.assertEqual(gated.effort, "high")

    def test_no_floor_leaves_decision(self):
        decision = Decision("sonnet", "medium", "implementation", "heuristic")
        gated = apply_gates("write a small helper function", decision, self.cfg)
        self.assertIs(gated, decision)


# ── Tests: gate/floor pattern resolution parity with classes (F9) ──────────

class TestGateFloorResolutionParity(unittest.TestCase):
    """capability_gates / effort_floors resolve via config.resolve_list, so
    extend/replace/remove_patterns behave exactly as they do for classes."""

    def setUp(self):
        self.cfg = _det_cfg()

    def test_remove_default_gate_pattern_disables_bump(self):
        """remove_patterns drops a shipped gate default (parity with class remove)."""
        self.cfg["capability_gates"] = {
            "mode": "extend",
            "patterns": [],
            "remove_patterns": [r"\bmulti[-\s]?agent\b"],
        }
        decision = target_for_class("mechanical", self.cfg)  # haiku
        gated = apply_gates("run a multi-agent workflow", decision, self.cfg)
        self.assertEqual(gated.model, "haiku")  # default gate removed -> no bump

    def test_extend_gate_pattern_adds_bump(self):
        self.cfg["capability_gates"] = {
            "mode": "extend",
            "patterns": [r"\bwidgetize\b"],
            "remove_patterns": [],
        }
        decision = target_for_class("mechanical", self.cfg)
        gated = apply_gates("please widgetize the thing", decision, self.cfg)
        self.assertEqual(gated.model, "sonnet")

    def test_replace_mode_discards_default_floor_patterns(self):
        self.cfg["effort_floors"] = {
            "mode": "replace",
            "patterns": [r"\bcustomfloor\b"],
            "floor": "high",
        }
        decision = Decision("sonnet", "low", "implementation", "heuristic")
        # A default floor phrase no longer raises the floor under replace mode.
        gated = apply_gates("run the database migration on prod", decision, self.cfg)
        self.assertEqual(gated.effort, "low")
        # The custom floor pattern does raise it.
        gated2 = apply_gates("apply the customfloor step", decision, self.cfg)
        self.assertEqual(gated2.effort, "high")

    def test_resolution_matches_config_resolve_list(self):
        """The gate resolver is config.resolve_list itself (no divergent copy)."""
        from router.config import resolve_list
        edit = {
            "mode": "extend",
            "patterns": [r"\bx\b"],
            "remove_patterns": [DEFAULT_GATE_PATTERNS[0]],
        }
        resolved = resolve_list(edit, "patterns", DEFAULT_GATE_PATTERNS)
        self.assertNotIn(DEFAULT_GATE_PATTERNS[0], resolved)
        self.assertIn(r"\bx\b", resolved)
        self.assertIn(DEFAULT_FLOOR_PATTERNS[0],
                      resolve_list({}, "patterns", DEFAULT_FLOOR_PATTERNS))


# ── Tests: effort_warn_distance match logic (AC-1.1/1.2 amendment) ──────────

class TestEffortWarnDistance(unittest.TestCase):

    def setUp(self):
        self.cfg = _det_cfg()  # effort_warn_distance = 2

    def test_distance_one_is_silent(self):
        """debugging target high; current xhigh (distance 1) -> match (None)."""
        d = main_prompt_decision("debugging", "sonnet", "xhigh", self.cfg, _score(0))
        self.assertIsNone(d)

    def test_distance_below_warn_is_silent(self):
        d = main_prompt_decision("debugging", "sonnet", "medium", self.cfg, _score(0))
        self.assertIsNone(d)

    def test_distance_two_warns(self):
        """current low vs target high (distance 2) -> Decision emitted."""
        d = main_prompt_decision("debugging", "sonnet", "low", self.cfg, _score(0))
        self.assertIsNotNone(d)
        self.assertEqual(d.model, "sonnet")
        self.assertEqual(d.effort, "high")

    def test_tier_mismatch_always_warns_regardless_of_effort(self):
        """Up-route target even when effort already matches (distance 0)."""
        d = main_prompt_decision("architecture", "sonnet", "high", self.cfg, _score(0))
        self.assertEqual(d.model, "opus")
        self.assertEqual(d.effort, "high")


class TestCliFallback(unittest.TestCase):
    """classify_cli fail-open ladder and child guard (mocked subprocess)."""

    def setUp(self):
        # cli_fallback on so the subprocess path is exercised; data_dir None
        # skips caching so every call hits the mocked subprocess.
        self.cfg = {"classifier": {"cli_fallback": True, "cli_timeout_seconds": 8}}

    @staticmethod
    def _completed(returncode=0, stdout=""):
        return subprocess.CompletedProcess(
            args=["claude"], returncode=returncode, stdout=stdout, stderr=""
        )

    def test_valid_class_reply_parsed(self):
        with mock.patch.object(cli_fallback.subprocess, "run",
                               return_value=self._completed(0, "architecture\n")) as run:
            self.assertEqual(classify_cli("design a system", self.cfg, None), "architecture")
        self.assertEqual(run.call_count, 1)

    def test_abstain_reply_parsed(self):
        with mock.patch.object(cli_fallback.subprocess, "run",
                               return_value=self._completed(0, "abstain")):
            self.assertEqual(classify_cli("???", self.cfg, None), "abstain")

    def test_garbage_reply_is_none(self):
        with mock.patch.object(cli_fallback.subprocess, "run",
                               return_value=self._completed(0, "banana split please")):
            self.assertIsNone(classify_cli("x", self.cfg, None))

    def test_empty_reply_is_none(self):
        with mock.patch.object(cli_fallback.subprocess, "run",
                               return_value=self._completed(0, "   \n")):
            self.assertIsNone(classify_cli("x", self.cfg, None))

    def test_nonzero_exit_is_none(self):
        with mock.patch.object(cli_fallback.subprocess, "run",
                               return_value=self._completed(1, "architecture")):
            self.assertIsNone(classify_cli("x", self.cfg, None))

    def test_timeout_is_none(self):
        with mock.patch.object(cli_fallback.subprocess, "run",
                               side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=8)):
            self.assertIsNone(classify_cli("x", self.cfg, None))

    def test_missing_binary_is_none(self):
        with mock.patch.object(cli_fallback.subprocess, "run",
                               side_effect=FileNotFoundError()):
            self.assertIsNone(classify_cli("x", self.cfg, None))

    def test_os_error_is_none(self):
        with mock.patch.object(cli_fallback.subprocess, "run",
                               side_effect=OSError()):
            self.assertIsNone(classify_cli("x", self.cfg, None))

    def test_subprocess_env_carries_child_flag(self):
        with mock.patch.object(cli_fallback.subprocess, "run",
                               return_value=self._completed(0, "mechanical")) as run:
            classify_cli("rename a file", self.cfg, None)
        _, kwargs = run.call_args
        self.assertEqual(kwargs["env"].get("CLAUDE_MODEL_ROUTER_CHILD"), "1")

    def test_cli_fallback_disabled_skips_subprocess(self):
        cfg = {"classifier": {"cli_fallback": False}}
        with mock.patch.object(cli_fallback.subprocess, "run") as run:
            self.assertIsNone(classify_cli("anything", cfg, None))
        run.assert_not_called()

    def test_timeout_clamped_to_ceiling(self):
        """A configured cli_timeout_seconds above the ceiling is clamped down (F4)."""
        cfg = {"classifier": {"cli_fallback": True, "cli_timeout_seconds": 20}}
        with mock.patch.object(cli_fallback.subprocess, "run",
                               return_value=self._completed(0, "architecture")) as run:
            classify_cli("design a system", cfg, None)
        _, kwargs = run.call_args
        self.assertLessEqual(kwargs["timeout"], cli_fallback.CLI_TIMEOUT_CEILING)
        self.assertEqual(kwargs["timeout"], cli_fallback.CLI_TIMEOUT_CEILING)

    def test_timeout_below_ceiling_preserved(self):
        cfg = {"classifier": {"cli_fallback": True, "cli_timeout_seconds": 3}}
        with mock.patch.object(cli_fallback.subprocess, "run",
                               return_value=self._completed(0, "architecture")) as run:
            classify_cli("design a system", cfg, None)
        _, kwargs = run.call_args
        self.assertEqual(kwargs["timeout"], 3)


class TestCliFallbackCache(unittest.TestCase):
    """classify_cli disk cache: hit, eviction, corruption, privacy (mocked)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cfg = {"classifier": {"cli_fallback": True, "cli_timeout_seconds": 8}}

    @staticmethod
    def _completed(returncode=0, stdout=""):
        return subprocess.CompletedProcess(
            args=["claude"], returncode=returncode, stdout=stdout, stderr=""
        )

    def _cache_file(self):
        return os.path.join(self.tmpdir, cli_fallback.CACHE_FILENAME)

    def test_cache_hit_skips_subprocess(self):
        """Second call with the same prompt is served from cache (AC-7.5)."""
        prompt = "design the whole auth architecture"
        with mock.patch.object(cli_fallback.subprocess, "run",
                               return_value=self._completed(0, "architecture")) as run:
            first = classify_cli(prompt, self.cfg, self.tmpdir)
            second = classify_cli(prompt, self.cfg, self.tmpdir)
        self.assertEqual(first, "architecture")
        self.assertEqual(second, "architecture")
        self.assertEqual(run.call_count, 1)

    def test_data_dir_none_writes_no_cache_still_returns(self):
        """CLAUDE_PLUGIN_DATA unset (data_dir None): no cache file, still returns."""
        with mock.patch.object(cli_fallback.subprocess, "run",
                               return_value=self._completed(0, "mechanical")) as run:
            result = classify_cli("rename a file", self.cfg, None)
        self.assertEqual(result, "mechanical")
        self.assertEqual(run.call_count, 1)
        self.assertFalse(os.path.exists(self._cache_file()))

    def test_corrupt_cache_discarded_and_rewritten(self):
        """A garbage cache file is ignored, subprocess runs, file rewritten (NFR-9)."""
        with open(self._cache_file(), "w") as fh:
            fh.write("{ not json at all ")
        with mock.patch.object(cli_fallback.subprocess, "run",
                               return_value=self._completed(0, "debugging")) as run:
            result = classify_cli("debug the failing test", self.cfg, self.tmpdir)
        self.assertEqual(result, "debugging")
        self.assertEqual(run.call_count, 1)
        with open(self._cache_file()) as fh:
            cache = json.load(fh)
        self.assertIsInstance(cache, dict)
        self.assertEqual(len(cache), 1)

    def test_eviction_drops_oldest_fraction(self):
        """Exceeding cache_max_entries evicts the oldest 20% by timestamp."""
        cfg = {"classifier": {
            "cli_fallback": True, "cli_timeout_seconds": 8, "cache_max_entries": 5,
        }}
        prompts = ["prompt number %d with unique text" % i for i in range(6)]
        clock = iter(range(100, 200))
        with mock.patch.object(cli_fallback.subprocess, "run",
                               return_value=self._completed(0, "implementation")):
            with mock.patch.object(cli_fallback.time, "time", lambda: next(clock)):
                for prompt in prompts:
                    classify_cli(prompt, cfg, self.tmpdir)
        with open(self._cache_file()) as fh:
            cache = json.load(fh)
        # 6 stored, max 5 -> oldest max(1, int(5*0.2))=1 dropped
        self.assertEqual(len(cache), 5)
        self.assertNotIn(cli_fallback._cache_key(prompts[0]), cache)
        self.assertIn(cli_fallback._cache_key(prompts[5]), cache)

    def test_cache_hit_on_shared_snippet_prefix(self):
        """Two prompts identical over the first SNIPPET_MAX_CHARS but differing
        after share a cache entry, so the second call is a hit (F8)."""
        base = "design the whole auth architecture tradeoffs and data model " * 40
        self.assertGreater(len(base), cli_fallback.SNIPPET_MAX_CHARS)
        p1 = base + " UNIQUE_TAIL_ONE"
        p2 = base + " UNIQUE_TAIL_TWO"
        self.assertNotEqual(p1, p2)
        with mock.patch.object(cli_fallback.subprocess, "run",
                               return_value=self._completed(0, "architecture")) as run:
            first = classify_cli(p1, self.cfg, self.tmpdir)
            second = classify_cli(p2, self.cfg, self.tmpdir)
        self.assertEqual(first, "architecture")
        self.assertEqual(second, "architecture")
        self.assertEqual(run.call_count, 1)  # second served from cache

    def test_cache_file_has_hashes_and_classes_only(self):
        """Cache stores hash keys + class/timestamp, never raw prompt text (NFR-5)."""
        prompt = "SECRETMARKER build the payment service integration"
        with mock.patch.object(cli_fallback.subprocess, "run",
                               return_value=self._completed(0, "implementation")):
            classify_cli(prompt, self.cfg, self.tmpdir)
        with open(self._cache_file()) as fh:
            raw = fh.read()
        self.assertNotIn("SECRETMARKER", raw)
        self.assertNotIn("payment", raw)
        cache = json.loads(raw)
        (key, entry), = cache.items()
        self.assertEqual(key, cli_fallback._cache_key(prompt))
        self.assertEqual(set(entry), {"c", "t"})
        self.assertEqual(entry["c"], "implementation")


AGENTS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "plugins", "claude-model-router-hook", "agents"
)


def _parse_frontmatter(path):
    """Parse the leading --- YAML frontmatter block into a flat dict."""
    fields = {}
    with open(path) as fh:
        lines = fh.read().splitlines()
    if not lines or lines[0].strip() != "---":
        return fields
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    return fields


class TestVariantCoverage(unittest.TestCase):
    """Every default class target has a shipped routed-* variant (AC-4.2)."""

    def _variant_name(self, model, effort):
        """Same convention pre_tool_use.py uses: routed-<model>[-<effort>]."""
        return "routed-" + model if effort is None else f"routed-{model}-{effort}"

    def test_every_default_target_has_matching_variant(self):
        classes = DEFAULTS["classes"]
        self.assertEqual(len(classes), 5)
        for class_name, class_cfg in classes.items():
            target = class_cfg["target"]
            model = target["model"]
            effort = target.get("effort")
            variant = self._variant_name(model, effort)
            path = os.path.join(AGENTS_DIR, variant + ".md")
            self.assertTrue(
                os.path.exists(path),
                f"{class_name} target -> missing variant {variant}.md",
            )
            fm = _parse_frontmatter(path)
            self.assertEqual(fm.get("name"), variant)
            self.assertEqual(fm.get("model"), model)
            if effort is None:
                self.assertNotIn("effort", fm)
            else:
                self.assertEqual(fm.get("effort"), effort)


if __name__ == "__main__":
    unittest.main()
