#!/usr/bin/env python3
"""PreToolUse entrypoint: deterministic subagent routing on Agent spawns (FR-12..FR-15).

Thin wiring only; all logic lives in the router package. Never denies:
either emits permissionDecision "allow" JSON or exits 0 silently (FR-13, FR-18).
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from router import config, hookio, policy, taxonomy  # noqa: E402
from router.ladder import detect_tier  # noqa: E402

PLUGIN_PREFIX = "claude-model-router-hook:"
GENERIC_TYPES = ("general-purpose", "default", "claude")

# (model, effort) -> shipped routed-* variant (design class-target table).
VARIANTS = {
    ("haiku", None): "routed-haiku",
    ("sonnet", "medium"): "routed-sonnet-medium",
    ("sonnet", "high"): "routed-sonnet-high",
    ("opus", "high"): "routed-opus-high",
    ("fable", "high"): "routed-fable-high",
}


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


def _global_config_path():
    """Global config path: canonical ~/.claude/model-router.json, with a
    fallback to ~/.claude/hooks/model-router.json (legacy hook-dir layout)."""
    canonical = Path.home() / ".claude" / "model-router.json"
    if canonical.exists():
        return canonical
    legacy = Path.home() / ".claude" / "hooks" / "model-router.json"
    if legacy.exists():
        return legacy
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

    cfg = config.load_config(global_path=_global_config_path())
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
    decision = policy.apply_gates(prompt, target, cfg)

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
    variant = VARIANTS.get((decision.model, decision.effort))
    if generic and variant:
        # Plugin-scoped name resolves only under a plugin install; manual
        # installs copy the agents in unscoped, so emit the bare name there.
        # Use the scoped prefix only when the shipped agent file actually exists
        # under CLAUDE_PLUGIN_ROOT: some hosts substitute ${CLAUDE_PLUGIN_ROOT}
        # textually in hooks.json without exporting it, and the bare name still
        # resolves against ~/.claude/agents (F6). Residual assumption: a plugin
        # install exports CLAUDE_PLUGIN_ROOT into the hook process env.
        prefix = ""
        plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
        if plugin_root and os.path.exists(
            os.path.join(plugin_root, "agents", variant + ".md")
        ):
            prefix = PLUGIN_PREFIX
        updated["subagent_type"] = prefix + variant

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
    if not (generic and variant) and decision.effort:
        # No matching shipped variant (custom type or overridden target):
        # model-only injection, effort stays advisory (AC-4.2, AC-5.2).
        messages.append(
            f"Model router: injected model {decision.model}; no matching "
            f"routed variant, so effort {decision.effort} is advisory only."
        )
    warning = _env_model_warning(decision.model)
    if warning:
        messages.append(warning)

    hookio.log(
        "SUBAGENT-REWRITE" if generic and variant else "SUBAGENT-MODEL",
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
