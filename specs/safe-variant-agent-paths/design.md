# Safe Routed-Agent Path Design

## Decision

Keep filesystem validity in one small `router.variants` stdlib helper.  It
returns a three-part tuple: `absent`, `safe` plus decoded text, or `unsafe`
plus a short reason.  This is intentionally a result tuple, not a new
ownership or filesystem abstraction.

`absent` is returned only when `os.lstat(path)` raises `FileNotFoundError`.
For an existing path, the helper uses `lstat` and `stat` to reject a symlink
explicitly and every other non-regular type, then reads a regular file with
UTF-8.  Any other inspection/read error or `UnicodeDecodeError` is `unsafe`.
The helper never turns an error into missing.

## Data Flow

1. `generate_variants.py` resolves the config and builds the wanted
   `filename -> markdown` map as it does now.
2. It lists existing `routed-*.md` names without creating `--agents-dir`.
   A missing directory means no existing candidates; any other listing error
   is a preflight failure rather than an empty directory.
3. It visits `sorted(wanted | existing)` and calls the shared inspector for
   every candidate before `makedirs`, a write, or a removal.  It retains safe
   text for later ownership checks and accumulates unsafe filename/reason
   diagnostics.
4. If any candidate is unsafe, it reports each rejected candidate and exits
   non-zero.  No directory is created and no sibling is changed.  `--force`
   does not bypass this branch; `--check` reaches it through reads only.
5. Only after the whole scan is safe does the generator build its complete
   action list: `ok`, `create`, `update`, `conflict`, `skip`, or `remove`.
   Existing `is_generated()` ownership decisions apply only to safe decoded
   text.  It then reports/apply actions using the existing mode semantics.
6. `variants.is_installed()` calls the same inspector.  It returns `False`
   unless the result is `safe`, then applies the existing `is_generated()`
   check to the decoded text.  `pre_tool_use.py`, `installed_names()`, and
   advisory divergence checks inherit that behavior through their current
   calls and need no edits.

## File Changes

### `plugins/claude-model-router-hook/hooks/router/variants.py`

- Add the standard-library `stat` import and one private-or-module-local
  routed-agent inspection helper next to `is_installed()`.
- The helper uses `os.lstat`, `stat.S_ISLNK`, and `stat.S_ISREG`; it catches
  `FileNotFoundError` separately, and reports other `OSError`/`ValueError`
  and UTF-8 decode failures as unsafe.
- Replace `is_installed()`'s `os.path.isfile()` and direct `open()` with this
  helper.  This stops a symlink to a regular generated file from being
  treated as installed while retaining normal generated-file recognition.

### `scripts/generate_variants.py`

- Delete `_read()`, whose `None` result currently conflates missing, unreadable,
  symlink-followed, and undecodable paths.
- Make `_existing_router_files()` distinguish a missing directory from an
  enumeration error so preflight cannot silently omit stale candidates.
- Add a read-only preflight over the sorted union of wanted and existing
  routed names.  Preserve each safe candidate's decoded text in the plan;
  emit a deterministic `UNSAFE: <filename> (<reason>)`-style failure for
  rejected paths and return `1` before any mutation.
- Build ownership/drift/remove actions from that preflight result.  In normal
  mode, create the directory only when applying a planned write, then perform
  the existing safe-file updates/removals.  In `--check`, print the planned
  `MISSING`/`DRIFT`/`STALE`/`CONFLICT` results and do not create the directory,
  write, or remove.
- `--force` continues to overwrite or prune only safe ordinary files; it never
  turns an unsafe path into a writable one.  Existing ownership conflicts keep
  their current behavior for safe foreign files rather than broadening this
  change into transactional conflict handling.

### `tests/test_variants.py`

- Extend `TestVariantGenerator` with compact `subTest` coverage for a regular
  file symlink, directory/non-regular path, unreadable ordinary file, and
  invalid UTF-8.  Each is rejected in default and `--force` modes.  The
  unreadable case follows the existing non-root permission guard.
- Port the validated retained regression: a symlink at a wanted routed name,
  a safe wanted sibling whose content would otherwise update, and a safe stale
  generated sibling whose file would otherwise prune.  Assert failure,
  byte-for-byte unchanged siblings, and that the symlink remains a symlink.
  Mirror this setup with an unsafe stale candidate so both halves of the union
  prove all-or-nothing preflight.
- Add/extend `--check` assertions for both a safe drift plan and rejected
  paths: no directory creation, write, removal, or symlink replacement.
- Extend `TestInstalledMeansUsable` with a symlink to a regular generated file
  and retain the directory, dangling-link, invalid UTF-8, unreadable, foreign,
  and normal generated-file cases.  All unsafe cases return `False`.
- Run `PYTHONDONTWRITEBYTECODE=1 python3 tests/test_variants.py`; the current
  baseline is green (113 tests, 2 permission-dependent skips).

## Error and Compatibility Semantics

- Failure is fail-closed: only `FileNotFoundError` permits creation.  Existing
  candidates that cannot be inspected or decoded are never passed to
  `is_generated()`, `open(..., "w")`, or `os.remove()`.
- Rejection output names the candidate and class of failure (symlink,
  non-regular, inspection/read failure, or invalid UTF-8), without repairing,
  unlinking, or following it.
- Safe ordinary generated files retain their update/prune and legacy
  ownership-key behavior.  Safe foreign files retain the current conflict or
  skip behavior, and `--force` retains its current override only for them.
- Variant derivation, markdown rendering, ownership rules, installer behavior,
  advisory wording, and policy/configuration remain unchanged.  Installer,
  advisory, and policy hardening belong to their separate specs.

## Risks

- Permission fixtures cannot prove unreadability when tests run as root; use
  the repository's existing conditional skip rather than weakening production
  behavior or adding a dependency.
- Preflight protects against the inspected filesystem state before mutation.
  Atomic adversarial race protection would require a broader descriptor-based
  design and is deliberately outside this direct-path, stdlib-only scope.
