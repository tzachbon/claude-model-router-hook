# Requirements: Extensible Model Router

**Spec**: extensible-model-router
**Issue**: #1
**Date**: 2026-03-08

---

## User Stories

### US-1: Global Config Loading

**As a** plugin user, **I want to** place a config file at `~/.claude/model-router-config.json` **so that** I can customize routing behavior without forking the repo.

**Acceptance Criteria:**
- Hook reads `~/.claude/model-router-config.json` on every invocation
- Missing file is silently ignored, defaults apply
- Malformed JSON prints warning to stderr and falls back to defaults
- Hook never crashes due to config issues

### US-2: Per-Project Config

**As a** developer working on multiple projects, **I want to** place `.claude/model-router-config.json` in a repo root **so that** each project can have its own routing rules.

**Acceptance Criteria:**
- Project root detected via `git rev-parse --show-toplevel`
- Project config at `<project-root>/.claude/model-router-config.json`
- Project config merges on top of global config (see US-3)
- Non-git directories skip project config silently
- Missing project config is silently ignored

### US-3: Config Merging

**As a** user with both global and project configs, **I want** them merged predictably **so that** project-specific rules layer on top of my global preferences.

**Acceptance Criteria:**
- Array fields (keywords, patterns): union with dedup (additive)
- Scalar fields (classifier, default_model): project overrides global (last-write-wins)
- Precedence (lowest to highest): built-in defaults < global config < project config < ENV variables
- Built-in keywords/patterns always present, never removed by config

### US-4: Custom Keywords Per Tier

**As a** user, **I want to** add custom keywords for opus, sonnet, and haiku tiers **so that** domain-specific terms route to the right model.

**Acceptance Criteria:**
- Config schema supports `keywords.opus`, `keywords.sonnet`, `keywords.haiku` arrays of strings
- Custom keywords merged additively with built-in keywords
- Keywords matched case-insensitively via substring match (existing behavior)
- Empty arrays are valid and add nothing

### US-5: Custom Regex Patterns Per Tier

**As a** user, **I want to** add custom regex patterns per tier **so that** I can define flexible matching rules beyond simple keywords.

**Acceptance Criteria:**
- Config schema supports `patterns.opus`, `patterns.sonnet`, `patterns.haiku` arrays of regex strings
- Custom patterns merged additively with built-in patterns
- Patterns compiled via Python `re.search`, invalid regex logged and skipped
- Opus tier gains pattern support (currently keyword-only)

### US-6: ENV Overrides

**As a** power user, **I want** environment variable overrides **so that** I can control routing behavior in CI, scripts, or per-session.

**Acceptance Criteria:**
- `CLAUDE_ROUTER_FORCE_MODEL=opus|sonnet|haiku` skips classification entirely, always recommends that model
- `CLAUDE_ROUTER_EXTRA_OPUS_KEYWORDS=kw1,kw2` adds comma-separated keywords to opus tier
- `CLAUDE_ROUTER_CLASSIFIER=keywords|ai|hybrid` overrides the classifier mode
- `CLAUDE_ROUTER_DISABLED=1` disables routing entirely (exit 0 immediately)
- ENV overrides take highest precedence, above all config files

### US-7: AI Classification Fallback

**As a** user, **I want** AI-powered classification via Claude CLI **so that** prompts that don't match any keyword still get routed appropriately.

**Acceptance Criteria:**
- Invoked via `timeout 8s claude -p --model haiku --max-turns 1 "<classification_prompt>"`
- Only used when keyword/regex matching returns no recommendation
- Classification prompt includes tier descriptions and user prompt (truncated to 500 chars)
- Response parsed: lowercase, trimmed, validated against opus/sonnet/haiku
- Invalid response or any error falls back to sonnet
- Timeout (exit code 124) falls back to sonnet

### US-8: Classifier Config Option

**As a** user, **I want to** choose my classifier mode **so that** I can control whether AI classification is used.

**Acceptance Criteria:**
- Config field `classifier` accepts: `"keywords"` (default), `"ai"`, `"hybrid"`
- `keywords`: keyword/regex matching only, no AI fallback (current behavior)
- `ai`: AI classification only, skip keyword/regex matching
- `hybrid`: keyword/regex first, AI fallback on no match
- Default is `keywords` for backward compatibility

### US-9: Test Script

**As a** developer, **I want** a test script that validates classification **so that** I can verify routing behavior after changes.

**Acceptance Criteria:**
- Script at `tests/test-model-router.sh`
- Pipes sample prompts as JSON to the hook and asserts expected classification
- Tests cover classification: opus keywords, sonnet patterns, haiku patterns, override bypass, no-match fallback
- Tests cover config loading: valid JSON parsed correctly, malformed JSON falls back to defaults with stderr warning, missing file silently ignored
- Tests cover config merging: global config only, project config only, global + project overlay with correct precedence
- Tests cover custom keywords from config: added keywords trigger expected tier classification
- Tests cover custom patterns from config: added regex patterns trigger expected tier classification
- Tests cover ENV overrides: `CLAUDE_ROUTER_FORCE_MODEL` bypasses classification, `CLAUDE_ROUTER_DISABLED=1` exits immediately
- Tests run without external dependencies (no AI mode testing required)
- Exit 0 on all pass, exit 1 on any failure with clear output

### US-10: Backward Compatibility

**As an** existing user with no config file, **I want** the hook to behave identically to today **so that** the update is non-breaking.

**Acceptance Criteria:**
- No config file + no ENV vars = exact same behavior as current hook
- Same built-in keywords and patterns
- Same mismatch detection and blocking logic
- Same log format and location
- Same `~` prefix override behavior

---

## Functional Requirements

### FR-1: Config Schema

```json
{
  "classifier": "keywords | ai | hybrid",
  "default_model": "sonnet",
  "keywords": {
    "opus": ["custom-keyword"],
    "sonnet": ["custom-keyword"],
    "haiku": ["custom-keyword"]
  },
  "patterns": {
    "opus": ["custom-regex"],
    "sonnet": ["custom-regex"],
    "haiku": ["custom-regex"]
  }
}
```

All fields optional. Unknown fields ignored (forward compatibility).
Default for `classifier` is `"keywords"` when omitted (backward compatible, no AI calls).
Default for `default_model` is `"sonnet"` when omitted.

### FR-2: Config Loading Order

1. Initialize with built-in defaults (current hardcoded keywords/patterns)
2. Load and merge `~/.claude/model-router-config.json` (if exists)
3. Detect project root via `git rev-parse --show-toplevel 2>/dev/null`
4. Load and merge `<project-root>/.claude/model-router-config.json` (if exists)
5. Apply ENV overrides

### FR-3: Keyword Merge Logic

```python
final_opus_keywords = deduplicate(builtin_opus + global_opus + project_opus + env_extra_opus)
```

Same pattern for sonnet, haiku (no ENV extras for those in this iteration).

### FR-4: Classification Flow

```
if CLAUDE_ROUTER_DISABLED=1 -> exit 0
if CLAUDE_ROUTER_FORCE_MODEL set -> use that model, skip classification
if classifier == "keywords" -> keyword/regex match only
if classifier == "ai" -> AI classify only
if classifier == "hybrid" -> keyword/regex first, AI on no match
```

### FR-5: AI Classification Invocation

- Command: `timeout 8s claude -p --model haiku --max-turns 1 "<prompt>"`
- Prompt truncated to first 500 characters
- Output: lowercase, strip whitespace, validate is one of opus/sonnet/haiku
- Any failure (timeout, non-zero exit, invalid output): return sonnet as default

### FR-6: Hook Timeout Update

- Update `timeout` in both `hooks/hooks.json` and `plugins/claude-model-router-hook/hooks/hooks.json` from `2` to `10`

### FR-7: Dual Hook Sync

- Both `hooks/model-router-hook.sh` and `plugins/claude-model-router-hook/hooks/model-router-hook.sh` must contain identical classification logic
- Both `hooks.json` files updated with matching timeout

### FR-8: Logging

- Existing log format preserved
- New log entries for: config loaded (debug), AI classification invoked, AI classification result/timeout
- Log destination unchanged: `~/.claude/hooks/model-router-hook.log`

---

## Non-Functional Requirements

### NFR-1: Performance

- Hook timeout budget: 10 seconds total
- AI classification budget: 8 seconds (`timeout 8s`)
- Keyword-only mode: < 500ms (no regression from current)
- Config loading overhead: negligible (local file reads)

### NFR-2: Compatibility

- Bash 3.2+ (macOS default)
- Python3 stdlib only (json, sys, os, re, datetime, subprocess)
- No external packages, no pip dependencies
- No jq dependency

### NFR-3: Error Handling

- Graceful degradation: any error in config loading, AI classification, or pattern compilation falls back to defaults
- Never crash the hook (exit 0 on unexpected errors)
- Malformed config JSON: warn on stderr, use defaults
- Invalid regex in config: warn on stderr, skip that pattern
- Missing `claude` CLI when AI mode requested: warn on stderr, fall back to keyword mode

### NFR-4: Security

- Config files must be local (no network fetching)
- AI classification prompt does not include sensitive file contents, only the user prompt text
- No shell injection from config values (keywords/patterns are used in Python, not shell)

---

## Glossary

| Term | Definition |
|------|-----------|
| **Tier** | Model capability level: opus (highest), sonnet (mid), haiku (lowest) |
| **Classifier** | The method used to determine which tier a prompt needs |
| **Keyword matching** | Exact substring match against the prompt (case-insensitive) |
| **Pattern matching** | Python regex match via `re.search` against the prompt |
| **AI classification** | Using Claude CLI with haiku to classify prompt complexity |
| **Hybrid mode** | Keyword/regex matching first, AI classification as fallback |
| **Hook** | Claude Code hook script triggered on UserPromptSubmit |
| **Mismatch** | When the recommended tier differs from the currently active model |
| **Config merge** | Combining global + project configs with additive arrays and override scalars |

---

## Out of Scope

- Custom tier definitions (only opus/sonnet/haiku supported)
- Log rotation or log management
- Auto-switch toggle (hook always blocks with suggestion, user switches manually)
- Slash command integration
- AI classification prompt customization via config
- Caching of AI classification results
- ENV extras for sonnet/haiku keywords (only opus in this iteration)

---

## Dependencies

| Dependency | Required | Purpose |
|-----------|----------|---------|
| Bash 3.2+ | Yes | Hook shell wrapper |
| Python3 | Yes | All classification logic (inline) |
| Python3 stdlib (json, sys, os, re, datetime, subprocess) | Yes | Config loading, matching, AI invocation |
| `claude` CLI | No (optional) | AI classification mode only |
| `git` | No (optional) | Project root detection for per-project config |
| `timeout` command | No (optional) | AI classification safety net |
