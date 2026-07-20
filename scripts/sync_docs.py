#!/usr/bin/env python3
"""Sync the canonical advisory text into doc marker blocks (FR-42, FR-43, AC-11.1).

router.advisory.ADVISORY_MD is the single source of the taxonomy table. This
script injects it between <!-- advisory:start --> / <!-- advisory:end -->
markers in the target docs. Default mode rewrites in place; --check mode exits
non-zero on any drift so CI can gate on parity.

stdlib only.
"""

import os
import sys

START = "<!-- advisory:start -->"
END = "<!-- advisory:end -->"

# Repo-relative doc targets carrying advisory marker blocks.
TARGETS = (
    "README.md",
    "prompt.md",
    os.path.join("plugins", "claude-model-router-hook", "prompt.md"),
)


def _repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_advisory():
    """Import router.advisory via a sys.path bootstrap relative to this script."""
    pkg_parent = os.path.join(
        _repo_root(), "plugins", "claude-model-router-hook", "hooks"
    )
    if pkg_parent not in sys.path:
        sys.path.insert(0, pkg_parent)
    from router.advisory import ADVISORY_MD

    return ADVISORY_MD


def _desired_block(advisory_md):
    # ADVISORY_MD ends with a newline; keep markers on their own lines.
    return START + "\n" + advisory_md + END


def _sync_text(text, advisory_md):
    """Return (new_text, status) where status is one of:
    'no_markers', 'in_sync', 'drift'. new_text is None unless a rewrite applies.
    """
    start_idx = text.find(START)
    end_idx = text.find(END)
    if start_idx == -1 or end_idx == -1 or end_idx < start_idx:
        return None, "no_markers"

    block_end = end_idx + len(END)
    current = text[start_idx:block_end]
    desired = _desired_block(advisory_md)
    if current == desired:
        return None, "in_sync"
    new_text = text[:start_idx] + desired + text[block_end:]
    return new_text, "drift"


def main(argv):
    check = "--check" in argv[1:]
    advisory_md = _load_advisory()
    root = _repo_root()

    drift = False
    for rel in TARGETS:
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            print("MISSING FILE: " + rel)
            drift = True
            continue
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        new_text, status = _sync_text(text, advisory_md)

        if status == "no_markers":
            # Docs gain markers in later tasks (4.7/4.8). Treat absence as drift
            # in --check so CI enforces the markers once those land; in write
            # mode there is nothing to inject, so report and move on.
            print("NO MARKERS: " + rel)
            drift = True
            continue
        if status == "in_sync":
            print("OK: " + rel)
            continue

        # status == "drift"
        if check:
            print("DRIFT: " + rel)
            drift = True
        else:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(new_text)
            print("UPDATED: " + rel)

    if check and drift:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
