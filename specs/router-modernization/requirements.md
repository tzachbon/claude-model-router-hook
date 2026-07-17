# Requirements: router-modernization (v2)

## Goal

Full v2 rewrite of claude-model-router-hook: routing engine emits (model, effort) pairs across the 4-tier Claude 5 ladder, deterministic subagent enforcement via PreToolUse, hybrid heuristics+LLM classifier, config schema v2 with in-memory v1 migration, labeled eval set as CI gate, unified docs/manifests at 2.0.0.

## Core Thesis

Effort-first routing. Effort is the cheap lever (no cache invalidation, no tokenizer change); tier is the expensive one. Modulate effort within the current tier first; jump tiers only at extremes (trivial -> haiku, hardest/long-horizon -> fable).

## Tier Ladder (fixed)

| Tier | Alias | Model ID | Effort support |
|---|---|---|---|
| 1 | haiku | claude-haiku-4-5 | None (effort must be absent) |
| 2 | sonnet | claude-sonnet-5 | low/medium/high/xhigh/max |
| 3 | opus | claude-opus-4-8 | low/medium/high/xhigh/max |
| 4 | fable | claude-fable-5 | low/medium/high/xhigh/max |

`claude-mythos-5` is NEVER a router output. No date suffixes on aliases.

## User Stories

### US-1: Main-prompt routing, warn mode (default)
**As a** Claude Code user
**I want** misrouted prompts flagged with a concrete suggested switch
**So that** I stay in control of model and effort changes

**Acceptance Criteria:**
- [ ] AC-1.1: Given warn mode (default) and a prompt classified to a different (model, effort) than the current session, when UserPromptSubmit fires, then hook exits 2 with stderr message suggesting `/model <alias>` and `/effort <level>` and asking user to resend.
- [ ] AC-1.2: Given classification matches current session tier and effort, when hook runs, then exit 0 with no message.
- [ ] AC-1.3: Given any internal error (malformed stdin, unreadable settings, config parse failure), when hook runs, then exit 0 (fail-open, prompt never blocked).
- [ ] AC-1.4: Given current model has a suffix tag (e.g. `[1m]`), when a switch is suggested, then the suggested model preserves the suffix.

### US-2: Effort-first classification
**As a** cost-conscious user
**I want** the classifier to prefer effort changes within my current tier over tier jumps
**So that** I keep cache/tokenizer continuity and pay only for reasoning depth

**Acceptance Criteria:**
- [ ] AC-2.1: Given a session on Opus and a moderately-hard prompt, when classified, then output stays on Opus with a modulated effort level (not a tier switch).
- [ ] AC-2.2: Given a trivially mechanical prompt (extreme low), when classified, then output is (haiku, no effort).
- [ ] AC-2.3: Given an extreme-difficulty prompt (architecture-scale, long-horizon), when classified, then output is (fable, high or above).
- [ ] AC-2.4: Given tier=haiku is the decision, when the pair is emitted, then no effort field is attached (haiku rejects effort).
- [ ] AC-2.5: In no case does classification output `claude-mythos-5` or any non-ladder model.

Note: AC-2.1..2.3 verified via the US-10 labeled eval set.

### US-3: Autoswitch mode (opt-in)
**As a** power user
**I want** an opt-in autoswitch mode
**So that** routing decisions apply without manual /model steps where the platform allows it

**Acceptance Criteria:**
- [ ] AC-3.1: Given `apply_mode: autoswitch` in config, when a subagent spawn is classified, then model/effort are enforced deterministically via PreToolUse (see US-5/US-6).
- [ ] AC-3.2: Given autoswitch and a main-prompt tier mismatch, when hook runs, then session-level behavior remains advisory (warn message); autoswitch never claims to change the live session model/effort (platform constraint: no hook can switch mid-session).
- [ ] AC-3.3: Given autoswitch enabled but `allow_fable_autoswitch` false (default), when classification says fable, then fable is not auto-applied anywhere; behavior downgrades to warn for that decision.
- [ ] AC-3.4: Given any `apply_mode` (including default warn), when a subagent spawn is classified, then PreToolUse enforcement is on by default, gated only by `subagent_enforcement` (FR-30, default on), not by apply_mode; enforcement is the documented default for subagents (see FR-14).

### US-4: Subagent routing, generic spawns
**As a** user running orchestrated workflows
**I want** generic subagent spawns (general-purpose/default) routed to the right (model, effort)
**So that** trivial delegations stop burning top-tier tokens

**Acceptance Criteria:**
- [ ] AC-4.1: Given a PreToolUse event on the Agent tool with `subagent_type` generic (general-purpose, absent, or default), when `tool_input.prompt` is classified, then hook returns `permissionDecision: "allow"` + `updatedInput` rewriting `subagent_type` to a plugin-shipped agent variant carrying the target effort frontmatter, and injecting `model`.
- [ ] AC-4.2: Given the taxonomy decision (model, effort), when the variant is selected, then plugin ships one agent definition per required (model, effort) cell so every decision maps to an existing variant.
- [ ] AC-4.3: Given classification is abstain (needs-info), when hook runs, then original tool_input passes through unmodified (allow, no rewrite).
- [ ] AC-4.4: Given any classifier error/timeout, when hook runs, then allow with unmodified input (fail-open).

### US-5: Subagent routing, custom agent types
**As a** user with custom agents
**I want** my custom agent definitions respected
**So that** routing never breaks agent-specific behavior

**Acceptance Criteria:**
- [ ] AC-5.1: Given a spawn with a custom (non-generic) `subagent_type`, when classified, then hook injects only `updatedInput.model`; `subagent_type` is never rewritten.
- [ ] AC-5.2: Given a custom-type spawn, when effort differs from the target, then effort is advisory only (no enforcement path exists without rewriting the type).
- [ ] AC-5.3: Given the SessionStart hook, when a session starts, then the taxonomy advisory text is injected as `additionalContext` as backup guidance for cases PreToolUse cannot enforce.

### US-6: Robust task taxonomy
**As a** user delegating varied work
**I want** classification by task class, not a 3-row difficulty table
**So that** debugging, mechanical work, and ambiguous asks each route correctly

**Acceptance Criteria:**
- [ ] AC-6.1: Taxonomy includes at minimum: mechanical, implementation, debugging (own class), architecture/deep-analysis, needs-info/abstain.
- [ ] AC-6.2: Every taxonomy class maps to exactly one (model, effort) pair (or abstain).
- [ ] AC-6.3: Capability constraints override difficulty: tasks requiring multi-agent handoff protocols (e.g. SendMessage) never route to haiku regardless of difficulty score.
- [ ] AC-6.4: Abstain resolves to safe default: current session model at default effort (main prompts) or unmodified spawn (subagents).
- [ ] AC-6.5: Debugging class routes to a higher effort floor than routine implementation (correctness-critical; low effort documented to hallucinate).

### US-7: Hybrid classifier with CLI fallback
**As a** user with ambiguous prompts
**I want** a Haiku LLM tiebreaker behind fast heuristics
**So that** hard-to-classify prompts route correctly without slowing common cases

**Acceptance Criteria:**
- [ ] AC-7.1: Given any prompt, when tier-1 heuristics run, then they produce a scored decision with margin-based confidence using multiple signals (keywords, patterns, structure, length) with per-signal influence caps.
- [ ] AC-7.2: Given confidence above threshold, when classified, then heuristic decision is final; no CLI call.
- [ ] AC-7.3: Given confidence below threshold, when fallback fires, then classification calls `claude -p ... --model haiku` headless (reuses Claude Code auth; no API key, no SDK).
- [ ] AC-7.4: Given CLI missing, erroring, or exceeding its timeout, when fallback fails, then the heuristic decision applies (fail-open); user is never blocked.
- [ ] AC-7.5: Given a repeated prompt, when fallback would fire, then a cached decision from `${CLAUDE_PLUGIN_DATA}` (keyed by prompt hash) is used instead of a new CLI call.
- [ ] AC-7.6: Fallback is enabled by default; config flag can disable it (heuristics-only mode).
- [ ] AC-7.7: Hook timeout registration is raised/budgeted so a cold CLI call fits inside it (current 2s is insufficient).

### US-8: Config v2 with v1 migration
**As an** existing v1 user
**I want** my current config to keep working untouched
**So that** upgrading to v2 is zero-action

**Acceptance Criteria:**
- [ ] AC-8.1: Given a config with v2 `version` discriminator, when loaded, then v2 schema applies (tiers incl. fable, effort fields, classifier and apply-mode settings).
- [ ] AC-8.2: Given a v1-shaped config (no discriminator, structural detection), when loaded, then it is migrated in memory: keywords/patterns/remove_*/mode preserved into v2 defaults; user file never modified.
- [ ] AC-8.3: Given a v1 config detected, when migration runs, then a one-time upgrade hint is shown (once, not per prompt).
- [ ] AC-8.4: Given global + project configs, when merged, then v1 layered semantics hold (project wins; extend vs replace list modes).
- [ ] AC-8.5: Given an unparseable config, when loaded, then built-in defaults apply (fail-open).

### US-9: Overrides and bypasses
**As a** user who knows better than the router
**I want** v1 escape hatches preserved
**So that** I can always bypass routing

**Acceptance Criteria:**
- [ ] AC-9.1: Given a prompt starting with `~`, when hook runs, then routing is skipped (override logged, exit 0).
- [ ] AC-9.2: Given a prompt starting with `<` (XML-tagged/system), when hook runs, then it passes through untouched.
- [ ] AC-9.3: Given malformed hook stdin, when hook runs, then exit 0.

### US-10: Eval set as CI gate
**As a** maintainer
**I want** a labeled eval set gating router changes in CI
**So that** classifier edits cannot silently collapse routing quality

**Acceptance Criteria:**
- [ ] AC-10.1: Repo contains a labeled eval set of 50-100 prompts spanning all taxonomy classes, each labeled with expected (model, effort) or abstain.
- [ ] AC-10.2: CI runs eval against the real classifier entry point; failure below accuracy threshold blocks merge.
- [ ] AC-10.3: Eval reports tier distribution; a collapse check fails if the top tier exceeds a configured share of decisions.
- [ ] AC-10.4: Unit tests import the real classifier entry point (no inline reimplementation as in v1 `test_config.py`).
- [ ] AC-10.5: Integration tests cover fable routing, effort emission, and PreToolUse Agent-tool rewriting end to end.

### US-11: Docs and manifest unification
**As a** maintainer and new user
**I want** one source of truth for routing rules and consistent version metadata
**So that** docs cannot drift from behavior again

**Acceptance Criteria:**
- [ ] AC-11.1: Advisory/taxonomy text exists in exactly one canonical source; all other surfaces (session-init, prompt.md, README) are generated from it or asserted equal by a test.
- [ ] AC-11.2: Duplicate prompt.md and install.sh copies deduplicated or parity-tested.
- [ ] AC-11.3: README/prompt.md/slides describe actual v2 behavior: warn default, opt-in autoswitch semantics, CLI fallback (the "no API calls" claim updated to "no API key; optional Claude CLI call").
- [ ] AC-11.4: Root plugin.json, nested plugin.json, marketplace.json all read 2.0.0; CHANGELOG closes the gap (1.0.1, 1.1.0, 1.3.0, 2.0.0).
- [ ] AC-11.5: Installer(s) register the PreToolUse hook and ship agent variants + schema.

## Functional Requirements

### Routing engine
Covers: US-1, US-2

| ID | Requirement | Priority |
|---|---|---|
| FR-1 | Router outputs a (model, effort) pair; model from fixed 4-tier ladder only | High |
| FR-2 | `claude-mythos-5` excluded from output vocabulary; asserted by test | High |
| FR-3 | Effort levels: low/medium/high/xhigh/max; omitted when model=haiku | High |
| FR-4 | Effort-first policy: within-tier effort modulation preferred; tier change only at score extremes | High |
| FR-5 | Asymmetric thresholds: down-routing requires stronger evidence than up-routing (down-route errors are the costly ones) | High |
| FR-6 | Current-tier detection extended with fable substring; suffix tags (`[1m]`) preserved on suggested/injected models | High |
| FR-7 | Length/single-signal influence capped so degenerate inputs cannot force the top tier | Medium |

### Apply modes
Covers: US-1, US-3

| ID | Requirement | Priority |
|---|---|---|
| FR-8 | `apply_mode: warn` default: exit 2 + stderr suggesting `/model` and `/effort` | High |
| FR-9 | `apply_mode: autoswitch` opt-in config flag | High |
| FR-10 | Autoswitch concrete meaning: deterministic subagent enforcement (PreToolUse) plus settings-level model/effort changes effective for new sessions; live-session behavior stays advisory (documented platform constraint) | High |
| FR-11 | `allow_fable_autoswitch` separate flag, default false; without it fable decisions degrade to warn | High |

### Subagent PreToolUse routing
Covers: US-3, US-4, US-5

| ID | Requirement | Priority |
|---|---|---|
| FR-12 | PreToolUse hook registered on Agent tool matcher (Task alias tolerated); classifies `tool_input.prompt` | High |
| FR-13 | Hook responds `permissionDecision: "allow"` + `updatedInput`; never denies a spawn | High |
| FR-14 | Generic spawns (general-purpose/default/absent type): rewrite `subagent_type` to plugin-shipped variant carrying target effort frontmatter, inject `model`; gated by `subagent_enforcement` (FR-30), default on regardless of apply_mode | High |
| FR-15 | Custom agent types: inject `model` only; effort advisory; `subagent_type` untouched | High |
| FR-16 | Plugin ships agent variants covering every (model, effort) cell the taxonomy can emit | High |
| FR-17 | SessionStart advisory retained as backup, sourced from the canonical taxonomy text | Medium |
| FR-18 | Abstain or classifier failure: pass through original tool_input unmodified | High |

### Taxonomy
Covers: US-6

| ID | Requirement | Priority |
|---|---|---|
| FR-19 | Classes at minimum: mechanical, implementation, debugging, architecture/deep-analysis, needs-info/abstain | High |
| FR-20 | Each class maps to one (model, effort) or abstain; mapping config-overridable in v2 schema | High |
| FR-21 | Capability gates: handoff/protocol-dependent tasks never assigned haiku | High |
| FR-22 | Effort floors per class where correctness is silently unverifiable (debugging, data-handling) | Medium |

### Classifier
Covers: US-7

| ID | Requirement | Priority |
|---|---|---|
| FR-23 | Tier-1: multi-signal scored heuristics (keywords, patterns, structure, length) with margin-based confidence | High |
| FR-24 | Tier-1 must always be able to decide alone (defensive fallback) | High |
| FR-25 | Tier-2 fallback for low-confidence: headless `claude -p ... --model haiku` subprocess (Claude Code auth reuse; no API key/SDK) | High |
| FR-26 | Fallback auto-enabled; config flag to disable | High |
| FR-27 | Fail-open on CLI absence/error/timeout: use heuristic decision | High |
| FR-28 | Decision cache in `${CLAUDE_PLUGIN_DATA}`, keyed by prompt hash; hit skips CLI | High |
| FR-29 | Hook timeouts in hooks.json raised/budgeted to cover CLI cold start | High |

### Config v2 + migration
Covers: US-3, US-8

| ID | Requirement | Priority |
|---|---|---|
| FR-30 | v2 schema with explicit `version` discriminator; adds fable tier, effort mappings, apply-mode flags, `subagent_enforcement: on\|advisory\|off` (default on), classifier/fallback settings | High |
| FR-31 | v1 detected structurally (no discriminator); auto-migrated in memory; keywords/patterns/remove_*/mode preserved | High |
| FR-32 | One-time upgrade hint on v1 detection; user config files never written | High |
| FR-33 | Layered global+project merge with extend/replace list modes preserved | High |
| FR-34 | JSON schema file updated for v2 (`additionalProperties: false` maintained) | Medium |

### Bypasses (v1 invariants)
Covers: US-9

| ID | Requirement | Priority |
|---|---|---|
| FR-35 | `~` prefix bypasses routing (logged override) | High |
| FR-36 | `<` prefix (XML/system prompts) passes through | High |
| FR-37 | Malformed stdin, unreadable settings, invalid regex: exit 0 / skip silently | High |

### Eval + tests
Covers: US-2, US-10

| ID | Requirement | Priority |
|---|---|---|
| FR-38 | Labeled eval set: 50-100 prompts across all taxonomy classes with expected (model, effort)/abstain | High |
| FR-39 | CI eval gate: accuracy threshold + top-tier share ceiling (routing-collapse detector) | High |
| FR-40 | Unit tests import the real classifier entry point; inline `_classify` reimplementation removed | High |
| FR-41 | Integration tests (test-hook.sh) extended: fable, effort output, PreToolUse rewrite paths | High |

### Docs + distribution
Covers: US-11

| ID | Requirement | Priority |
|---|---|---|
| FR-42 | Single canonical source for advisory/taxonomy text; other copies generated or parity-tested | High |
| FR-43 | prompt.md and install.sh duplicates deduplicated or parity-tested | Medium |
| FR-44 | README/prompt.md/slides claims corrected: warn default, autoswitch semantics, CLI fallback disclosure | High |
| FR-45 | Version 2.0.0 across root plugin.json, nested plugin.json, marketplace.json; CHANGELOG gap closed | High |
| FR-46 | Installers register PreToolUse hook and ship agent variants/schema | High |

## Non-Functional Requirements

| ID | Requirement | Metric | Target |
|---|---|---|---|
| NFR-1 | Heuristic-path latency | Wall time, classify without CLI | < 200ms p95 |
| NFR-2 | CLI fallback latency | Hard subprocess timeout | Bounded, fits registered hook timeout; timeout value set in design |
| NFR-3 | Fail-open reliability | Any error path outcome | Exit 0 / allow, 100% of error paths; asserted by tests |
| NFR-4 | Dependencies | Third-party packages in core | Zero; Python stdlib only (subprocess to `claude` CLI allowed) |
| NFR-5 | Prompt privacy | Log content | Preserve v1 behavior: max 30-char snippet, never full prompts; cache stores prompt hashes + decisions, not raw prompt text |
| NFR-6 | Network disclosure | Fallback behavior | CLI fallback sends prompt text through user's own Claude Code auth; documented in README; disableable |
| NFR-7 | Offline operation | Heuristics-only mode | Fully functional with no network/CLI |
| NFR-8 | Backward compatibility | v1 configs | Load and route without user edits |
| NFR-9 | Cache hygiene | Corrupt/oversized cache | Ignored/evicted silently; never blocks; bounded size |
| NFR-10 | Determinism | Same prompt + config, heuristic tier | Identical decision |

## Glossary

| Term | Definition |
|---|---|
| Tier | Position on the 4-model ladder haiku -> sonnet -> opus -> fable |
| Effort | Reasoning-depth dial (low/medium/high/xhigh/max); unsupported on haiku |
| Effort-first | Policy: change effort within tier before changing tier |
| Taxonomy class | Task category (mechanical, implementation, debugging, architecture, abstain) mapping to a (model, effort) |
| Apply mode | How decisions take effect: warn (suggest) vs autoswitch (enforce where possible) |
| Abstain | Classifier declines to route; safe default applies |
| Routing collapse | Drift toward always picking the strongest tier |
| Generic spawn | Agent tool call with general-purpose/default/absent subagent_type |
| Agent variant | Plugin-shipped agent definition carrying fixed model + effort frontmatter |
| Fail-open | On any error, allow the action unrouted; never block the user |
| Margin-based confidence | Confidence = gap between top-2 class scores |
| Suffix tag | Trailing bracket tag on model string (e.g. `[1m]`) preserved across switches |

## Out of Scope

- Routing to `claude-mythos-5` (hard exclusion, not configurable)
- Mid-session automatic model/effort switching via hooks (platform cannot; advisory only)
- Embedding-similarity middle tier of the classifier cascade
- Training a learned router (RouteLLM/NotDiamond style)
- API-key/SDK-based LLM fallback (CLI-only by decision)
- Request proxying / non-Anthropic model routing
- New per-request effort override channels beyond documented platform surfaces
- Cost analytics/telemetry dashboards
- Rewriting slides content beyond correcting behavior claims

## Dependencies

- Claude Code version providing: PreToolUse `updatedInput` + `permissionDecision` on Agent tool; agent `effort` frontmatter; `${CLAUDE_PLUGIN_DATA}`; alias enum incl. `fable`
- `claude` CLI on PATH for tier-2 fallback (optional at runtime; fail-open)
- Python 3.11+ stdlib; bash for wrappers/installers
- CI: GitHub Actions (existing test.yml extended)

## Assumptions to Verify in Design (from research open questions)

| # | Assumption | Risk if wrong |
|---|---|---|
| A-1 | `updatedInput.model` accepts alias enum (sonnet/opus/haiku/fable); full IDs unverified | Model injection format must change |
| A-2 | Claude Code default effort level (xhigh vs medium, plan-dependent) | Warn-message effort baseline wrong |
| A-3 | Multi-hook conflict on Agent PreToolUse: precedence undocumented | Another plugin could override injection |
| A-4 | `CLAUDE_CODE_SUBAGENT_MODEL`, if set, outranks injected model; router should detect and warn | Silent enforcement failure |
| A-5 | prompt-type hooks cannot emit `updatedInput` (so self-managed CLI call is required) | Simpler fallback architecture possible |
| A-6 | Settings-level autoswitch write mechanics for new sessions (which file/key) | FR-10 implementation shape |

## Success Criteria

- Eval gate green: accuracy >= threshold (set in design, target >= 90%) on labeled set; top-tier share within ceiling
- Zero mythos emissions across eval + fuzz inputs
- All v1 integration tests pass unmodified semantics (bypasses, fail-open, suffix)
- Docs parity test green (no drift between canonical text and surfaces)
- All three manifests at 2.0.0; CHANGELOG complete

## Unresolved Questions

- Exact accuracy threshold and top-tier ceiling for the CI gate (design decision, needs baseline run)
- Whether hook should skip injection when the caller explicitly set `model` on the Agent tool call (respect explicit intent vs enforce; recommend respect, decide in design)
- CLI fallback timeout value and raised hook timeout number (needs cold-start measurement)

## Next Steps

1. Run `/ralph-specum:design` to generate technical design from these requirements
2. Design resolves A-1..A-6 empirically before locking hook/injection contracts
3. Design sets eval thresholds and timeout budgets from measurements
