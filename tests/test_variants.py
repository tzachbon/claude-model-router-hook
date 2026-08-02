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
| implementation | sonnet | medium | Writing or editing code, building features, creating components or APIs, writing tests, standard feature work. |
| debugging | sonnet | high | Diagnosing failures, flaky tests, races, regressions, stack traces, bisecting, reproducing bugs. |
| architecture | opus | high | Architecture decisions, tradeoff analysis, redesigns, deep multi-file analysis, sustained reasoning over large context. |
| extreme | fable | high | Multi-system migrations, codebase-wide rewrites, long-horizon plans, RFCs and design docs, platform-scale work. |
| abstain | (no routing) | - | Prompt does not clearly match any class; current model and effort pass through unmodified. |

### Sub-agent model selection (MANDATORY)

When calling the Agent tool, set the model parameter to match the task class
above. Never default all sub-agents to opus. Match the model to the work:
mechanical work goes to haiku, standard coding to sonnet, deep analysis to
opus, and only platform-scale efforts to fable.
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
        self.assertEqual(len(ADVISORY_MD), 1334)

    def test_explicit_defaults_config_renders_the_same(self):
        self.assertEqual(render_advisory(copy.deepcopy(DEFAULTS)), EXPECTED_ADVISORY_MD)

    def test_table_names_the_configured_model(self):
        rendered = render_advisory(_sonnet_free_cfg())
        self.assertIn("| implementation | opus | medium |", rendered)
        self.assertIn("| debugging | opus | high |", rendered)
        self.assertNotIn("sonnet", rendered)

    def test_closing_prose_names_the_configured_model(self):
        rendered = render_advisory(_sonnet_free_cfg())
        self.assertIn("standard coding to opus", rendered)
        self.assertNotIn("standard coding to sonnet", rendered)

    def test_session_context_is_sonnet_free_on_every_tier(self):
        cfg = _sonnet_free_cfg()
        for current in ("claude-haiku-4-5", "claude-sonnet-5", "claude-opus-4-8",
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
        self.assertNotIn("| implementation | sonnet | medium |", rendered)
        # The prose must not name a model for it either.
        self.assertNotIn("standard coding to", rendered)
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
        self.assertIn("Never default all sub-agents to fable", rendered)
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
        context = render_session_context("claude-opus-4-8", cfg)
        self.assertIn("For mechanical tasks haiku is cheaper.", context)
        self.assertNotIn("standard implementation", context)

    def test_tier_hint_survives_every_class_being_unroutable(self):
        context = render_session_context("claude-opus-4-8", {"classes": None})
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
                       ("routed-fable-high", "fable", "high", ("extreme",))])
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
            self.assertIn("| implementation | sonnet | medium |", self._context(home))

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
                ("sonnet", "medium"): "routed-sonnet-medium",
                ("sonnet", "high"): "routed-sonnet-high",
                ("opus", "high"): "routed-opus-high",
                ("fable", "high"): "routed-fable-high",
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
        self.assertNotIn(("fable", "high"), mapping)
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
                ["routed-fable-high.md", "routed-haiku.md",
                 "routed-opus-high.md", "routed-opus-medium.md"],
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
            legacy = os.path.join(agents, "routed-opus-xhigh.md")
            with open(legacy, "w") as fh:
                fh.write(
                    "---\nname: routed-opus-xhigh\n"
                    "description: Router-managed variant for architecture tasks. "
                    "Spawned by the model router hook; do not invoke directly.\n"
                    "model: opus\neffort: xhigh\n---\n\n"
                    "Complete the delegated task exactly as prompted; "
                    "return a concise report.\n"
                )
            proc = self._run("--agents-dir", agents)
            self.assertEqual(proc.returncode, 0, proc.stdout)
            self.assertIn("REMOVED: routed-opus-xhigh.md", proc.stdout)
            self.assertFalse(os.path.exists(legacy))

    def test_remove_failure_exits_non_zero(self):
        """A stale variant that survives stays selectable; never report success."""
        if os.geteuid() == 0:
            self.skipTest("root ignores directory permissions")
        with tempfile.TemporaryDirectory() as tmp:
            agents = os.path.join(tmp, "agents")
            os.makedirs(agents)
            stale = os.path.join(agents, "routed-opus-xhigh.md")
            with open(stale, "w") as fh:
                fh.write(variants.agent_markdown(
                    "routed-opus-xhigh", "opus", "xhigh", ("architecture",)))
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
    """install.sh must never fall back to a set the config rejects."""

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
                ["bash", os.path.join(REPO_ROOT, "install.sh")],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            installed = sorted(os.listdir(os.path.join(home, ".claude", "agents")))
            self.assertEqual(
                installed,
                ["routed-fable-high.md", "routed-haiku.md",
                 "routed-opus-high.md", "routed-opus-medium.md"],
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
                ["bash", os.path.join(REPO_ROOT, "install.sh")],
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
                ["bash", os.path.join(REPO_ROOT, "install.sh")],
                capture_output=True, text=True, env=env,
            )
            self.assertNotEqual(proc.returncode, 0)
            for name in os.listdir(agents):
                self.assertNotIn("sonnet", name)


class TestPreToolUseVariantSelection(unittest.TestCase):
    """End-to-end: the hook selects only variants that exist on disk."""

    MECH = "rename the file src/a.py to src/b.py"
    IMPL = "implement a new React component and write tests for it"

    def _spawn(self, home, prompt):
        payload = json.dumps({
            "tool_name": "Agent",
            "tool_input": {"subagent_type": "general-purpose", "prompt": prompt},
        })
        code, stdout = _run_hook("pre_tool_use.py", payload, home)
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
        self.assertEqual(min_gated_target(copy.deepcopy(DEFAULTS)), ("sonnet", "medium"))

    def test_follows_configured_implementation_target(self):
        self.assertEqual(min_gated_target(_sonnet_free_cfg()), ("opus", "medium"))

    def test_haiku_implementation_walks_to_the_cheapest_other_tier(self):
        """Escalation must survive a bottom-tier implementation target."""
        cfg = _cfg(implementation={"model": "haiku"})
        self.assertEqual(min_gated_target(cfg), ("sonnet", "high"))  # debugging

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
        self.assertEqual(min_gated_target(cfg), ("haiku", None))

    def test_invalid_values_fall_back_to_defaults(self):
        self.assertEqual(
            min_gated_target(_cfg(implementation={"model": "gpt-9"})),
            ("sonnet", "medium"),
        )
        self.assertEqual(
            min_gated_target(_cfg(implementation={"model": "opus", "effort": "ultra"})),
            ("opus", "medium"),
        )

    def test_malformed_config_never_raises(self):
        for cfg in MALFORMED_CFGS:
            self.assertEqual(min_gated_target(cfg), ("sonnet", "medium"))


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
        self.assertEqual(gated.model, "sonnet")
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
        for cfg in MALFORMED_CFGS:
            for klass in ("mechanical", "debugging"):
                for prompt in ("plain prompt", "coordinate agents", "delete data"):
                    apply_gates(prompt, Decision("haiku", None, klass, "heuristic"), cfg)


if __name__ == "__main__":
    unittest.main()
