#!/usr/bin/env python3
"""PreToolUse entrypoint: deterministic subagent routing on Agent spawns (FR-12..FR-15).

Thin wiring only; all logic lives in the router package. Never denies:
either emits permissionDecision "allow" JSON or exits 0 silently (FR-13, FR-18).
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from router import config, hookio, policy, taxonomy, variants  # noqa: E402
from router.ladder import detect_tier  # noqa: E402

PLUGIN_PREFIX = "claude-model-router-hook:"
GENERIC_TYPES = ("general-purpose", "default", "claude")


def _env_model_warning(decision_model):
    """A-4: CLAUDE_CODE_SUBAGENT_MODEL outranks injected model; warn on mismatch."""
    env_model = os.environ.get("CLAUDE_CODE_SUBAGENT_MODEL")
    if not env_model:
        return None
    if (detect_tier(env_model) or env_model) == decision_model:
        return None
    return (
        f"Warning: CLAUDE_CODE_SUBAGENT_MODEL={env_model} overrides the "
        f"router's model choice ({decision_model})."
    )


def _resolve_variant(variant, cwd):
    """Subagent_type for a variant, or None when no usable agent file backs it.

    A plugin-scoped name resolves only under a plugin install, so it is used
    only when the file is actually present under CLAUDE_PLUGIN_ROOT: some hosts
    substitute ${CLAUDE_PLUGIN_ROOT} textually in hooks.json without exporting
    it, and the bare name still resolves against ~/.claude/agents (F6).

    "Present" means variants.is_installed, not path existence. A directory, an
    unreadable file, a symlink to a directory, or a hand-written file occupying
    the name are all things the host cannot spawn, and the last of those is
    precisely the file the generator refuses to overwrite: auto-selecting it
    here would undo that protection at runtime.

    Returning None is deliberate. The variant set is config-derived, so an
    edited config can declare a variant the last install never generated;
    naming it would hand the host a subagent_type that does not resolve.
    Model-only injection is the honest degradation, and the caller says so in a
    systemMessage.
    """
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if plugin_root and variants.is_installed(
        os.path.join(plugin_root, "agents"), variant
    ):
        return PLUGIN_PREFIX + variant
    # A bare agent name may resolve from a project directory nearer than the
    # global ~/.claude/agents directory.  Check that same host search shape so
    # a usable project-scoped routed variant is never mistaken for missing.
    agent_dirs = [*variants.project_agent_dirs(cwd), str(Path.home() / ".claude" / "agents")]
    if any(variants.is_installed(directory, variant) for directory in agent_dirs):
        return variant
    return None


@hookio.fail_open
def main():
    if hookio.is_child():
        sys.exit(0)

    event = hookio.read_event()
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        sys.exit(0)
    prompt = tool_input.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        sys.exit(0)  # missing/unusable prompt: pass through (FR-18)

    subagent_type = tool_input.get("subagent_type")
    if isinstance(subagent_type, str) and (
        subagent_type.startswith(PLUGIN_PREFIX + "routed-")
        or subagent_type.startswith("routed-")
    ):
        sys.exit(0)  # idempotency guard: already rewritten (scoped or unscoped)

    cwd = event.get("cwd") if isinstance(event.get("cwd"), str) else os.getcwd()
    cfg = config.load_config(global_path=config.global_config_path(), cwd=cwd)
    enforcement = cfg.get("subagent_enforcement", "on")
    if enforcement == "off":
        sys.exit(0)

    klass, _score = taxonomy.classify(
        prompt, cfg, os.environ.get("CLAUDE_PLUGIN_DATA")
    )
    if klass is None:
        sys.exit(0)  # abstain: pass through (AC-4.3)

    target = policy.target_for_class(klass, cfg)
    if target is None:
        sys.exit(0)  # invalid class target: pass through (fail-safe skip)
    decision = policy.apply_gates(
        prompt, target, cfg, delegated=bool(event.get("agent_id"))
    )

    explicit = tool_input.get("model")
    if explicit is not None:
        # Explicit caller model: NO injection, respect it (locked decision 4).
        if (
            isinstance(explicit, str)
            and (detect_tier(explicit) or explicit) != decision.model
        ):
            messages = [
                f"Model router: caller pinned model {explicit}; router would "
                f"pick {decision.model} ({decision.klass})."
            ]
            warning = _env_model_warning(decision.model)
            if warning:
                messages.append(warning)
            hookio.log(
                "SUBAGENT-ADVISORY", prompt, klass=decision.klass, model=decision.model
            )
            hookio.emit_pretooluse(system_message=" ".join(messages))
        sys.exit(0)

    if decision.model == "fable" and not cfg.get("allow_fable_autoswitch"):
        # Fable gated off: advisory only, no rewrite (design "fable decision").
        hookio.log("SUBAGENT-ADVISORY", prompt, klass=decision.klass, model="fable")
        hookio.emit_pretooluse(
            system_message=(
                "Model router: this subagent task looks extreme-class "
                "(fable-tier). Set allow_fable_autoswitch to enable rewrites."
            )
        )
        sys.exit(0)

    generic = not subagent_type or (
        isinstance(subagent_type, str) and subagent_type in GENERIC_TYPES
    )
    if not isinstance(subagent_type, str) and subagent_type is not None:
        generic = False  # unexpected type value: leave subagent_type untouched

    updated = dict(tool_input)
    updated["model"] = decision.model  # bare alias only (A-1)
    # Variant set comes from the configured class targets, so the hook can only
    # ever select a variant this config declares (and install.sh generated).
    declared = variants.variant_map(cfg).get((decision.model, decision.effort))
    variant = _resolve_variant(declared, cwd) if (generic and declared) else None
    uninstalled = declared if (generic and declared and not variant) else None
    if variant:
        updated["subagent_type"] = variant

    if enforcement == "advisory":
        # Advisory mode: systemMessage only, never updatedInput (AC-3.3 shape).
        messages = [
            f"Model router: would route this subagent to "
            f"{decision.model} ({decision.klass})."
        ]
        warning = _env_model_warning(decision.model)
        if warning:
            messages.append(warning)
        hookio.emit_pretooluse(system_message=" ".join(messages))
        sys.exit(0)

    messages = []
    if uninstalled:
        # Declared by the config but not installed as a usable agent file: the
        # config changed after install, a project config declares a target the
        # global install did not see, or something else occupies the name.
        # Naming it would hand the host a subagent_type that does not resolve,
        # so inject the model alone and say why (F7). Warned even for a haiku
        # decision that carries no effort: the missing variant is the point.
        effort_note = (
            f", so effort {decision.effort} is advisory only"
            if decision.effort
            else ""
        )
        messages.append(
            f"Model router: injected model {decision.model}; routed variant "
            f"{uninstalled} is declared by the config but not installed"
            f"{effort_note}. Re-run install.sh."
        )
    elif not variant and decision.effort:
        # No matching variant at all (custom subagent_type, or a target the
        # config does not declare): model-only injection, effort stays
        # advisory (AC-4.2, AC-5.2).
        messages.append(
            f"Model router: injected model {decision.model}; no matching "
            f"routed variant, so effort {decision.effort} is advisory only."
        )
    warning = _env_model_warning(decision.model)
    if warning:
        messages.append(warning)

    hookio.log(
        "SUBAGENT-REWRITE" if variant else "SUBAGENT-MODEL",
        prompt,
        klass=decision.klass,
        model=decision.model,
        subagent_type=updated.get("subagent_type", ""),
    )
    hookio.emit_pretooluse(
        updated_input=updated,
        system_message=" ".join(messages) if messages else None,
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
