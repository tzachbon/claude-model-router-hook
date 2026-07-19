#!/usr/bin/env python3
"""UserPromptSubmit entrypoint: warn-mode advisory routing (FR-8).

Thin wiring only; all logic lives in the router package. Exit 0 = allow,
exit 2 = warn (stderr suggestion, prompt blocked for resend).
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from router import config, hookio, ladder, policy, taxonomy  # noqa: E402


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

    cfg = config.load_config()
    klass, score = taxonomy.classify(
        prompt, cfg, os.environ.get("CLAUDE_PLUGIN_DATA")
    )
    if klass is None:
        sys.exit(0)  # abstain

    decision = policy.main_prompt_decision(
        klass, current_model, current_effort, cfg, score
    )
    if decision is None:
        sys.exit(0)  # match

    # Warn mode: suggest /model (suffix preserved, FR-6) and /effort, block for resend.
    _, suffix = ladder.split_suffix(current_model)
    suggestion = decision.model + suffix
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
    print(
        f"Run {' and '.join(parts)}, then resend  (~ prefix to skip)",
        file=sys.stderr,
    )
    sys.exit(2)


if __name__ == "__main__":
    main()
