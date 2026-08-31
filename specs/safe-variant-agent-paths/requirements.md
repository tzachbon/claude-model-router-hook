# Safe Routed-Agent Paths Requirements

## Scope

Harden direct routed-agent variant generation in `scripts/generate_variants.py` and runtime installed-ness in `router.variants`. A routed-agent candidate is a path considered for a wanted variant or an existing/stale generated variant.

## User Stories

- As a user running variant generation, I want an unsafe pre-existing routed-agent path rejected before anything changes so generation cannot overwrite, follow, or remove an unintended target.
- As a runtime caller, I want unsafe routed-agent paths treated as not installed so they cannot be selected as valid generated agents.
- As a maintainer, I want focused regression coverage at the existing variants test seam so the safety rule remains deterministic.

## Functional Requirements

1. A candidate is writable only when it is absent because `lstat` raises `FileNotFoundError`.
2. An existing candidate is safe only when `lstat` identifies an ordinary regular file (not a symlink) and it can be read and decoded as UTF-8. A symlink, any non-regular type, read error, or `UnicodeDecodeError` is unsafe.
3. Before creating directories, writing, or removing files, the generator must inspect every candidate in `wanted ∪ existing` and construct its complete mutation plan. If any candidate is unsafe, it must report failure and make no filesystem mutation.
4. The same rejection applies with `--force`; `--force` may retain its normal behavior only for safe ordinary files. `--check` remains read-only.
5. A safe existing generated file keeps the current ownership-controlled update and prune behavior.
6. `router.variants.is_installed()` must return `False` unless the routed-agent path passes the same non-symlink, regular, readable, UTF-8-decodable check and then passes the existing generated-file check.
7. Share one small stdlib-only inspection seam between the generator and `router.variants`; do not add a dependency or a new ownership abstraction.

## Acceptance Criteria

- A symlink to a regular file, a directory or other non-regular path, an unreadable file, and invalid UTF-8 each cause generator rejection, including with `--force`.
- The generator rejects an unsafe candidate in either the wanted set or the stale/existing set before changing a safe wanted sibling or a safe stale sibling.
- `--check` performs no mutation for both safe and rejected plans.
- `is_installed()` is `False` for each unsafe-path case above.
- Existing ordinary-file generated-variant update, prune, and `--force` behavior remains passing.
- `python3 tests/test_variants.py` covers these cases and passes.

## Non-Functional and Safety Requirements

- Fail closed: absence is the sole writable state; every other inspection or decode failure is rejection.
- Do not follow symlinks while deciding whether a routed-agent path is valid.
- Preflight must be deterministic and all-or-nothing with respect to generator mutations; a rejected path leaves sibling agents unchanged.
- Failure output must identify the rejected candidate and why it is unsafe without attempting repair.

## Dependencies

- Existing `scripts/generate_variants.py`, `router.variants`, and `tests/test_variants.py` seams.
- Python standard-library filesystem inspection and UTF-8 decoding.
- Existing generated-file ownership checks for normal safe-file update and prune behavior.

## Explicit Exclusions

- No installer changes, installer-path repair, or installation-time migration.
- No advisory/UI messaging changes or policy/configuration changes; those are independent installer, advisory, and policy specs.
- No new dependency, ownership model, automatic repair, symlink replacement, or broad filesystem-hardening work outside direct routed-agent paths.

## Success Criteria

The generator and runtime both reject unsafe routed-agent paths, no unsafe preflight can partially mutate sibling agents, ordinary generated files retain current behavior, and the focused variants test command passes.
