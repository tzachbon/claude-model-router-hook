#!/usr/bin/env python3
"""SessionStart entrypoint: emit advisory routing context (FR-17).

Thin wiring only; all logic lives in the router package. Emits
hookSpecificOutput.additionalContext from advisory.render_session_context.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from router import advisory, hookio  # noqa: E402


@hookio.fail_open
def main():
    if hookio.is_child():
        sys.exit(0)

    hookio.read_event()
    current_model, _ = hookio.current_model_effort()
    context = advisory.render_session_context(current_model)
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
