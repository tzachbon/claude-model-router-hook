# Plan: Safe variant agent paths

## Scope

Make generator inspection, write/delete behavior, and runtime installed-ness apply one conservative routed-agent path rule. Absent paths may be created; only readable regular, non-symlink files can undergo ownership checks. Refuse unreadable paths, directories, symlinks, FIFOs/sockets/devices, and undecodable paths without mutation. Preflight every generated and stale candidate before a direct generator run changes any file.

## Excluded scope

- Installer staging and general rollback.
- New ownership markers or broader filesystem abstractions.

## Target files

- `scripts/generate_variants.py`
- `plugins/claude-model-router-hook/hooks/router/variants.py`
- `tests/test_variants.py`

## Minimal approach

Keep one small conservative path check at the generator/runtime seam. Distinguish absence from access failure; do not let `--force` bypass target safety. Validate all candidate targets before writes or deletions.

## Acceptance checks

- Unreadable file/directory, symlink-to-file, and non-regular target fail without changing that target or sibling generated files.
- The same rejection holds with `--force`; `--check` writes nothing.
- Runtime installed-ness rejects unsafe routed-agent paths.
- `python3 -m unittest tests.test_variants` passes.

## Ordering and dependencies

No hard dependency. Do this before the staging spec for shared filesystem coverage.
