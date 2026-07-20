# Changelog

All notable changes to this project will be documented here.

## [2.0.0] - 2026-07-20

Full rewrite of the router from bash wrappers into a Python `router` package with three hook entrypoints. The old `model_router.py` and shell wrappers are removed.

### Added
- 4-tier model ladder (haiku, sonnet, opus, fable) with effort-first routing: decisions are `(model, effort)` pairs, with `effort_warn_distance` damping to avoid noisy switches near a boundary
- `PreToolUse` sub-agent enforcement: generic spawns are rewritten to the shipped routed-* agent variants, custom agent types get model-only injection, an explicit caller-supplied model is respected, and `CLAUDE_CODE_SUBAGENT_MODEL` is detected
- Opt-in autoswitch that writes `~/.claude/settings.json` for new sessions (fable gated behind `allow_fable_autoswitch`); warn remains the default action
- Hybrid classifier: scored multi-signal heuristics with margin-based confidence, plus an optional headless `claude -p --model haiku` fallback. The fallback uses no API key, a hash-only cache, and a `CLAUDE_MODEL_ROUTER_CHILD` recursion guard
- Config schema v2 with a `oneOf` schema and automatic in-memory v1 migration (config files are never rewritten on disk)
- Eval harness with 70 labeled rows and docs-parity CI gates; baseline accuracy 95.71% with a documented threshold rationale

### Changed
- Timeouts raised from 2s to 10s/10s/5s across the hook stages

### Breaking
- The bash wrappers and `model_router.py` are removed in favor of the `router` package and its three hook entrypoints
- Semantic routing change: a haiku session now up-routes implementation and debugging prompts to sonnet, where v1 refused to escalate

## [1.4.0] - 2026-03-14

### Added
- `action` config option with `warn` as the default behavior
- Configuration guidance surfaced in the session prompt (#6)
- Sub-agent routing demo in the slides and README

## [1.3.0] - 2026-03-10

### Added
- User-configurable routing rules via JSON config (#3)
- Slidev presentation deck (#4)

### Changed
- Moved the plugin into the `plugins/` subdirectory with an explicit hooks path in `plugin.json`
- Registered the smart-ralph marketplace and enabled the plugin-dev plugin

### Fixed
- Always pass through XML-tagged system prompts instead of misclassifying them (#5)

## [1.1.0] - 2026-03-07

### Changed
- Replaced the direct `settings.json` write with a non-destructive `/model` suggestion

## [1.0.1] - 2026-03-07

### Added
- Claude Code plugin support with `marketplace.json` for marketplace distribution

### Changed
- Renamed the project from claude-model-advisor to claude-model-router-hook
- Moved hooks into `hooks/hooks.json` and dropped the bundled `settings.json`

### Fixed
- Wrapped the `SessionStart` hook in a hooks array so it registers correctly

## [1.0.0] - 2026-03-07

### Added
- `hooks/model-router-hook.sh` — `UserPromptSubmit` hook that classifies task complexity and auto-switches the active model in `settings.json`
- `hooks/session-init.sh` — `SessionStart` hook that injects sub-agent model-selection rules into every session
- `prompt.md` — classification prompt used by the advisor
- `install.sh` — one-command installer
- Community files: `CONTRIBUTING.md`, `SECURITY.md`, issue templates, PR template
