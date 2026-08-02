#!/usr/bin/env python3
"""Generate the routed-* agent files a config declares (FR-14).

The variant set is derived from the configured class targets via
router.variants, the same module the PreToolUse hook uses to pick a variant.
A tier the config never targets gets no agent file, so a session cannot be
rewritten onto a model the config does not declare.

Modes:
  (default)          write the declared set into --agents-dir, prune stale
                     router-owned files, and report what changed
  --check            report drift and exit non-zero, writing nothing
  --use-user-config  resolve the user's ~/.claude config instead of DEFAULTS

The committed set under plugins/claude-model-router-hook/agents is generated
from DEFAULTS so a plain clone works with no install step. install.sh
regenerates against the user's own config at install time.

stdlib only.
"""

import argparse
import copy
import os
import sys

START_MARKER = "Spawned by the model router hook"


def _repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _plugin_dir():
    return os.path.join(_repo_root(), "plugins", "claude-model-router-hook")


def _bootstrap():
    """Import the router package via a sys.path bootstrap relative to this script."""
    pkg_parent = os.path.join(_plugin_dir(), "hooks")
    if pkg_parent not in sys.path:
        sys.path.insert(0, pkg_parent)
    from router import config, variants

    return config, variants


def _resolve_config(config, use_user_config):
    """DEFAULTS, or the user's resolved global config.

    User resolution is anchored at $HOME rather than the current directory: a
    project-scoped config must not decide which agents get installed globally.
    """
    if not use_user_config:
        return copy.deepcopy(config.DEFAULTS)
    try:
        return config.load_config(
            global_path=config.global_config_path(), cwd=os.path.expanduser("~")
        )
    except Exception:
        return copy.deepcopy(config.DEFAULTS)


def _router_owned(path):
    """True when a routed-*.md file was written by this generator.

    Guards the prune step so a hand-written agent that happens to be named
    routed-something is never deleted.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return START_MARKER in fh.read()
    except OSError:
        return False


def _existing_router_files(agents_dir):
    try:
        names = os.listdir(agents_dir)
    except OSError:
        return {}
    found = {}
    for name in sorted(names):
        if not name.startswith("routed-") or not name.endswith(".md"):
            continue
        found[name] = os.path.join(agents_dir, name)
    return found


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--agents-dir",
        default=None,
        help="target directory (default: the committed plugin agents dir)",
    )
    parser.add_argument(
        "--use-user-config",
        action="store_true",
        help="resolve ~/.claude/model-router.json instead of the shipped DEFAULTS",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report drift and exit non-zero; write nothing",
    )
    args = parser.parse_args(argv[1:])

    config, variants = _bootstrap()
    agents_dir = args.agents_dir or os.path.join(_plugin_dir(), "agents")
    cfg = _resolve_config(config, args.use_user_config)

    declared = variants.target_variants(cfg)
    wanted = {}
    for name, model, effort, classes in declared:
        wanted[name + ".md"] = variants.agent_markdown(name, model, effort, classes)

    if not args.check:
        os.makedirs(agents_dir, exist_ok=True)

    existing = _existing_router_files(agents_dir)
    drift = False

    for filename in sorted(wanted):
        path = os.path.join(agents_dir, filename)
        current = None
        if filename in existing:
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    current = fh.read()
            except OSError:
                current = None
        if current == wanted[filename]:
            print("OK: " + filename)
            continue
        drift = True
        if args.check:
            print(("DRIFT: " if current is not None else "MISSING: ") + filename)
            continue
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(wanted[filename])
        print(("UPDATED: " if current is not None else "CREATED: ") + filename)

    for filename, path in existing.items():
        if filename in wanted:
            continue
        if not _router_owned(path):
            print("SKIP (not router-owned): " + filename)
            continue
        drift = True
        if args.check:
            print("STALE: " + filename)
            continue
        try:
            os.remove(path)
            print("REMOVED: " + filename)
        except OSError as exc:
            print("REMOVE FAILED: " + filename + " (" + str(exc) + ")")

    if args.check and drift:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
