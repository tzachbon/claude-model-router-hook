# Research: extensible-model-router

## Executive Summary

The model router hook can be extended with config-driven keyword extensibility and AI-powered classification fallback with minimal architectural changes. The existing inline Python3 pattern handles config loading, merging, and AI classification naturally. Claude CLI's `-p --model haiku --max-turns 1` provides a clean non-interactive classification path with `timeout 8s` as safety net within the 10s hook budget.

## External Research

### AI Classification via Claude CLI

**Invocation pattern:**
```bash
classification=$(timeout 8s claude -p --model haiku --max-turns 1 "prompt" 2>/dev/null)
```

Key flags:
- `-p` / `--print`: non-interactive mode, prints to stdout and exits
- `--model haiku`: use haiku for fast/cheap classification
- `--max-turns 1`: prevents tool calls and agent loops, single LLM call
- `--output-format text`: plain text (default)

**Timeout handling:**
- `timeout 8s` wrapper leaves 2s buffer within 10s hook budget
- Exit code 124 = timed out, other non-zero = CLI error
- Fall back to sonnet on any error

**Classification prompt design:**
```
Based on the following user prompt, classify which AI model tier should handle it.
Reply with exactly one word: opus, sonnet, or haiku.

- opus: complex reasoning, architecture, debugging hard problems, multi-file refactoring
- sonnet: moderate tasks, code generation, explanations, standard development
- haiku: simple questions, typo fixes, formatting, one-line changes, quick lookups

User prompt: {PROMPT}
```

**Output parsing:** lowercase + trim + validate against opus/sonnet/haiku, else fallback to sonnet.

**Gotchas:** cold start latency, auth must be pre-configured, consider truncating long prompts to ~500 chars.

### Config Loading Patterns

**Recommendation: use inline Python3** (already used for classification). Avoids jq dependency.

**Config locations:**
- Global: `~/.claude/model-router-config.json`
- Project: `$PROJECT_ROOT/.claude/model-router-config.json` (via `git rev-parse --show-toplevel`)

**Merge rules:**
| Field Type | Merge Behavior |
|-----------|---------------|
| Array (keywords) | Union + dedup (additive) |
| Scalar (string) | Last-write-wins (project > global) |

**Precedence (lowest to highest):**
1. Built-in defaults (hardcoded)
2. Global user config
3. Project config
4. Environment variables

**ENV overrides:**
| Variable | Purpose |
|----------|---------|
| `CLAUDE_ROUTER_FORCE_MODEL` | Skip classification, always use this model |
| `CLAUDE_ROUTER_EXTRA_OPUS_KEYWORDS` | Comma-separated additional opus keywords |
| `CLAUDE_ROUTER_CLASSIFIER` | Override classifier type |
| `CLAUDE_ROUTER_DISABLED` | Disable routing entirely |

**Error handling:** missing config = silent fallback to defaults. Malformed JSON = stderr warning + defaults. Never crash the hook.

### Best Practices
- Config files always optional
- Use `CLAUDE_ROUTER_` prefix for all env vars
- `additionalProperties: true` in schema for forward compatibility
- Validate minimally: check enum values, check array items are strings

### Pitfalls to Avoid
- Do not add jq dependency when Python3 already handles JSON
- Do not crash hook on config errors
- Do not make config required
- AI classifier cold start can be slow on first call
- Rate limits possible with frequent haiku calls

## Codebase Analysis

### Existing Patterns
- Hook receives JSON on stdin with `prompt` and `model` fields
- All logic in inline Python3 within bash heredoc
- Keyword matching: exact string `in` check for opus, regex `re.search` for haiku/sonnet
- Exit 0 = allow, exit 2 = block with stderr message
- `~` prefix bypass mechanism
- Logging to `~/.claude/hooks/model-router-hook.log`

### Dependencies
- Bash 3.2+, Python3 stdlib only (json, sys, os, re, datetime)
- No external packages, no build step
- No test infrastructure exists

### Constraints
- Current timeout: 2s per hook
- Must work as both standalone hooks and plugin (${CLAUDE_PLUGIN_ROOT})
- Plugin variant at `plugins/claude-model-router-hook/hooks/`
- Both hook sets must stay in sync
- No package.json, no CI/CD, no test runner

### Extension Points
- Config loading fits naturally before the classification block in the Python3 inline code
- AI classification fits as a fallback after keyword matching returns None
- Keyword lists are simple Python lists, easy to extend via config merge

## Related Specs

No related specs found (first spec in this project).

## Quality Commands

| Type | Command | Source |
|------|---------|--------|
| Manual test | `echo '{"prompt":"test","model":"opus"}' \| ./hooks/model-router-hook.sh` | Codebase |
| Log check | `tail -f ~/.claude/hooks/model-router-hook.log` | Codebase |
| Hook perms | `ls -l ~/.claude/hooks/` | Codebase |

No automated test suite exists. Test script creation is part of this spec's scope.

## Feasibility Assessment

| Aspect | Assessment | Notes |
|--------|-----------|-------|
| Config loading | High feasibility | Python3 json module, no new deps |
| Config merging | High feasibility | Simple list concat + dedup |
| Per-project config | High feasibility | git rev-parse for project root |
| ENV overrides | High feasibility | os.environ in Python3 |
| AI classification | Medium-high feasibility | Claude CLI dependency, timeout concerns |
| Test script | High feasibility | Pipe JSON to hook, assert exit code + output |

## Recommendations for Requirements

1. Keep all config loading in the existing inline Python3 block
2. Config schema: `classifier`, `keywords.opus/sonnet/haiku` arrays, `default_model`
3. AI classifier: `timeout 8s claude -p --model haiku --max-turns 1`
4. Bump hook timeout to 10s in both hooks.json files
5. Create test script that validates classification with sample prompts
6. Both standalone and plugin hook scripts must be updated in sync
7. Fall back to sonnet on any AI classifier error

## Open Questions

1. Should the AI classification prompt be customizable via config?
2. Should there be a caching mechanism for AI classification results?
3. Should the config support custom haiku/sonnet regex patterns (not just keywords)?

## Sources

- Claude CLI documentation (web search)
- ESLint, AWS CLI config precedence patterns (web search)
- hooks/model-router-hook.sh (codebase)
- hooks/session-init.sh (codebase)
- hooks/hooks.json (codebase)
- plugins/claude-model-router-hook/ (codebase)
