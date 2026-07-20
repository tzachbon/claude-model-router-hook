<div align="center">

# Claude Model Router Hook

**Effort-first model routing for Claude Code. Heuristics-first, opt-in autoswitch.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey)
![Shell](https://img.shields.io/badge/shell-bash-blue)

<video src="docs/slides/public/model-router.mov" width="887" controls></video>

</div>

A Claude Code hook system that classifies every prompt into a task class and effort level, then routes it to the right model. Warning is the default; autoswitch is opt-in. Sub-agent routing is enforced at spawn time so spawned agents also land on the right tier.

## Features

- Classifies each prompt into a task class and effort level with a heuristics-first classifier; no API key required
- Warns by default; opt-in autoswitch writes the recommended model to `~/.claude/settings.json` for new sessions only
- Enforces sub-agent routing at spawn time via a `PreToolUse` hook, and injects the tier rules into every session via `SessionStart`
- Effort-first routing with boundary damping, so near-threshold prompts warn instead of flipping the model
- Prefix any prompt with `~` or `<` to bypass classification and keep the current model

## How It Works

Three hooks run inside Claude Code, all backed by a shared Python router package:

**`user_prompt_submit.py`** (`UserPromptSubmit`) classifies the incoming prompt into a task class and effort level, then compares the recommendation against your current model. In the default `warn` mode it injects an advisory message. In autoswitch mode it writes the recommended model to `~/.claude/settings.json` so the next session starts on the right tier; running sessions are never switched mid-flight.

**`pre_tool_use.py`** (`PreToolUse` on `Agent`/`Task`) enforces sub-agent routing at spawn time. Generic spawns are rewritten to the matching `routed-*` agent variant, custom agent types get a model-only recommendation, and an explicit model set by the caller is always respected. Controlled by `subagent_enforcement` (`on` | `advisory` | `off`, default `on`).

**`session_init.py`** (`SessionStart`) injects the task-class rules below into every session so you and your sub-agents share one routing table.

![Sub-agent spawned with the routed model](assets/sub-agent-routing.png)

### Routing model

Routing is effort-first: the classifier picks an effort level, then the model that fits it. `effort_warn_distance` damps borderline cases so a prompt near a class boundary warns rather than flipping the model. The classifier is heuristics-first (keyword and pattern matching) with an optional headless `claude -p --model haiku` fallback for ambiguous prompts. The fallback needs no API key (it uses your Claude Code auth), caches results by prompt hash in the plugin data dir, and can be disabled with `classifier.cli_fallback: false`. Everything fails open: any error passes the prompt through unmodified.

<!-- advisory:start -->
## Model Tier Rules

These rules apply to YOU and to every sub-agent you spawn.

### Task classes and default targets

| Class | Target model | Effort | When to use |
|---|---|---|---|
| mechanical | haiku | none | Git ops, renames, formatting, lint, file moves, version bumps, quick lookups, short imperative tasks. |
| implementation | sonnet | medium | Writing or editing code, building features, creating components or APIs, writing tests, standard feature work. |
| debugging | sonnet | high | Diagnosing failures, flaky tests, races, regressions, stack traces, bisecting, reproducing bugs. |
| architecture | opus | high | Architecture decisions, tradeoff analysis, redesigns, deep multi-file analysis, sustained reasoning over large context. |
| extreme | fable | high | Multi-system migrations, codebase-wide rewrites, long-horizon plans, RFCs and design docs, platform-scale work. |
| abstain | (no routing) | - | Prompt does not clearly match any class; current model and effort pass through unmodified. |

### Sub-agent model selection (MANDATORY)

When calling the Agent tool, set the model parameter to match the task class
above. Never default all sub-agents to opus. Match the model to the work:
mechanical work goes to haiku, standard coding to sonnet, deep analysis to
opus, and only platform-scale efforts to fable.
<!-- advisory:end -->

## Installation

### Plugin install (recommended)

```bash
claude plugin marketplace add tzachbon/claude-model-router-hook
claude plugin install claude-model-router-hook@claude-model-router-hook
```

Hooks are registered automatically. Restart Claude Code to activate.

### Manual

```bash
git clone https://github.com/tzachbon/claude-model-router-hook.git
cd claude-model-router-hook
./install.sh
```

The plugin registers its `SessionStart`, `UserPromptSubmit`, and `PreToolUse` hooks through its bundled `hooks.json`; there is nothing to wire into `settings.json` by hand. Restart Claude Code to activate.

## Override

Prefix any prompt with `~` or `<` to skip classification entirely and keep the current model active.

## Configuration

Config lives in `~/.claude/model-router.json` (global) and `.claude/model-router.json` inside a project (project wins), merged over built-in defaults. Both files are optional. The schema is v2; a v1 config is migrated in memory at load time and your files are never rewritten. Example:

```json
{
  "version": 2,
  "apply_mode": "warn",
  "allow_fable_autoswitch": false,
  "subagent_enforcement": "on",
  "classifier": { "cli_fallback": true },
  "thresholds": { "effort_warn_distance": 2 }
}
```

Key knobs:

| Key | Default | Effect |
|---|---|---|
| `apply_mode` | `warn` | `warn` advises only; autoswitch writes the recommended model to `~/.claude/settings.json` for new sessions only, never the live one. |
| `allow_fable_autoswitch` | `false` | Extra gate: even in autoswitch mode, routing up to `fable` only writes when this is on. |
| `subagent_enforcement` | `on` | `on` rewrites/injects sub-agent routing in `PreToolUse`; `advisory` recommends only; `off` disables it. |
| `classifier.cli_fallback` | `true` | Enables the optional headless `claude -p --model haiku` classifier fallback for ambiguous prompts. |
| `thresholds.effort_warn_distance` | `2` | Boundary damping: prompts within this effort distance of a class edge warn instead of switching. |

## Log

Activity is written to `~/.claude/hooks/model-router-hook.log`:

```
[2026-03-07 12:00:00] action=AUTOSWITCH->opus model=sonnet effort=medium klass=architecture target_effort=high prompt="evaluate the tradeoffs betwee..."
[2026-03-07 12:01:00] action=SUGGEST->sonnet model=haiku effort=none klass=implementation target_effort=medium prompt="build the settings panel comp..."
[2026-03-07 12:02:00] action=OVERRIDE prompt="~ keep opus for this one"
```

`action=` comes first, followed by any `model` / `effort` / `klass` / `target_effort` fields, then the truncated prompt snippet. `AUTOSWITCH->` lines record a settings write (autoswitch mode); `SUGGEST->` lines record a warn-mode advisory; `OVERRIDE` marks a bypassed prompt. A prompt that already matches its tier exits silently and writes no line.


## Known limitations

- Multi-hook `updatedInput` merge order (A-3): when more than one `PreToolUse` hook returns an `updatedInput` for the same tool call, the order in which Claude Code merges them is undocumented platform behavior. The router writes its rewrite defensively, but a competing hook that also rewrites the spawn can win depending on merge order.

## Credits

Based on [model-matchmaker](https://github.com/coyvalyss1/model-matchmaker) by [@coyvalyss1](https://github.com/coyvalyss1).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT. See [LICENSE](LICENSE).
