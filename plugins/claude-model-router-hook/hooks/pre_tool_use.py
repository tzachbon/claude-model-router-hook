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
    if isinstance(subagent_type, str) and subagent_type.startswith(
        PLUGIN_PREFIX + "routed-"
    ):
        sys.exit(0)  # idempotency guard: already rewritten

    if tool_input.get("model"):
        sys.exit(0)  # explicit caller model: respect it (advisory in 2.18)

    cfg = config.load_config(global_path=_global_config_path())
    enforcement = cfg.get("subagent_enforcement", "on")
    if enforcement == "off":
        sys.exit(0)

    klass, _score = taxonomy.classify(
        prompt, cfg, os.environ.get("CLAUDE_PLUGIN_DATA")
    )
    if klass is None:
        sys.exit(0)  # abstain: pass through (AC-4.3)

    decision = policy.apply_gates(prompt, policy.target_for_class(klass, cfg), cfg)

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
        updated["subagent_type"] = PLUGIN_PREFIX + variant

    if enforcement == "advisory":
        hookio.emit_pretooluse(
            system_message=(
                f"Model router: would route this subagent to "
                f"{decision.model} ({decision.klass})."
            )
        )
        sys.exit(0)

    hookio.log(
        "SUBAGENT-REWRITE" if generic and variant else "SUBAGENT-MODEL",
        prompt,
        klass=decision.klass,
        model=decision.model,
        subagent_type=updated.get("subagent_type", ""),
    )
    hookio.emit_pretooluse(updated_input=updated)
    sys.exit(0)


if __name__ == "__main__":
    main()
