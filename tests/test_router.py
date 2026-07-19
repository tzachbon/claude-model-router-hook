"""
Unit tests for the v2 router modules. Imports the real router package
(no logic reimplementation) and asserts behavior directly.

Phase 3.1 covers router.ladder: Decision invariants and model-string utilities.
"""

import os
import sys
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


if __name__ == "__main__":
    unittest.main()
