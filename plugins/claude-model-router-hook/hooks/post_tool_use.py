#!/usr/bin/env python3
"""PostToolUse entrypoint: record the model Claude Code actually used.

The PreToolUse hook records the requested route.  Claude Code may substitute a
model because of an organization allowlist or a fallback chain, so the matching
PostToolUse event is the only reliable place to record the completed route.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from router import hookio  # noqa: E402


def _models_used(response):
    """Comma-separated resolved model IDs, tolerating malformed hook data."""
    models = response.get("modelsUsed")
    if not isinstance(models, list):
        return ""
    return ",".join(model for model in models if isinstance(model, str))


@hookio.fail_open
def main():
    if hookio.is_child():
        sys.exit(0)

    event = hookio.read_event()
    if event.get("tool_name") not in ("Agent", "Task"):
        sys.exit(0)

    tool_input = event.get("tool_input")
    response = event.get("tool_response")
    if not isinstance(tool_input, dict) or not isinstance(response, dict):
        sys.exit(0)

    prompt = tool_input.get("prompt")
    if not isinstance(prompt, str):
        prompt = ""
    status = response.get("status")
    if status == "completed":
        action = "SUBAGENT-COMPLETE"
    elif status == "async_launched":
        action = "SUBAGENT-LAUNCHED"
    else:
        action = "SUBAGENT-RESULT"

    hookio.log(
        action,
        prompt,
        requested_model=tool_input.get("model", ""),
        resolved_model=response.get("resolvedModel", ""),
        models_used=_models_used(response),
        status=status or "",
        duration_ms=response.get("totalDurationMs", ""),
        tokens=response.get("totalTokens", ""),
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
