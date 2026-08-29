"""Tests: config-driven advisory, config-driven variants, config-driven tier floor.

Covers the three places a model name used to be hard-coded:
  1. router.advisory - the SessionStart table and its closing prose
  2. router.variants / pre_tool_use - the routed-* variant set
  3. router.policy.apply_gates - the minimum tier for gated work

The shared property under test: with a model absent from every configured
class target, no surface can name it. Plus the two boundaries that protect a
user's own files (agent-file ownership) and the user's attention (telling them
when the installed variant set is behind the config).
"""

import copy
import itertools
import json
import os
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_DIR = os.path.join(REPO_ROOT, "plugins", "claude-model-router-hook")
MANUAL_INSTALLER = os.path.join(PLUGIN_DIR, "install.sh")
HOOKS_DIR = os.path.join(PLUGIN_DIR, "hooks")
AGENTS_DIR = os.path.join(PLUGIN_DIR, "agents")
GENERATOR = os.path.join(REPO_ROOT, "scripts", "generate_variants.py")
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
from router.ladder import EFFORTS, TIERS, Decision  # noqa: E402
from router.policy import (  # noqa: E402
    apply_gates,
    gate_outcomes,
    main_prompt_decision,
    min_gated_target,
    target_for_class,
)

# The advisory table as the shipped defaults describe it, pinned as bytes.
# render_advisory() produces this; comparing the renderer to itself would be
# green by construction, so the expected text is spelled out here instead.
EXPECTED_ADVISORY_MD = """\
## Model Tier Rules

These rules apply to YOU and to every sub-agent you spawn.

### Task classes and default targets

| Class | Target model | Effort | When to use |
|---|---|---|---|
| mechanical | haiku | none | Git ops, renames, formatting, lint, file moves, version bumps, quick lookups, short imperative tasks. |
| implementation | opus | medium | Writing or editing code, building features, creating components or APIs, writing tests, standard feature work. |
| debugging | opus | high | Diagnosing failures, flaky tests, races, regressions, stack traces, bisecting, reproducing bugs. |
| architecture | opus | xhigh | Architecture decisions, tradeoff analysis, redesigns, deep multi-file analysis, sustained reasoning over large context. |
| extreme | opus | max | Multi-system migrations, codebase-wide rewrites, long-horizon plans, RFCs and design docs, platform-scale work. |
| abstain | (no routing) | - | Prompt does not clearly match any class; current model and effort pass through unmodified. |

### Sub-agent model selection (MANDATORY)

When calling the Agent tool, set the model parameter to match the task class
above. Do not default every sub-agent to the highest effort. Match the model
and effort to the work: mechanical work goes to haiku, implementation to opus,
debugging to opus, deep analysis to opus, and platform-scale work to opus.
"""

TRIGGERS = (
    "", "sendmessage", "hand-offs", "coordinate agents", "spawn subagents",
    "multi-agent", "migrate", "database", "production", "delete data", "backfill",
)
GATE_PROMPTS = list(TRIGGERS) + [
    a + " " + b for a, b in itertools.combinations(TRIGGERS, 2)
]

MALFORMED_CFGS = (None, {}, {"classes": None}, {"classes": {}}, {"classes": "x"},
                  {"classes": {"implementation": 3}}, 7, "nope", [])

# Nested containers holding a non-dict. Every one of these used to reach a
# .get on a string, an int or None somewhere on the new code paths.
NESTED_MALFORMED_CFGS = (
    {"effort_floors": "broken"},
    {"effort_floors": 7},
    {"effort_floors": True},
    {"effort_floors": []},
    {"effort_floors": {"floor": {"nested": "dict"}}},
    {"capability_gates": "broken"},
    {"capability_gates": 0},
    {"thresholds": "broken"},
    {"classes": {"implementation": {"target": "broken"}}},
    {"classes": {"implementation": {"target": {"model": []}}}},
    {"classes": {"implementation": "broken"}, "effort_floors": "broken"},
)


def _cfg(**class_targets):
    """DEFAULTS copy with the named class targets replaced."""
    cfg = copy.deepcopy(DEFAULTS)
    for klass, target in class_targets.items():
        cfg["classes"][klass]["target"] = target
    return cfg


def _sonnet_free_cfg():
    """A config that bans sonnet outright: the shape this change exists for."""
    return _cfg(
        implementation={"model": "opus", "effort": "medium"},
        debugging={"model": "opus", "effort": "high"},
    )


def _write_home(tmp, cfg_dict=None, agents=()):
    """A temp HOME with an optional router config and agent files."""
    os.makedirs(os.path.join(tmp, ".claude"), exist_ok=True)
    if cfg_dict is not None:
        with open(os.path.join(tmp, ".claude", "model-router.json"), "w") as fh:
            json.dump(cfg_dict, fh)
    if agents:
        agent_dir = os.path.join(tmp, ".claude", "agents")
        os.makedirs(agent_dir, exist_ok=True)
        for name, model, effort, classes in agents:
            with open(os.path.join(agent_dir, name + ".md"), "w") as fh:
                fh.write(variants.agent_markdown(name, model, effort, classes))
    return tmp


def _run_hook(script, payload, home, extra_env=None):
    """Run a hook entrypoint under a temp HOME; return (returncode, stdout)."""
    env = dict(os.environ)
    env["HOME"] = home
    for key in ("CLAUDE_MODEL_ROUTER_CHILD", "CLAUDE_PLUGIN_ROOT",
                "CLAUDE_CODE_SUBAGENT_MODEL", "ANTHROPIC_MODEL"):
        env.pop(key, None)
    env.update(extra_env or {})
    proc = subprocess.run(
        [sys.executable, os.path.join(HOOKS_DIR, script)],
        input=payload, capture_output=True, text=True, env=env, cwd=home,
    )
    return proc.returncode, proc.stdout


# ── Change 1: advisory rendered from config ────────────────────────────────

class TestAdvisoryRendersFromConfig(unittest.TestCase):

    def test_defaults_rendering_is_pinned_to_bytes(self):
        """The committed-doc form, spelled out rather than round-tripped."""
        self.assertEqual(ADVISORY_MD, EXPECTED_ADVISORY_MD)

    def test_explicit_defaults_config_renders_the_same(self):
        self.assertEqual(render_advisory(copy.deepcopy(DEFAULTS)), EXPECTED_ADVISORY_MD)

    def test_table_names_the_configured_model(self):
        rendered = render_advisory(_sonnet_free_cfg())
        self.assertIn("| implementation | opus | medium |", rendered)
        self.assertIn("| debugging | opus | high |", rendered)
        self.assertNotIn("sonnet", rendered)

    def test_closing_prose_names_the_configured_model(self):
        rendered = render_advisory(_sonnet_free_cfg())
        self.assertIn("implementation to opus", rendered)
        self.assertNotIn("implementation to sonnet", rendered)

    def test_session_context_is_sonnet_free_on_every_tier(self):
        cfg = _sonnet_free_cfg()
        for current in ("claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5",
                        "claude-fable-5", "", None, "some-unknown-model"):
            context = render_session_context(current, cfg)
            # "You are currently on sonnet" states a fact about the session,
            # not a routing target; everything else must be clean.
            lower = context.lower().replace("you are currently on sonnet.", "")
            self.assertNotIn("sonnet", lower, "leaked for current model %r" % current)

    def test_haiku_target_renders_effort_none(self):
        self.assertIn("| mechanical | haiku | none |", render_advisory())

    def test_effort_column_follows_config(self):
        rendered = render_advisory(_cfg(extreme={"model": "fable", "effort": "max"}))
        self.assertIn("| extreme | fable | max |", rendered)

    def test_abstain_row_is_not_configurable(self):
        self.assertIn("| abstain | (no routing) | - |",
                      render_advisory(_sonnet_free_cfg()))


class TestAdvisoryMatchesEnforcement(unittest.TestCase):
    """The advisory must never advertise a decision enforcement will not make."""

    def _assert_agrees(self, cfg):
        for klass, target in resolved_targets(cfg).items():
            decision = target_for_class(klass, cfg)
            if decision is None:
                self.assertIsNone(target, "%s: advertised but unroutable" % klass)
            else:
                self.assertEqual((decision.model, decision.effort), target, klass)

    def test_agrees_on_a_valid_config(self):
        self._assert_agrees(_sonnet_free_cfg())

    def test_agrees_on_every_malformed_target(self):
        for bad in ({"model": "gpt-9"}, {"model": None}, {"model": "sonnet-5"},
                    {}, "not-a-dict", None, 7):
            cfg = copy.deepcopy(DEFAULTS)
            cfg["classes"]["implementation"]["target"] = bad
            self._assert_agrees(cfg)

    def test_agrees_on_every_malformed_config_shape(self):
        for cfg in MALFORMED_CFGS:
            if not isinstance(cfg, dict):
                continue  # non-dict renders DEFAULTS, nothing to enforce against
            self._assert_agrees(cfg)

    def test_unroutable_class_is_advertised_as_unroutable(self):
        """A rejected target must not be replaced by a shipped default."""
        cfg = copy.deepcopy(DEFAULTS)
        cfg["classes"]["implementation"]["target"] = {"model": "gpt-9", "effort": "medium"}
        rendered = render_advisory(cfg)
        self.assertIn("| implementation | (no routing) | - |", rendered)
        self.assertNotIn("| implementation | opus | medium |", rendered)
        # The prose must not name a model for it either.
        self.assertNotIn("implementation to", rendered)
        self.assertIn("mechanical work goes to haiku", rendered)

    def test_classes_null_advertises_nothing_routable(self):
        rendered = render_advisory({"classes": None})
        for klass in ("mechanical", "implementation", "debugging",
                      "architecture", "extreme"):
            self.assertIn("| %s | (no routing) | - |" % klass, rendered)
        self.assertIn("No class is routable under this config", rendered)
        self.assertNotIn("sonnet", rendered)

    def test_unroutable_architecture_still_yields_a_closing_sentence(self):
        cfg = copy.deepcopy(DEFAULTS)
        cfg["classes"]["architecture"]["target"] = {"model": "gpt-9"}
        rendered = render_advisory(cfg)
        self.assertIn("Do not default every sub-agent to the highest effort", rendered)
        self.assertNotIn("deep analysis to", rendered)

    def test_non_dict_config_renders_the_shipped_defaults(self):
        for cfg in (None, 7, "nope", []):
            self.assertEqual(render_advisory(cfg), EXPECTED_ADVISORY_MD)

    def test_no_malformed_shape_raises(self):
        for cfg in MALFORMED_CFGS:
            self.assertIn("## Model Tier Rules", render_advisory(cfg))
            self.assertIn("## Model Tier Rules", render_session_context("opus", cfg))

    def test_tier_hint_drops_clauses_for_unroutable_classes(self):
        cfg = copy.deepcopy(DEFAULTS)
        cfg["classes"]["implementation"]["target"] = {"model": "gpt-9"}
        context = render_session_context("claude-opus-5", cfg)
        self.assertIn("For mechanical tasks haiku is cheaper.", context)
        self.assertNotIn("standard implementation", context)

    def test_tier_hint_survives_every_class_being_unroutable(self):
        context = render_session_context("claude-opus-5", {"classes": None})
        self.assertIn("You are currently on opus.", context)


class TestSessionInitUsesConfig(unittest.TestCase):
    """End-to-end: the SessionStart hook renders against the resolved config."""

    def _context(self, home):
        code, stdout = _run_hook("session_init.py", "{}", home)
        self.assertEqual(code, 0)
        return json.loads(stdout)["hookSpecificOutput"]["additionalContext"]

    def test_sonnet_free_config_yields_sonnet_free_context(self):
        with tempfile.TemporaryDirectory() as home:
            _write_home(home, {
                "version": 2,
                "classes": {
                    "implementation": {"target": {"model": "opus", "effort": "medium"}},
                    "debugging": {"target": {"model": "opus", "effort": "high"}},
                },
            }, agents=[("routed-haiku", "haiku", None, ("mechanical",)),
                       ("routed-opus-medium", "opus", "medium", ("implementation",)),
                       ("routed-opus-high", "opus", "high", ("debugging",)),
                       ("routed-opus-xhigh", "opus", "xhigh", ("architecture",)),
                       ("routed-opus-max", "opus", "max", ("extreme",))])
            context = self._context(home)
            self.assertNotIn("sonnet", context)
            self.assertIn("| implementation | opus | medium |", context)
            self.assertNotIn("Routed variants out of date", context)

    def test_no_config_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as home:
            _write_home(home, None, agents=[
                (name, model, effort, classes)
                for name, model, effort, classes
                in variants.target_variants(copy.deepcopy(DEFAULTS))
            ])
            self.assertIn("| implementation | opus | medium |", self._context(home))

    def test_unreadable_config_still_emits_advisory(self):
        with tempfile.TemporaryDirectory() as home:
            os.makedirs(os.path.join(home, ".claude"))
            with open(os.path.join(home, ".claude", "model-router.json"), "w") as fh:
                fh.write("{ not json at all")
            self.assertIn("## Model Tier Rules", self._context(home))


class TestSessionInitDivergenceWarning(unittest.TestCase):
    """F7: a config ahead of the installed agent set must not be silent."""

    def _context(self, home):
        code, stdout = _run_hook("session_init.py", "{}", home)
        self.assertEqual(code, 0)
        return json.loads(stdout)["hookSpecificOutput"]["additionalContext"]

    def test_warns_when_a_declared_variant_is_not_installed(self):
        with tempfile.TemporaryDirectory() as home:
            _write_home(home, {
                "version": 2,
                "classes": {
                    "implementation": {"target": {"model": "opus", "effort": "medium"}},
                },
            }, agents=[("routed-haiku", "haiku", None, ("mechanical",))])
            context = self._context(home)
            self.assertIn("Routed variants out of date", context)
            self.assertIn("routed-opus-medium", context)
            self.assertIn("Re-run install.sh", context)

    def test_no_warning_when_every_declared_variant_is_installed(self):
        with tempfile.TemporaryDirectory() as home:
            _write_home(home, {"version": 2}, agents=list(
                variants.target_variants(copy.deepcopy(DEFAULTS))
            ))
            self.assertNotIn("Routed variants out of date", self._context(home))

    def test_plugin_agents_dir_counts_as_installed(self):
        with tempfile.TemporaryDirectory() as home:
            _write_home(home, {"version": 2})
            code, stdout = _run_hook(
                "session_init.py", "{}", home,
                extra_env={"CLAUDE_PLUGIN_ROOT": PLUGIN_DIR},
            )
            self.assertEqual(code, 0)
            context = json.loads(stdout)["hookSpecificOutput"]["additionalContext"]
            self.assertNotIn("Routed variants out of date", context)


# ── Change 2: variant set derived from config ──────────────────────────────

class TestVariantMap(unittest.TestCase):

    def test_defaults_map_matches_the_shipped_set(self):
        self.assertEqual(
            variants.variant_map(copy.deepcopy(DEFAULTS)),
            {
                ("haiku", None): "routed-haiku",
                ("opus", "medium"): "routed-opus-medium",
                ("opus", "high"): "routed-opus-high",
                ("opus", "xhigh"): "routed-opus-xhigh",
                ("opus", "max"): "routed-opus-max",
            },
        )

    def test_sonnet_free_config_declares_no_sonnet_variant(self):
        mapping = variants.variant_map(_sonnet_free_cfg())
        for (model, _effort), name in mapping.items():
            self.assertNotEqual(model, "sonnet")
            self.assertNotIn("sonnet", name)

    def test_opus_medium_gap_closes(self):
        """The (opus, medium) target had no shipped variant; config declares it."""
        self.assertEqual(
            variants.variant_map(_sonnet_free_cfg())[("opus", "medium")],
            "routed-opus-medium",
        )

    def test_variant_name_shape(self):
        self.assertEqual(variants.variant_name("haiku", None), "routed-haiku")
        self.assertEqual(variants.variant_name("opus", "xhigh"), "routed-opus-xhigh")

    def test_unusable_target_is_skipped_not_raised(self):
        cfg = copy.deepcopy(DEFAULTS)
        cfg["classes"]["extreme"]["target"] = {"model": "gpt-9"}
        mapping = variants.variant_map(cfg)
        self.assertNotIn(("opus", "max"), mapping)
        self.assertIn(("haiku", None), mapping)

    def test_malformed_config_yields_empty_map_without_raising(self):
        for cfg in MALFORMED_CFGS:
            self.assertEqual(variants.variant_map(cfg), {})


class TestVariantClosure(unittest.TestCase):
    """The set must cover every pair apply_gates can synthesize, not just targets."""

    def _closure_covers_gates(self, cfg):
        declared = set(variants.variant_map(cfg))
        for klass in ("mechanical", "implementation", "debugging",
                      "architecture", "extreme"):
            target = target_for_class(klass, cfg)
            if target is None:
                continue
            for prompt in GATE_PROMPTS:
                gated = apply_gates(prompt, target, cfg)
                self.assertIn(
                    (gated.model, gated.effort), declared,
                    "%s on %r produced an undeclared variant" % (klass, prompt),
                )

    def test_defaults_closure_covers_every_gate_outcome(self):
        self._closure_covers_gates(copy.deepcopy(DEFAULTS))

    def test_single_effort_config_closure_covers_the_floor(self):
        """The reported regression: all reasoning classes on one effort."""
        cfg = _cfg(
            implementation={"model": "opus", "effort": "medium"},
            debugging={"model": "opus", "effort": "medium"},
            architecture={"model": "opus", "effort": "medium"},
            extreme={"model": "opus", "effort": "medium"},
        )
        self.assertEqual(
            sorted(variants.variant_map(cfg).values()),
            ["routed-haiku", "routed-opus-high", "routed-opus-medium"],
        )
        self._closure_covers_gates(cfg)

    def test_custom_effort_floor_is_in_the_closure(self):
        cfg = _cfg(implementation={"model": "opus", "effort": "low"})
        cfg["effort_floors"] = {"mode": "extend", "patterns": [], "floor": "xhigh"}
        self.assertIn(("opus", "xhigh"), variants.variant_map(cfg))
        self._closure_covers_gates(cfg)

    def test_closure_covers_gates_for_a_sonnet_free_config(self):
        self._closure_covers_gates(_sonnet_free_cfg())

    def test_gate_outcomes_is_empty_for_an_unroutable_class(self):
        cfg = copy.deepcopy(DEFAULTS)
        cfg["classes"]["extreme"]["target"] = {"model": "gpt-9"}
        self.assertEqual(gate_outcomes("extreme", cfg), [])

    def test_escalation_only_variant_is_described_as_such(self):
        cfg = _cfg(
            implementation={"model": "opus", "effort": "medium"},
            debugging={"model": "opus", "effort": "medium"},
            architecture={"model": "opus", "effort": "medium"},
            extreme={"model": "opus", "effort": "medium"},
        )
        declared = {name: classes for name, _m, _e, classes
                    in variants.target_variants(cfg)}
        self.assertEqual(declared["routed-opus-high"], ())
        markdown = variants.agent_markdown("routed-opus-high", "opus", "high", ())
        self.assertIn("gate-escalated tasks", markdown)


class TestAgentMarkdown(unittest.TestCase):

    def test_matches_every_committed_file(self):
        for name, model, effort, classes in variants.target_variants(
            copy.deepcopy(DEFAULTS)
        ):
            with open(os.path.join(AGENTS_DIR, name + ".md"), encoding="utf-8") as fh:
                self.assertEqual(
                    fh.read(), variants.agent_markdown(name, model, effort, classes),
                    name,
                )

    def test_omits_effort_for_haiku(self):
        md = variants.agent_markdown("routed-haiku", "haiku", None, ("mechanical",))
        self.assertNotIn("effort:", md)
        self.assertIn("model: haiku", md)
        self.assertIn("disallowedTools: Agent", md)
        self.assertIn("do not delegate it", md)

    def test_names_every_declaring_class(self):
        md = variants.agent_markdown(
            "routed-opus-high", "opus", "high", ("debugging", "architecture")
        )
        self.assertIn("for debugging and architecture tasks", md)

    def test_carries_the_ownership_key(self):
        md = variants.agent_markdown("routed-haiku", "haiku", None, ("mechanical",))
        self.assertIn("router-generated: true", md)
        self.assertTrue(variants.is_generated(md, "routed-haiku.md"))


class TestOwnershipBoundary(unittest.TestCase):
    """Ownership is declared in frontmatter, never inferred from body text."""

    def test_generated_file_is_owned(self):
        md = variants.agent_markdown("routed-opus-high", "opus", "high", ("architecture",))
        self.assertTrue(variants.is_generated(md, "routed-opus-high.md"))

    def test_prose_quoting_the_description_is_not_owned(self):
        """The old marker sniff called this ours and deleted it."""
        text = (
            "---\nname: routed-zach-notes\n---\n\n"
            "Notes on the router. Generated agents say 'Spawned by the model "
            "router hook; do not invoke directly.' in their description.\n"
        )
        self.assertFalse(variants.is_generated(text, "routed-zach-notes.md"))

    def test_hand_written_file_at_a_wanted_name_is_not_owned(self):
        text = "---\nname: routed-opus-high\nmodel: opus\n---\n\nmine\n"
        self.assertFalse(variants.is_generated(text, "routed-opus-high.md"))

    def test_pre_key_rendering_is_recognised_for_upgrade(self):
        """Files written before the ownership key existed stay manageable."""
        legacy = (
            "---\n"
            "name: routed-opus-high\n"
            "description: Router-managed variant for architecture tasks. "
            "Spawned by the model router hook; do not invoke directly.\n"
            "model: opus\n"
            "effort: high\n"
            "---\n\n"
            "Complete the delegated task exactly as prompted; return a concise report.\n"
        )
        self.assertTrue(variants.is_generated(legacy, "routed-opus-high.md"))

    def test_pre_key_rendering_under_a_mismatched_filename_is_not_owned(self):
        legacy = (
            "---\n"
            "name: routed-opus-high\n"
            "description: Router-managed variant for architecture tasks. "
            "Spawned by the model router hook; do not invoke directly.\n"
            "model: opus\n"
            "effort: high\n"
            "---\n\n"
            "Complete the delegated task exactly as prompted; return a concise report.\n"
        )
        self.assertFalse(variants.is_generated(legacy, "routed-something-else.md"))

    def test_trailing_content_after_a_legacy_body_is_not_owned(self):
        legacy_plus = (
            "---\n"
            "name: routed-opus-high\n"
            "description: Router-managed variant for architecture tasks. "
            "Spawned by the model router hook; do not invoke directly.\n"
            "model: opus\n"
            "effort: high\n"
            "---\n\n"
            "Complete the delegated task exactly as prompted; return a concise report.\n"
            "\nAnd my own notes below.\n"
        )
        self.assertFalse(variants.is_generated(legacy_plus, "routed-opus-high.md"))

    def test_non_string_input_is_not_owned(self):
        for value in (None, 7, b"bytes", []):
            self.assertFalse(variants.is_generated(value, "routed-haiku.md"))


class TestVariantGenerator(unittest.TestCase):

    def _run(self, *args, env=None):
        run_env = dict(os.environ)
        run_env.update(env or {})
        return subprocess.run(
            [sys.executable, GENERATOR] + list(args),
            capture_output=True, text=True, env=run_env,
        )

    def test_committed_set_is_in_sync(self):
        proc = self._run("--check")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_generates_sonnet_free_set_and_prunes_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            agents = os.path.join(tmp, "agents")
            os.makedirs(agents)
            stale = os.path.join(agents, "routed-sonnet-medium.md")
            with open(stale, "w") as fh:
                fh.write(variants.agent_markdown(
                    "routed-sonnet-medium", "sonnet", "medium", ("implementation",)))

            home = _write_home(os.path.join(tmp, "home"), {
                "version": 2,
                "classes": {
                    "implementation": {"target": {"model": "opus", "effort": "medium"}},
                    "debugging": {"target": {"model": "opus", "effort": "high"}},
                },
            })
            proc = self._run("--agents-dir", agents, "--use-user-config",
                             env={"HOME": home})
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(
                sorted(os.listdir(agents)),
                ["routed-haiku.md", "routed-opus-high.md",
                 "routed-opus-max.md", "routed-opus-medium.md",
                 "routed-opus-xhigh.md"],
            )
            self.assertFalse(os.path.exists(stale))

    def test_refuses_to_overwrite_a_hand_written_file_at_a_wanted_name(self):
        """The overwrite path needs the same ownership check as the prune path."""
        with tempfile.TemporaryDirectory() as agents:
            target = os.path.join(agents, "routed-opus-high.md")
            original = "---\nname: routed-opus-high\nmodel: opus\n---\n\nmine\n"
            with open(target, "w") as fh:
                fh.write(original)
            proc = self._run("--agents-dir", agents)
            self.assertEqual(proc.returncode, 1, proc.stdout)
            self.assertIn("CONFLICT (not router-generated", proc.stdout)
            with open(target) as fh:
                self.assertEqual(fh.read(), original)

    def test_force_overwrites_a_hand_written_file(self):
        with tempfile.TemporaryDirectory() as agents:
            target = os.path.join(agents, "routed-opus-high.md")
            with open(target, "w") as fh:
                fh.write("---\nname: routed-opus-high\n---\n\nmine\n")
            proc = self._run("--agents-dir", agents, "--force")
            self.assertEqual(proc.returncode, 0, proc.stdout)
            with open(target) as fh:
                self.assertIn("router-generated: true", fh.read())

    def test_prune_spares_a_file_that_merely_quotes_the_description(self):
        with tempfile.TemporaryDirectory() as agents:
            notes = os.path.join(agents, "routed-zach-notes.md")
            with open(notes, "w") as fh:
                fh.write(
                    "---\nname: routed-zach-notes\n---\n\n"
                    "Generated agents say 'Spawned by the model router hook; "
                    "do not invoke directly.' in their description.\n"
                )
            proc = self._run("--agents-dir", agents)
            self.assertEqual(proc.returncode, 0, proc.stdout)
            self.assertIn("SKIP (not router-generated)", proc.stdout)
            self.assertTrue(os.path.exists(notes))

    def test_prune_removes_a_pre_key_generated_file(self):
        """Upgrade path: a stale variant from before the key is still pruned."""
        with tempfile.TemporaryDirectory() as agents:
            legacy = os.path.join(agents, "routed-fable-high.md")
            with open(legacy, "w") as fh:
                fh.write(
                    "---\nname: routed-fable-high\n"
                    "description: Router-managed variant for extreme tasks. "
                    "Spawned by the model router hook; do not invoke directly.\n"
                    "model: fable\neffort: high\n---\n\n"
                    "Complete the delegated task exactly as prompted; "
                    "return a concise report.\n"
                )
            proc = self._run("--agents-dir", agents)
            self.assertEqual(proc.returncode, 0, proc.stdout)
            self.assertIn("REMOVED: routed-fable-high.md", proc.stdout)
            self.assertFalse(os.path.exists(legacy))

    def test_remove_failure_exits_non_zero(self):
        """A stale variant that survives stays selectable; never report success."""
        if os.geteuid() == 0:
            self.skipTest("root ignores directory permissions")
        with tempfile.TemporaryDirectory() as tmp:
            agents = os.path.join(tmp, "agents")
            os.makedirs(agents)
            stale = os.path.join(agents, "routed-fable-high.md")
            with open(stale, "w") as fh:
                fh.write(variants.agent_markdown(
                    "routed-fable-high", "fable", "high", ("extreme",)))
            for name, model, effort, classes in variants.target_variants(
                copy.deepcopy(DEFAULTS)
            ):
                with open(os.path.join(agents, name + ".md"), "w") as fh:
                    fh.write(variants.agent_markdown(name, model, effort, classes))
            os.chmod(agents, 0o500)  # readable and executable, not writable
            try:
                proc = self._run("--agents-dir", agents)
                self.assertEqual(proc.returncode, 1, proc.stdout)
                self.assertIn("REMOVE FAILED", proc.stdout)
                self.assertTrue(os.path.exists(stale))
            finally:
                os.chmod(agents, 0o700)

    def test_check_mode_reports_drift_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as agents:
            proc = self._run("--check", "--agents-dir", agents)
            self.assertEqual(proc.returncode, 1)
            self.assertIn("MISSING: routed-haiku.md", proc.stdout)
            self.assertEqual(os.listdir(agents), [])

    def test_check_mode_reports_a_conflict_without_writing(self):
        with tempfile.TemporaryDirectory() as agents:
            target = os.path.join(agents, "routed-haiku.md")
            with open(target, "w") as fh:
                fh.write("---\nname: routed-haiku\n---\n\nmine\n")
            proc = self._run("--check", "--agents-dir", agents)
            self.assertEqual(proc.returncode, 1, proc.stdout)
            self.assertIn("CONFLICT", proc.stdout)
            with open(target) as fh:
                self.assertIn("mine", fh.read())


class TestInstallScript(unittest.TestCase):
    """The manual installer must never restore a config-rejected tier."""

    def test_sonnet_free_config_installs_no_sonnet_agent(self):
        with tempfile.TemporaryDirectory() as home:
            _write_home(home, {
                "version": 2,
                "classes": {
                    "implementation": {"target": {"model": "opus", "effort": "medium"}},
                    "debugging": {"target": {"model": "opus", "effort": "high"}},
                },
            })
            env = dict(os.environ)
            env["HOME"] = home
            proc = subprocess.run(
                ["bash", MANUAL_INSTALLER],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertTrue(os.path.isfile(
                os.path.join(home, ".claude", "hooks", "post_tool_use.py")
            ))
            self.assertIn("Under 'PostToolUse'", proc.stdout)
            installed = sorted(os.listdir(os.path.join(home, ".claude", "agents")))
            self.assertEqual(
                installed,
                ["routed-haiku.md", "routed-opus-high.md",
                 "routed-opus-max.md", "routed-opus-medium.md",
                 "routed-opus-xhigh.md"],
            )

    def test_generator_conflict_aborts_the_install(self):
        """A hand-written agent file stops the install rather than being eaten."""
        with tempfile.TemporaryDirectory() as home:
            _write_home(home, {"version": 2})
            agents = os.path.join(home, ".claude", "agents")
            os.makedirs(agents)
            handwritten = os.path.join(agents, "routed-haiku.md")
            original = "---\nname: routed-haiku\n---\n\nmine\n"
            with open(handwritten, "w") as fh:
                fh.write(original)
            env = dict(os.environ)
            env["HOME"] = home
            proc = subprocess.run(
                ["bash", MANUAL_INSTALLER],
                capture_output=True, text=True, env=env,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("CONFLICT", proc.stdout)
            self.assertNotIn("Then restart Claude Code", proc.stdout)
            with open(handwritten) as fh:
                self.assertEqual(fh.read(), original)

    def test_failed_install_does_not_reinstate_a_rejected_tier(self):
        """The old fallback copied the DEFAULTS set, reintroducing sonnet."""
        with tempfile.TemporaryDirectory() as home:
            _write_home(home, {
                "version": 2,
                "classes": {
                    "implementation": {"target": {"model": "opus", "effort": "medium"}},
                    "debugging": {"target": {"model": "opus", "effort": "high"}},
                },
            })
            agents = os.path.join(home, ".claude", "agents")
            os.makedirs(agents)
            with open(os.path.join(agents, "routed-haiku.md"), "w") as fh:
                fh.write("---\nname: routed-haiku\n---\n\nmine\n")
            env = dict(os.environ)
            env["HOME"] = home
            proc = subprocess.run(
                ["bash", MANUAL_INSTALLER],
                capture_output=True, text=True, env=env,
            )
            self.assertNotEqual(proc.returncode, 0)
            for name in os.listdir(agents):
                self.assertNotIn("sonnet", name)


class TestPreToolUseVariantSelection(unittest.TestCase):
    """End-to-end: the hook selects only variants that exist on disk."""

    MECH = "rename the file src/a.py to src/b.py"
    IMPL = "implement a new React component and write tests for it"

    def _spawn(self, home, prompt, cwd=None, agent_id=None):
        payload = {
            "tool_name": "Agent",
            "tool_input": {"subagent_type": "general-purpose", "prompt": prompt},
        }
        if cwd is not None:
            payload["cwd"] = cwd
        if agent_id is not None:
            payload["agent_id"] = agent_id
        code, stdout = _run_hook("pre_tool_use.py", json.dumps(payload), home)
        self.assertEqual(code, 0)
        if not stdout.strip():
            return {}, ""
        emitted = json.loads(stdout)
        return (emitted["hookSpecificOutput"].get("updatedInput", {}),
                emitted.get("systemMessage", ""))

    def test_defaults_select_the_shipped_variant(self):
        with tempfile.TemporaryDirectory() as home:
            _write_home(home, {"version": 2, "classifier": {"cli_fallback": False}},
                        agents=list(variants.target_variants(copy.deepcopy(DEFAULTS))))
            updated, _msg = self._spawn(home, self.MECH)
            self.assertEqual(updated.get("model"), "haiku")
            self.assertEqual(updated.get("subagent_type"), "routed-haiku")

    def test_opus_medium_variant_is_selected_when_installed(self):
        with tempfile.TemporaryDirectory() as home:
            _write_home(home, {
                "version": 2,
                "classifier": {"cli_fallback": False},
                "classes": {
                    "implementation": {"target": {"model": "opus", "effort": "medium"}},
                    "debugging": {"target": {"model": "opus", "effort": "high"}},
                },
            }, agents=[("routed-opus-medium", "opus", "medium", ("implementation",))])
            updated, _msg = self._spawn(home, self.IMPL)
            self.assertEqual(updated.get("model"), "opus")
            self.assertEqual(updated.get("subagent_type"), "routed-opus-medium")

    def test_project_scoped_variant_is_selected_from_event_cwd(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as project:
            _write_home(home, {"version": 2, "classifier": {"cli_fallback": False}})
            agents = os.path.join(project, ".claude", "agents")
            os.makedirs(agents)
            with open(os.path.join(agents, "routed-opus-medium.md"), "w") as fh:
                fh.write(variants.agent_markdown(
                    "routed-opus-medium", "opus", "medium", ("implementation",)
                ))
            updated, _msg = self._spawn(home, self.IMPL, cwd=project)
            self.assertEqual(updated.get("model"), "opus")
            self.assertEqual(updated.get("subagent_type"), "routed-opus-medium")

    def test_nested_mechanical_spawn_is_gated_to_opus(self):
        with tempfile.TemporaryDirectory() as home:
            _write_home(
                home,
                {"version": 2, "classifier": {"cli_fallback": False}},
                agents=list(variants.target_variants(copy.deepcopy(DEFAULTS))),
            )
            updated, _msg = self._spawn(home, self.MECH, agent_id="agent-parent")
            self.assertEqual(updated.get("model"), "opus")
            self.assertEqual(updated.get("subagent_type"), "routed-opus-medium")

    def test_declared_but_uninstalled_variant_degrades_and_says_so(self):
        """F7: never name a subagent_type with no agent file behind it."""
        with tempfile.TemporaryDirectory() as home:
            _write_home(home, {
                "version": 2,
                "classifier": {"cli_fallback": False},
                "classes": {
                    "implementation": {"target": {"model": "opus", "effort": "medium"}},
                },
            })
            updated, message = self._spawn(home, self.IMPL)
            self.assertEqual(updated.get("model"), "opus")
            self.assertEqual(updated.get("subagent_type"), "general-purpose")
            self.assertIn("declared by the config but not installed", message)
            self.assertIn("routed-opus-medium", message)


# ── Change 3: gated tier floor follows the configured implementation target ──

class TestMinGatedTarget(unittest.TestCase):

    def test_defaults_are_the_shipped_implementation_target(self):
        self.assertEqual(min_gated_target(copy.deepcopy(DEFAULTS)), ("opus", "medium"))

    def test_follows_configured_implementation_target(self):
        self.assertEqual(min_gated_target(_sonnet_free_cfg()), ("opus", "medium"))

    def test_haiku_implementation_walks_to_the_cheapest_other_tier(self):
        """Escalation must survive a bottom-tier implementation target."""
        cfg = _cfg(implementation={"model": "haiku"})
        self.assertEqual(min_gated_target(cfg), ("opus", "high"))  # debugging

    def test_walk_prefers_the_lowest_tier_available(self):
        cfg = _cfg(
            implementation={"model": "haiku"},
            debugging={"model": "fable", "effort": "high"},
            architecture={"model": "opus", "effort": "xhigh"},
            extreme={"model": "fable", "effort": "high"},
        )
        self.assertEqual(min_gated_target(cfg), ("opus", "xhigh"))

    def test_all_haiku_config_has_nothing_to_escalate_to(self):
        cfg = _cfg(
            implementation={"model": "haiku"}, debugging={"model": "haiku"},
            architecture={"model": "haiku"}, extreme={"model": "haiku"},
        )
        self.assertIsNone(min_gated_target(cfg))

    def test_unusable_implementation_walks_within_the_config(self):
        """It must not reach for a target the config rejects."""
        self.assertEqual(
            min_gated_target(_cfg(implementation={"model": "gpt-9"})),
            ("opus", "high"),  # debugging, the cheapest non-haiku DEFAULTS target
        )

    def test_unusable_implementation_in_a_sonnet_free_config_stays_sonnet_free(self):
        cfg = _cfg(
            implementation={"model": "gpt-9"},
            debugging={"model": "opus", "effort": "high"},
            architecture={"model": "opus", "effort": "high"},
            extreme={"model": "fable", "effort": "high"},
        )
        self.assertEqual(min_gated_target(cfg), ("opus", "high"))

    def test_invalid_effort_falls_back_within_the_class(self):
        self.assertEqual(
            min_gated_target(_cfg(implementation={"model": "opus", "effort": "ultra"})),
            ("opus", "medium"),
        )

    def test_malformed_config_declares_no_escalation_target(self):
        for cfg in MALFORMED_CFGS + NESTED_MALFORMED_CFGS:
            self.assertIsNone(min_gated_target(cfg), repr(cfg))


class TestGatedBumpFollowsConfig(unittest.TestCase):

    def _gate(self, cfg, klass="mechanical", model="haiku", effort=None,
              prompt="coordinate agents to split this work"):
        return apply_gates(prompt, Decision(model, effort, klass, "heuristic"), cfg)

    def test_capability_gate_bumps_to_configured_tier(self):
        gated = self._gate(_sonnet_free_cfg())
        self.assertEqual((gated.model, gated.effort), ("opus", "medium"))

    def test_effort_floor_bump_targets_configured_tier(self):
        gated = self._gate(_sonnet_free_cfg(),
                           prompt="backfill the database and delete data")
        self.assertEqual((gated.model, gated.effort), ("opus", "high"))

    def test_haiku_implementation_still_escalates_gated_work(self):
        """The guard protects the invariant; it must not drop the guarantee."""
        cfg = _cfg(implementation={"model": "haiku"})
        gated = self._gate(cfg)
        self.assertEqual(gated.model, "opus")
        self.assertIsNotNone(gated.effort)

    def test_haiku_debugging_floor_still_applies(self):
        cfg = _cfg(implementation={"model": "haiku"})
        gated = apply_gates(
            "plain prompt", Decision("haiku", None, "debugging", "heuristic"), cfg
        )
        self.assertNotEqual(gated.model, "haiku")
        self.assertEqual(gated.effort, "high")

    def test_all_haiku_config_keeps_the_decision_invariant(self):
        """Nothing above haiku exists, so no effort may be attached to it."""
        cfg = _cfg(
            implementation={"model": "haiku"}, debugging={"model": "haiku"},
            architecture={"model": "haiku"}, extreme={"model": "haiku"},
        )
        gated = apply_gates(
            "plain prompt", Decision("haiku", None, "debugging", "heuristic"), cfg
        )
        self.assertEqual(gated.model, "haiku")
        self.assertIsNone(gated.effort)

    def test_decision_at_or_above_min_tier_is_untouched(self):
        cfg = _sonnet_free_cfg()
        decision = Decision("fable", "high", "extreme", "heuristic")
        self.assertIs(
            apply_gates("coordinate agents to split this work", decision, cfg), decision
        )

    def test_ungated_prompt_returns_the_same_object(self):
        cfg = _sonnet_free_cfg()
        decision = Decision("haiku", None, "mechanical", "heuristic")
        self.assertIs(apply_gates("rename this variable", decision, cfg), decision)

    def test_no_sonnet_survives_a_sonnet_free_config(self):
        """Every class x tier x effort x trigger, sonnet inputs included.

        Sonnet inputs are included deliberately: apply_gates must not be the
        thing that keeps a sonnet decision alive under a config that rejects
        it. It has no mechanism to lower a tier, so a sonnet input can only
        stay sonnet or rise, and the assertion below records which.
        """
        cfg = _sonnet_free_cfg()
        for klass in ("mechanical", "implementation", "debugging",
                      "architecture", "extreme"):
            for model in TIERS:
                for effort in ([None] if model == "haiku" else EFFORTS):
                    for prompt in GATE_PROMPTS:
                        gated = apply_gates(
                            prompt, Decision(model, effort, klass, "heuristic"), cfg
                        )
                        where = "%s/%s/%s on %r" % (klass, model, effort, prompt)
                        if model == "sonnet":
                            # Only a sonnet input may carry sonnet out, and the
                            # router never produces one under this config.
                            self.assertIn(gated.model, ("sonnet", "opus"), where)
                        else:
                            self.assertNotEqual(gated.model, "sonnet", where)

    def test_malformed_configs_never_raise_in_the_gate_path(self):
        for cfg in MALFORMED_CFGS + NESTED_MALFORMED_CFGS:
            for klass in ("mechanical", "debugging"):
                for prompt in ("plain prompt", "coordinate agents", "delete data"):
                    apply_gates(prompt, Decision("haiku", None, klass, "heuristic"), cfg)


class TestGateNeverReachesOutsideTheConfig(unittest.TestCase):
    """The floor may only name a model some class actually declares."""

    UNUSABLE_IMPL = {
        "version": 2,
        "classifier": {"cli_fallback": False},
        "classes": {
            "mechanical": {"target": {"model": "haiku"}},
            "implementation": {"target": {"model": "gpt-9"}},
            "debugging": {"target": {"model": "opus", "effort": "high"}},
            "architecture": {"target": {"model": "opus", "effort": "high"}},
            "extreme": {"target": {"model": "fable", "effort": "high"}},
        },
    }

    def _resolved(self):
        cfg = copy.deepcopy(DEFAULTS)
        for klass, entry in self.UNUSABLE_IMPL["classes"].items():
            cfg["classes"][klass]["target"] = dict(entry["target"])
        return cfg

    def test_unusable_class_never_resurrects_a_model_the_config_rejects(self):
        cfg = self._resolved()
        self.assertNotIn("sonnet", json.dumps(self.UNUSABLE_IMPL))
        for name in variants.variant_map(cfg).values():
            self.assertNotIn("sonnet", name)
        for klass in ("mechanical", "implementation", "debugging",
                      "architecture", "extreme"):
            for pair in gate_outcomes(klass, cfg):
                self.assertNotEqual(pair[0], "sonnet", "%s -> %s" % (klass, pair))

    def test_gated_spawn_stays_sonnet_free(self):
        cfg = self._resolved()
        gated = apply_gates(
            "rename the file and coordinate agents on the handoff",
            Decision("haiku", None, "mechanical", "heuristic"), cfg,
        )
        self.assertEqual((gated.model, gated.effort), ("opus", "high"))

    def test_no_legal_target_leaves_the_decision_alone(self):
        cfg = _cfg(
            implementation={"model": "haiku"}, debugging={"model": "haiku"},
            architecture={"model": "haiku"}, extreme={"model": "haiku"},
        )
        decision = Decision("haiku", None, "mechanical", "heuristic")
        self.assertIs(apply_gates("coordinate agents", decision, cfg), decision)

    def test_end_to_end_spawn_never_names_an_undeclared_model(self):
        with tempfile.TemporaryDirectory() as home:
            _write_home(home, self.UNUSABLE_IMPL)
            payload = json.dumps({
                "tool_name": "Agent",
                "tool_input": {
                    "subagent_type": "general-purpose",
                    "prompt": "rename the file and coordinate agents on the handoff",
                },
            })
            code, stdout = _run_hook("pre_tool_use.py", payload, home)
            self.assertEqual(code, 0)
            self.assertNotIn("sonnet", stdout)
            updated = json.loads(stdout)["hookSpecificOutput"]["updatedInput"]
            self.assertEqual(updated["model"], "opus")

    def test_generator_never_writes_an_undeclared_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = _write_home(os.path.join(tmp, "home"), self.UNUSABLE_IMPL)
            agents = os.path.join(tmp, "agents")
            env = dict(os.environ)
            env["HOME"] = home
            proc = subprocess.run(
                [sys.executable, GENERATOR, "--agents-dir", agents,
                 "--use-user-config"],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            for name in os.listdir(agents):
                self.assertNotIn("sonnet", name)


class TestNestedMalformedConfigNeverShutsRoutingDown(unittest.TestCase):
    """A silent exit 0 is the worst failure here: nothing surfaces it."""

    def test_no_nested_shape_raises_in_the_variant_path(self):
        for cfg in NESTED_MALFORMED_CFGS:
            variants.variant_map(cfg)
            variants.target_variants(cfg)
            for klass in ("mechanical", "implementation", "debugging",
                          "architecture", "extreme"):
                gate_outcomes(klass, cfg)

    def test_no_nested_shape_raises_in_the_advisory_path(self):
        for cfg in NESTED_MALFORMED_CFGS:
            self.assertIn("## Model Tier Rules", render_advisory(cfg))
            self.assertIn("## Model Tier Rules", render_session_context("opus", cfg))

    def test_no_nested_shape_raises_in_the_main_prompt_path(self):
        for cfg in NESTED_MALFORMED_CFGS:
            main_prompt_decision("implementation", "opus", "high", cfg, None, "hi")

    def test_broken_thresholds_beside_valid_classes_does_not_raise(self):
        """Needs valid classes: an unroutable one returns before reading them.

        load_config repairs thresholds, so this is defence in depth rather than
        a reachable production shape, but it is the one nested container the
        main-prompt path reads and it must not be the exception.
        """
        for broken in ("broken", 7, [], True):
            cfg = copy.deepcopy(DEFAULTS)
            cfg["thresholds"] = broken
            main_prompt_decision("implementation", "haiku", "high", cfg, None, "hi")
            main_prompt_decision("mechanical", "opus", "high", cfg, None, "hi")

    def test_broken_effort_floors_still_routes_a_spawn(self):
        """The reported repro: PreToolUse produced no output at all."""
        with tempfile.TemporaryDirectory() as home:
            _write_home(home, {
                "version": 2,
                "classifier": {"cli_fallback": False},
                "effort_floors": "broken",
            }, agents=list(variants.target_variants(copy.deepcopy(DEFAULTS))))
            payload = json.dumps({
                "tool_name": "Agent",
                "tool_input": {"subagent_type": "general-purpose",
                               "prompt": "rename the file src/a.py to src/b.py"},
            })
            code, stdout = _run_hook("pre_tool_use.py", payload, home)
            self.assertEqual(code, 0)
            self.assertTrue(stdout.strip(), "hook produced no output: routing died")
            updated = json.loads(stdout)["hookSpecificOutput"]["updatedInput"]
            self.assertEqual(updated["model"], "haiku")

    def test_broken_nested_value_does_not_abort_the_generator(self):
        for broken in ("broken", 7, []):
            with tempfile.TemporaryDirectory() as tmp:
                home = _write_home(os.path.join(tmp, "home"), {
                    "version": 2, "effort_floors": broken, "capability_gates": broken,
                })
                agents = os.path.join(tmp, "agents")
                env = dict(os.environ)
                env["HOME"] = home
                proc = subprocess.run(
                    [sys.executable, GENERATOR, "--agents-dir", agents,
                     "--use-user-config"],
                    capture_output=True, text=True, env=env,
                )
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertIn("routed-haiku.md", os.listdir(agents))


class TestLegacyMatchIsByteEquality(unittest.TestCase):
    """The pre-key proof must be what it claims: an exact rendering match."""

    LEGACY = (
        "---\n"
        "name: routed-opus-high\n"
        "description: Router-managed variant for architecture tasks. "
        "Spawned by the model router hook; do not invoke directly.\n"
        "model: opus\n"
        "effort: high\n"
        "---\n\n"
        "Complete the delegated task exactly as prompted; return a concise report.\n"
    )

    def test_genuine_pre_key_rendering_is_owned(self):
        self.assertTrue(variants.is_generated(self.LEGACY, "routed-opus-high.md"))

    def test_foreign_model_is_not_owned(self):
        """The reported repro: boilerplate body, someone else's model."""
        text = self.LEGACY.replace("model: opus", "model: local-custom-model")
        text = text.replace("name: routed-opus-high", "name: routed-my-notes")
        self.assertFalse(variants.is_generated(text, "routed-my-notes.md"))

    def test_foreign_effort_is_not_owned(self):
        text = self.LEGACY.replace("effort: high", "effort: enormous")
        self.assertFalse(variants.is_generated(text, "routed-opus-high.md"))

    def test_name_not_matching_the_pair_is_not_owned(self):
        text = self.LEGACY.replace("name: routed-opus-high", "name: routed-opus-low")
        self.assertFalse(variants.is_generated(text, "routed-opus-low.md"))

    def test_effort_on_haiku_is_not_owned(self):
        text = (
            "---\nname: routed-haiku\n"
            "description: Router-managed variant for mechanical tasks. "
            "Spawned by the model router hook; do not invoke directly.\n"
            "model: haiku\neffort: high\n---\n\n"
            "Complete the delegated task exactly as prompted; return a concise report.\n"
        )
        self.assertFalse(variants.is_generated(text, "routed-haiku.md"))

    def test_missing_effort_on_a_non_haiku_model_is_not_owned(self):
        text = self.LEGACY.replace("effort: high\n", "")
        self.assertFalse(variants.is_generated(text, "routed-opus-high.md"))

    def test_class_list_that_is_not_routable_classes_is_not_owned(self):
        text = self.LEGACY.replace(
            "for architecture tasks", "for whatever-i-like tasks")
        self.assertFalse(variants.is_generated(text, "routed-opus-high.md"))

    def test_multi_class_pre_key_rendering_is_owned(self):
        text = self.LEGACY.replace(
            "for architecture tasks", "for debugging and architecture tasks")
        self.assertTrue(variants.is_generated(text, "routed-opus-high.md"))

    def test_generator_does_not_prune_a_foreign_lookalike(self):
        with tempfile.TemporaryDirectory() as agents:
            path = os.path.join(agents, "routed-my-notes.md")
            text = self.LEGACY.replace("model: opus", "model: local-custom-model")
            text = text.replace("name: routed-opus-high", "name: routed-my-notes")
            with open(path, "w") as fh:
                fh.write(text)
            proc = subprocess.run(
                [sys.executable, GENERATOR, "--agents-dir", agents],
                capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout)
            self.assertIn("SKIP (not router-generated)", proc.stdout)
            with open(path) as fh:
                self.assertEqual(fh.read(), text)


class TestInstalledMeansUsable(unittest.TestCase):
    """Resolution requires a readable regular file this generator wrote."""

    def _agents(self, tmp):
        agents = os.path.join(tmp, "agents")
        os.makedirs(agents, exist_ok=True)
        return agents

    def test_directory_at_the_name_is_not_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            agents = self._agents(tmp)
            os.makedirs(os.path.join(agents, "routed-haiku.md"))
            self.assertFalse(variants.is_installed(agents, "routed-haiku"))

    def test_symlink_to_a_directory_is_not_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            agents = self._agents(tmp)
            target = os.path.join(tmp, "somedir")
            os.makedirs(target)
            os.symlink(target, os.path.join(agents, "routed-haiku.md"))
            self.assertFalse(variants.is_installed(agents, "routed-haiku"))

    def test_dangling_symlink_is_not_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            agents = self._agents(tmp)
            os.symlink(os.path.join(tmp, "nope"),
                       os.path.join(agents, "routed-haiku.md"))
            self.assertFalse(variants.is_installed(agents, "routed-haiku"))

    def test_foreign_file_is_not_installed(self):
        """The file the generator refuses to overwrite must not be selected."""
        with tempfile.TemporaryDirectory() as tmp:
            agents = self._agents(tmp)
            with open(os.path.join(agents, "routed-haiku.md"), "w") as fh:
                fh.write("---\nname: routed-haiku\n---\n\nhand written\n")
            self.assertFalse(variants.is_installed(agents, "routed-haiku"))

    def test_undecodable_bytes_are_not_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            agents = self._agents(tmp)
            with open(os.path.join(agents, "routed-haiku.md"), "wb") as fh:
                fh.write(b"\xff\xfe\x00binary")
            self.assertFalse(variants.is_installed(agents, "routed-haiku"))

    def test_unreadable_file_is_not_installed(self):
        if os.geteuid() == 0:
            self.skipTest("root ignores file permissions")
        with tempfile.TemporaryDirectory() as tmp:
            agents = self._agents(tmp)
            path = os.path.join(agents, "routed-haiku.md")
            with open(path, "w") as fh:
                fh.write(variants.agent_markdown(
                    "routed-haiku", "haiku", None, ("mechanical",)))
            os.chmod(path, 0o000)
            try:
                self.assertFalse(variants.is_installed(agents, "routed-haiku"))
            finally:
                os.chmod(path, 0o600)

    def test_generated_file_is_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            agents = self._agents(tmp)
            with open(os.path.join(agents, "routed-haiku.md"), "w") as fh:
                fh.write(variants.agent_markdown(
                    "routed-haiku", "haiku", None, ("mechanical",)))
            self.assertTrue(variants.is_installed(agents, "routed-haiku"))

    def test_missing_directory_is_not_installed(self):
        self.assertFalse(variants.is_installed("/nonexistent/nowhere", "routed-haiku"))
        self.assertFalse(variants.is_installed("", "routed-haiku"))

    def test_spawn_does_not_select_a_directory(self):
        with tempfile.TemporaryDirectory() as home:
            _write_home(home, {"version": 2, "classifier": {"cli_fallback": False}})
            os.makedirs(os.path.join(home, ".claude", "agents", "routed-haiku.md"))
            payload = json.dumps({
                "tool_name": "Agent",
                "tool_input": {"subagent_type": "general-purpose",
                               "prompt": "rename the file src/a.py to src/b.py"},
            })
            code, stdout = _run_hook("pre_tool_use.py", payload, home)
            self.assertEqual(code, 0)
            emitted = json.loads(stdout)
            self.assertEqual(
                emitted["hookSpecificOutput"]["updatedInput"]["subagent_type"],
                "general-purpose",
            )
            self.assertIn("not installed", emitted.get("systemMessage", ""))

    def test_spawn_does_not_select_a_foreign_file(self):
        with tempfile.TemporaryDirectory() as home:
            _write_home(home, {"version": 2, "classifier": {"cli_fallback": False}})
            agent_dir = os.path.join(home, ".claude", "agents")
            os.makedirs(agent_dir)
            with open(os.path.join(agent_dir, "routed-haiku.md"), "w") as fh:
                fh.write("---\nname: routed-haiku\n---\n\nhand written\n")
            payload = json.dumps({
                "tool_name": "Agent",
                "tool_input": {"subagent_type": "general-purpose",
                               "prompt": "rename the file src/a.py to src/b.py"},
            })
            code, stdout = _run_hook("pre_tool_use.py", payload, home)
            self.assertEqual(code, 0)
            updated = json.loads(stdout)["hookSpecificOutput"]["updatedInput"]
            self.assertEqual(updated["subagent_type"], "general-purpose")

    def test_divergence_warning_fires_for_an_occupied_name(self):
        with tempfile.TemporaryDirectory() as home:
            _write_home(home, {"version": 2})
            agent_dir = os.path.join(home, ".claude", "agents")
            os.makedirs(agent_dir)
            with open(os.path.join(agent_dir, "routed-haiku.md"), "w") as fh:
                fh.write("---\nname: routed-haiku\n---\n\nhand written\n")
            code, stdout = _run_hook("session_init.py", "{}", home)
            self.assertEqual(code, 0)
            context = json.loads(stdout)["hookSpecificOutput"]["additionalContext"]
            self.assertIn("Routed variants out of date", context)
            self.assertIn("routed-haiku", context)


if __name__ == "__main__":
    unittest.main()
