"""Hook I/O: fail-open wrapper, stdin parse, settings resolution, logging, output builders.

Covers FR-35, FR-36, FR-37, NFR-3, NFR-5.
"""

import functools
import json
import os
import sys
import tempfile
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


def write_settings(model_with_suffix, effort):
    """Atomically write model/effortLevel to ~/.claude/settings.json (FR-9, FR-10).

    Unparseable settings -> return False (degrade to warn, never clobber).
    Missing file -> treated as empty dict and created. `max` clamps to `xhigh`
    (settings rejects max). effort None (haiku decision) writes model only and
    removes any stale effortLevel. All other keys preserved.
    """
    path = os.path.expanduser("~/.claude/settings.json")
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                settings = json.load(f)
            if not isinstance(settings, dict):
                return False
        else:
            settings = {}
    except Exception:
        return False

    settings["model"] = model_with_suffix
    if effort is None:
        settings.pop("effortLevel", None)
    else:
        settings["effortLevel"] = "xhigh" if effort == "max" else effort

    try:
        directory = os.path.dirname(path)
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".settings-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(settings, f, indent=2)
                f.write("\n")
            os.replace(tmp_path, path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception:
        return False
    return True


def settings_masked():
    """True when a higher-precedence source would mask the ~/.claude write (A-6).

    ANTHROPIC_MODEL env or a project settings file defining `model` outranks
    ~/.claude/settings.json; caller surfaces a caveat in the autoswitch message.
    """
    if os.environ.get("ANTHROPIC_MODEL"):
        return True
    for path in (
        os.path.join(".claude", "settings.local.json"),
        os.path.join(".claude", "settings.json"),
    ):
        if isinstance(_read_settings(path).get("model"), str):
            return True
    return False


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
