#!/usr/bin/env python3
"""SessionStart entrypoint: emit advisory routing context (FR-17).

Thin wiring only; all logic lives in the router package. Emits
hookSpecificOutput.additionalContext from advisory.render_session_context,
rendered against the resolved config so the advertised table matches the
targets the router will actually pick.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from router import advisory, config, hookio  # noqa: E402


def _load_config():
    """Resolved config, or None when it cannot be read.

    A config failure must not cost the session its advisory text, so the
    caller renders the DEFAULTS table instead of emitting nothing.
    """
    try:
        return config.load_config(global_path=config.global_config_path())
    except Exception:
        return None


@hookio.fail_open
def main():
    if hookio.is_child():
        sys.exit(0)

    hookio.read_event()
    current_model, _ = hookio.current_model_effort()
    context = advisory.render_session_context(current_model, _load_config())
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": context,
                }
            }
        )
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
