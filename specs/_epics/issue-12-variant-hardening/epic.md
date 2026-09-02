# Epic: Issue #12 variant hardening

## Scope

Harden variant generation and installation against hostile filesystem state, keep advisory prose truthful to resolved targets, and select gated fallbacks by tier and effort. Stage generation before live installation; reject every symlink and non-regular routed-agent target; keep each spec independently shippable.

## Ordered specs

1. `safe-variant-agent-paths` — refuse unsafe routed-agent paths before any generator mutation.
2. `stage-manual-variant-install` — generate in a temporary copy before replacing live install files.
3. `truthful-advisory-prose` — retain the fixed debugging clause and suppress unroutable Fable advice.
4. `effort-aware-gated-fallback` — rank fallback candidates by tier, then effort.

## Dependency graph

There are no hard delivery dependencies.

```text
safe-variant-agent-paths ──recommended shared-seam order──> stage-manual-variant-install
truthful-advisory-prose                                   (independent)
effort-aware-gated-fallback                               (independent)
```

## Shared contracts

- Generator exit `0` means complete generation; a rejected agent path leaves every candidate unchanged, including with `--force`.
- `--check` remains write-free; `router-generated: true` or legacy bytes remain the only ownership proof.
- Rejected paths are not installed/routable at runtime.
- A failed staged generation changes no live installer files; no generic rollback framework is added.
- Advisory prose only names resolved routable targets; gated fallback never invents a target outside configuration.

## Test and verification

- `python3 -m unittest tests.test_variants` covers unsafe paths, advisory truthfulness, and fallback ordering.
- `bash tests/test-install.sh` snapshots the live install and proves a generator conflict leaves it byte-for-byte unchanged.
- Keep the debugging-only advisory regression in `truthful-advisory-prose`; its clause was already fixed in `f687111` and needs no separate repair spec.

## Next unblocked spec

All ordered specs are complete. The shared variants suite is the final regression check.
