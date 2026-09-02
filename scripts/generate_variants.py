#!/usr/bin/env python3
"""Generate the routed-* agent files a config declares (FR-14).

The variant set is derived from the configured class targets via
router.variants, the same module the PreToolUse hook uses to pick a variant.
A tier the config never targets gets no agent file, so a session cannot be
rewritten onto a model the config does not declare.

Modes:
  (default)          write the declared set into --agents-dir, prune stale
                     generated files, and report what changed
  --check            report drift and exit non-zero, writing nothing
  --use-user-config  resolve the user's ~/.claude config instead of DEFAULTS
  --force            overwrite and prune files this generator did not write

Only files this generator wrote are ever overwritten or removed; ownership is
a `router-generated: true` frontmatter key, not a guess at the body text. A
routed-*.md the user wrote themselves is reported as a conflict and the run
exits non-zero rather than replacing it.

The committed set under plugins/claude-model-router-hook/agents is generated
from DEFAULTS so a plain clone works with no install step. install.sh
regenerates against the user's own config at install time.

stdlib only.
"""

import argparse
import copy
import os
import stat
import sys


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


def _existing_router_files(agents_dir):
    try:
        names = os.listdir(agents_dir)
    except FileNotFoundError:
        return {}
    found = {}
    for name in sorted(names):
        if not name.startswith("routed-") or not name.endswith(".md"):
            continue
        found[name] = name
    return found


def _open_agents_dir(path, router_variants, create=False):
    """Open the final agents directory without following a replacement link."""
    directory = os.path.abspath(path)
    parent, name = os.path.split(directory)
    if not name:
        raise OSError("agents directory must not be root")
    try:
        parent_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    except FileNotFoundError:
        if not create:
            return None
        os.makedirs(parent, exist_ok=True)
        parent_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    fd = None
    try:
        if not stat.S_ISDIR(os.fstat(parent_fd).st_mode):
            raise NotADirectoryError(parent)
        try:
            fd = router_variants.open_agent_file(
                name, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0), dir_fd=parent_fd
            )
        except FileNotFoundError:
            if not create:
                return None
            os.mkdir(name, dir_fd=parent_fd)
            fd = router_variants.open_agent_file(
                name, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0), dir_fd=parent_fd
            )
        if not stat.S_ISDIR(os.fstat(fd).st_mode):
            raise NotADirectoryError(name)
        result = fd
        fd = None
        return result
    finally:
        if fd is not None:
            os.close(fd)
        os.close(parent_fd)


def _write_agent_file(router_variants, directory_fd, filename, contents, force, create):
    """Write one regular routed-agent file through an already-open directory."""
    flags = os.O_RDWR | getattr(os, "O_NONBLOCK", 0)
    if create:
        flags |= os.O_CREAT | os.O_EXCL
    fd = router_variants.open_agent_file(filename, flags, dir_fd=directory_fd)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("not regular")
        with os.fdopen(fd, "w" if create else "r+", encoding="utf-8") as fh:
            fd = None
            if not create:
                current = fh.read()
                if not force and not router_variants.is_generated(current, filename):
                    raise ValueError("not router-generated")
                fh.seek(0)
                fh.truncate()
            fh.write(contents)
    finally:
        if fd is not None:
            os.close(fd)


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
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite and prune agent files this generator did not write",
    )
    args = parser.parse_args(argv[1:])

    config, variants = _bootstrap()
    agents_dir = args.agents_dir or os.path.join(_plugin_dir(), "agents")
    cfg = _resolve_config(config, args.use_user_config)

    declared = variants.target_variants(cfg)
    wanted = {}
    for name, model, effort, classes in declared:
        wanted[name + ".md"] = variants.agent_markdown(name, model, effort, classes)

    agents_fd = None
    try:
        agents_fd = _open_agents_dir(agents_dir, variants)
        existing = _existing_router_files(agents_fd) if agents_fd is not None else {}
    except (OSError, ValueError):
        print("UNSAFE: agents directory (cannot list)")
        return 1

    inspected = {}
    unsafe = []
    for filename in sorted(set(wanted) | set(existing)):
        status, payload = (
            variants.inspect_agent_file(filename, dir_fd=agents_fd)
            if agents_fd is not None
            else ("absent", None)
        )
        if status == "safe":
            inspected[filename] = payload
        elif status == "unsafe":
            unsafe.append((filename, payload))
    if unsafe:
        for filename, reason in unsafe:
            print("UNSAFE: " + filename + " (" + reason + ")")
        if agents_fd is not None:
            os.close(agents_fd)
        return 1

    actions = []
    for filename in sorted(wanted):
        current = inspected.get(filename)
        if current == wanted[filename]:
            actions.append(("ok", filename))
            continue
        # Ownership is checked before writing, not only before deleting: a
        # wanted name can collide with a file a human wrote, and clobbering it
        # would be silent data loss.
        if (
            current is not None
            and not args.force
            and not variants.is_generated(current, filename)
        ):
            actions.append(("conflict", filename))
            continue
        actions.append(("update" if current is not None else "create", filename))

    for filename in sorted(existing):
        if filename in wanted or filename not in inspected:
            continue
        if not args.force and not variants.is_generated(inspected[filename], filename):
            actions.append(("skip", filename))
            continue
        actions.append(("remove", filename))

    drift = False
    conflicts = []
    failures = []

    if not args.check and any(
        action in ("create", "update", "remove") for action, _filename in actions
    ) and agents_fd is None:
        try:
            agents_fd = _open_agents_dir(agents_dir, variants, create=True)
        except (OSError, ValueError):
            print("UNSAFE: agents directory (cannot open)")
            return 1

    for action, filename in actions:
        if action == "ok":
            print("OK: " + filename)
            continue
        if action == "conflict":
            print("CONFLICT (not router-generated, refusing to overwrite): " + filename)
            conflicts.append(filename)
            continue
        if action == "skip":
            print("SKIP (not router-generated): " + filename)
            continue
        drift = True
        if action in ("create", "update"):
            if args.check:
                print(("DRIFT: " if action == "update" else "MISSING: ") + filename)
                continue
            try:
                _write_agent_file(
                    variants, agents_fd, filename, wanted[filename], args.force,
                    action == "create"
                )
            except (OSError, UnicodeDecodeError, ValueError) as exc:
                print("WRITE FAILED: " + filename + " (" + str(exc) + ")")
                failures.append(filename)
                break
            print(("UPDATED: " if action == "update" else "CREATED: ") + filename)
            continue
        if args.check:
            print("STALE: " + filename)
            continue
        try:
            status, current = variants.inspect_agent_file(filename, dir_fd=agents_fd)
            if status != "safe" or (
                not args.force and not variants.is_generated(current, filename)
            ):
                raise OSError("changed since preflight")
            os.unlink(filename, dir_fd=agents_fd)
            print("REMOVED: " + filename)
        except OSError as exc:
            # A stale variant that survives is a routing hazard, not a cosmetic
            # one: it stays selectable by name. Never report success.
            print("REMOVE FAILED: " + filename + " (" + str(exc) + ")")
            failures.append(filename)
            break

    if agents_fd is not None:
        os.close(agents_fd)

    if conflicts:
        print(
            "Refused to overwrite "
            + str(len(conflicts))
            + " file(s) not written by this generator. Move them aside, or pass "
            "--force to replace them."
        )
    if conflicts or failures:
        return 1
    if args.check and drift:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
