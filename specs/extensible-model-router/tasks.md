# Tasks: Extensible Model Router

## Phase 1: Make It Work (POC)

Focus: Get config loading, merging, ENV overrides, AI classification, and symlinks working end-to-end. Skip edge case polish.

- [x] 1.1 Create symlinks for hook sync
  - **Do**:
    1. Replace `hooks/model-router-hook.sh` with symlink to `../plugins/claude-model-router-hook/hooks/model-router-hook.sh`
    2. Replace `hooks/session-init.sh` with symlink to `../plugins/claude-model-router-hook/hooks/session-init.sh`
    3. Verify symlinks resolve correctly
  - **Files**: hooks/model-router-hook.sh, hooks/session-init.sh
  - **Done when**: Both files are symlinks pointing to plugin directory, `readlink` shows correct targets
  - **Verify**: `cd /home/tzachb/Projects/claude-model-advisor/.claude/worktrees/zazzy-squishing-raven && readlink hooks/model-router-hook.sh | grep -q "plugins/claude-model-router-hook" && readlink hooks/session-init.sh | grep -q "plugins/claude-model-router-hook" && echo PASS`
  - **Commit**: `feat(hooks): symlink hooks/ to plugins/ for single source of truth`
  - _Requirements: FR-7_
  - _Design: Symlink Details_

- [x] 1.2 Bump timeout in both hooks.json files
  - **Do**:
    1. In `hooks/hooks.json`, change UserPromptSubmit timeout from 2 to 10
    2. In `plugins/claude-model-router-hook/hooks/hooks.json`, change UserPromptSubmit timeout from 2 to 10
  - **Files**: hooks/hooks.json, plugins/claude-model-router-hook/hooks/hooks.json
  - **Done when**: Both hooks.json files have `"timeout": 10` for UserPromptSubmit
  - **Verify**: `cd /home/tzachb/Projects/claude-model-advisor/.claude/worktrees/zazzy-squishing-raven && python3 -c "import json; d=json.load(open('hooks/hooks.json')); assert d['hooks']['UserPromptSubmit'][0]['hooks'][0]['timeout']==10" && python3 -c "import json; d=json.load(open('plugins/claude-model-router-hook/hooks/hooks.json')); assert d['hooks']['UserPromptSubmit'][0]['hooks'][0]['timeout']==10" && echo PASS`
  - **Commit**: `feat(hooks): bump UserPromptSubmit timeout to 10s for AI classification budget`
  - _Requirements: FR-6_
  - _Design: File Structure_

- [x] 1.3 Add ENV early exits (DISABLED and FORCE_MODEL)
  - **Do**:
    1. In `plugins/claude-model-router-hook/hooks/model-router-hook.sh`, add `import subprocess` to the import line
    2. After prompt extraction and `~` bypass check, before model detection, add ENV early exit logic:
       - `CLAUDE_ROUTER_DISABLED=1` causes `sys.exit(0)`
       - `CLAUDE_ROUTER_FORCE_MODEL=opus|sonnet|haiku` sets recommendation directly, skips classification (but still does mismatch detection)
    3. For FORCE_MODEL, jump past classification to mismatch detection with the forced recommendation
  - **Files**: plugins/claude-model-router-hook/hooks/model-router-hook.sh
  - **Done when**: `CLAUDE_ROUTER_DISABLED=1` causes exit 0 on any input. `CLAUDE_ROUTER_FORCE_MODEL=haiku` with an opus-classified prompt still recommends haiku
  - **Verify**: `cd /home/tzachb/Projects/claude-model-advisor/.claude/worktrees/zazzy-squishing-raven && CLAUDE_ROUTER_DISABLED=1 echo '{"prompt":"architect the system","model":"opus"}' | bash plugins/claude-model-router-hook/hooks/model-router-hook.sh; test $? -eq 0 && echo PASS`
  - **Commit**: `feat(router): add CLAUDE_ROUTER_DISABLED and CLAUDE_ROUTER_FORCE_MODEL ENV overrides`
  - _Requirements: US-6, FR-4_
  - _Design: Component 1 - ENV Early Exit_

- [x] 1.4 [VERIFY] Quality checkpoint: verify hook still works after ENV changes
  - **Do**: Run hook with existing classification prompts to confirm no regression
  - **Verify**: `cd /home/tzachb/Projects/claude-model-advisor/.claude/worktrees/zazzy-squishing-raven && echo '{"prompt":"architect the system","model":"sonnet"}' | bash plugins/claude-model-router-hook/hooks/model-router-hook.sh 2>&1; test $? -eq 2 && echo '{"prompt":"hello","model":"sonnet"}' | bash plugins/claude-model-router-hook/hooks/model-router-hook.sh 2>&1; test $? -eq 0 && echo PASS`
  - **Done when**: Opus keyword still triggers block on sonnet model, neutral prompt still allows
  - **Commit**: `chore(router): pass quality checkpoint` (if fixes needed)

- [x] 1.5 Add load_config and merge_config functions
  - **Do**:
    1. Add `load_config(path)` function in the Python block, after imports. Reads JSON from path, returns dict. FileNotFoundError returns `{}` silently. Other exceptions print warning to stderr and return `{}`
    2. Add `merge_config(base, override)` function. Scalars (`classifier`, `default_model`) are last-write-wins. Arrays in `keywords` and `patterns` sections are union with dedup (using `dict.fromkeys`)
  - **Files**: plugins/claude-model-router-hook/hooks/model-router-hook.sh
  - **Done when**: Both functions defined in the inline Python block
  - **Verify**: `cd /home/tzachb/Projects/claude-model-advisor/.claude/worktrees/zazzy-squishing-raven && python3 -c "
import json, os
exec(open('plugins/claude-model-router-hook/hooks/model-router-hook.sh').read().split(\"python3 -c '\")[1].split(\"' 2>\")[0].replace('\\\\n','\n')[:500])
" 2>&1 | head -5; echo "PARSE_CHECK_DONE"`
  - **Commit**: `feat(router): add load_config and merge_config functions`
  - _Requirements: US-1, US-2, US-3, FR-2, FR-3_
  - _Design: Components 2, 3_

- [x] 1.6 Add config assembly pipeline
  - **Do**:
    1. After the functions but before classification, add config assembly:
       - Define `builtin` dict with current hardcoded keywords/patterns as defaults, `classifier: "keywords"`, `default_model: "sonnet"`
       - Merge global config: `~/.claude/model-router-config.json`
       - Detect project root via `subprocess.check_output(["git", "rev-parse", "--show-toplevel"])`
       - Merge project config: `<project-root>/.claude/model-router-config.json`
       - Apply ENV overrides: `CLAUDE_ROUTER_CLASSIFIER` and `CLAUDE_ROUTER_EXTRA_OPUS_KEYWORDS`
    2. Replace hardcoded `opus_keywords`, `haiku_patterns`, `sonnet_patterns` lists with references to `cfg["keywords"]` and `cfg["patterns"]`
  - **Files**: plugins/claude-model-router-hook/hooks/model-router-hook.sh
  - **Done when**: Classification uses config-driven keyword/pattern lists instead of hardcoded lists
  - **Verify**: `cd /home/tzachb/Projects/claude-model-advisor/.claude/worktrees/zazzy-squishing-raven && echo '{"prompt":"architect the system","model":"sonnet"}' | bash plugins/claude-model-router-hook/hooks/model-router-hook.sh 2>&1; test $? -eq 2 && echo PASS`
  - **Commit**: `feat(router): add config assembly pipeline with global and project config loading`
  - _Requirements: US-1, US-2, US-3, FR-2_
  - _Design: Component 4 - Config Assembly_

- [x] 1.7 [VERIFY] Quality checkpoint: backward compatibility after config refactor
  - **Do**: Verify hook behavior unchanged with no config files
  - **Verify**: `cd /home/tzachb/Projects/claude-model-advisor/.claude/worktrees/zazzy-squishing-raven && echo '{"prompt":"architect the system","model":"sonnet"}' | bash plugins/claude-model-router-hook/hooks/model-router-hook.sh 2>&1 | grep -q "opus" && echo '{"prompt":"git commit all changes","model":"opus"}' | bash plugins/claude-model-router-hook/hooks/model-router-hook.sh 2>&1 | grep -q "haiku" && echo '{"prompt":"build the feature","model":"opus"}' | bash plugins/claude-model-router-hook/hooks/model-router-hook.sh 2>&1 | grep -q "sonnet" && echo '{"prompt":"hello","model":"sonnet"}' | bash plugins/claude-model-router-hook/hooks/model-router-hook.sh 2>&1; test $? -eq 0 && echo PASS`
  - **Done when**: All four classification scenarios produce same results as before
  - **Commit**: `chore(router): pass backward compatibility checkpoint` (if fixes needed)

- [x] 1.8 Add custom keywords support via config
  - **Do**:
    1. Verify config assembly already merges `keywords.opus`, `keywords.sonnet`, `keywords.haiku` from config files into the built-in lists
    2. Test by creating a temp global config with a custom opus keyword and verifying it triggers opus classification
  - **Files**: plugins/claude-model-router-hook/hooks/model-router-hook.sh (if fixes needed)
  - **Done when**: Custom keyword in config file triggers expected tier classification
  - **Verify**: `cd /home/tzachb/Projects/claude-model-advisor/.claude/worktrees/zazzy-squishing-raven && mkdir -p /tmp/test-router && echo '{"keywords":{"opus":["xyzmagicword"]}}' > /tmp/test-router/config.json && HOME=/tmp/test-router-home mkdir -p /tmp/test-router-home/.claude && cp /tmp/test-router/config.json /tmp/test-router-home/.claude/model-router-config.json && HOME=/tmp/test-router-home echo '{"prompt":"xyzmagicword please","model":"sonnet"}' | bash plugins/claude-model-router-hook/hooks/model-router-hook.sh 2>&1 | grep -q "opus" && echo PASS; rm -rf /tmp/test-router /tmp/test-router-home`
  - **Commit**: `feat(router): verify custom keywords from config work`
  - _Requirements: US-4, FR-3_
  - _Design: Component 5 - Classification Engine_

- [x] 1.9 Add custom regex patterns support and opus pattern matching
  - **Do**:
    1. Refactor classification to use `classify_keywords(prompt_lower, word_count, cfg)` function that checks keywords AND patterns for all tiers (opus currently only checks keywords, add pattern support)
    2. For opus: check `cfg["keywords"]["opus"]` then `cfg["patterns"]["opus"]`, then length heuristics
    3. For haiku: check `cfg["keywords"]["haiku"]` then `cfg["patterns"]["haiku"]` (with word_count<60 guard)
    4. For sonnet: check `cfg["keywords"]["sonnet"]` then `cfg["patterns"]["sonnet"]`
    5. Invalid regex patterns caught via `re.error`, skipped with no crash
  - **Files**: plugins/claude-model-router-hook/hooks/model-router-hook.sh
  - **Done when**: Custom regex patterns from config trigger expected tier. Opus supports patterns. Invalid regex does not crash
  - **Verify**: `cd /home/tzachb/Projects/claude-model-advisor/.claude/worktrees/zazzy-squishing-raven && mkdir -p /tmp/test-router-home2/.claude && echo '{"patterns":{"opus":["\\\\bxyz\\\\d+"]}}' > /tmp/test-router-home2/.claude/model-router-config.json && HOME=/tmp/test-router-home2 echo '{"prompt":"handle xyz123 now","model":"sonnet"}' | bash plugins/claude-model-router-hook/hooks/model-router-hook.sh 2>&1 | grep -q "opus" && echo PASS; rm -rf /tmp/test-router-home2`
  - **Commit**: `feat(router): add custom regex patterns and opus pattern matching`
  - _Requirements: US-5, FR-1_
  - _Design: Component 5 - Classification Engine_

- [x] 1.10 [VERIFY] Quality checkpoint: full classification pipeline
  - **Do**: Test all classification modes with config
  - **Verify**: `cd /home/tzachb/Projects/claude-model-advisor/.claude/worktrees/zazzy-squishing-raven && echo '{"prompt":"architect the system","model":"sonnet"}' | bash plugins/claude-model-router-hook/hooks/model-router-hook.sh 2>&1 | grep -q "opus" && echo '{"prompt":"hello","model":"sonnet"}' | bash plugins/claude-model-router-hook/hooks/model-router-hook.sh; test $? -eq 0 && echo PASS`
  - **Done when**: Classification works with built-in and custom keywords/patterns
  - **Commit**: `chore(router): pass classification pipeline checkpoint` (if fixes needed)

- [x] 1.11 Add ENV override for extra opus keywords and classifier mode
  - **Do**:
    1. Verify `CLAUDE_ROUTER_EXTRA_OPUS_KEYWORDS=kw1,kw2` adds comma-separated keywords to opus tier (should already be in config assembly from task 1.6)
    2. Verify `CLAUDE_ROUTER_CLASSIFIER=keywords|ai|hybrid` overrides classifier mode
    3. Fix if not working
  - **Files**: plugins/claude-model-router-hook/hooks/model-router-hook.sh (if fixes needed)
  - **Done when**: ENV variables override config values as expected
  - **Verify**: `cd /home/tzachb/Projects/claude-model-advisor/.claude/worktrees/zazzy-squishing-raven && CLAUDE_ROUTER_EXTRA_OPUS_KEYWORDS=xyzenvword echo '{"prompt":"xyzenvword please","model":"sonnet"}' | bash plugins/claude-model-router-hook/hooks/model-router-hook.sh 2>&1 | grep -q "opus" && echo PASS`
  - **Commit**: `feat(router): verify ENV overrides for extra keywords and classifier mode`
  - _Requirements: US-6_
  - _Design: Component 4 - Config Assembly_

- [x] 1.12 Add AI classification function
  - **Do**:
    1. Add `classify_ai(prompt)` function in the Python block
    2. Uses `subprocess.run(["timeout", "8s", "claude", "-p", "--model", "haiku", "--max-turns", "1", classification_prompt])`
    3. Classification prompt includes tier descriptions and user prompt truncated to 500 chars
    4. Parse output: lowercase, strip, validate against opus/sonnet/haiku
    5. Any exception or invalid output returns "sonnet" as fallback
    6. Add logging for AI classification invocation and result
  - **Files**: plugins/claude-model-router-hook/hooks/model-router-hook.sh
  - **Done when**: `classify_ai` function defined and callable
  - **Verify**: `cd /home/tzachb/Projects/claude-model-advisor/.claude/worktrees/zazzy-squishing-raven && grep -c "def classify_ai" plugins/claude-model-router-hook/hooks/model-router-hook.sh | grep -q "1" && echo PASS`
  - **Commit**: `feat(router): add AI classification function via Claude CLI`
  - _Requirements: US-7, FR-5_
  - _Design: Component 5 - classify_ai_

- [x] 1.13 Add classifier mode dispatcher
  - **Do**:
    1. Replace direct classification call with mode dispatcher:
       - `keywords`: call `classify_keywords()` only (current behavior)
       - `ai`: call `classify_ai()` only
       - `hybrid`: call `classify_keywords()` first, if None call `classify_ai()`
    2. Read mode from `cfg.get("classifier", "keywords")`
    3. Handle `classify_keywords` returning None: in keywords mode, recommendation stays None (no block). In hybrid mode, falls back to AI
  - **Files**: plugins/claude-model-router-hook/hooks/model-router-hook.sh
  - **Done when**: All three classifier modes work as specified
  - **Verify**: `cd /home/tzachb/Projects/claude-model-advisor/.claude/worktrees/zazzy-squishing-raven && echo '{"prompt":"architect the system","model":"sonnet"}' | bash plugins/claude-model-router-hook/hooks/model-router-hook.sh 2>&1 | grep -q "opus" && echo PASS`
  - **Commit**: `feat(router): add classifier mode dispatcher (keywords/ai/hybrid)`
  - _Requirements: US-8, FR-4_
  - _Design: Component 5 - Main classification dispatcher_

- [x] 1.14 [VERIFY] Quality checkpoint: full feature verification
  - **Do**: Run comprehensive tests covering all new features
  - **Verify**: `cd /home/tzachb/Projects/claude-model-advisor/.claude/worktrees/zazzy-squishing-raven && CLAUDE_ROUTER_DISABLED=1 echo '{"prompt":"test","model":"opus"}' | bash plugins/claude-model-router-hook/hooks/model-router-hook.sh; E1=$?; echo '{"prompt":"architect the system","model":"sonnet"}' | bash plugins/claude-model-router-hook/hooks/model-router-hook.sh 2>/dev/null; E2=$?; echo '{"prompt":"hello","model":"sonnet"}' | bash plugins/claude-model-router-hook/hooks/model-router-hook.sh; E3=$?; test $E1 -eq 0 && test $E2 -eq 2 && test $E3 -eq 0 && echo PASS`
  - **Done when**: DISABLED exits 0, opus keyword blocks on sonnet, neutral prompt allows
  - **Commit**: `chore(router): pass full feature checkpoint` (if fixes needed)

- [x] 1.15 Add config loading and AI classification log entries
  - **Do**:
    1. Add log entry when config is loaded (debug level, only to log file): source path and whether it was found
    2. Add log entry when AI classification is invoked: classifier mode, prompt snippet
    3. Add log entry for AI classification result or timeout/error
    4. Use existing log format: `[timestamp] key=value`
  - **Files**: plugins/claude-model-router-hook/hooks/model-router-hook.sh
  - **Done when**: Log file shows config loading and AI classification events
  - **Verify**: `cd /home/tzachb/Projects/claude-model-advisor/.claude/worktrees/zazzy-squishing-raven && echo '{"prompt":"architect the system","model":"sonnet"}' | bash plugins/claude-model-router-hook/hooks/model-router-hook.sh 2>/dev/null; grep -q "config" ~/.claude/hooks/model-router-hook.log && echo PASS`
  - **Commit**: `feat(router): add logging for config loading and AI classification`
  - _Requirements: FR-8_
  - _Design: Existing Patterns to Follow_

- [x] 1.16 POC Checkpoint
  - **Do**: Verify all features work end-to-end with automated checks:
    1. Symlinks resolve
    2. Timeout bumped
    3. ENV DISABLED works
    4. ENV FORCE_MODEL works
    5. Config loading works (custom keyword triggers tier)
    6. Classification unchanged with no config
    7. Symlinked hook produces same results as plugin hook
  - **Done when**: All automated checks pass
  - **Verify**: `cd /home/tzachb/Projects/claude-model-advisor/.claude/worktrees/zazzy-squishing-raven && readlink hooks/model-router-hook.sh | grep -q "plugins" && python3 -c "import json; assert json.load(open('hooks/hooks.json'))['hooks']['UserPromptSubmit'][0]['hooks'][0]['timeout']==10" && CLAUDE_ROUTER_DISABLED=1 echo '{"prompt":"test","model":"opus"}' | bash hooks/model-router-hook.sh; test $? -eq 0 && echo '{"prompt":"architect the system","model":"sonnet"}' | bash hooks/model-router-hook.sh 2>/dev/null; test $? -eq 2 && echo "POC_PASS"`
  - **Commit**: `feat(router): complete POC for extensible model router`

## Phase 2: Refactoring

- [x] 2.1 Extract classify_keywords into clean function
  - **Do**:
    1. Ensure `classify_keywords(prompt_lower, word_count, cfg)` is a clean standalone function
    2. All keyword/pattern lists come from `cfg` parameter, no globals
    3. Return value is `"opus"`, `"sonnet"`, `"haiku"`, or `None`
    4. Opus checks keywords + patterns + length heuristics (preserving word_count>100 and word_count>200 checks)
    5. Haiku checks keywords + patterns with word_count<60 guard
    6. Sonnet checks keywords + patterns
  - **Files**: plugins/claude-model-router-hook/hooks/model-router-hook.sh
  - **Done when**: Classification logic is a clean function, no hardcoded lists outside builtin config
  - **Verify**: `cd /home/tzachb/Projects/claude-model-advisor/.claude/worktrees/zazzy-squishing-raven && echo '{"prompt":"architect the system","model":"sonnet"}' | bash plugins/claude-model-router-hook/hooks/model-router-hook.sh 2>&1 | grep -q "opus" && echo '{"prompt":"git commit all","model":"opus"}' | bash plugins/claude-model-router-hook/hooks/model-router-hook.sh 2>&1 | grep -q "haiku" && echo PASS`
  - **Commit**: `refactor(router): clean up classify_keywords function`
  - _Design: Component 5_

- [x] 2.2 Add error handling for edge cases
  - **Do**:
    1. Ensure `load_config` handles: non-dict JSON root (returns `{}`), permission errors, encoding issues
    2. Ensure `merge_config` handles: missing sections gracefully, non-list values in keyword/pattern arrays
    3. Ensure invalid regex patterns in config are caught per-pattern (log warning, skip pattern, continue)
    4. Wrap entire config assembly in try/except so config errors never crash the hook
  - **Files**: plugins/claude-model-router-hook/hooks/model-router-hook.sh
  - **Done when**: Malformed config files produce stderr warnings but hook continues with defaults
  - **Verify**: `cd /home/tzachb/Projects/claude-model-advisor/.claude/worktrees/zazzy-squishing-raven && mkdir -p /tmp/test-bad-cfg/.claude && echo '{bad json' > /tmp/test-bad-cfg/.claude/model-router-config.json && HOME=/tmp/test-bad-cfg echo '{"prompt":"hello","model":"sonnet"}' | bash plugins/claude-model-router-hook/hooks/model-router-hook.sh 2>/tmp/test-bad-stderr; EXIT=$?; test $EXIT -eq 0 && grep -q "warning" /tmp/test-bad-stderr && echo PASS; rm -rf /tmp/test-bad-cfg /tmp/test-bad-stderr`
  - **Commit**: `refactor(router): add robust error handling for config edge cases`
  - _Requirements: NFR-3_
  - _Design: Error Handling table_

- [x] 2.3 [VERIFY] Quality checkpoint: post-refactoring verification
  - **Do**: Run full suite of classification checks after refactoring
  - **Verify**: `cd /home/tzachb/Projects/claude-model-advisor/.claude/worktrees/zazzy-squishing-raven && echo '{"prompt":"architect the system","model":"sonnet"}' | bash plugins/claude-model-router-hook/hooks/model-router-hook.sh 2>/dev/null; test $? -eq 2 && echo '{"prompt":"git commit all","model":"opus"}' | bash plugins/claude-model-router-hook/hooks/model-router-hook.sh 2>/dev/null; test $? -eq 2 && echo '{"prompt":"build the feature","model":"opus"}' | bash plugins/claude-model-router-hook/hooks/model-router-hook.sh 2>/dev/null; test $? -eq 2 && echo '{"prompt":"hello","model":"sonnet"}' | bash plugins/claude-model-router-hook/hooks/model-router-hook.sh; test $? -eq 0 && echo PASS`
  - **Done when**: All classification scenarios produce correct results
  - **Commit**: `chore(router): pass post-refactoring checkpoint` (if fixes needed)

## Phase 3: Testing

- [x] 3.1 Create test script skeleton
  - **Do**:
    1. Create `tests/test-model-router.sh`
    2. Add shebang, PASS/FAIL counters, HOOK path variable
    3. Add `assert_exit()` helper: runs hook with given JSON input, checks exit code
    4. Add `assert_stderr_contains()` helper: checks stderr output contains expected string
    5. Add `setup_config()` helper: creates temp dir with config file, sets HOME
    6. Add `cleanup()` helper: removes temp dirs
    7. Add summary output at end: total pass/fail, exit 1 if any failures
    8. Make executable: `chmod +x`
  - **Files**: tests/test-model-router.sh
  - **Done when**: Script runs and reports 0 tests (skeleton only)
  - **Verify**: `cd /home/tzachb/Projects/claude-model-advisor/.claude/worktrees/zazzy-squishing-raven && bash tests/test-model-router.sh 2>&1 | grep -q "PASS\|FAIL\|pass\|fail\|0" && echo PASS`
  - **Commit**: `test(router): create test script skeleton with helpers`
  - _Requirements: US-9_
  - _Design: Test Strategy_

- [x] 3.2 Add classification tests
  - **Do**:
    1. Test opus keyword triggers opus: `{"prompt":"architect the system","model":"sonnet"}` -> exit 2, stderr mentions opus
    2. Test sonnet pattern triggers sonnet: `{"prompt":"build the feature","model":"opus"}` -> exit 2, stderr mentions sonnet
    3. Test haiku pattern triggers haiku: `{"prompt":"git commit all changes","model":"opus"}` -> exit 2, stderr mentions haiku
    4. Test no match allows: `{"prompt":"hello","model":"sonnet"}` -> exit 0
    5. Test `~` prefix bypasses: `{"prompt":"~ architect it","model":"sonnet"}` -> exit 0
    6. Test word count heuristics: long prompt (>200 words) -> opus
  - **Files**: tests/test-model-router.sh
  - **Done when**: All classification tests pass
  - **Verify**: `cd /home/tzachb/Projects/claude-model-advisor/.claude/worktrees/zazzy-squishing-raven && bash tests/test-model-router.sh 2>&1 | tail -3`
  - **Commit**: `test(router): add classification test cases`
  - _Requirements: US-9, US-10_

- [x] 3.3 Add config loading tests
  - **Do**:
    1. Test valid JSON parsed: temp config with custom opus keyword, keyword triggers opus
    2. Test malformed JSON warns: temp file with `{bad`, stderr warning, defaults apply
    3. Test missing file silent: no config, no stderr warning, exit 0
    4. Test non-dict JSON: temp file with `[1,2,3]`, falls back to defaults
  - **Files**: tests/test-model-router.sh
  - **Done when**: All config loading tests pass
  - **Verify**: `cd /home/tzachb/Projects/claude-model-advisor/.claude/worktrees/zazzy-squishing-raven && bash tests/test-model-router.sh 2>&1 | tail -3`
  - **Commit**: `test(router): add config loading test cases`
  - _Requirements: US-1, US-9_

- [x] 3.4 [VERIFY] Quality checkpoint: test suite status
  - **Do**: Run full test suite and verify all pass
  - **Verify**: `cd /home/tzachb/Projects/claude-model-advisor/.claude/worktrees/zazzy-squishing-raven && bash tests/test-model-router.sh; test $? -eq 0 && echo PASS`
  - **Done when**: All tests pass with exit 0
  - **Commit**: `chore(router): pass test suite checkpoint` (if fixes needed)

- [x] 3.5 Add config merging tests
  - **Do**:
    1. Test global config only: custom keyword from global config triggers tier
    2. Test project config only: custom keyword from project config triggers tier (create temp git repo)
    3. Test global + project overlay: global has classifier=keywords, project has classifier=hybrid, verify hybrid takes effect
    4. Test arrays merged additively: global opus kw=["foo"], project opus kw=["bar"], both trigger opus
  - **Files**: tests/test-model-router.sh
  - **Done when**: All merge tests pass
  - **Verify**: `cd /home/tzachb/Projects/claude-model-advisor/.claude/worktrees/zazzy-squishing-raven && bash tests/test-model-router.sh 2>&1 | tail -3`
  - **Commit**: `test(router): add config merging test cases`
  - _Requirements: US-3, US-9_

- [x] 3.6 Add custom keywords and patterns tests
  - **Do**:
    1. Test custom keyword triggers tier: config adds "foobar" to opus keywords, prompt with "foobar" -> opus
    2. Test custom regex pattern triggers tier: config adds `\\bxyz\\d+` to opus patterns, prompt with "xyz123" -> opus
    3. Test custom haiku keyword: config adds "quickfix" to haiku keywords, prompt with "quickfix" (short) -> haiku
    4. Test invalid regex skipped: config has invalid regex `[bad`, hook does not crash
  - **Files**: tests/test-model-router.sh
  - **Done when**: All custom keyword/pattern tests pass
  - **Verify**: `cd /home/tzachb/Projects/claude-model-advisor/.claude/worktrees/zazzy-squishing-raven && bash tests/test-model-router.sh 2>&1 | tail -3`
  - **Commit**: `test(router): add custom keywords and patterns test cases`
  - _Requirements: US-4, US-5, US-9_

- [x] 3.7 Add ENV override tests
  - **Do**:
    1. Test `CLAUDE_ROUTER_DISABLED=1` exits immediately: any prompt -> exit 0
    2. Test `CLAUDE_ROUTER_FORCE_MODEL=haiku` bypasses classification: opus prompt -> recommends haiku
    3. Test `CLAUDE_ROUTER_EXTRA_OPUS_KEYWORDS=myword`: prompt with "myword" -> opus
    4. Test `CLAUDE_ROUTER_CLASSIFIER=keywords`: only keyword matching used
  - **Files**: tests/test-model-router.sh
  - **Done when**: All ENV override tests pass
  - **Verify**: `cd /home/tzachb/Projects/claude-model-advisor/.claude/worktrees/zazzy-squishing-raven && bash tests/test-model-router.sh 2>&1 | tail -3`
  - **Commit**: `test(router): add ENV override test cases`
  - _Requirements: US-6, US-9_

- [x] 3.8 [VERIFY] Quality checkpoint: complete test suite
  - **Do**: Run full test suite, verify all pass, check test count
  - **Verify**: `cd /home/tzachb/Projects/claude-model-advisor/.claude/worktrees/zazzy-squishing-raven && bash tests/test-model-router.sh; test $? -eq 0 && echo PASS`
  - **Done when**: All tests pass, exit 0, test count >= 15
  - **Commit**: `chore(router): pass complete test suite checkpoint` (if fixes needed)

## Phase 4: Quality Gates

- [x] 4.1 [VERIFY] Full local verification
  - **Do**: Run complete test suite and backward compatibility checks
  - **Verify**: `cd /home/tzachb/Projects/claude-model-advisor/.claude/worktrees/zazzy-squishing-raven && bash tests/test-model-router.sh && readlink hooks/model-router-hook.sh | grep -q "plugins" && python3 -c "import json; assert json.load(open('hooks/hooks.json'))['hooks']['UserPromptSubmit'][0]['hooks'][0]['timeout']==10" && echo "ALL_PASS"`
  - **Done when**: Tests pass, symlinks correct, timeout bumped
  - **Commit**: `fix(router): address issues from local verification` (if fixes needed)

- [x] V4 [VERIFY] Full local CI: bash tests/test-model-router.sh
  - **Do**: Run complete test suite as final gate
  - **Verify**: `cd /home/tzachb/Projects/claude-model-advisor/.claude/worktrees/zazzy-squishing-raven && bash tests/test-model-router.sh && echo V4_PASS`
  - **Done when**: All tests pass
  - **Commit**: None

- [x] V5 [VERIFY] Backward compatibility final check
  - **Do**: Verify no-config behavior matches original hook behavior exactly
  - **Verify**: `cd /home/tzachb/Projects/claude-model-advisor/.claude/worktrees/zazzy-squishing-raven && echo '{"prompt":"architect the system","model":"sonnet"}' | bash plugins/claude-model-router-hook/hooks/model-router-hook.sh 2>&1 | grep -q "opus" && echo '{"prompt":"git commit all changes","model":"opus"}' | bash plugins/claude-model-router-hook/hooks/model-router-hook.sh 2>&1 | grep -q "haiku" && echo '{"prompt":"build the feature","model":"opus"}' | bash plugins/claude-model-router-hook/hooks/model-router-hook.sh 2>&1 | grep -q "sonnet" && echo '{"prompt":"hello","model":"sonnet"}' | bash plugins/claude-model-router-hook/hooks/model-router-hook.sh; test $? -eq 0 && echo '{"prompt":"~ architect","model":"sonnet"}' | bash plugins/claude-model-router-hook/hooks/model-router-hook.sh; test $? -eq 0 && echo V5_PASS`
  - **Done when**: All backward compat scenarios pass
  - **Commit**: None
  - _Requirements: US-10_

- [x] V6 [VERIFY] AC checklist
  - **Do**: Programmatically verify each acceptance criteria:
    1. AC US-1: Config file loaded from `~/.claude/model-router-config.json` (grep code for path)
    2. AC US-2: Project config via git rev-parse (grep code for git rev-parse)
    3. AC US-3: Merge logic with dedup (grep code for dict.fromkeys)
    4. AC US-4: Custom keywords schema (grep code for keywords.opus)
    5. AC US-5: Custom patterns schema (grep code for patterns.opus)
    6. AC US-6: ENV overrides (grep code for CLAUDE_ROUTER)
    7. AC US-7: AI classification (grep code for classify_ai)
    8. AC US-8: Classifier modes (grep code for classifier)
    9. AC US-9: Test script exists and passes
    10. AC US-10: Backward compat verified in V5
  - **Verify**: `cd /home/tzachb/Projects/claude-model-advisor/.claude/worktrees/zazzy-squishing-raven && grep -q "model-router-config.json" plugins/claude-model-router-hook/hooks/model-router-hook.sh && grep -q "git.*rev-parse" plugins/claude-model-router-hook/hooks/model-router-hook.sh && grep -q "dict.fromkeys" plugins/claude-model-router-hook/hooks/model-router-hook.sh && grep -q "CLAUDE_ROUTER" plugins/claude-model-router-hook/hooks/model-router-hook.sh && grep -q "classify_ai" plugins/claude-model-router-hook/hooks/model-router-hook.sh && grep -q "classifier" plugins/claude-model-router-hook/hooks/model-router-hook.sh && test -x tests/test-model-router.sh && echo V6_PASS`
  - **Done when**: All AC items verified
  - **Commit**: None

## Phase 5: PR Lifecycle

- [ ] 5.1 Create PR
  - **Do**:
    1. Verify on feature branch: `git branch --show-current`
    2. Push branch: `git push -u origin <branch>`
    3. Create PR: `gh pr create --title "feat: extensible model router with config, ENV overrides, and AI classification" --body "..."`
  - **Verify**: `gh pr view --json state | python3 -c "import json,sys; print(json.load(sys.stdin)['state'])"`
  - **Done when**: PR created and visible on GitHub
  - **Commit**: None

- [ ] 5.2 [VERIFY] CI pipeline passes
  - **Do**: Monitor CI checks on PR
  - **Verify**: `gh pr checks 2>&1 | head -20`
  - **Done when**: All CI checks green (or no CI configured)
  - **Commit**: None

- [ ] 5.3 [VERIFY] Final validation
  - **Do**: Confirm PR is ready for review with all criteria met:
    1. Zero test regressions
    2. Code is modular (functions extracted)
    3. Backward compatible (no config = same behavior)
    4. All acceptance criteria met
  - **Verify**: `cd /home/tzachb/Projects/claude-model-advisor/.claude/worktrees/zazzy-squishing-raven && bash tests/test-model-router.sh && echo FINAL_PASS`
  - **Done when**: All validation checks pass
  - **Commit**: None

## Notes

- **POC shortcuts taken**: AI classification not tested in automated tests (requires Claude CLI). Hybrid mode tested only via code path verification, not live AI calls.
- **Production TODOs**: Consider caching AI classification results, adding AI prompt customization via config, ENV extras for sonnet/haiku keywords.
- **Backward compat risk**: The refactor from hardcoded lists to config-driven lists is the main risk. Built-in defaults must exactly match current hardcoded values.
- **Both hooks.json files currently use `${CLAUDE_PLUGIN_ROOT}`**: design note about them differing is outdated, but keep them as separate files per design decision.
