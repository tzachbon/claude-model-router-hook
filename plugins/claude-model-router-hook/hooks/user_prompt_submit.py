#!/usr/bin/env python3
"""UserPromptSubmit entrypoint: warn/autoswitch routing (FR-8..FR-11).

Thin wiring only; all logic lives in the router package. Exit 0 = allow,
exit 2 = warn or autoswitch notice (stderr, prompt blocked for resend).
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from router import config, hookio, ladder, policy, taxonomy  # noqa: E402

V1_HINT = (
    "Model router: a v1 config was detected and migrated in memory. "
    "Update model-router.json to the v2 schema (add \"version\": 2). "
    "This hint is shown once."
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


def _v1_config_detected(global_path):
    """True when the global or nearest project config file is v1-shaped (FR-31)."""
    paths = []
    if global_path is not None:
        paths.append(global_path)
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        project_path = parent / ".claude" / "model-router.json"
        if project_path.exists():
            paths.append(project_path)
            break
    for path in paths:
        raw = config._read_json(path)
        if raw and config.detect_version(raw) == 1:
            return True
    return False


@hookio.fail_open
def main():
    if hookio.is_child():
        sys.exit(0)

    event = hookio.read_event()
    prompt = event.get("prompt")
    if not isinstance(prompt, str):
        sys.exit(0)
    if hookio.bypassed(prompt):
        sys.exit(0)

    current_model, current_effort = hookio.current_model_effort()
    if ladder.detect_tier(current_model) is None:
        sys.exit(0)  # unknown/unset session model: fail-open (v1 parity)

    global_path = _global_config_path()
    cfg = config.load_config(global_path=global_path)

    # One-time v1 upgrade hint (FR-32, AC-8.3): marker in CLAUDE_PLUGIN_DATA;
    # user config files are never written.
    hint = None
    data_dir = os.environ.get("CLAUDE_PLUGIN_DATA")
    if _v1_config_detected(global_path) and config.v1_hint_due(data_dir):
        hint = V1_HINT

    klass, score = taxonomy.classify(prompt, cfg, data_dir)
    if klass is None:
        if hint:
            print(json.dumps({"systemMessage": hint}))
        sys.exit(0)  # abstain

    decision = policy.main_prompt_decision(
        klass, current_model, current_effort, cfg, score
    )
    if decision is None:
        if hint:
            print(json.dumps({"systemMessage": hint}))
        sys.exit(0)  # match

    _, suffix = ladder.split_suffix(current_model)  # suffix preserved (FR-6)
    suggestion = decision.model + suffix

    # Autoswitch: write the default for new sessions (FR-9, FR-10); a fable
    # decision with the gate off behaves as warn (FR-11); a settings write
    # failure degrades to warn.
    autoswitch = cfg.get("apply_mode") == "autoswitch" and not (
        decision.model == "fable" and not cfg.get("allow_fable_autoswitch")
    )
    if autoswitch and hookio.write_settings(suggestion, decision.effort):
        shown_effort = decision.effort
        if shown_effort == "max":
            shown_effort = "xhigh"  # write_settings clamps; message matches file
        effort_part = f" (effort {shown_effort})" if shown_effort else ""
        message = (
            f"Router set default to {suggestion}{effort_part} for new sessions. "
            f"Run /model {suggestion} to apply now, then resend. (~ to skip)"
        )
        if hookio.settings_masked():
            message += (
                " Note: a higher-precedence model setting (ANTHROPIC_MODEL or "
                "project settings) masks this default."
            )
        if hint:
            message += "\n" + hint
        hookio.log(
            f"AUTOSWITCH->{suggestion}",
            prompt,
            model=current_model,
            effort=current_effort,
            klass=decision.klass,
            target_effort=decision.effort,
        )
        print(message, file=sys.stderr)
        sys.exit(2)

    # Warn mode: suggest /model and /effort, block for resend.
    parts = [f"/model {suggestion}"]
    if decision.effort is not None:
        parts.append(f"/effort {decision.effort}")
    hookio.log(
        f"SUGGEST->{suggestion}",
        prompt,
        model=current_model,
        effort=current_effort,
        klass=decision.klass,
        target_effort=decision.effort,
    )
    warn_line = f"Run {' and '.join(parts)}, then resend  (~ prefix to skip)"
    if hint:
        warn_line += "\n" + hint
    print(warn_line, file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
