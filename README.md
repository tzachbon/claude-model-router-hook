<div align="center">

# Claude Model Router Hook

**Effort-first model routing for Claude Code. Heuristics-first, opt-in autoswitch.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey)
![Shell](https://img.shields.io/badge/shell-bash-blue)

</div>

## Install

```bash
installer="$(curl -fsSL https://raw.githubusercontent.com/tzachbon/claude-model-router-hook/361031c9381fd6d2b5c47b311b7037015b3c2f6d/install.sh)" && bash -c "$installer"
```

The wizard asks whether to install globally and star the GitHub repository. Both prompts default to yes. Installation requires Claude Code and Python 3; starring requires an authenticated `gh` command. Restart Claude Code after installation.

<video src="docs/slides/public/model-router.mov" width="887" controls></video>

Claude Model Router classifies each prompt by task and effort, then recommends the matching Claude model. It warns by default. Autoswitch is opt-in and only affects new sessions.

## What it does

- Routes prompts with local heuristics and an optional Claude Code fallback.
- Uses Haiku only for clearly mechanical work; defaults agentic coding to Opus with graduated effort.
- Routes `Agent` and `Task` sub-agents when they spawn. Nested delegation is floored at the implementation target, and an explicit model always wins.
- Records the requested and resolved model for completed sub-agents, so host-side fallback or allowlist substitutions are visible.
- Dampens borderline classifications instead of switching tiers on weak evidence.

## How it works

| Hook | Job |
|---|---|
| `UserPromptSubmit` | Classifies the prompt and warns or writes the next-session model. |
| `PreToolUse` | Routes `Agent` and `Task` spawns. |
| `PostToolUse` | Logs the model actually used by completed `Agent` and `Task` work. |
| `SessionStart` | Adds the shared task-class rules to each session. |

Errors fail open and leave the prompt unchanged. Prefix a prompt with `~` or `<` to skip routing.

![Sub-agent spawned with the routed model](assets/sub-agent-routing.png)

<!-- advisory:start -->
## Model Tier Rules

These rules apply to YOU and to every sub-agent you spawn.

### Task classes and default targets

| Class | Target model | Effort | When to use |
|---|---|---|---|
| mechanical | haiku | none | Git ops, renames, formatting, lint, file moves, version bumps, quick lookups, short imperative tasks. |
| implementation | opus | medium | Writing or editing code, building features, creating components or APIs, writing tests, standard feature work. |
| debugging | opus | high | Diagnosing failures, flaky tests, races, regressions, stack traces, bisecting, reproducing bugs. |
| architecture | opus | xhigh | Architecture decisions, tradeoff analysis, redesigns, deep multi-file analysis, sustained reasoning over large context. |
| extreme | opus | max | Multi-system migrations, codebase-wide rewrites, long-horizon plans, RFCs and design docs, platform-scale work. |
| abstain | (no routing) | - | Prompt does not clearly match any class; current model and effort pass through unmodified. |

### Sub-agent model selection (MANDATORY)

When calling the Agent tool, set the model parameter to match the task class
above. Do not default every sub-agent to the highest effort. Match the model
and effort to the work: mechanical work goes to haiku, implementation to opus,
debugging to opus, deep analysis to opus, and platform-scale work to opus.
<!-- advisory:end -->

## Configure

Use `~/.claude/model-router.json` globally or `.claude/model-router.json` in one project. Project settings win.

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

| Key | Default | Effect |
|---|---|---|
| `apply_mode` | `warn` | Warn or write the model for the next session. |
| `allow_fable_autoswitch` | `false` | Allow autoswitching to an explicitly configured `fable` target. |
| `subagent_enforcement` | `on` | Route, advise, or ignore sub-agent spawns. |
| `classifier.cli_fallback` | `true` | Use `claude -p --model haiku` for ambiguous prompts. |
| `thresholds.effort_warn_distance` | `2` | Warn near a class boundary. |

<details>
<summary>Alternative installs</summary>

### Claude plugin manager

```bash
claude plugin marketplace add tzachbon/claude-model-router-hook
claude plugin install claude-model-router-hook@claude-model-router-hook
```

### Manual

```bash
git clone https://github.com/tzachbon/claude-model-router-hook.git
cd claude-model-router-hook
./plugins/claude-model-router-hook/install.sh
```

The manual installer prints the `settings.json` entries that you need to add.

</details>

## Notes

- Activity is logged at `~/.claude/hooks/model-router-hook.log`, including requested versus resolved sub-agent models.
- If another `PreToolUse` hook rewrites the same spawn, Claude Code's undocumented merge order decides which rewrite wins.

## Project

[Contributing](CONTRIBUTING.md) | [MIT license](LICENSE) | Based on [model-matchmaker](https://github.com/coyvalyss1/model-matchmaker) by [@coyvalyss1](https://github.com/coyvalyss1)
