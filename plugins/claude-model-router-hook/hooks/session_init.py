#!/usr/bin/env python3
"""SessionStart entrypoint: emit advisory routing context (FR-17).

Thin wiring only; all logic lives in the router package. Emits
hookSpecificOutput.additionalContext from advisory.render_session_context,
rendered against the resolved config so the advertised table matches the
targets the router will actually pick.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from router import advisory, config, hookio, variants  # noqa: E402


def _load_config(cwd=None):
    """Resolved config, or None when it cannot be read.

    A config failure must not cost the session its advisory text, so the
    caller renders the DEFAULTS table instead of emitting nothing.
    """
    try:
        return config.load_config(global_path=config.global_config_path(), cwd=cwd)
    except Exception:
        return None


def _agent_dirs(cwd=None):
    """Directories a routed variant can resolve from (plugin, then user)."""
    dirs = []
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if plugin_root:
        dirs.append(os.path.join(plugin_root, "agents"))
    dirs.extend(variants.project_agent_dirs(cwd))
    dirs.append(str(Path.home() / ".claude" / "agents"))
    return dirs


def _missing_variants(cfg, cwd=None):
    """Declared variants with no agent file, so the session can be told (F7).

    A config edited after install, or a project config the global install never
    saw, declares variants that do not exist on disk. Spawns degrade to
    model-only injection; surfacing it here is what makes that non-silent.
    """
    if cfg is None:
        return ()
    try:
        return variants.missing_variants(cfg, _agent_dirs(cwd))
    except Exception:
        return ()


@hookio.fail_open
def main():
    if hookio.is_child():
        sys.exit(0)

    event = hookio.read_event()
    cwd = event.get("cwd") if isinstance(event.get("cwd"), str) else os.getcwd()
    current_model, _ = hookio.current_model_effort(event)
    cfg = _load_config(cwd)
    context = advisory.render_session_context(
        current_model, cfg, _missing_variants(cfg, cwd)
    )
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
