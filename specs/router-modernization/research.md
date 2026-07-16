# Research: router-modernization

## Executive Summary

The planned v2 ladder (`claude-haiku-4-5` -> `claude-sonnet-5` -> `claude-opus-4-8` -> `claude-fable-5`) is exactly Anthropic's current Claude 5 lineup, and `effort` (low/medium/high/xhigh/max) is a first-class GA API lever on the top three tiers, confirming effort-first routing as the primary cost/quality dial (ARES: intra-model effort switching beats cross-model routing and preserves KV cache; model switches invalidate cache and change tokenizers). Claude Code's PreToolUse hook can deterministically rewrite a subagent's `model` via `updatedInput` on the `Agent` tool, but there is no `effort` param on that tool (effort requires rewriting `subagent_type` to an agent definition with `effort` frontmatter) and no hook can auto-switch the session model/effort mid-conversation (advisory only). The current codebase is a zero-dependency, offline regex-only 3-tier router (warn-only in committed code despite stale autoswitch docs) with no version discriminator, no effort/fable/PreToolUse support, and duplicated source-of-truth text across four files — every v2 capability (effort, fable, PreToolUse enforcement, Haiku LLM fallback, config v2) is greenfield.

## External Research

### Best Practices

**Effort-first routing (validated):**
- ARES (arXiv 2603.07915): a lightweight router picks per-step reasoning effort; intra-model effort switching beats cross-model routing on cost/accuracy frontier and reuses KV cache. Results: 52.7% reasoning-cost reduction (TAU-Bench Retail), 41.8% (BrowseComp), 45.3% (WebArena) with maintained/better accuracy.
- Adaptive-reasoning survey (arXiv 2603.04445v2) splits control into length-aware (how deep to think = effort) and capability-aware (which model = tier). Effort is the cheaper lever; exhaust it before jumping tiers.
- Anthropic effort guidance: low for high-volume simple/classification/routing tasks, medium for production agentic workflows, high (default) baseline, max for hardest quality-first work. Effort biases behavior (tool-call count, preamble), it is not a hard token budget. `budget_tokens` is deprecated in favor of effort on 4.6+ models.
- Cost stakes: low-vs-max can differ ~10x in time/tokens on simple tasks; documented hallucinations (fabricated SHAs/package names) at low effort + adaptive thinking allocating zero reasoning tokens — do not down-effort accuracy-critical classes.
- OpenAI mirrors this pattern: `reasoning_effort` none->max is a "tuning knob, not the primary way to recover quality"; ~3x latency per step.

**Model/effort platform facts (Claude 5 lineup, Claude Code v2.1.2xx):**

| Tier | Model ID | Context | Max out | Price in/out per MTok | Effort support |
|---|---|---|---|---|---|
| 1 | `claude-haiku-4-5` (full `claude-haiku-4-5-20251001`) | 200K | 64K | $1 / $5 | **None** — `effort` errors |
| 2 | `claude-sonnet-5` | 1M | 128K | $3 / $15 (intro $2/$10 through 2026-08-31) | low/medium/high/xhigh/max |
| 3 | `claude-opus-4-8` | 1M | 128K | $5 / $25 | low/medium/high/xhigh/max |
| 4 | `claude-fable-5` | 1M | 128K | $10 / $50 (2x Opus) | low/medium/high/xhigh/max |

- Never append date suffixes to aliases. Claude Code accepts family aliases `haiku`/`sonnet`/`opus`/`fable` in `/model`, `claude --model`, `ANTHROPIC_MODEL`, settings, and the Agent tool `model` param (confirmed enum: exactly `["sonnet","opus","haiku","fable"]`).
- Fable 5 = first public Mythos-class model, safety-classifier-gated (auto-falls back to Opus 4.8, billed at Opus rates, on refusal — beta `server-side-fallback-2026-06-01`). **Mythos 5** (`claude-mythos-5`) is Project Glasswing-only (US-gov/cyberdefense) and must never be a router output.
- `xhigh` only exists on 4.7+ models; Opus/Sonnet 4.6 lack it (falls back to `max`). Sonnet 4.5/Haiku 4.5 reject `effort` entirely.
- Effort is free of cache/context penalties within a model; model switching invalidates cache and changes tokenizer (Sonnet 5 ~30% more tokens than 4.6) — strong quantitative backing for "effort first, tier jump at extremes."
- Fable latency: single turns can run minutes at high effort — implies async/streaming tolerance, another reason to reserve fable for extremes.
- Claude Code `/effort low|medium|high|xhigh|max|auto`; `ultracode` = xhigh + standing multiagent permission (not an API effort level, session/UI-only, not settable via settings/env).

**Hook/subagent contracts (Claude Code, code.claude.com/docs):**
- PreToolUse hook, matcher `"Agent"` (renamed from `Task` in v2.1.63, alias retained), can return `hookSpecificOutput.permissionDecision: "allow"` + `updatedInput` — a documented, shallow per-field merge that replaces only the fields given (verbatim example in docs uses this exact combination).
- Agent tool params: `description`, `prompt`, `subagent_type`, `model` (enum sonnet/opus/haiku/fable — "takes precedence over agent definition frontmatter"), `isolation`, `run_in_background`. **No `effort` param.**
- Subagent model resolution order: `CLAUDE_CODE_SUBAGENT_MODEL` env (outranks hook) -> Agent tool `model` param (hook target) -> agent definition `model` frontmatter -> main conversation model.
- Subagent frontmatter supports both `model` and `effort` (low/medium/high/xhigh/max, "overrides session effort level"). Plugin agents support `model`/`effort` frontmatter but not `hooks`/`mcpServers`/`permissionMode`.
- UserPromptSubmit hook has no field that sets model/effort — only `systemMessage` (user-visible warning), `additionalContext` (steer Claude), or `decision:"block"` + `reason`. Session model/effort auto-switch mid-session is **not possible** via documented hook APIs.
- Hook timeouts: `command`/`http`/`mcp_tool` default 600s (UserPromptSubmit event itself: 30s); `prompt` type 30s; `agent` type 60s. Per-hook `"timeout"` override available. `prompt`-type hooks are single-turn LLM eval ("defaults to a fast model") but docs don't show them emitting `updatedInput` — unverified whether they can replace a self-managed Haiku call.
- No built-in hook-result caching — implement via hash-of-prompt -> cached decision in `${CLAUDE_PLUGIN_DATA}` (persists across plugin updates, unlike `${CLAUDE_PLUGIN_ROOT}`).

**Classifier design for sub-second routing:**
- Canonical 3-tier cascade (PRISM, arXiv 2605.12260): (1) keyword/regex 10-50ms, (2) embedding similarity 50-200ms, (3) small-LLM fallback 500-2000ms only on low confidence. V2's heuristics + Haiku fallback = tier 1 + tier 3 of this pattern (tier 2 skipped).
- Confidence thresholds: >0.8 auto-route, 0.5-0.8 route+flag, <0.5 escalate. Margin-based (top-2 gap) confidence works well for scored classifiers.
- Keyword layer should double as defensive fallback when the LLM tier errors/times out — must always be able to decide alone.
- Multi-signal scoring is standard (prompt complexity, task type, length) — OpenRouter Auto's `cost_quality_tradeoff` 0-10 dial is a good single-knob UX pattern.
- Useful task-tier taxonomy anchors: Morph's easy/medium/hard/**needs_info** (abstain class); OpenAI Codex usage taxonomy (implementation/understanding/validation/ops/app-management); debugging is consistently its own hard class in the literature (Reflexion, Self-Debugging, LDB) — don't lump with routine edits.

### Prior Art

| System | Approach | Signals | Notes |
|---|---|---|---|
| RouteLLM (LMSYS) | Trained binary router | Elo-weighted similarity, BERT, causal-LLM, matrix factorization | 85% cost savings @ 95% GPT-4 quality (MT-Bench); embedding-API latency risk (>100ms per RouterArena) |
| NotDiamond | Learned per-query quality prediction | Prompt complexity, task type, model capabilities | Powers OpenRouter Auto; trains from >=15 labeled samples |
| OpenRouter Auto | NotDiamond + provider selection | Prompt analysis, session stickiness | `cost_quality_tradeoff` 0-10 dial, no surcharge |
| Martian | Interpretability-based model mapping | Model-internal behavior prediction | Built RouterBench |
| Aider | Static role split (not dynamic) | Architect (strong) / editor (cheap, diff-precise) / weak (commits) | Role split ~ effort split; 30-50% cheaper than architect-alone |
| claude-code-router (musistudio) | Request-type routing proxy | default/background/think/longContext(>60k)/webSearch | Routes by request *type* not difficulty — "fix typo" and "design event-sourcing" both hit `default`; the gap v2 addresses |
| tzachbon/claude-model-router-hook (this repo, v1) | SessionStart rules + regex classifier | Keywords, patterns, `opus_word_count` threshold; warn/autoswitch | The crude 3-way baseline being replaced |
| Gearbox plugin | SessionStart routing policy | T0 haiku / T1 sonnet / T2 opus | Same family as v1 |
| ARES | Fine-tuned 1.7B effort router | Per-step agent state | Effort-first, intra-model; 40-80% reasoning-token reduction |

Context: Claude Code's own routing surfaces are subagent `model` frontmatter, Agent tool `model` param, `CLAUDE_CODE_SUBAGENT_MODEL`, skill/command model frontmatter. GitHub issue #27665 measured 93.8% of a Max user's tokens going to Opus with zero routing; subagents inherit parent model unless overridden.

### Pitfalls to Avoid

1. **Down-routing is the expensive error** — routing up wastes money; routing down silently degrades output (missed nuance, failing tool calls) surfacing as pain days later plus retries that negate savings. Use asymmetric thresholds (e.g. 55%-easy/45%-medium stays on the higher tier by default).
2. **Routing collapse** (arXiv 2602.03478) — tuned routers drift toward always picking the strongest model as tolerance loosens. Monitor tier-distribution over time.
3. **Keyword heuristics can be worse than chance** on some signal types — validate the heuristic tier against labeled examples, don't assume.
4. **Cascade latency accumulation** — a query escalating through all tiers pays for all of them. Keep the Haiku fallback rate low; time-box with a heuristic default on timeout.
5. **Model switching breaks prompt/KV cache** — prefer effort changes and sticky tier decisions over mid-session tier flapping.
6. **Adversarial/degenerate inputs** ("confounder gadget" tokens force routers to the expensive tier across multiple commercial routers, arXiv 2501.01818) — cap how much any single signal (e.g. raw length) can move the score.
7. **Low effort + adaptive thinking can allocate zero reasoning tokens** — documented hallucination cases; set an effort floor per task class where correctness is silently unverifiable.
8. **Haiku subagent capability gotcha** (community-reported) — Haiku agents reportedly idle instead of completing SendMessage-based handoffs; taxonomy must weigh required tool/protocol *capabilities*, not just difficulty, before assigning the lowest tier.
9. **No universally optimal router** (RouterArena, 12 routers evaluated) — build a labeled eval set (50-500 prompts) as a pre-merge gate for router changes.
10. **Ambiguity should abstain, not guess** — Morph's `needs_info` class / RACER abstention. Safe default for Claude Code = current session model at default effort.

## Codebase Analysis

### Existing Patterns

- **Classification pipeline** (`plugins/claude-model-router-hook/hooks/model_router.py`, `main()` at line 92): parse stdin JSON (malformed -> exit 0) -> bypass if prompt starts with `<` (XML/system prompts, added in ae27bcff/#5, `:100-102`) -> bypass if prompt starts with `~` (`OVERRIDE` log, `:104-114`) -> read `~/.claude/settings.json` model (unreadable -> exit 0, `:117-125`) -> detect current tier via substring match `"opus"/"sonnet"/"haiku" in model` (`:127-132`) -> load merged config, thresholds `opus_word_count=200`, `opus_question_word_count=100`, `haiku_max_word_count=60` (`:138-142`) -> classify by priority (opus keyword/pattern OR >100 words+`?` OR >200 words; else haiku if <60 words+pattern; else sonnet if pattern; else none, `:172-185`) -> on mismatch, print `Run /model {base} then resend` to stderr and exit 2 (`:216-219`); only haiku-downgrade, sonnet-downgrade-from-opus, and opus-upgrade directions are enforced (haiku->sonnet upgrade is NOT enforced, pinned by `test-hook.sh:94-96`).
- **Config merge** (`model_router.py:16-89`): `load_config` deep-merges global `~/.claude/model-router.json` then first project `.claude/model-router.json` found walking up from CWD; per top-level key, dict+dict does a shallow spread (project wins) else project replaces; `$schema` skipped. `resolve_list` implements `mode: extend` (defaults + additions - `remove_*`) vs `replace` (tier field verbatim). `safe_regex_match` silently skips invalid regex.
- **Shell wrapper** (`hooks/model-router-hook.sh:16-32`): pipes stdin to `model_router.py`; Python exit 2 -> echoes captured stderr to fd 2 and exits 2 (Claude Code surfaces this as the block message); else exit 0.
- **SessionStart advisory** (`hooks/session-init.sh:8-34`): reads model from stdin, builds a per-tier `TIER_HINT`, emits `hookSpecificOutput.additionalContext` containing the "Model Tier Rules" / "Sub-agent model selection (MANDATORY)" text (haiku=mechanical, sonnet=standard implementation, opus=architecture/deep reasoning) — this exact string is **duplicated in 4 places**: `session-init.sh:31`, `prompt.md:50`, `README.md:176`, `plugins/claude-model-router-hook/prompt.md:50`. This is the 3-tier subagent table the requirements should replace with a more robust taxonomy.
- **Hook registration** (`hooks/hooks.json:3-25`): `SessionStart` -> `session-init.sh`, `timeout: 2`; `UserPromptSubmit` (matcher `""`) -> `model-router-hook.sh`, `timeout: 2`. No `PreToolUse` entry exists today.

### Dependencies

- Python 3 stdlib only (`json, os, pathlib, re, sys, datetime`), no third-party packages (`model_router.py:8-13`); CI pins Python 3.11.
- Bash for hook wrappers, installer, integration tests.
- Claude Code hook runtime provides `${CLAUDE_PLUGIN_ROOT}`, stdin JSON, and interprets exit codes / `hookSpecificOutput` / `systemMessage`.
- `~/.claude/settings.json` (read for current model) and `~/.claude/model-router.json` + `<project>/.claude/model-router.json` (config).
- Slides: Node 20, `@slidev/cli ^51.5.0`, `@slidev/theme-default ^0.25.0`.
- **No `anthropic` SDK, no `ANTHROPIC_API_KEY` usage anywhere.** A Haiku LLM fallback is the first-ever runtime network dependency + auth requirement in this codebase.

### Constraints

1. **2-second hook timeout** (`hooks.json:9,23`) — hard ceiling for the whole classify path including any LLM call; a Haiku fallback needs a fast local path plus a tight per-call timeout well under 2s, or the timeout must be deliberately raised.
2. **Fail-open everywhere** — every exception path exits 0 (allow); must be preserved so routing never blocks the user on config/parse/network errors.
3. **Model detection is substring-based** (`"opus" in model"`, `:127-129`) — adding `fable` is a 4th substring; check for collisions (e.g. `claude-fable-5`). Effort has no existing storage/representation in `settings.json.model`.
4. **Model suffix preservation** — `re.search(r"(\[.+?\])$", model)` keeps trailing `[1m]`-style tags on switch (`:196,200`); must be preserved when emitting `(model, effort)`.
5. **Config `additionalProperties: false`** (`model-router.schema.json:6,27,50`) rejects unknown keys — adding effort/fable/v2 fields requires explicit schema changes/migration, not silent extension.
6. **Channel semantics** — exit 2 + stderr = block message; stdout JSON `systemMessage`/`hookSpecificOutput` = non-blocking. v2 apply modes (warn vs autoswitch) map onto these; PreToolUse enforcement needs its own `permissionDecision` contract.
7. **Duplicated source of truth** — advisory string in 4 files, hook script logic effectively in 3 (hook + 2 `prompt.md` copies); already drifted (committed code is warn-only; `README.md`/`prompt.md` still document an older autoswitch variant that writes `settings.json` and injects `systemMessage`). Any v2 text/behavior change must hit all copies or a test must assert parity.
8. **No version/schemaVersion discriminator** in config today — v1 shape must be detected structurally for migration; `additionalProperties:false` means unknown v2 keys fail v1 schema validation outright.
9. **Test coupling risk** — `tests/test_config.py` re-implements the classifier inline (`_classify`, `:237-266`) rather than importing `main()`; it will silently diverge from a v2 classification engine unless refactored to import the real entry point.
10. **Distribution/versioning drift** — 3 manifests (root `plugin.json`, nested `plugins/.../plugin.json`, `marketplace.json`) all say 1.3.0 but `CHANGELOG.md` stops at 1.0.0; two `prompt.md` and two `install.sh` copies must stay in sync; neither installer registers a `PreToolUse` hook or ships config/schema.

## Related Specs

None; first spec in repo.

## Quality Commands

| Type | Command | Source |
|---|---|---|
| Unit tests | `python3 -m unittest tests/test_config.py -v` | `.github/workflows/test.yml:21` |
| Integration tests | `bash tests/test-hook.sh` | `.github/workflows/test.yml:24` |
| Shell lint | not configured (no shellcheck in CI) | - |
| Python lint/format | not configured (no ruff/flake8/black/pyproject) | - |
| Pre-commit | not configured | - |
| Install | `bash install.sh` | `./install.sh` |
| Manifest/schema validation | none in CI (`schema/model-router.schema.json` exists for IDE hints only) | - |
| CI | unit + integration, ubuntu-latest, Python 3.11, on push to main + PRs | `.github/workflows/test.yml` |
| Slides deploy | `npm install && npx slidev build` | `.github/workflows/deploy-slides.yml` |

Manual verification:
```bash
echo '{"prompt":"analyze the architecture"}' | bash plugins/claude-model-router-hook/hooks/model-router-hook.sh   # exit 0 allow, exit 2 suggest switch
echo '{"prompt":"lint the code"}' | python3 plugins/claude-model-router-hook/hooks/model_router.py
python3 -m unittest tests/test_config.py -v && bash tests/test-hook.sh
```
Hooks log to `~/.claude/hooks/model-router-hook.log`. No lint/format/type gates exist anywhere in CI, only tests; only runtime dependency is Python 3.11+ stdlib.

## Feasibility Assessment

| Aspect | Assessment | Notes |
|---|---|---|
| Classify + override subagent **model** per spawn | Feasible, fully deterministic | PreToolUse matcher `Agent`, `allow` + `updatedInput.model` — documented verbatim pattern |
| Override subagent **effort** per spawn | Feasible, indirect | No `effort` param on Agent tool; requires `updatedInput.subagent_type` -> plugin agent definition carrying `effort` frontmatter |
| UserPromptSubmit auto-switch session model/effort | Not feasible via documented API | Advisory only: `systemMessage` warn + `additionalContext` steer, or `decision:"block"` telling user to run `/model`/`/effort` |
| SessionStart advisory | Feasible | `hookSpecificOutput.additionalContext`, already implemented in v1 |
| Haiku LLM classification fallback within budget | Feasible with care | Own Haiku call (SDK or raw `/v1/messages`) + file cache in `${CLAUDE_PLUGIN_DATA}`, explicit tight `timeout`, fail-open on miss/timeout; current 2s hook timeout likely needs raising |
| Config schema v2 + v1 migration | Feasible | Needs `version`/`schemaVersion` discriminator (none exists today) since `additionalProperties:false` rejects unknown v1 keys silently-failing rather than ignoring |
| Doc/source-of-truth unification | Feasible | 4 copies of advisory text, 2 of `prompt.md`/`install.sh`; mechanical but must be exhaustive or drift resumes |
| Test refactor to exercise real classifier | Feasible | `test_config.py` currently reimplements classifier inline; needs to import the real entry point |
| Never-route-to-mythos guarantee | Feasible, trivial | Simply exclude `claude-mythos-5` from the router's output vocabulary; not accessible outside Project Glasswing anyway |

**Overall Feasibility: High** — every required capability has a documented, confirmed mechanism except session-level auto-switch (which the requirements should treat as advisory-only by design, not a blocker).
**Risk: Medium** — new runtime network/auth surface (first-ever in this codebase), undocumented multi-hook conflict resolution, doc drift already present pre-v2, and schema migration must be explicit due to `additionalProperties:false`.
**Effort: L** — touches classifier engine, config schema + migration, new PreToolUse hook, Haiku fallback with caching, subagent taxonomy, test suite, and docs/manifests across ~10+ files.

## Recommendations for Requirements

1. Make **effort** (low/medium/high/xhigh/max) the primary routing lever within a fixed model tier; only jump tiers at the extremes (very trivial -> haiku, very hard/long-horizon -> fable). Reflects ARES findings and Anthropic's own cache/tokenizer economics (effort changes are free of cache invalidation; model switches are not).
2. Adopt the 4-tier ladder `haiku -> sonnet -> opus -> fable` (`claude-haiku-4-5`, `claude-sonnet-5`, `claude-opus-4-8`, `claude-fable-5`), with haiku's degenerate case (no effort dial) handled explicitly (effort field optional/ignored when tier=haiku).
3. **Never emit `claude-mythos-5`** as a router output; treat fable as the top public tier with Opus 4.8 as its implicit fallback (matches Anthropic's own classifier-refusal fallback behavior).
4. Add a **PreToolUse hook** matching the `Agent` tool that classifies `tool_input.prompt` and returns `hookSpecificOutput.permissionDecision:"allow"` + `updatedInput.model`. Since the Agent tool has no `effort` param, effort enforcement must go through `updatedInput.subagent_type` rewritten to a plugin-shipped agent definition carrying `effort` frontmatter, or be advisory-only (steer via `additionalContext`) — decide per task-taxonomy entry which path applies.
5. Keep **warn as the default apply mode** (current committed behavior: suggest `/model X`, exit 2) for the session-level UserPromptSubmit hook; add an explicit opt-in `autoswitch` config flag, with **Fable autoswitch gated behind its own separate flag** (higher cost/latency tier deserves a stricter opt-in than sonnet/opus autoswitch).
6. Design **config schema v2** with an explicit `version`/`schemaVersion` discriminator (absent in v1), since `additionalProperties:false` means unknown v2 keys fail v1 validation rather than being ignored. Ship a v1-detection + migration path that preserves user `keywords`/`patterns`/`remove_*`/`mode` customizations, and add a `fable` tierConfig plus effort-axis fields.
7. Treat the **Haiku LLM fallback as fully greenfield**: implement via SDK or raw `/v1/messages` call, source auth from env/existing Claude Code credentials, fail-open (exit 0 / defer to heuristic result) on any error or timeout, cache classification results in `${CLAUDE_PLUGIN_DATA}` keyed by prompt hash, and budget the call well inside (or explicitly raise) the current 2-second hook timeout.
8. Replace the duplicated 3-way subagent table ("haiku=mechanical / sonnet=standard / opus=architecture") with a **robust task taxonomy** informed by prior art: explicit categories beyond difficulty alone (e.g. mechanical, implementation, debugging-as-its-own-class, architecture/deep-analysis, needs-clarification/abstain), and account for capability constraints (e.g. Haiku subagents reportedly struggling with SendMessage-based handoffs) not just difficulty when assigning the lowest tier.
9. Fix the **warn-vs-autoswitch doc drift** as part of this spec: `README.md`, `prompt.md` (root and `plugins/.../prompt.md`), and the "No API calls" marketing claims must match the committed warn-only + new-fallback behavior; deduplicate the advisory text (currently in 4 files) so future changes can't drift again, ideally with a generated-or-tested single source of truth.
10. **Refactor tests to exercise the real classifier**: `tests/test_config.py`'s inline `_classify` (`:237-266`) must be replaced with an import of the actual v2 classification entry point so unit tests can't silently diverge from behavior; extend `tests/test-hook.sh` end-to-end coverage for fable/effort/PreToolUse and update CI accordingly.
11. Build a **labeled eval set** (per RouterArena/prior-art pitfall #9) of representative prompts across the taxonomy as a pre-merge gate for router changes, specifically to catch **routing collapse** (drift toward always picking the strongest tier) over time.
12. Bump all three version manifests together (root `plugin.json`, nested `plugins/.../plugin.json`, `marketplace.json`) and close the `CHANGELOG.md` gap (stuck at 1.0.0 despite 1.0.1/1.1.0/1.3.0 releases) as part of the v2 release.

## Open Questions

1. **Claude Code default effort level is disputed**: Anthropic's own skill docs say `xhigh` is default; a secondary source claims `medium` default for Opus on Max/Team plans. Verify empirically in the target Claude Code version before hardcoding a "default = X" assumption anywhere in the router.
2. **Does `updatedInput.model` on the Agent tool accept full model IDs, or only the alias enum** (`sonnet|opus|haiku|fable`)? The live schema only showed the alias enum; agent-definition frontmatter separately accepts full IDs. Needs an empirical test.
3. **Can a `prompt`-type hook emit `updatedInput`?** Docs present `prompt` hooks as decision-oriented (allow/deny), not documented as able to rewrite tool input. If yes, it could remove the need for a self-managed Haiku call in the PreToolUse path. Verify empirically.
4. **Multi-hook conflict resolution is undocumented**: if another plugin's PreToolUse hook also returns a decision on `Agent`, precedence/merge behavior is unspecified (most-restrictive-wins is a plausible but unconfirmed assumption). Needs testing before shipping a hook that assumes exclusive control.
5. Is there any programmatic/per-request effort override channel beyond `/effort` session state and agent/skill frontmatter (e.g. something the UserPromptSubmit hook could emit)? Current research found none, but this should be reconfirmed against the current hook/settings schema.
6. `ultracode` semantics (xhigh + standing multiagent permission) — is it selectable by a hook, or strictly a UI/session-menu setting?
7. `CLAUDE_CODE_SUBAGENT_MODEL`, if user-set, silently outranks the hook's injected `model` — should the router detect and warn when this env var is present and would override its decision?

## Sources

- https://www.anthropic.com/news/claude-fable-5-mythos-5
- https://platform.claude.com/docs/en/about-claude/models/introducing-claude-fable-5-and-claude-mythos-5
- https://platform.claude.com/docs/en/build-with-claude/effort
- https://platform.claude.com/docs/en/build-with-claude/adaptive-thinking
- https://code.claude.com/docs/en/model-config
- https://code.claude.com/docs/en/fast-mode
- https://code.claude.com/docs/en/hooks
- https://code.claude.com/docs/en/sub-agents
- https://code.claude.com/docs/en/plugins-reference
- https://claudelog.com/faqs/what-is-slash-effort-command/
- https://caylent.com/blog/claude-fable-5-anthropics-first-public-mythos-class-model
- https://www.finout.io/blog/claude-fable-5-mythos-5-pricing-benchmarks
- https://github.com/anthropics/skills/blob/main/skills/claude-api/shared/models.md (bundled claude-api skill, cache 2026-06-24)
- https://arxiv.org/html/2603.07915 (ARES)
- https://arxiv.org/html/2603.04445v2 (routing/cascading survey)
- https://arxiv.org/html/2510.00202v1 (RouterArena)
- https://arxiv.org/pdf/2605.12260 (PRISM cascade)
- https://arxiv.org/pdf/2603.08501 (Fanar-Sadiq margin-based classifier)
- https://arxiv.org/html/2602.03478v1 (routing collapse)
- https://arxiv.org/html/2603.06616 (RACER)
- https://arxiv.org/pdf/2606.07587 (routing plateau)
- https://arxiv.org/html/2501.01818v1 (rerouting/confounder attacks)
- https://arxiv.org/html/2604.07494 (Triage: SE task-tier routing)
- https://arxiv.org/pdf/2606.26959 (Codex usage taxonomy)
- https://arxiv.org/pdf/2605.02241 (keyword classifier at-or-below chance)
- https://github.com/lm-sys/routellm ; https://www.lmsys.org/blog/2024-07-01-routellm/
- https://openrouter.ai/docs/guides/routing/routers/auto-router ; https://openrouter.ai/blog/insights/model-routing/
- https://docs.notdiamond.ai/docs/what-is-model-routing ; https://docs.notdiamond.ai/docs/router-training-quickstart
- https://aider.chat/2024/09/26/architect.html ; https://aider.chat/docs/usage/modes.html
- https://musistudio.github.io/claude-code-router/docs/server/config/routing/
- https://www.morphllm.com/llm-router
- https://tianpan.co/blog/2026-04-16-intent-classification-agent-routers ; https://tianpan.co/blog/2025-11-03-llm-routing-model-cascades
- https://www.mindstudio.ai/blog/set-up-ai-model-router-llm-stack-c2610
- https://blog.logrocket.com/llm-routing-right-model-for-requests/
- https://www.digitalapplied.com/blog/llm-model-routing-2026-cost-quality-optimization-engineering-guide
- https://www.ibuildwith.ai/blog/effort-thinking-opus-4-7-changed-the-rules/
- https://medium.com/@roanmonteiro/claude-code-subagent-model-routing-stop-paying-for-opus-on-haiku-work-ee76dc32cb88
- https://developers.openai.com/api/docs/guides/reasoning
- https://github.com/anthropics/claude-code/issues/27665
- Codebase (this repo): `plugins/claude-model-router-hook/hooks/model_router.py`, `hooks/model-router-hook.sh`, `hooks/session-init.sh`, `hooks/hooks.json`, `schema/model-router.schema.json`, `tests/test_config.py`, `tests/test-hook.sh`, `.github/workflows/test.yml`, `README.md`, `prompt.md`, `plugins/claude-model-router-hook/prompt.md`, `CHANGELOG.md`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`
