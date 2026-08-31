---
spec: "effort-aware-gated-fallback"
phase: "prototype"
id: "fallback-effort-rank"
status: "terminal"
verdict: "validated"
kind: "logic"
captureMode: "retained"
triggerMode: "quick"
triggerPhase: "requirements"
returnPhase: "design"
returnTaskIndex: 0
decisionOwner: "quick"
resolutionMode: "quick"
gateApproved: true
created: "2026-08-31T13:05:10Z"
completed: "2026-08-31T13:08:24Z"
sourceDisposition: "retained"
evidenceHash: "f87bbed018a2515633d30f0d6a2ac9418525936bbe8052815473a3e59ab8d2c6"
cleanupReceiptHash: null
staleArtifacts: []
staleTaskIndexes: []
supersedes: []
conflictsWith: []
resolves: []
resolvedAt: "2026-08-31T13:08:24Z"
isolationBranch: "prototype/effort-aware-gated-fallback/fallback-effort-rank"
isolationPath: "/root/.codex/worktrees/fad3/prototype-effort-aware-gated-fallback-fallback-effort-rank"
sourcePointers: ["plugins/claude-model-router-hook/hooks/router/policy.py","tests/test_variants.py"]
---

## Question

Can a tier-then-effort fallback key preserve min_gated_target() no-raise behavior when a direct raw non-haiku target has effort None?

## Blocking Declaration

Design needed a rank expression that obeys tier-then-effort ordering without making direct raw configurations with a non-haiku missing effort raise.

## Isolation

Retained isolated worktree on local branch `prototype/effort-aware-gated-fallback/fallback-effort-rank`, based on `3d29738700b845a238dec98ece9c174f482e0c29`; no dirty primary-worktree paths were transferred.

## Run Instructions

From the isolated worktree, run `python3 -m unittest tests.test_variants.TestMinGatedTarget`, then `python3 -m unittest tests.test_variants`.

## Cases Or Variants

Use implementation haiku with debugging opus/max and architecture opus/low; then direct raw configs with a missing opus effort alongside opus/max and by itself.

## Evidence And Observations

The red probe had two expected failures: tier-only selection kept opus/max before opus/low, and missing effort beat a fully ranked opus target. The inline rank `(tier, effort-is-missing, effort-rank)` made all 12 focused tests pass and kept exact ties under strict `<`. The full suite passed 125 tests with 3 permission-related skips; `git diff --check` passed. The isolated source diff SHA-256 is `f87bbed018a2515633d30f0d6a2ac9418525936bbe8052815473a3e59ab8d2c6`.

## Verdict

Validated. Treat a missing non-haiku effort as less preferable than any explicit valid effort; when it is the only candidate, retain the existing non-raising tuple.

## Downstream Handoff

Add the direct tier-then-effort regression and the two raw missing-effort safety cases in `TestMinGatedTarget`. In `min_gated_target()`, compare existing candidates by `(TIERS.index(model), effort is None, EFFORTS.index(effort or EFFORTS[0]))` with strict `<`; keep the designated implementation early return unchanged.

## Conflict Resolution

No competing prototype record affects this blocker.

## Staleness

No upstream artifact is stale.

## Source Disposition

Retained locally in the recorded worktree and local branch; no remote pointer was created or authorized.
