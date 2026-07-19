"""Hook I/O: fail-open wrapper, stdin parse, settings resolution, logging, output builders.

Covers FR-35, FR-36, FR-37, NFR-3, NFR-5.
"""

import functools
import json
import os
import sys
from datetime import datetime

LOG_PATH = os.path.expanduser("~/.claude/hooks/model-router-hook.log")
CHILD_ENV = "CLAUDE_MODEL_ROUTER_CHILD"


def fail_open(fn):
    """Decorator: any exception in the wrapped hook -> exit 0 (NFR-3)."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except SystemExit:
            raise
        except BaseException:
            sys.exit(0)

    return wrapper


def read_event():
    """Parse the hook event JSON from stdin; malformed input -> exit 0 (FR-37)."""
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    if not isinstance(data, dict):
        sys.exit(0)
    return data


def _read_settings(path):
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def current_model_effort():
    """Return (model_str, effort) from settings precedence (A-2/A-6).

    Model: env ANTHROPIC_MODEL > .claude/settings.local.json > .claude/settings.json
    > ~/.claude/settings.json. Effort: effortLevel key, same file precedence,
    default "high".
    """
    paths = (
        os.path.join(".claude", "settings.local.json"),
        os.path.join(".claude", "settings.json"),
        os.path.expanduser("~/.claude/settings.json"),
    )
    model = os.environ.get("ANTHROPIC_MODEL", "")
    effort = ""
    for path in paths:
        settings = _read_settings(path)
        if not model and isinstance(settings.get("model"), str):
            model = settings["model"]
        if not effort and isinstance(settings.get("effortLevel"), str):
            effort = settings["effortLevel"]
        if model and effort:
            break
    return model, effort or "high"


def log(action, prompt, **kv):
    """Append a log line with a max 30-char prompt snippet (NFR-5). Never raises."""
    try:
        snippet = prompt[:30].replace("\n", " ") + ("..." if len(prompt) > 30 else "")
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        fields = " ".join(f"{k}={v}" for k, v in kv.items())
        line = f"[{ts}] action={action}" + (f" {fields}" if fields else "")
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a") as f:
            f.write(f'{line} prompt="{snippet}"\n')
    except Exception:
        pass


def bypassed(prompt):
    """True when routing must be skipped: "<" system prompts (FR-36) or "~" override (FR-35)."""
    stripped = prompt.lstrip()
    if stripped.startswith("<"):
        return True
    if stripped.startswith("~"):
        log("OVERRIDE", prompt)
        return True
    return False


def is_child():
    """True inside a router-spawned child process (CLAUDE_MODEL_ROUTER_CHILD env guard)."""
    return bool(os.environ.get(CHILD_ENV))


def emit_pretooluse(updated_input=None, system_message=None):
    """Print PreToolUse hook JSON with permissionDecision "allow" to stdout."""
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
        }
    }
    if updated_input is not None:
        output["hookSpecificOutput"]["updatedInput"] = updated_input
    if system_message is not None:
        output["systemMessage"] = system_message
    print(json.dumps(output))
