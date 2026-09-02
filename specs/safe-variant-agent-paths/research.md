# Safe Variant Agent Paths Research

## Executive Summary

`scripts/generate_variants.py` currently treats every failed read like an absent file, while `router.variants.is_installed()` follows a symlink to a regular file. Treat only `FileNotFoundError` as absent; an existing routed-agent path must be a readable, UTF-8-decodable, non-symlink regular file before it can participate in generation or runtime selection.

## Current Failure Path

The generator's `_read()` returns `None` for an unreadable path, so a wanted path can reach `open(path, "w")` as though it were missing; it also follows symlinks, and uncaught decode failures can occur after earlier siblings have changed. Its wanted loop mutates before the stale loop is inspected. `is_installed()` uses `os.path.isfile()`, which follows a symlink to a regular generated file and can therefore report that symlink as installed.

## Conservative Rule

Inspect every routed candidate in `wanted ∪ existing` with `lstat`: only `FileNotFoundError` is absent; reject symlinks and every non-regular type; then read ordinary files as UTF-8 and reject `OSError` or `UnicodeDecodeError`. A readable regular generated file remains eligible for its existing ownership-controlled update or prune behavior. Build the whole plan first; if any candidate is unsafe, return non-zero before `makedirs`, writes, or removals, including with `--force` and `--check` remains read-only. Runtime installed-ness uses the same regular/non-symlink/readable/decodeable predicate before `is_generated()`.

## Regression Loop

Extend `tests/test_variants.py` and run `python3 tests/test_variants.py`. Cover a regular-file symlink, directory/non-regular path, unreadable file, and invalid UTF-8 for both generator rejection and `is_installed() == False`; snapshot a safe wanted sibling and a safe stale sibling to prove an unsafe wanted or stale candidate leaves both unchanged. Keep the existing generated-file update/prune and `--force` tests green for ordinary files.

## Recommendation

Use one small stdlib-only safe inspection helper shared by the generator and `router.variants`; do not add a dependency or a new ownership model. It should distinguish absent from unsafe rather than returning `None` for both, and generator mutation should consume only its fully preflighted result.
