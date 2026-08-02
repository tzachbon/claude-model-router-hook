"""Tests: config-driven advisory, config-driven variants, config-driven tier floor.

Covers the three places a model name used to be hard-coded:
  1. router.advisory - the SessionStart table and its closing prose
  2. router.variants / pre_tool_use - the routed-* variant set
  3. router.policy.apply_gates - the minimum tier for gated work

The shared property under test: with a model absent from every configured
class target, no surface can name it.
"""

import copy
import os
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_DIR = os.path.join(REPO_ROOT, "plugins", "claude-model-router-hook")
HOOKS_DIR = os.path.join(PLUGIN_DIR, "hooks")
if HOOKS_DIR not in sys.path:
    sys.path.insert(0, HOOKS_DIR)

from router import variants  # noqa: E402
from router.advisory import (  # noqa: E402
    ADVISORY_MD,
    render_advisory,
    render_session_context,
    resolved_targets,
)
from router.config import DEFAULTS  # noqa: E402
from router.ladder import Decision  # noqa: E402
from router.policy import apply_gates, min_gated_target  # noqa: E402


def _cfg(**class_targets):
    """DEFAULTS copy with the named class targets replaced."""
    cfg = copy.deepcopy(DEFAULTS)
    for klass, target in class_targets.items():
        cfg["classes"][klass]["target"] = target
    return cfg


# A config that bans sonnet outright: the shape this whole change exists for.
def _sonnet_free_cfg():
    return _cfg(
        implementation={"model": "opus", "effort": "medium"},
        debugging={"model": "opus", "effort": "high"},
    )


# ── Change 1: advisory rendered from config ────────────────────────────────

class TestAdvisoryRendersFromConfig(unittest.TestCase):

    def test_defaults_rendering_is_the_committed_form(self):
        """ADVISORY_MD is render_advisory() over DEFAULTS, so docs never drift."""
        self.assertEqual(ADVISORY_MD, render_advisory())
        self.assertEqual(ADVISORY_MD, render_advisory(copy.deepcopy(DEFAULTS)))

    def test_table_names_the_configured_model(self):
        rendered = render_advisory(_sonnet_free_cfg())
        self.assertIn("| implementation | opus | medium |", rendered)
        self.assertIn("| debugging | opus | high |", rendered)
        self.assertNotIn("sonnet", rendered)

    def test_closing_prose_names_the_configured_model(self):
        """The MANDATORY paragraph must not name a model the config rejects."""
        rendered = render_advisory(_sonnet_free_cfg())
        self.assertIn("standard coding to opus", rendered)
        self.assertNotIn("standard coding to sonnet", rendered)

    def test_session_context_is_sonnet_free_on_every_tier(self):
        cfg = _sonnet_free_cfg()
        for current in ("claude-haiku-4-5", "claude-sonnet-5", "claude-opus-4-8",
                        "claude-fable-5", "", None, "some-unknown-model"):
            context = render_session_context(current, cfg)
            lower = context.lower()
            # "You are currently on sonnet" is a statement of fact about the
            # session, not a routing target; everything else must be clean.
            lower = lower.replace("you are currently on sonnet.", "")
            self.assertNotIn("sonnet", lower, "leaked for current model %r" % current)

    def test_haiku_target_renders_effort_none(self):
        self.assertIn("| mechanical | haiku | none |", render_advisory())

    def test_effort_column_follows_config(self):
        rendered = render_advisory(_cfg(extreme={"model": "fable", "effort": "max"}))
        self.assertIn("| extreme | fable | max |", rendered)

    def test_abstain_row_is_not_configurable(self):
        self.assertIn("| abstain | (no routing) | - |", render_advisory(_sonnet_free_cfg()))

    def test_unusable_target_falls_back_to_default_without_raising(self):
        """Fail-open: a bogus model must not blank the advisory or raise."""
        for bad in ({"model": "gpt-9"}, {"model": None}, {}, "not-a-dict", None):
            cfg = copy.deepcopy(DEFAULTS)
            cfg["classes"]["implementation"]["target"] = bad
            self.assertEqual(resolved_targets(cfg)["implementation"], ("sonnet", "medium"))
            self.assertIn("| implementation | sonnet | medium |", render_advisory(cfg))

    def test_malformed_config_shapes_never_raise(self):
        for cfg in (None, {}, {"classes": None}, {"classes": {}}, {"classes": "x"}, 7):
            self.assertEqual(render_advisory(cfg), ADVISORY_MD)
            self.assertIn("## Model Tier Rules", render_session_context("opus", cfg))

    def test_advisory_matches_router_choice(self):
        """The advertised model is the one target_for_class actually returns."""
        from router.policy import target_for_class
        cfg = _sonnet_free_cfg()
        for klass, (model, effort) in resolved_targets(cfg).items():
            decision = target_for_class(klass, cfg)
            self.assertEqual((decision.model, decision.effort), (model, effort), klass)


class TestSessionInitUsesConfig(unittest.TestCase):
    """End-to-end: the SessionStart hook renders against the resolved config."""

    def _run(self, home):
        env = dict(os.environ)
        env["HOME"] = home
        env.pop("CLAUDE_MODEL_ROUTER_CHILD", None)
        env.pop("ANTHROPIC_MODEL", None)
        proc = subprocess.run(
            [sys.executable, os.path.join(HOOKS_DIR, "session_init.py")],
            input="{}", capture_output=True, text=True, env=env, cwd=home,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        import json
        return json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]

    def test_sonnet_free_config_yields_sonnet_free_context(self):
        import json
        with tempfile.TemporaryDirectory() as home:
            os.makedirs(os.path.join(home, ".claude"))
            with open(os.path.join(home, ".claude", "model-router.json"), "w") as fh:
                json.dump({
                    "version": 2,
                    "classes": {
                        "implementation": {"target": {"model": "opus", "effort": "medium"}},
                        "debugging": {"target": {"model": "opus", "effort": "high"}},
                    },
                }, fh)
            context = self._run(home)
            self.assertNotIn("sonnet", context)
            self.assertIn("| implementation | opus | medium |", context)

    def test_no_config_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as home:
            context = self._run(home)
            self.assertIn("| implementation | sonnet | medium |", context)

    def test_unreadable_config_still_emits_advisory(self):
        with tempfile.TemporaryDirectory() as home:
            os.makedirs(os.path.join(home, ".claude"))
            with open(os.path.join(home, ".claude", "model-router.json"), "w") as fh:
                fh.write("{ not json at all")
            context = self._run(home)
            self.assertIn("## Model Tier Rules", context)


# ── Change 2: variant set derived from config ──────────────────────────────

class TestVariantMap(unittest.TestCase):

    def test_defaults_map_matches_the_shipped_set(self):
        self.assertEqual(
            variants.variant_map(copy.deepcopy(DEFAULTS)),
            {
                ("haiku", None): "routed-haiku",
                ("sonnet", "medium"): "routed-sonnet-medium",
                ("sonnet", "high"): "routed-sonnet-high",
                ("opus", "high"): "routed-opus-high",
                ("fable", "high"): "routed-fable-high",
            },
        )

    def test_sonnet_free_config_declares_no_sonnet_variant(self):
        mapping = variants.variant_map(_sonnet_free_cfg())
        self.assertNotIn(("sonnet", "medium"), mapping)
        self.assertNotIn(("sonnet", "high"), mapping)
        for name in mapping.values():
            self.assertNotIn("sonnet", name)

    def test_opus_medium_gap_closes(self):
        """The (opus, medium) target had no shipped variant; config now declares it."""
        mapping = variants.variant_map(_sonnet_free_cfg())
        self.assertEqual(mapping[("opus", "medium")], "routed-opus-medium")

    def test_classes_sharing_a_target_collapse_to_one_variant(self):
        declared = variants.target_variants(_sonnet_free_cfg())
        names = [name for name, _m, _e, _c in declared]
        self.assertEqual(len(names), len(set(names)))
        shared = [c for n, _m, _e, c in declared if n == "routed-opus-high"][0]
        self.assertEqual(set(shared), {"debugging", "architecture"})

    def test_variant_name_shape(self):
        self.assertEqual(variants.variant_name("haiku", None), "routed-haiku")
        self.assertEqual(variants.variant_name("opus", "xhigh"), "routed-opus-xhigh")

    def test_unusable_target_is_skipped_not_raised(self):
        cfg = copy.deepcopy(DEFAULTS)
        cfg["classes"]["extreme"]["target"] = {"model": "gpt-9"}
        mapping = variants.variant_map(cfg)
        self.assertNotIn(("fable", "high"), mapping)
        self.assertIn(("haiku", None), mapping)

    def test_malformed_config_yields_empty_map_without_raising(self):
        for cfg in (None, {}, {"classes": {}}, "nope"):
            self.assertEqual(variants.variant_map(cfg), {})

    def test_agent_markdown_matches_committed_file(self):
        for name, model, effort, classes in variants.target_variants(
            copy.deepcopy(DEFAULTS)
        ):
            path = os.path.join(PLUGIN_DIR, "agents", name + ".md")
            with open(path, "r", encoding="utf-8") as fh:
                self.assertEqual(
                    fh.read(), variants.agent_markdown(name, model, effort, classes), name
                )

    def test_agent_markdown_omits_effort_for_haiku(self):
        md = variants.agent_markdown("routed-haiku", "haiku", None, ("mechanical",))
        self.assertNotIn("effort:", md)
        self.assertIn("model: haiku", md)

    def test_agent_markdown_names_every_sharing_class(self):
        md = variants.agent_markdown(
            "routed-opus-high", "opus", "high", ("debugging", "architecture")
        )
        self.assertIn("for debugging and architecture tasks", md)


class TestVariantGenerator(unittest.TestCase):

    SCRIPT = os.path.join(REPO_ROOT, "scripts", "generate_variants.py")

    def _run(self, *args, **kwargs):
        return subprocess.run(
            [sys.executable, self.SCRIPT] + list(args),
            capture_output=True, text=True, **kwargs
        )

    def test_committed_set_is_in_sync(self):
        """The checked-in agents dir is exactly what DEFAULTS declares."""
        proc = self._run("--check")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_generates_sonnet_free_set_and_prunes_stale(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            agents = os.path.join(tmp, "agents")
            os.makedirs(agents)
            # A stale router-owned sonnet variant left over from an older config.
            stale = os.path.join(agents, "routed-sonnet-medium.md")
            with open(stale, "w") as fh:
                fh.write(variants.agent_markdown(
                    "routed-sonnet-medium", "sonnet", "medium", ("implementation",)))

            home = os.path.join(tmp, "home")
            os.makedirs(os.path.join(home, ".claude"))
            with open(os.path.join(home, ".claude", "model-router.json"), "w") as fh:
                json.dump({
                    "version": 2,
                    "classes": {
                        "implementation": {"target": {"model": "opus", "effort": "medium"}},
                        "debugging": {"target": {"model": "opus", "effort": "high"}},
                    },
                }, fh)

            env = dict(os.environ)
            env["HOME"] = home
            proc = subprocess.run(
                [sys.executable, self.SCRIPT, "--agents-dir", agents, "--use-user-config"],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

            written = sorted(os.listdir(agents))
            self.assertEqual(
                written,
                ["routed-fable-high.md", "routed-haiku.md",
                 "routed-opus-high.md", "routed-opus-medium.md"],
            )
            self.assertFalse(os.path.exists(stale), "stale sonnet variant not pruned")

    def test_prune_spares_files_this_generator_did_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            agents = os.path.join(tmp, "agents")
            os.makedirs(agents)
            handwritten = os.path.join(agents, "routed-my-own.md")
            with open(handwritten, "w") as fh:
                fh.write("---\nname: routed-my-own\n---\n\nhand written\n")
            proc = self._run("--agents-dir", agents)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertTrue(os.path.exists(handwritten))
            self.assertIn("SKIP (not router-owned)", proc.stdout)

    def test_check_mode_reports_drift_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            agents = os.path.join(tmp, "agents")
            os.makedirs(agents)
            proc = self._run("--check", "--agents-dir", agents)
            self.assertEqual(proc.returncode, 1)
            self.assertIn("MISSING: routed-haiku.md", proc.stdout)
            self.assertEqual(os.listdir(agents), [])


class TestPreToolUseVariantSelection(unittest.TestCase):
    """End-to-end: the hook selects only variants the config declares."""

    MECH = "rename the file src/a.py to src/b.py"
    IMPL = "implement a new React component and write tests for it"

    def _spawn(self, home, prompt):
        import json
        env = dict(os.environ)
        env["HOME"] = home
        env.pop("CLAUDE_MODEL_ROUTER_CHILD", None)
        env.pop("CLAUDE_PLUGIN_ROOT", None)
        env.pop("CLAUDE_CODE_SUBAGENT_MODEL", None)
        payload = json.dumps({
            "tool_name": "Agent",
            "tool_input": {"subagent_type": "general-purpose", "prompt": prompt},
        })
        proc = subprocess.run(
            [sys.executable, os.path.join(HOOKS_DIR, "pre_tool_use.py")],
            input=payload, capture_output=True, text=True, env=env, cwd=home,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        if not proc.stdout.strip():
            return {}
        return json.loads(proc.stdout)["hookSpecificOutput"].get("updatedInput", {})

    def _home(self, cfg_dict):
        import json
        tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(tmp, ".claude"))
        if cfg_dict is not None:
            with open(os.path.join(tmp, ".claude", "model-router.json"), "w") as fh:
                json.dump(cfg_dict, fh)
        # Offline: no CLI tiebreak subprocess during tests.
        return tmp

    def test_defaults_still_select_the_shipped_variant(self):
        home = self._home({"version": 2, "classifier": {"cli_fallback": False}})
        updated = self._spawn(home, self.MECH)
        self.assertEqual(updated.get("model"), "haiku")
        self.assertEqual(updated.get("subagent_type"), "routed-haiku")

    def test_opus_medium_target_now_selects_a_variant(self):
        home = self._home({
            "version": 2,
            "classifier": {"cli_fallback": False},
            "classes": {
                "implementation": {"target": {"model": "opus", "effort": "medium"}},
                "debugging": {"target": {"model": "opus", "effort": "high"}},
            },
        })
        updated = self._spawn(home, self.IMPL)
        self.assertEqual(updated.get("model"), "opus")
        self.assertEqual(updated.get("subagent_type"), "routed-opus-medium")


# ── Change 3: gated tier floor follows the configured implementation target ──

class TestMinGatedTarget(unittest.TestCase):

    def test_defaults_are_the_shipped_implementation_target(self):
        self.assertEqual(min_gated_target(copy.deepcopy(DEFAULTS)), ("sonnet", "medium"))

    def test_follows_configured_implementation_target(self):
        self.assertEqual(min_gated_target(_sonnet_free_cfg()), ("opus", "medium"))

    def test_haiku_implementation_target_carries_no_effort(self):
        cfg = _cfg(implementation={"model": "haiku", "effort": "high"})
        self.assertEqual(min_gated_target(cfg), ("haiku", None))

    def test_invalid_values_fall_back_to_defaults(self):
        self.assertEqual(
            min_gated_target(_cfg(implementation={"model": "gpt-9"})), ("sonnet", "medium")
        )
        self.assertEqual(
            min_gated_target(_cfg(implementation={"model": "opus", "effort": "ultra"})),
            ("opus", "medium"),
        )

    def test_malformed_config_never_raises(self):
        for cfg in (None, {}, {"classes": None}, {"classes": {"implementation": 3}}, "x"):
            self.assertEqual(min_gated_target(cfg), ("sonnet", "medium"))


class TestGatedBumpFollowsConfig(unittest.TestCase):

    def _gate(self, cfg, klass="mechanical", model="haiku", effort=None,
              prompt="coordinate agents to split this work"):
        return apply_gates(prompt, Decision(model, effort, klass, "heuristic"), cfg)

    def test_capability_gate_bumps_to_configured_tier(self):
        gated = self._gate(_sonnet_free_cfg())
        self.assertEqual((gated.model, gated.effort), ("opus", "medium"))

    def test_effort_floor_bump_targets_configured_tier(self):
        gated = self._gate(
            _sonnet_free_cfg(), prompt="backfill the database and delete data"
        )
        self.assertEqual(gated.model, "opus")
        self.assertEqual(gated.effort, "high")  # data-handling floor still applies

    def test_no_sonnet_anywhere_under_a_sonnet_free_config(self):
        """Exhaustive: every class x tier x effort x trigger, no sonnet."""
        import itertools
        from router.ladder import EFFORTS, TIERS
        cfg = _sonnet_free_cfg()
        triggers = ["", "sendmessage", "hand-offs", "coordinate agents",
                    "spawn subagents", "multi-agent", "migrate", "database",
                    "production", "delete data", "backfill"]
        prompts = triggers + [
            a + " " + b for a, b in itertools.combinations(triggers, 2)
        ]
        for klass in ("mechanical", "implementation", "debugging",
                      "architecture", "extreme"):
            for model in TIERS:
                if model == "sonnet":
                    continue  # only a sonnet input could carry sonnet out
                for effort in ([None] if model == "haiku" else EFFORTS):
                    for prompt in prompts:
                        gated = apply_gates(
                            prompt, Decision(model, effort, klass, "heuristic"), cfg
                        )
                        self.assertNotEqual(
                            gated.model, "sonnet",
                            "%s/%s/%s on %r" % (klass, model, effort, prompt),
                        )

    def test_haiku_implementation_target_cannot_break_the_decision_invariant(self):
        """A floor must not put an effort on a decision that stays haiku."""
        cfg = _cfg(implementation={"model": "haiku"})
        gated = apply_gates(
            "plain prompt", Decision("haiku", None, "debugging", "heuristic"), cfg
        )
        self.assertEqual(gated.model, "haiku")
        self.assertIsNone(gated.effort)

    def test_decision_at_or_above_min_tier_is_untouched(self):
        cfg = _sonnet_free_cfg()
        decision = Decision("fable", "high", "extreme", "heuristic")
        gated = apply_gates("coordinate agents to split this work", decision, cfg)
        self.assertIs(gated, decision)

    def test_ungated_prompt_returns_the_same_object(self):
        cfg = _sonnet_free_cfg()
        decision = Decision("haiku", None, "mechanical", "heuristic")
        self.assertIs(apply_gates("rename this variable", decision, cfg), decision)


if __name__ == "__main__":
    unittest.main()
