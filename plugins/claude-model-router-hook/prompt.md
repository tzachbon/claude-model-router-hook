# Claude Model Router Hook Setup

Install the router as a Claude Code plugin. The hooks are Python entrypoints
registered by the bundled `hooks.json`, so there is nothing to wire into
`settings.json` by hand.

## Install

### Plugin (recommended)

```bash
claude plugin marketplace add tzachbon/claude-model-router-hook
claude plugin install claude-model-router-hook@claude-model-router-hook
```

### From a clone

```bash
git clone https://github.com/tzachbon/claude-model-router-hook.git
cd claude-model-router-hook
./plugins/claude-model-router-hook/install.sh
```

Restart Claude Code after either path to activate the hooks.

## What gets registered

`hooks.json` wires three Python entrypoints:

- `session_init.py` (`SessionStart`) injects the task-class rules below into every session.
- `user_prompt_submit.py` (`UserPromptSubmit`) classifies each prompt and warns or autoswitches.
- `pre_tool_use.py` (`PreToolUse` on `Agent`/`Task`) routes sub-agent spawns to the matching tier.

## Configure

Config lives at `~/.claude/model-router.json` (global) or `.claude/model-router.json`
inside a project (project wins). Both are optional; built-in defaults apply when
absent. The schema is v2; a v1 config is migrated in memory at load time and your
files are never rewritten.

Prefix any prompt with `~` or `<` to skip classification and keep the current model.

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
