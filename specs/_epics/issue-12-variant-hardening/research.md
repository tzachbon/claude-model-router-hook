# Research: Issue #12 variant hardening

## Executive Summary

Issue #12 spans four remaining, independently shippable fixes: unsafe variant-file handling, manual-install staging, a false Fable tier hint, and gated-target effort ordering.  The issue's debugging-only advisory failure is already fixed in `f687111`: `_SELECTION_CLAUSES` now includes `debugging`; a direct check renders `debugging to opus` and does not claim that no class is routable.

## Current-State Evidence

| Area | Evidence | Required outcome |
|---|---|---|
| Variant generation | `scripts/generate_variants.py:68-81` maps every `OSError` from `_read`/`listdir` to absence; `:131-153` then writes with ordinary `open(..., "w")`. An unreadable known file or unreadable directory can therefore bypass ownership, and a symlink/non-regular target is not rejected before mutation. | Distinguish absent from inaccessible; reject every symlink and non-regular routed-agent target, including for `--force`; runtime installed-ness must reject them too. |
| Manual install | `plugins/claude-model-router-hook/install.sh:21-37` replaces router/hooks before invoking the generator, then copies the schema afterward. A generator conflict leaves a partial live install. | Generate against a staged copy before any live replacement; discard staging on non-zero generation. |
| Advisory prose | `advisory.py:80-83` now includes `debugging`, so issue item 3 is resolved. `:181-185` still supplies a static Fable sentence; `_tier_hint` returns it even when every resolved target is `None`. | Keep prose derived from resolved targets: no down-ladder instruction for an all-unroutable table. |
| Gated fallback | `policy.py:168-177` compares only `TIERS.index`; with implementation=haiku, debugging=opus/max, architecture=opus/low, it returns opus/max because debugging appears first in `CLASSES`. | For the fallback only, rank by lower tier then lower effort; keep `CLASSES` order for exact-pair ties. A valid non-haiku implementation target remains the designated target. |

The current targeted suite passes (`33` tests, one permission test skipped as root), so these are regression gaps rather than existing test failures.

## Proposed Spec Boundaries

1. **safe-variant-agent-paths** — Make generator inspection/write/delete and `variants.is_installed` share one conservative target rule: absent is writable; readable regular non-symlink files may undergo ownership checks; unreadable, symlink, directory, FIFO/socket/device, and undecodable paths are refused without mutation. Preflight all candidates before mutation so a detected hazard cannot leave a direct generator run partially changed.
2. **stage-manual-variant-install** — Copy the existing agents tree, including unrelated user agents, into a temporary staging area; run the existing generator there; only after success replace live router/hooks/entrypoints, staged agents, and schema. Scope atomicity to generator failure as requested; do not add a general rollback framework.
3. **truthful-advisory-prose** — Retain the already-correct debugging clause and add its regression; suppress the Fable down-ladder hint when no resolved target is routable.
4. **effort-aware-gated-fallback** — Change only `min_gated_target`'s non-haiku fallback comparison to the `(tier, effort)` ordering, preserving configuration-only targets and deterministic `CLASSES` order for exact ties.

## Dependencies and Stable Contracts

All four specs can ship alone. Run path safety before or alongside installer staging so the staging test also covers the new rejection cases. The shared contracts are: generator `0` means a complete generation and non-zero leaves live install untouched; `--check` remains write-free; `router-generated: true`/legacy byte ownership remains the ownership proof; rejected paths are never selectable at runtime; advisory names only `resolved_targets`; gated fallback never invents a target outside configuration.

## Minimal Regression Checks

- Extend `tests/test_variants.py` with unreadable/write-only, unreadable-directory, symlink-to-regular, and non-regular routed target cases; assert both target bytes and sibling generated files stay unchanged on refusal, including `--force`.
- Snapshot hooks, schema, and agents before a manual-install conflict; assert byte-for-byte equality after the failed installer run.
- Assert debugging-only advisory prose agrees with its table; assert all-unroutable Fable context contains no routing/down-ladder instruction.
- Assert opus/low beats opus/max in the gated fallback and equal `(tier, effort)` candidates resolve by `CLASSES` order.
- Shared command: `python3 -m unittest tests.test_variants`.
