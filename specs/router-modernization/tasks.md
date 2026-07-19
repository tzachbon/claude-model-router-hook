# Tasks: router-modernization (v2)

Total tasks: 74 (Phase 1: 9, Phase 2: 28, Phase 3: 14, Phase 4: 20, Phase 5: 3)

Paths are repo-relative. `PLUGIN` = `plugins/claude-model-router-hook`. Granularity: fine (one commit per task). E2E verification: disabled by user decision; integration coverage = `tests/test-hook.sh` + `tests/eval` CI gate. CLI fallback is OFF in all scripted tests.

Non-negotiable invariants (repeated in relevant tasks): never emit `claude-mythos-5`; haiku decisions carry NO effort; fail-open exit 0 on all errors; 30-char max log snippet; `CLAUDE_MODEL_ROUTER_CHILD` recursion guard; respect explicit caller `model`; aliases only in `updatedInput`.

## Phase 1: Make It Work (POC)

Minimal vertical slice: ladder + minimal taxonomy/policy + UserPromptSubmit entrypoint emitting a correct warn with (model, effort) on a canned prompt, fail-open intact.

- [x] 1.1 Create router package + ladder.py
  - **Do**:
    1. Create `PLUGIN/hooks/router/__init__.py` (empty).
    2. Create `PLUGIN/hooks/router/ladder.py`: `TIERS = ("haiku","sonnet","opus","fable")`, `MODEL_IDS` per design, `EFFORTS = ("low","medium","high","xhigh","max")`, frozen dataclass `Decision(model, effort, klass, source)`.
    3. `Decision.__post_init__` raises on: `effort is not None and model == "haiku"`; model not in TIERS; `"mythos" in model` (belt and braces, FR-2).
    4. Add `detect_tier(model_str)` (substring match incl. fable), `split_suffix(model_str)` (e.g. `opus[1m]` -> `("opus","[1m]")`), `effort_distance(a, b)`.
  - **Files**: plugins/claude-model-router-hook/hooks/router/__init__.py, plugins/claude-model-router-hook/hooks/router/ladder.py
  - **Done when**: `Decision("haiku", None, "mechanical", "heuristic")` constructs; `Decision("haiku","high",...)` and any mythos/non-ladder model raise; suffix split and tier detection work for all 4 aliases
  - **Verify**:
    ```bash
    python3 - <<'EOF'
    import sys; sys.path.insert(0, 'plugins/claude-model-router-hook/hooks')
    from router.ladder import Decision, detect_tier, split_suffix
    Decision('haiku', None, 'mechanical', 'heuristic')
    for args in [('haiku', 'high'), ('claude-mythos-5', 'high'), ('gpt-5', 'high')]:
        try:
            Decision(args[0], args[1], 'x', 'y')
        except Exception:
            pass
        else:
            raise SystemExit(f'FAIL: Decision{args} did not raise')
    assert detect_tier('claude-fable-5') == 'fable'
    assert split_suffix('opus[1m]') == ('opus', '[1m]')
    print('PASS')
    EOF
    ```
  - **Commit**: `feat(router): add ladder module with Decision invariants`
  - _Requirements: FR-1, FR-2, FR-3, FR-6, AC-2.4, AC-2.5_
  - _Design: ladder.py_

- [x] 1.2 Create hookio.py
  - **Do**:
    1. Create `PLUGIN/hooks/router/hookio.py`: `fail_open(fn)` decorator (any exception -> `sys.exit(0)`), `read_event()` (malformed stdin -> exit 0).
    2. `current_model_effort()` -> (model_str, effort): precedence env `ANTHROPIC_MODEL` > `.claude/settings.local.json` > `.claude/settings.json` > `~/.claude/settings.json`; effort from `effortLevel` else `"high"` (A-2/A-6).
    3. `log(action, prompt, **kv)` with 30-char max prompt snippet (v1 privacy invariant, NFR-5); `bypassed(prompt)` for `<` and `~` prefixes (`~` logged OVERRIDE); `is_child()` checking `CLAUDE_MODEL_ROUTER_CHILD` env.
    4. `emit_pretooluse(updated_input=None, system_message=None)` building `permissionDecision: "allow"` JSON.
  - **Files**: plugins/claude-model-router-hook/hooks/router/hookio.py
  - **Done when**: all functions importable; snippet capped at 30 chars; bypass prefixes and child guard detected
  - **Verify**: `python3 -c "import sys; sys.path.insert(0,'plugins/claude-model-router-hook/hooks'); from router import hookio; assert hookio.bypassed('~force'); assert hookio.bypassed('<tag>'); assert not hookio.bypassed('normal'); print('PASS')"`
  - **Commit**: `feat(router): add hookio fail-open, settings resolution, logging`
  - _Requirements: FR-35, FR-36, FR-37, NFR-3, NFR-5_
  - _Design: hookio.py_

- [x] 1.3 [VERIFY] Quality checkpoint: compile + existing unit tests
  - **Do**: `python3 -m py_compile plugins/claude-model-router-hook/hooks/router/*.py` then `python3 -m unittest discover tests -v` (existing v1 tests untouched, must stay green)
  - **Verify**: Both commands exit 0
  - **Done when**: Package compiles, existing tests pass
  - **Commit**: `chore(router): pass quality checkpoint` (only if fixes needed)

- [x] 1.4 config.py: v2 defaults + load
  - **Do**:
    1. Create `PLUGIN/hooks/router/config.py` with `DEFAULTS` dict matching the v2 schema in design (apply_mode warn, allow_fable_autoswitch false, subagent_enforcement on, classifier block, thresholds block, classes with targets, capability_gates, effort_floors).
    2. `load_config(global_path=None, cwd=None)`: read global + project JSON, unparseable file -> `{}` (fail-open, AC-8.5), shallow-merge onto DEFAULTS (full v1 merge semantics come in Phase 2).
    3. `detect_version(raw)` stub returning 2 for now.
    4. Port v1 `safe_regex_match` from `model_router.py` into config.py unchanged (invalid user regex skipped silently, FR-37); taxonomy and the 2.25 test refactor import it from `router.config`.
  - **Files**: plugins/claude-model-router-hook/hooks/router/config.py
  - **Done when**: `load_config()` with no files returns full defaults; garbage JSON file ignored; `safe_regex_match` importable and silent on invalid regex
  - **Verify**: `python3 -c "import sys; sys.path.insert(0,'plugins/claude-model-router-hook/hooks'); from router.config import load_config, DEFAULTS, safe_regex_match; c=load_config(); assert c['apply_mode']=='warn'; assert c['classes']['extreme']['target']['model']=='fable'; assert safe_regex_match('[invalid(', 'text') in (False, None); print('PASS')"`
  - **Commit**: `feat(router): add config defaults and v2 load`
  - _Requirements: FR-30, AC-8.5_
  - _Design: config.py, Config Schema v2_

- [x] 1.5 taxonomy.py: scored classifier core
  - **Do**:
    1. Create `PLUGIN/hooks/router/taxonomy.py`: `CLASSES = ("mechanical","implementation","debugging","architecture","extreme")`, default keyword/pattern lists per design table (v1 haiku/sonnet/opus lists + debugging list).
    2. `score(prompt, cfg)` -> ScoreResult (scores per class, top, second, margin, word_count); keyword/pattern hit = +2; mechanical score zeroed when word_count > `mechanical_max_words`; text signal cap +6 per class.
    3. `classify_heuristic(prompt, cfg)` decision ladder: margin >= confident_margin AND top >= 3 -> top class; elif top >= 2 -> top (low-confidence); else abstain (None). Empty/whitespace prompt -> abstain. Standalone, no CLI (FR-24).
  - **Files**: plugins/claude-model-router-hook/hooks/router/taxonomy.py
  - **Done when**: architecture prompt classifies architecture; git-op prompt classifies mechanical; empty prompt abstains; deterministic (NFR-10)
  - **Verify**: `python3 -c "import sys; sys.path.insert(0,'plugins/claude-model-router-hook/hooks'); from router.taxonomy import classify_heuristic; from router.config import load_config; c=load_config(); k,_=classify_heuristic('analyze the architecture tradeoffs and redesign the deployment strategy', c); assert k=='architecture', k; k2,_=classify_heuristic('', c); assert k2 is None; print('PASS')"`
  - **Commit**: `feat(router): add scored taxonomy classifier with margin confidence`
  - _Requirements: FR-19, FR-23, FR-24, AC-7.1, AC-7.2_
  - _Design: taxonomy.py, Taxonomy Design_

- [x] 1.6 policy.py: effort-first mapping
  - **Do**:
    1. Create `PLUGIN/hooks/router/policy.py`: `target_for_class(klass, cfg)` -> Decision from `classes.<name>.target` (haiku target has NO effort).
    2. `main_prompt_decision(klass, current_model, current_effort, cfg, score)` implementing the full 5x4 matrix from design (stay cells, xhigh cells for architecture@opus and extreme@fable, up-routes incl. haiku->sonnet).
    3. Downroute guard: tier-lowering decisions additionally require `margin >= downroute_margin` (FR-5); match = same tier AND `effort_distance < effort_warn_distance` -> return None (no warn).
  - **Files**: plugins/claude-model-router-hook/hooks/router/policy.py
  - **Done when**: all 20 matrix cells return per design; match cases return None; no decision ever pairs haiku with effort
  - **Verify**: `python3 -c "import sys; sys.path.insert(0,'plugins/claude-model-router-hook/hooks'); from router.policy import target_for_class; from router.config import load_config; c=load_config(); d=target_for_class('mechanical', c); assert d.model=='haiku' and d.effort is None; d2=target_for_class('extreme', c); assert d2.model=='fable' and d2.effort=='high'; print('PASS')"`
  - **Commit**: `feat(router): add effort-first policy matrix with downroute guard`
  - _Requirements: FR-4, FR-5, FR-20, AC-2.1, AC-2.2, AC-2.3_
  - _Design: policy.py, (model, effort) output matrix_

- [x] 1.7 [VERIFY] Quality checkpoint: compile + unit tests
  - **Do**: `python3 -m py_compile plugins/claude-model-router-hook/hooks/router/*.py && python3 -m unittest discover tests -v`
  - **Verify**: Both exit 0
  - **Done when**: Package compiles, existing tests still green
  - **Commit**: `chore(router): pass quality checkpoint` (only if fixes needed)

- [x] 1.8 user_prompt_submit.py entrypoint (warn path)
  - **Do**:
    1. Create `PLUGIN/hooks/user_prompt_submit.py`: `fail_open`-wrapped main; exit 0 immediately on `is_child()` (CLAUDE_MODEL_ROUTER_CHILD guard), `bypassed(prompt)`, malformed stdin, unreadable settings.
    2. Read current (model, effort) via `current_model_effort`; classify via taxonomy + policy; abstain or match -> exit 0.
    3. Mismatch (warn mode): exit 2, stderr suggesting `/model <alias+preserved suffix>` and `/effort <level>` and asking to resend; log decision (30-char snippet max).
  - **Files**: plugins/claude-model-router-hook/hooks/user_prompt_submit.py
  - **Done when**: canned architecture prompt on a sonnet session exits 2 with opus + high in stderr; garbage stdin exits 0
  - **Verify**: `T=$(mktemp -d) && mkdir -p $T/.claude && echo '{"model":"claude-sonnet-5","effortLevel":"high"}' > $T/.claude/settings.json && echo '{"prompt":"analyze the architecture tradeoffs and redesign the deployment strategy, deep dive"}' | HOME=$T python3 plugins/claude-model-router-hook/hooks/user_prompt_submit.py 2>$T/err; [ $? -eq 2 ] && grep -qi opus $T/err && echo PASS`
  - **Commit**: `feat(router): add UserPromptSubmit entrypoint with warn mode`
  - _Requirements: FR-8, AC-1.1, AC-1.2, AC-1.3, AC-9.1, AC-9.2, AC-9.3_
  - _Design: Data flow UserPromptSubmit, Entrypoints_

- [x] 1.9 POC Checkpoint
  - **Do**:
    1. Run the canned warn case from 1.8 (sonnet session + architecture prompt -> exit 2, stderr has `/model` and `/effort`).
    2. Run fail-open cases: `echo 'not json' | python3 ...` -> exit 0; `~prefixed` prompt -> exit 0; `CLAUDE_MODEL_ROUTER_CHILD=1` -> exit 0.
    3. Run match case: haiku session + mechanical prompt -> exit 0 silent.
  - **Done when**: Core loop proven: correct (model, effort) warn on canned prompt, all fail-open paths exit 0
  - **Verify**: `T=$(mktemp -d) && mkdir -p $T/.claude && echo '{"model":"claude-sonnet-5","effortLevel":"high"}' > $T/.claude/settings.json && echo '{"prompt":"analyze the architecture tradeoffs and redesign the deployment strategy, deep dive"}' | HOME=$T python3 plugins/claude-model-router-hook/hooks/user_prompt_submit.py 2>$T/err; [ $? -eq 2 ] && grep -q '/model' $T/err && grep -q '/effort' $T/err && (echo 'not json' | HOME=$T python3 plugins/claude-model-router-hook/hooks/user_prompt_submit.py); [ $? -eq 0 ] && (echo '{"prompt":"x"}' | CLAUDE_MODEL_ROUTER_CHILD=1 HOME=$T python3 plugins/claude-model-router-hook/hooks/user_prompt_submit.py); [ $? -eq 0 ] && echo POC_PASS`
  - **Commit**: `feat(router): complete POC vertical slice`
  - _Requirements: US-1, US-2_

## Phase 2: Full Engine + Enforcement

Full taxonomy signals, config migration, CLI fallback, advisory/SessionStart, agent variants, PreToolUse enforcement, autoswitch, hooks.json rewire, v1 deletion.

- [x] 2.1 taxonomy: structural and length signals with caps
  - **Do**:
    1. Add structural signals per design table: code fence +1 (implementation), error/traceback block +2 (debugging), short imperative <=12 words +1 (mechanical).
    2. Add length signals: word_count >= `long_prompt_words` +1, >= 2x +2 (architecture); `?` with word_count >= `question_words` +1 (architecture).
    3. Enforce per-signal-type caps: text +6, structure +1/+2 per class, architecture length hard cap +2 (FR-7: no single signal type forces top tier).
  - **Files**: plugins/claude-model-router-hook/hooks/router/taxonomy.py
  - **Done when**: 500-word keyword-free prompt cannot exceed architecture score 2 from length alone
  - **Verify**: `python3 -c "import sys; sys.path.insert(0,'plugins/claude-model-router-hook/hooks'); from router.taxonomy import score; from router.config import load_config; c=load_config(); r=score('word '*500, c); assert r.scores['architecture']<=2, r.scores; print('PASS')"`
  - **Commit**: `feat(router): add structural and length signals with influence caps`
  - _Requirements: FR-7, FR-23, AC-7.1_
  - _Design: Taxonomy Design signals table_

- [x] 2.2 taxonomy: extreme escalation
  - **Do**:
    1. Add extreme markers (multi-system, migration plan, across the entire codebase, long-horizon, RFC/design doc, epic, rewrite the platform), each +1, cap +3.
    2. Evaluate only when architecture is top class; escalate architecture -> extreme when extremity >= 2.
  - **Files**: plugins/claude-model-router-hook/hooks/router/taxonomy.py
  - **Done when**: architecture-scale multi-system prompt classifies extreme; plain architecture prompt stays architecture
  - **Verify**: `python3 -c "import sys; sys.path.insert(0,'plugins/claude-model-router-hook/hooks'); from router.taxonomy import classify_heuristic; from router.config import load_config; c=load_config(); k,_=classify_heuristic('design an RFC for the multi-system migration plan across the entire codebase, long-horizon architecture rewrite of the platform', c); assert k=='extreme', k; print('PASS')"`
  - **Commit**: `feat(router): add extreme class escalation from architecture`
  - _Requirements: FR-19, AC-2.3_
  - _Design: Taxonomy Design extreme row_

- [x] 2.3 [VERIFY] Quality checkpoint: compile + unit tests
  - **Do**: `python3 -m py_compile plugins/claude-model-router-hook/hooks/router/*.py && python3 -m unittest discover tests -v && bash tests/test-hook.sh`
  - **Verify**: All exit 0
  - **Done when**: Compiles, v1 tests still green
  - **Commit**: `chore(router): pass quality checkpoint` (only if fixes needed)

- [x] 2.4 policy: capability gates and effort floors
  - **Do**:
    1. Add `apply_gates(prompt, decision, cfg)`: `capability_gates` patterns (SendMessage, handoff, coordinate agents, spawn subagents, multi-agent) -> min tier sonnet; mechanical->haiku bumped to (sonnet, medium) (FR-21, AC-6.3).
    2. Debugging class floor: effort >= high (FR-22, AC-6.5).
    3. `effort_floors` patterns (migration, database, prod, delete data, backfill) -> effort >= floor (high); any floor implies min tier sonnet (haiku carries no effort).
  - **Files**: plugins/claude-model-router-hook/hooks/router/policy.py
  - **Done when**: handoff-pattern mechanical prompt yields (sonnet, medium), never haiku; data-handling prompt gets effort >= high
  - **Verify**: `python3 -c "import sys; sys.path.insert(0,'plugins/claude-model-router-hook/hooks'); from router.policy import apply_gates, target_for_class; from router.config import load_config; c=load_config(); d=apply_gates('rename the file then coordinate agents via SendMessage handoff', target_for_class('mechanical', c), c); assert d.model!='haiku' and d.effort is not None; print('PASS')"`
  - **Commit**: `feat(router): add capability gates and effort floors`
  - _Requirements: FR-21, FR-22, AC-6.3, AC-6.5_
  - _Design: Capability gates and effort floors_

- [x] 2.5 config: v1 detection + in-memory migration
  - **Do**:
    1. Implement `detect_version(raw)`: `version==2` -> 2; version absent AND any of `{opus, sonnet, haiku, thresholds}` present -> 1; else 2 (defaults).
    2. Implement `migrate_v1(raw)` pure function per design mapping table (opus->classes.architecture, sonnet->classes.implementation, haiku->classes.mechanical, threshold key renames, implicit `apply_mode: warn`). Never writes files (AC-8.2).
  - **Files**: plugins/claude-model-router-hook/hooks/router/config.py
  - **Done when**: v1-shaped dict migrates with keywords/patterns/remove_*/mode preserved; empty dict detects as v2
  - **Verify**: `python3 -c "import sys; sys.path.insert(0,'plugins/claude-model-router-hook/hooks'); from router.config import detect_version, migrate_v1; assert detect_version({'opus':{'keywords':['x']}})==1; assert detect_version({})==2; m=migrate_v1({'opus':{'mode':'extend','keywords':['x']},'thresholds':{'opus_word_count':150}}); assert m['classes']['architecture']['keywords']==['x']; assert m['thresholds']['long_prompt_words']==150; print('PASS')"`
  - **Commit**: `feat(config): add v1 structural detection and in-memory migration`
  - _Requirements: FR-31, AC-8.1, AC-8.2_
  - _Design: v1 detection + in-memory migration_

- [x] 2.6 config: layered merge, resolve_list, v1 hint marker
  - **Do**:
    1. Implement `merge(base, overlay)` with v1 semantics (per-key, dict spread, `$schema` skipped, classes merged per class) and `resolve_list(class_cfg, field, defaults)` preserving v1 extend/replace/remove_* behavior.
    2. Wire `load_config` full path: each file version-detected and migrated independently, then merged (project wins, AC-8.4).
    3. Add `v1_hint_due(data_dir)`: True once until marker file `<data_dir>/v1-hint-shown` written; user config files never touched.
  - **Files**: plugins/claude-model-router-hook/hooks/router/config.py
  - **Done when**: project overlay overrides global per-key; extend/replace/remove list modes match v1; hint fires once
  - **Verify**: `python3 -c "import sys, tempfile; sys.path.insert(0,'plugins/claude-model-router-hook/hooks'); from router.config import merge, resolve_list, v1_hint_due; m=merge({'a':1,'classes':{'mechanical':{'keywords':['k']}}},{'a':2}); assert m['a']==2 and m['classes']['mechanical']['keywords']==['k']; d=tempfile.mkdtemp(); assert v1_hint_due(d); assert not v1_hint_due(d); print('PASS')"`
  - **Commit**: `feat(config): add layered merge and one-time v1 upgrade hint`
  - _Requirements: FR-32, FR-33, AC-8.3, AC-8.4_
  - _Design: config.py_

- [x] 2.7 [VERIFY] Quality checkpoint: compile + unit + integration
  - **Do**: `python3 -m py_compile plugins/claude-model-router-hook/hooks/router/*.py && python3 -m unittest discover tests -v && bash tests/test-hook.sh`
  - **Verify**: All exit 0
  - **Done when**: All green
  - **Commit**: `chore(router): pass quality checkpoint` (only if fixes needed)

- [x] 2.8 cli_fallback.py: headless CLI classification
  - **Do**:
    1. Create `PLUGIN/hooks/router/cli_fallback.py` with the design's prompt template (first 1500 chars of user prompt).
    2. `subprocess.run(["claude","-p",template,"--model","haiku"], timeout=cfg cli_timeout_seconds (8), env={**os.environ, "CLAUDE_MODEL_ROUTER_CHILD": "1"})` (recursion guard on child).
    3. Parse strip/lower first token; must be in CLASSES + abstain else discard; FileNotFoundError / non-zero exit / timeout / garbage -> return None (fail-open ladder, AC-7.4).
  - **Files**: plugins/claude-model-router-hook/hooks/router/cli_fallback.py
  - **Done when**: missing binary returns None without raising; child env var set on subprocess
  - **Verify**:
    ```bash
    python3 - <<'EOF'
    import sys; sys.path.insert(0, 'plugins/claude-model-router-hook/hooks')
    from unittest import mock
    from router import cli_fallback
    from router.config import load_config
    with mock.patch('subprocess.run', side_effect=FileNotFoundError):
        assert cli_fallback.classify_cli('x', load_config(), None) is None
    print('PASS')
    EOF
    ```
  - **Commit**: `feat(router): add headless CLI fallback classifier`
  - _Requirements: FR-25, FR-27, AC-7.3, AC-7.4_
  - _Design: CLI Fallback Design_

- [x] 2.9 cli_fallback: hash-keyed cache
  - **Do**:
    1. Cache file `${CLAUDE_PLUGIN_DATA}/classifier-cache.json`: key `sha256(taxonomy_rev + prompt).hexdigest()[:32]`, value `{"c": class, "t": epoch}`; hashes + classes only, never prompt text (NFR-5).
    2. Max `cache_max_entries` (1000); on overflow evict oldest 20%; corrupt/unreadable -> discard and rewrite (NFR-9); atomic write via tempfile + `os.replace`.
    3. `CLAUDE_PLUGIN_DATA` unset -> skip caching entirely, still functional.
  - **Files**: plugins/claude-model-router-hook/hooks/router/cli_fallback.py
  - **Done when**: cache hit skips subprocess; corrupt cache ignored; no raw prompt text in cache file
  - **Verify**:
    ```bash
    python3 - <<'EOF'
    import sys, tempfile, os
    sys.path.insert(0, 'plugins/claude-model-router-hook/hooks')
    from unittest import mock
    from router import cli_fallback
    from router.config import load_config
    d = tempfile.mkdtemp()
    open(os.path.join(d, 'classifier-cache.json'), 'w').write('CORRUPT')
    with mock.patch('subprocess.run', side_effect=FileNotFoundError):
        assert cli_fallback.classify_cli('x', load_config(), d) is None
    print('PASS')
    EOF
    ```
  - **Commit**: `feat(router): add hash-keyed classifier cache with eviction`
  - _Requirements: FR-28, AC-7.5, NFR-5, NFR-9_
  - _Design: CLI Fallback Design cache_

- [x] 2.10 Wire CLI fallback into classification path
  - **Do**:
    1. Add `classify(prompt, cfg, data_dir)` orchestrator (in taxonomy.py): heuristic first; if below confidence AND `classifier.cli_fallback` true -> cache -> `classify_cli` tiebreak; on None fall back to heuristic low-confidence decision (FR-24, FR-27).
    2. `classifier.cli_fallback: false` -> pure heuristics, no subprocess import side effects (AC-7.6, NFR-7).
  - **Files**: plugins/claude-model-router-hook/hooks/router/taxonomy.py, plugins/claude-model-router-hook/hooks/user_prompt_submit.py
  - **Done when**: with fallback disabled no subprocess is invoked; ambiguous prompt still resolves per decision ladder
  - **Verify**:
    ```bash
    python3 - <<'EOF'
    import sys; sys.path.insert(0, 'plugins/claude-model-router-hook/hooks')
    from unittest import mock
    from router import taxonomy
    from router.config import load_config
    c = load_config()
    c['classifier']['cli_fallback'] = False
    with mock.patch('subprocess.run', side_effect=AssertionError('CLI called')):
        taxonomy.classify('fix the thing maybe', c, None)
    print('PASS')
    EOF
    ```
  - **Commit**: `feat(router): wire tiered classify with cache and CLI tiebreak`
  - _Requirements: FR-24, FR-26, AC-7.2, AC-7.6, NFR-7_
  - _Design: Confidence and decision ladder_

- [x] 2.11 [VERIFY] Quality checkpoint: compile + unit + integration
  - **Do**: `python3 -m py_compile plugins/claude-model-router-hook/hooks/router/*.py plugins/claude-model-router-hook/hooks/*.py && python3 -m unittest discover tests -v && bash tests/test-hook.sh`
  - **Verify**: All exit 0
  - **Done when**: All green
  - **Commit**: `chore(router): pass quality checkpoint` (only if fixes needed)

- [x] 2.12 advisory.py: canonical taxonomy text
  - **Do**:
    1. Create `PLUGIN/hooks/router/advisory.py`: `ADVISORY_MD` constant, the single canonical taxonomy/advisory markdown table (classes, targets, when to use), FR-42.
    2. `render_session_context(current_model)` returning SessionStart context text embedding ADVISORY_MD.
  - **Files**: plugins/claude-model-router-hook/hooks/router/advisory.py
  - **Done when**: ADVISORY_MD covers all 5 classes + abstain; render includes current model
  - **Verify**: `python3 -c "import sys; sys.path.insert(0,'plugins/claude-model-router-hook/hooks'); from router.advisory import ADVISORY_MD, render_session_context; [ADVISORY_MD.index(w) for w in ['mechanical','implementation','debugging','architecture','extreme']]; assert 'sonnet' in render_session_context('claude-sonnet-5'); print('PASS')"`
  - **Commit**: `feat(router): add canonical advisory taxonomy text`
  - _Requirements: FR-17, FR-42, AC-11.1_
  - _Design: advisory.py_

- [x] 2.13 session_init.py entrypoint
  - **Do**:
    1. Create `PLUGIN/hooks/session_init.py`: fail_open-wrapped; child guard exit 0; read current model; emit `hookSpecificOutput.additionalContext` from `render_session_context` as JSON on stdout.
  - **Files**: plugins/claude-model-router-hook/hooks/session_init.py
  - **Done when**: valid SessionStart JSON in -> additionalContext JSON out; malformed stdin -> exit 0
  - **Verify**: `echo '{}' | python3 plugins/claude-model-router-hook/hooks/session_init.py | python3 -c "import json,sys; d=json.load(sys.stdin); assert 'additionalContext' in d.get('hookSpecificOutput',{}); print('PASS')"`
  - **Commit**: `feat(router): add SessionStart entrypoint with advisory context`
  - _Requirements: FR-17, AC-5.3_
  - _Design: Entrypoints_

- [x] 2.14 [VERIFY] Quality checkpoint: compile + unit + integration
  - **Do**: `python3 -m py_compile plugins/claude-model-router-hook/hooks/router/*.py plugins/claude-model-router-hook/hooks/*.py && python3 -m unittest discover tests -v && bash tests/test-hook.sh`
  - **Verify**: All exit 0
  - **Done when**: All green
  - **Commit**: `chore(router): pass quality checkpoint` (only if fixes needed)

- [x] 2.15 [P] Agent variants: haiku, sonnet-medium, sonnet-high
  - **Do**:
    1. Create `PLUGIN/agents/routed-haiku.md` (`name: routed-haiku`, `model: haiku`, NO effort key), `routed-sonnet-medium.md` (`model: sonnet`, `effort: medium`), `routed-sonnet-high.md` (`model: sonnet`, `effort: high`).
    2. Identical minimal body ("Complete the delegated task exactly as prompted; return a concise report"); description states router-managed variant.
  - **Files**: plugins/claude-model-router-hook/agents/routed-haiku.md, plugins/claude-model-router-hook/agents/routed-sonnet-medium.md, plugins/claude-model-router-hook/agents/routed-sonnet-high.md
  - **Done when**: 3 files exist with correct frontmatter; routed-haiku has no effort line
  - **Verify**: `grep -q 'model: haiku' plugins/claude-model-router-hook/agents/routed-haiku.md && ! grep -q 'effort' plugins/claude-model-router-hook/agents/routed-haiku.md && grep -q 'effort: medium' plugins/claude-model-router-hook/agents/routed-sonnet-medium.md && grep -q 'effort: high' plugins/claude-model-router-hook/agents/routed-sonnet-high.md && echo PASS`
  - **Commit**: `feat(agents): add routed haiku and sonnet variants`
  - _Requirements: FR-16, AC-4.2, AC-2.4_
  - _Design: Plugin-Shipped Agent Variants_

- [x] 2.16 [P] Agent variants: opus-high, fable-high
  - **Do**:
    1. Create `PLUGIN/agents/routed-opus-high.md` (`model: opus`, `effort: high`) and `routed-fable-high.md` (`model: fable`, `effort: high`), same body/description pattern as 2.15.
  - **Files**: plugins/claude-model-router-hook/agents/routed-opus-high.md, plugins/claude-model-router-hook/agents/routed-fable-high.md
  - **Done when**: Both files exist; every default class target now has a shipped variant
  - **Verify**: `grep -q 'model: opus' plugins/claude-model-router-hook/agents/routed-opus-high.md && grep -q 'model: fable' plugins/claude-model-router-hook/agents/routed-fable-high.md && ls plugins/claude-model-router-hook/agents | grep -c 'routed-' | grep -q 5 && echo PASS`
  - **Commit**: `feat(agents): add routed opus and fable variants`
  - _Requirements: FR-16, AC-4.2_
  - _Design: Plugin-Shipped Agent Variants_

- [x] 2.17 pre_tool_use.py: core enforcement
  - **Do**:
    1. Create `PLUGIN/hooks/pre_tool_use.py`: fail_open-wrapped; exit 0 on child guard, `subagent_enforcement: off`, idempotency (`subagent_type` already `claude-model-router-hook:routed-*`), missing `tool_input.prompt` (FR-18).
    2. Classify `tool_input.prompt` via `target_for_class` + gates; abstain/error -> exit 0 pass-through (AC-4.3, AC-4.4).
    3. Generic type (`general-purpose`/`default`/`claude`/absent/empty): emit allow + `updatedInput` rewriting `subagent_type` to `claude-model-router-hook:routed-<variant>` AND injecting `model` as bare ALIAS only (A-1; never full IDs, never suffixes, never claude-mythos-5).
    4. Custom type: inject `updatedInput.model` alias only; `subagent_type` untouched (FR-15).
  - **Files**: plugins/claude-model-router-hook/hooks/pre_tool_use.py
  - **Done when**: generic mechanical spawn rewrites to routed-haiku + model haiku; custom type gets model-only; never denies; any error exits 0
  - **Verify**: `T=$(mktemp -d) && mkdir -p $T/.claude/hooks && echo '{"version":2,"classifier":{"cli_fallback":false}}' > $T/.claude/hooks/model-router.json && echo '{"tool_name":"Agent","tool_input":{"subagent_type":"general-purpose","prompt":"rename the file src/a.py to src/b.py and fix imports"}}' | HOME=$T python3 plugins/claude-model-router-hook/hooks/pre_tool_use.py | python3 -c "import json,sys; d=json.load(sys.stdin)['hookSpecificOutput']; assert d['permissionDecision']=='allow'; u=d['updatedInput']; assert 'routed-' in u['subagent_type'] and u['model'] in ('haiku','sonnet','opus','fable'); print('PASS')"`
  - **Commit**: `feat(router): add PreToolUse entrypoint with subagent rewrite`
  - _Requirements: FR-12, FR-13, FR-14, FR-15, FR-18, AC-4.1, AC-4.3, AC-4.4, AC-5.1_
  - _Design: Data flow PreToolUse, PreToolUse Contract Details_

- [x] 2.18 [VERIFY] Quality checkpoint: compile + unit + integration
  - **Do**: `python3 -m py_compile plugins/claude-model-router-hook/hooks/router/*.py plugins/claude-model-router-hook/hooks/*.py && python3 -m unittest discover tests -v && bash tests/test-hook.sh`
  - **Verify**: All exit 0
  - **Done when**: All green
  - **Commit**: `chore(router): pass quality checkpoint` (only if fixes needed)

- [x] 2.19 pre_tool_use.py: respect, modes, fable gate, env warning
  - **Do**:
    1. Explicit caller `model` in tool_input -> NO injection (respect, locked decision); if router disagrees, `systemMessage` one-liner advisory only.
    2. `subagent_enforcement: advisory` -> systemMessage only, no updatedInput; fable decision with `allow_fable_autoswitch: false` -> degrade to advisory systemMessage (AC-3.3).
    3. `CLAUDE_CODE_SUBAGENT_MODEL` in env and != decision -> append warning to systemMessage (A-4).
    4. Overridden class target without matching shipped variant -> degrade to model-only injection, effort advisory (amended AC-4.2).
  - **Files**: plugins/claude-model-router-hook/hooks/pre_tool_use.py
  - **Done when**: explicit-model spawn passes with no updatedInput; extreme prompt with default fable gate yields no fable injection
  - **Verify**: `T=$(mktemp -d) && mkdir -p $T/.claude/hooks && echo '{"version":2,"classifier":{"cli_fallback":false}}' > $T/.claude/hooks/model-router.json && echo '{"tool_name":"Agent","tool_input":{"subagent_type":"general-purpose","model":"opus","prompt":"rename file a to b"}}' | HOME=$T python3 plugins/claude-model-router-hook/hooks/pre_tool_use.py | python3 -c "import json,sys; raw=sys.stdin.read(); d=json.loads(raw) if raw.strip() else {}; assert 'updatedInput' not in d.get('hookSpecificOutput',{}), raw; print('PASS')"`
  - **Commit**: `feat(router): respect explicit model, enforcement modes, fable gating`
  - _Requirements: FR-11, FR-30, AC-3.3, AC-5.1, AC-5.2_
  - _Design: PreToolUse Contract Details, A-4_

- [x] 2.20 hookio: atomic settings writer for autoswitch
  - **Do**:
    1. Add `write_settings(model_with_suffix, effort)` to hookio.py: read `~/.claude/settings.json`, unparseable -> return False (degrade to warn, never clobber).
    2. Write `model` (alias + preserved suffix) and `effortLevel` clamped to xhigh (`max` -> `xhigh`; haiku decision writes model only, no effortLevel); preserve all other keys; tempfile + `os.replace` atomic.
    3. Add precedence-mask detection helper: `ANTHROPIC_MODEL` env or project settings `model` present -> caller can surface caveat (A-6).
  - **Files**: plugins/claude-model-router-hook/hooks/router/hookio.py
  - **Done when**: existing keys preserved; max clamps to xhigh; haiku writes no effortLevel; corrupt settings returns False
  - **Verify**: `python3 -c "import sys, tempfile, json, os; sys.path.insert(0,'plugins/claude-model-router-hook/hooks'); from router import hookio; d=tempfile.mkdtemp(); os.makedirs(d+'/.claude'); json.dump({'model':'claude-sonnet-5','other':1}, open(d+'/.claude/settings.json','w')); os.environ['HOME']=d; assert hookio.write_settings('opus[1m]','max'); s=json.load(open(d+'/.claude/settings.json')); assert s['model']=='opus[1m]' and s['effortLevel']=='xhigh' and s['other']==1; print('PASS')"`
  - **Commit**: `feat(router): add atomic settings writer with xhigh clamp`
  - _Requirements: FR-9, FR-10, AC-1.4, AC-3.2_
  - _Design: Autoswitch Design_

- [x] 2.21 [VERIFY] Quality checkpoint: compile + unit + integration
  - **Do**: `python3 -m py_compile plugins/claude-model-router-hook/hooks/router/*.py plugins/claude-model-router-hook/hooks/*.py && python3 -m unittest discover tests -v && bash tests/test-hook.sh`
  - **Verify**: All exit 0
  - **Done when**: All green
  - **Commit**: `chore(router): pass quality checkpoint` (only if fixes needed)

- [x] 2.22 user_prompt_submit: autoswitch branch + v1 hint
  - **Do**:
    1. Add autoswitch branch (`apply_mode: "autoswitch"`): fable decision with `allow_fable_autoswitch: false` -> behave as warn (FR-11); else `write_settings`, on failure degrade to warn; exit 2 message per design ("default updated for new sessions; /model X to apply now"; never claims live switch, AC-3.2); surface precedence-mask caveat when detected.
    2. Wire v1 hint: when `v1_hint_due` and v1 config detected, append one-time hint to warn stderr (exit-2 path) or emit systemMessage (exit-0 path); write marker file.
  - **Files**: plugins/claude-model-router-hook/hooks/user_prompt_submit.py
  - **Done when**: autoswitch writes settings and exits 2 with new-sessions wording; hint appears exactly once
  - **Verify**: `T=$(mktemp -d) && mkdir -p $T/.claude $T/data && echo '{"model":"claude-sonnet-5","effortLevel":"high"}' > $T/.claude/settings.json && mkdir -p $T/.claude/hooks && echo '{"version":2,"apply_mode":"autoswitch","classifier":{"cli_fallback":false}}' > $T/.claude/hooks/model-router.json && echo '{"prompt":"analyze the architecture tradeoffs and redesign the deployment strategy, deep dive"}' | HOME=$T CLAUDE_PLUGIN_DATA=$T/data python3 plugins/claude-model-router-hook/hooks/user_prompt_submit.py 2>$T/err; [ $? -eq 2 ] && grep -qi 'new sessions' $T/err && python3 -c "import json; s=json.load(open('$T/.claude/settings.json')); assert 'opus' in s['model']" && echo PASS`
  - **Commit**: `feat(router): add autoswitch mode with fable gate and v1 hint`
  - _Requirements: FR-9, FR-10, FR-11, FR-32, AC-3.1, AC-3.2, AC-3.3, AC-8.3_
  - _Design: Autoswitch Design, v1 hint_

- [x] 2.23 hooks.json rewire
  - **Do**:
    1. Rewrite `PLUGIN/hooks/hooks.json`: UserPromptSubmit -> `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/user_prompt_submit.py"` timeout 10; SessionStart -> `session_init.py` timeout 5; add PreToolUse matcher `"Agent|Task"` -> `pre_tool_use.py` timeout 10 (FR-29 budget table).
  - **Files**: plugins/claude-model-router-hook/hooks/hooks.json
  - **Done when**: 3 hook events registered, correct timeouts, no bash wrapper references
  - **Verify**: `python3 -c "import json; h=json.load(open('plugins/claude-model-router-hook/hooks/hooks.json'))['hooks']; assert set(h)=={'SessionStart','UserPromptSubmit','PreToolUse'}; assert h['PreToolUse'][0]['matcher']=='Agent|Task'; assert h['UserPromptSubmit'][0]['hooks'][0]['timeout']==10; assert 'user_prompt_submit.py' in h['UserPromptSubmit'][0]['hooks'][0]['command']; print('PASS')"`
  - **Commit**: `feat(hooks): rewire hooks.json to python entrypoints with new timeouts`
  - _Requirements: FR-12, FR-29, AC-7.7_
  - _Design: Entrypoints, timeout budget_

- [x] 2.24 [VERIFY] Quality checkpoint: compile + unit + integration
  - **Do**: `python3 -m py_compile plugins/claude-model-router-hook/hooks/router/*.py plugins/claude-model-router-hook/hooks/*.py && python3 -m unittest discover tests -v && bash tests/test-hook.sh`
  - **Verify**: All exit 0
  - **Done when**: All green (v1 scripts still present, v1 suites still pass)
  - **Commit**: `chore(router): pass quality checkpoint` (only if fixes needed)

- [x] 2.25 Refactor tests/test_config.py to router.config imports
  - **Do**:
    1. Change sys.path/import to `router.config` (`load_config`, `resolve_list`, plus `safe_regex_match` home in v2); drop the inline `_classify` reimplementation (FR-40).
    2. Adapt assertions to v2 config shape where key names moved (classes.* instead of opus/sonnet/haiku top level) while keeping v1-semantics coverage via `migrate_v1`.
  - **Files**: tests/test_config.py
  - **Done when**: test_config.py no longer imports model_router; all its tests pass against router.config
  - **Verify**: `! grep -q 'from model_router' tests/test_config.py && ! grep -q '_classify' tests/test_config.py && python3 -m unittest tests.test_config -v && echo PASS`
  - **Commit**: `refactor(tests): point test_config at router.config, drop inline classifier`
  - _Requirements: FR-40, AC-10.4_
  - _Design: File Structure, Test Strategy_

- [x] 2.26 Update test-hook.sh v1 suites for v2 entrypoint
  - **Do**:
    1. Point `HOOK` invocation at `python3 plugins/claude-model-router-hook/hooks/user_prompt_submit.py` (bash wrapper going away).
    2. `make_home` writes a global v2 config with `classifier.cli_fallback: false` (CLI fallback OFF in all scripted tests).
    3. Flip the v1 pinned expectation: haiku session + implementation prompt now expects sonnet warn (documented intentional semantic change); keep suites 1-8 semantics otherwise (bypasses, fail-open, suffix).
  - **Files**: tests/test-hook.sh
  - **Done when**: full suite passes against the python entrypoint with fallback disabled
  - **Verify**: `bash tests/test-hook.sh`
  - **Commit**: `test(hooks): run v1 suites against v2 entrypoint, flip haiku up-route case`
  - _Requirements: FR-41, AC-1.3, AC-9.1, AC-9.2_
  - _Design: Test Strategy, haiku->sonnet decision_

- [x] 2.27 Delete v1 implementation files
  - **Do**:
    1. `git rm plugins/claude-model-router-hook/hooks/model_router.py plugins/claude-model-router-hook/hooks/model-router-hook.sh plugins/claude-model-router-hook/hooks/session-init.sh`.
  - **Files**: plugins/claude-model-router-hook/hooks/model_router.py, plugins/claude-model-router-hook/hooks/model-router-hook.sh, plugins/claude-model-router-hook/hooks/session-init.sh
  - **Done when**: 3 files gone; no remaining references in hooks.json/tests
  - **Verify**: `! test -f plugins/claude-model-router-hook/hooks/model_router.py && ! test -f plugins/claude-model-router-hook/hooks/model-router-hook.sh && ! test -f plugins/claude-model-router-hook/hooks/session-init.sh && ! grep -rq 'model-router-hook.sh\|model_router\|session-init.sh' plugins/claude-model-router-hook/hooks/hooks.json tests/ && echo PASS`
  - **Commit**: `refactor(hooks): delete v1 monolith and bash wrappers`
  - _Design: File Structure delete rows_

- [x] 2.28 [VERIFY] Quality checkpoint: full local suite post-deletion
  - **Do**: `python3 -m py_compile plugins/claude-model-router-hook/hooks/router/*.py plugins/claude-model-router-hook/hooks/*.py && python3 -m unittest discover tests -v && bash tests/test-hook.sh`
  - **Verify**: All exit 0
  - **Done when**: Everything green with v1 files removed
  - **Commit**: `chore(router): pass quality checkpoint` (only if fixes needed)

## Phase 3: Testing

Unit tests importing real modules; new integration suites. All scripted tests run with CLI fallback OFF.

- [x] 3.1 test_router.py: ladder tests
  - **Do**:
    1. Create `tests/test_router.py` importing `router.ladder`: Decision haiku-with-effort raises; non-ladder model raises; mythos asserted absent from TIERS/MODEL_IDS values and rejected by Decision (FR-2 test-asserted).
    2. Tests for `detect_tier` (all aliases + full IDs + fable substring + unknown -> None), `split_suffix` (`[1m]`, no suffix), `effort_distance`.
  - **Files**: tests/test_router.py
  - **Done when**: ladder invariants covered and green
  - **Verify**: `python3 -m unittest tests.test_router -v`
  - **Commit**: `test(router): add ladder invariant tests`
  - _Requirements: FR-1, FR-2, FR-3, FR-6, AC-2.4, AC-2.5, AC-10.4_

- [x] 3.2 test_router.py: config tests
  - **Do**:
    1. Add config tests: v1 detection matrix (v1 keys, version 2, empty); full `migrate_v1` mapping table per design; merge semantics (project wins, `$schema` skipped, per-class merge); extend/replace/remove_* via `resolve_list`.
    2. `v1_hint_due` fires once; unparseable file -> defaults (AC-8.5); user file never written by migration (assert mtime/content unchanged).
  - **Files**: tests/test_router.py
  - **Done when**: all migration/merge rows asserted
  - **Verify**: `python3 -m unittest tests.test_router -v`
  - **Commit**: `test(config): cover v1 detection, migration, merge semantics`
  - _Requirements: FR-31, FR-32, FR-33, AC-8.1..AC-8.5_

- [x] 3.3 [VERIFY] Quality checkpoint: unit + integration
  - **Do**: `python3 -m unittest discover tests -v && bash tests/test-hook.sh`
  - **Verify**: All exit 0
  - **Done when**: All green
  - **Commit**: `chore(tests): pass quality checkpoint` (only if fixes needed)

- [x] 3.4 test_router.py: taxonomy tests
  - **Do**:
    1. Scoring/margin tests per class; signal caps (degenerate 500-word prompt, keyword-stuffed trivia cannot force top tier, FR-7); extreme escalation only from architecture top.
    2. Abstain: empty/whitespace, low-signal prompt; determinism: same prompt + config -> identical result across 3 runs (NFR-10); mechanical zeroed above `mechanical_max_words`.
  - **Files**: tests/test_router.py
  - **Done when**: taxonomy behavior locked by tests
  - **Verify**: `python3 -m unittest tests.test_router -v`
  - **Commit**: `test(taxonomy): cover scoring, caps, escalation, abstain, determinism`
  - _Requirements: FR-7, FR-19, FR-23, FR-24, AC-7.1, NFR-10_

- [x] 3.5 test_router.py: policy tests
  - **Do**:
    1. Assert all 20 main-prompt matrix cells (5 classes x 4 current tiers) incl. stay cells and xhigh cells; haiku decisions never carry effort anywhere.
    2. Downroute guard (margin < downroute_margin blocks tier lowering); capability gates (handoff never haiku, AC-6.3); debugging and data-handling effort floors; `effort_warn_distance` match logic (distance 1 silent, distance 2 warns).
  - **Files**: tests/test_router.py
  - **Done when**: full matrix + gates + floors asserted
  - **Verify**: `python3 -m unittest tests.test_router -v`
  - **Commit**: `test(policy): cover full matrix, downroute guard, gates, floors`
  - _Requirements: FR-4, FR-5, FR-20, FR-21, FR-22, AC-2.1, AC-6.3, AC-6.5_

- [x] 3.6 [VERIFY] Quality checkpoint: unit + integration
  - **Do**: `python3 -m unittest discover tests -v && bash tests/test-hook.sh`
  - **Verify**: All exit 0
  - **Done when**: All green
  - **Commit**: `chore(tests): pass quality checkpoint` (only if fixes needed)

- [x] 3.7 test_router.py: cli_fallback tests (mocked subprocess)
  - **Do**:
    1. Mock `subprocess.run`: valid class reply parsed; garbage reply -> None; non-zero exit -> None; TimeoutExpired -> None; FileNotFoundError -> None (fail-open ladder, AC-7.4).
    2. Assert subprocess env carries `CLAUDE_MODEL_ROUTER_CHILD=1`; assert `cli_fallback: false` never invokes subprocess (AC-7.6).
  - **Files**: tests/test_router.py
  - **Done when**: every fail-open branch asserted without real CLI calls
  - **Verify**: `python3 -m unittest tests.test_router -v`
  - **Commit**: `test(cli): cover fallback parse, fail-open ladder, child guard`
  - _Requirements: FR-25, FR-26, FR-27, AC-7.3, AC-7.4, AC-7.6_

- [ ] 3.8 test_router.py: cache tests
  - **Do**:
    1. Cache hit skips subprocess (AC-7.5); eviction at `cache_max_entries` drops oldest 20%; corrupt cache file discarded and rewritten (NFR-9); `CLAUDE_PLUGIN_DATA` unset -> no cache file, still returns.
    2. Assert cache file contains hashes + classes only, no raw prompt substring (NFR-5).
  - **Files**: tests/test_router.py
  - **Done when**: cache hygiene and privacy asserted
  - **Verify**: `python3 -m unittest tests.test_router -v`
  - **Commit**: `test(cli): cover cache hit, eviction, corruption, privacy`
  - _Requirements: FR-28, AC-7.5, NFR-5, NFR-9_

- [ ] 3.9 test_router.py: variant coverage test
  - **Do**:
    1. Add test: for every DEFAULT class target in `config.DEFAULTS`, a matching `PLUGIN/agents/routed-*.md` file exists with frontmatter `model`/`effort` equal to the target (haiku variant asserted to have NO effort key) (amended AC-4.2).
  - **Files**: tests/test_router.py
  - **Done when**: default target -> variant mapping asserted for all 5 cells
  - **Verify**: `python3 -m unittest tests.test_router -v`
  - **Commit**: `test(agents): assert every default target has a shipped variant`
  - _Requirements: FR-16, AC-4.2_

- [ ] 3.10 [VERIFY] Quality checkpoint: unit + integration
  - **Do**: `python3 -m unittest discover tests -v && bash tests/test-hook.sh`
  - **Verify**: All exit 0
  - **Done when**: All green
  - **Commit**: `chore(tests): pass quality checkpoint` (only if fixes needed)

- [ ] 3.11 test-hook.sh: new UserPromptSubmit suites
  - **Do**:
    1. Add suites: extreme prompt on sonnet session -> fable suggestion in stderr; warn message contains `/effort <level>`; `[1m]` suffix preserved alongside effort suggestion (AC-1.4); effort-only distance 1 mismatch silent, distance >= 2 warns.
    2. All with fake HOME configs, `classifier.cli_fallback: false`.
  - **Files**: tests/test-hook.sh
  - **Done when**: fable, effort emission, suffix suites pass
  - **Verify**: `bash tests/test-hook.sh`
  - **Commit**: `test(hooks): add fable, effort message, suffix suites`
  - _Requirements: FR-41, AC-1.1, AC-1.4, AC-10.5_

- [ ] 3.12 test-hook.sh: PreToolUse suites
  - **Do**:
    1. Add suites piping PreToolUse JSON to `python3 .../hooks/pre_tool_use.py`: generic mechanical spawn -> stdout updatedInput with `routed-haiku` + `model: haiku` (assert JSON fields); custom subagent_type -> model-only injection, type untouched; explicit caller model -> no updatedInput.
    2. Abstain prompt -> pass-through (no updatedInput); `CLAUDE_MODEL_ROUTER_CHILD=1` -> exit 0 no output; malformed stdin -> exit 0.
  - **Files**: tests/test-hook.sh
  - **Done when**: all PreToolUse contract paths asserted end to end
  - **Verify**: `bash tests/test-hook.sh`
  - **Commit**: `test(hooks): add PreToolUse rewrite and respect suites`
  - _Requirements: FR-41, AC-4.1, AC-4.3, AC-5.1, AC-10.5_

- [ ] 3.13 test-hook.sh: autoswitch suites
  - **Do**:
    1. Add suites with fake HOME + autoswitch config: tier mismatch writes `model`/`effortLevel` to fake `~/.claude/settings.json` preserving other keys; stderr says new-sessions (never live-switch claim).
    2. Fable decision with `allow_fable_autoswitch: false` -> no settings write, warn only; corrupt settings.json -> degrade to warn, file untouched.
  - **Files**: tests/test-hook.sh
  - **Done when**: autoswitch write, gating, degrade paths asserted
  - **Verify**: `bash tests/test-hook.sh`
  - **Commit**: `test(hooks): add autoswitch settings write and fable gating suites`
  - _Requirements: FR-9, FR-10, FR-11, AC-3.2, AC-3.3_

- [ ] 3.14 [VERIFY] Quality checkpoint: full unit + integration
  - **Do**: `python3 -m unittest discover tests -v && bash tests/test-hook.sh`
  - **Verify**: All exit 0
  - **Done when**: Entire test suite green
  - **Commit**: `chore(tests): pass quality checkpoint` (only if fixes needed)

## Phase 4: Eval, Docs, CI, Manifests, Quality Gates

- [ ] 4.1 Build eval_set.jsonl
  - **Do**:
    1. Create `tests/eval/eval_set.jsonl`: 50-100 rows, one JSON object per line with `id`, `prompt`, `expected_class`, `expected` (model, effort; haiku rows have no effort key), `tags`.
    2. >= 8 rows per class (mechanical, implementation, debugging, architecture, extreme, abstain) incl. adversarial/degenerate rows (huge mechanical prompts, keyword-stuffed trivia).
  - **Files**: tests/eval/eval_set.jsonl
  - **Done when**: valid JSONL, class coverage >= 8 each, no expected model outside the 4-alias ladder
  - **Verify**: `python3 -c "import json,collections; rows=[json.loads(l) for l in open('tests/eval/eval_set.jsonl')]; c=collections.Counter(r['expected_class'] for r in rows); assert 50<=len(rows)<=100, len(rows); assert all(c[k]>=8 for k in ['mechanical','implementation','debugging','architecture','extreme','abstain']), c; assert all(r.get('expected',{}).get('model') in (None,'haiku','sonnet','opus','fable') for r in rows); print('PASS', len(rows))"`
  - **Commit**: `test(eval): add labeled eval set across all taxonomy classes`
  - _Requirements: FR-38, AC-10.1_
  - _Design: Eval Harness_

- [ ] 4.2 run_eval.py harness
  - **Do**:
    1. Create `tests/eval/run_eval.py` importing `router.taxonomy` + `router.policy` directly (real entry point, AC-10.2/10.4), running with `cli_fallback: false` (deterministic, NFR-10).
    2. Print per-class accuracy, confusion matrix, tier distribution; exit 1 on: accuracy < `ACCURACY_MIN` (provisional 0.90), fable share > `FABLE_SHARE_MAX` (0.10), opus+fable share > `TOP_SHARE_MAX` (0.40), heuristic p95 >= 200ms (NFR-1).
    3. Thresholds as top-of-file constants with a comment: provisional until baseline run; also assert zero mythos emissions across the set.
  - **Files**: tests/eval/run_eval.py
  - **Done when**: harness runs the full set and reports; gate logic implemented
  - **Verify**: `python3 tests/eval/run_eval.py; test $? -le 1 && echo HARNESS_RUNS`
  - **Commit**: `test(eval): add eval harness with accuracy and collapse gates`
  - _Requirements: FR-39, AC-10.2, AC-10.3, AC-2.5, NFR-1_
  - _Design: Eval Harness_

- [ ] [VERIFY] Quality checkpoint: unit + integration + eval harness runs
  - **Do**: `python3 -m unittest discover tests -v && bash tests/test-hook.sh && python3 tests/eval/run_eval.py; test $? -le 1`
  - **Verify**: Unit and integration exit 0; eval harness executes to completion (exit 0 or 1, no crash; gates are provisional until 4.4)
  - **Done when**: Full suite green and the eval harness produces a report
  - **Commit**: `chore(eval): pass quality checkpoint` (only if fixes needed)

- [ ] 4.3 Baseline eval run + record
  - **Do**:
    1. Run `python3 tests/eval/run_eval.py`; capture per-class accuracy, confusion matrix, tier shares, p95.
    2. Fix classifier/eval-set labeling issues until baseline is sane; record baseline numbers in `specs/router-modernization/.progress.md` Learnings.
  - **Files**: specs/router-modernization/.progress.md (plus classifier/eval fixes if needed)
  - **Done when**: baseline numbers documented; accuracy at or near target
  - **Verify**: `python3 tests/eval/run_eval.py 2>&1 | grep -qi 'accuracy' && grep -qi 'baseline' specs/router-modernization/.progress.md && echo PASS`
  - **Commit**: `chore(eval): record baseline eval numbers`
  - _Requirements: FR-39_
  - _Design: Eval Harness thresholds note_

- [ ] 4.4 Lock eval thresholds
  - **Do**:
    1. Set final `ACCURACY_MIN`, `FABLE_SHARE_MAX`, `TOP_SHARE_MAX` in run_eval.py from the 4.3 baseline (accuracy >= 0.90 target); replace "provisional" comment with rationale referencing baseline numbers.
  - **Files**: tests/eval/run_eval.py
  - **Done when**: thresholds locked, gate passes at locked values
  - **Verify**: `python3 tests/eval/run_eval.py && ! grep -qi provisional tests/eval/run_eval.py && echo PASS`
  - **Commit**: `test(eval): lock CI gate thresholds from baseline`
  - _Requirements: FR-39, AC-10.2, AC-10.3_

- [ ] 4.5 [VERIFY] Quality checkpoint: unit + integration + eval
  - **Do**: `python3 -m unittest discover tests -v && bash tests/test-hook.sh && python3 tests/eval/run_eval.py`
  - **Verify**: All exit 0
  - **Done when**: Eval gate green alongside full suite
  - **Commit**: `chore(eval): pass quality checkpoint` (only if fixes needed)

- [ ] 4.6 scripts/sync_docs.py
  - **Do**:
    1. Create `scripts/sync_docs.py`: injects `router.advisory.ADVISORY_MD` between `<!-- advisory:start -->` / `<!-- advisory:end -->` markers in `README.md`, `prompt.md`, `PLUGIN/prompt.md`.
    2. `--check` mode: exit 1 on any drift (CI gate, AC-11.1); default mode rewrites in place.
  - **Files**: scripts/sync_docs.py
  - **Done when**: generation and check modes work against marker blocks
  - **Verify**: `python3 -c "import pathlib; assert pathlib.Path('scripts/sync_docs.py').exists()" && python3 scripts/sync_docs.py --help >/dev/null 2>&1 || python3 -m py_compile scripts/sync_docs.py && echo PASS`
  - **Commit**: `feat(docs): add advisory sync script with check mode`
  - _Requirements: FR-42, FR-43, AC-11.1_
  - _Design: advisory.py, sync_docs_

- [ ] 4.7 README v2 rewrite
  - **Do**:
    1. Update `README.md`: warn default + opt-in autoswitch semantics (new-sessions-only), subagent PreToolUse enforcement, effort-first routing, config v2 + migration note, replace "No API calls" claim with "no API key; optional Claude CLI call" + disable knob (FR-44, NFR-6); remove the embedded stale hook-script variant.
    2. Insert advisory marker block and run `python3 scripts/sync_docs.py` to populate it; document known limitation: multi-hook updatedInput merge order undocumented (A-3).
  - **Files**: README.md
  - **Done when**: README describes actual v2 behavior; advisory block generated
  - **Verify**: `grep -q 'advisory:start' README.md && ! grep -qi 'no api calls' README.md && python3 scripts/sync_docs.py --check && echo PASS`
  - **Commit**: `docs(readme): describe v2 behavior with generated advisory block`
  - _Requirements: FR-44, AC-11.3, NFR-6_

- [ ] 4.8 prompt.md rewrite (both copies)
  - **Do**:
    1. Rewrite `prompt.md` and `PLUGIN/prompt.md` as clone+install instructions (no inline scripts), with advisory marker blocks populated via sync_docs.
    2. Keep both byte-identical or generated from the same source (dedup guarantee, FR-43).
  - **Files**: prompt.md, plugins/claude-model-router-hook/prompt.md
  - **Done when**: both copies are clone+install docs, identical, markers in sync
  - **Verify**: `cmp prompt.md plugins/claude-model-router-hook/prompt.md && grep -q 'advisory:start' prompt.md && python3 scripts/sync_docs.py --check && echo PASS`
  - **Commit**: `docs(prompt): rewrite as clone and install instructions, dedup copies`
  - _Requirements: FR-43, FR-44, AC-11.2, AC-11.3_

- [ ] 4.9 [VERIFY] Quality checkpoint: docs parity + tests
  - **Do**: `python3 scripts/sync_docs.py --check && python3 -m unittest discover tests -v && bash tests/test-hook.sh`
  - **Verify**: All exit 0
  - **Done when**: No docs drift, tests green
  - **Commit**: `chore(docs): pass quality checkpoint` (only if fixes needed)

- [ ] 4.10 Correct slides claims
  - **Do**:
    1. Edit `docs/slides/slides.md`: correct behavior claims only (warn default, autoswitch semantics, CLI fallback disclosure, 4-tier ladder with effort); no content rewrite beyond claims (out of scope guard).
  - **Files**: docs/slides/slides.md
  - **Done when**: no stale claims (autoswitch-by-default, no-API-calls, 3-tier-only) remain
  - **Verify**: `! grep -qi 'no api calls' docs/slides/slides.md && echo PASS`
  - **Commit**: `docs(slides): correct behavior claims for v2`
  - _Requirements: FR-44, AC-11.3_

- [ ] 4.11 install.sh: plugin update + root delegation
  - **Do**:
    1. Update `PLUGIN/install.sh`: copy `hooks/router/` package, entrypoints, `agents/` variants, `schema/`; print registration incl. PreToolUse hook and agents dir (FR-46).
    2. Replace root `install.sh` body with delegation to the plugin copy (single real script, FR-43).
    3. Update `schema/model-router.schema.json` to `oneOf` [v1-shape, v2-shape], v2 branch requires `"version": 2`, both branches `additionalProperties: false` (FR-34).
  - **Files**: install.sh, plugins/claude-model-router-hook/install.sh, schema/model-router.schema.json
  - **Done when**: root script delegates; plugin script ships agents+schema+PreToolUse registration; schema validates both shapes
  - **Verify**: `bash -n install.sh && bash -n plugins/claude-model-router-hook/install.sh && grep -q 'install.sh' install.sh && grep -qi 'pretooluse\|pre_tool_use' plugins/claude-model-router-hook/install.sh && python3 -c "import json; s=json.load(open('schema/model-router.schema.json')); assert 'oneOf' in s; print('PASS')"`
  - **Commit**: `feat(install): dedup installers, ship agents and v2 schema`
  - _Requirements: FR-34, FR-43, FR-46, AC-11.2, AC-11.5_

- [ ] 4.12 [VERIFY] Quality checkpoint: full local suite
  - **Do**: `python3 -m unittest discover tests -v && bash tests/test-hook.sh && python3 tests/eval/run_eval.py && python3 scripts/sync_docs.py --check`
  - **Verify**: All exit 0
  - **Done when**: All four gates green locally
  - **Commit**: `chore(router): pass quality checkpoint` (only if fixes needed)

- [ ] 4.13 CI wiring in test.yml
  - **Do**:
    1. Update `.github/workflows/test.yml`: unit step -> `python3 -m unittest discover tests -v`; keep integration `bash tests/test-hook.sh`; add eval gate step `python3 tests/eval/run_eval.py`; add docs parity step `python3 scripts/sync_docs.py --check`.
  - **Files**: .github/workflows/test.yml
  - **Done when**: 4 steps present in order unit -> integration -> eval -> docs parity
  - **Verify**: `grep -q 'unittest discover' .github/workflows/test.yml && grep -q 'run_eval.py' .github/workflows/test.yml && grep -q 'sync_docs.py --check' .github/workflows/test.yml && echo PASS`
  - **Commit**: `ci: add eval gate and docs parity steps`
  - _Requirements: FR-39, AC-10.2, AC-11.1_

- [ ] 4.14 Bump manifests to 2.0.0
  - **Do**:
    1. Set version `2.0.0` in `.claude-plugin/plugin.json`, `PLUGIN/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`.
  - **Files**: .claude-plugin/plugin.json, plugins/claude-model-router-hook/.claude-plugin/plugin.json, .claude-plugin/marketplace.json
  - **Done when**: all three read 2.0.0
  - **Verify**: `python3 -c "import json; assert all('2.0.0' in open(f).read() for f in ['.claude-plugin/plugin.json','plugins/claude-model-router-hook/.claude-plugin/plugin.json','.claude-plugin/marketplace.json']); print('PASS')"`
  - **Commit**: `chore(release): bump manifests to 2.0.0`
  - _Requirements: FR-45, AC-11.4_

- [ ] 4.15 CHANGELOG backfill + 2.0.0 entry
  - **Do**:
    1. Backfill `CHANGELOG.md` entries 1.0.1, 1.1.0, 1.3.0 from `git log` history.
    2. Add 2.0.0 entry: v2 rewrite summary, effort-first routing, PreToolUse enforcement, CLI fallback disclosure, config v2 + migration, breaking/semantic change note (haiku session now up-routes to sonnet for implementation/debugging), eval baseline threshold rationale.
  - **Files**: CHANGELOG.md
  - **Done when**: version gap closed, semantic change documented
  - **Verify**: `grep -q '2.0.0' CHANGELOG.md && grep -q '1.1.0' CHANGELOG.md && grep -q '1.0.1' CHANGELOG.md && grep -q '1.3.0' CHANGELOG.md && grep -qi 'sonnet' CHANGELOG.md && echo PASS`
  - **Commit**: `docs(changelog): close version gap and add 2.0.0`
  - _Requirements: FR-45, AC-11.4_

- [ ] V4 [VERIFY] Full local CI
  - **Do**: Run the complete local CI suite: `python3 -m unittest discover tests -v && bash tests/test-hook.sh && python3 tests/eval/run_eval.py && python3 scripts/sync_docs.py --check && python3 -m py_compile plugins/claude-model-router-hook/hooks/router/*.py plugins/claude-model-router-hook/hooks/*.py scripts/sync_docs.py tests/eval/run_eval.py`
  - **Verify**: All commands exit 0
  - **Done when**: Unit, integration, eval, docs parity, compile all green
  - **Commit**: `chore(router): pass local CI` (only if fixes needed)

- [ ] 4.16 Create PR
  - **Do**:
    1. Confirm branch: `git branch --show-current` = `feat/router-modernization` (STOP if on main).
    2. Push: `git push -u origin feat/router-modernization`.
    3. `gh pr create --title "feat: router v2, effort-first routing with subagent enforcement" --body "<summary of v2 scope, semantic changes, eval baseline>"`.
  - **Files**: none
  - **Done when**: PR open against main
  - **Verify**: `gh pr view --json url -q .url`
  - **Commit**: None

- [ ] V5 [VERIFY] CI pipeline passes
  - **Do**: `gh pr checks --watch` until completion; on failure read logs, fix, push, re-watch
  - **Verify**: `gh pr checks` shows all green
  - **Done when**: All CI checks pass on the PR
  - **Commit**: None

- [ ] V6 [VERIFY] AC checklist
  - **Do**: Read `specs/router-modernization/requirements.md`; for each AC-1.1..AC-11.5 verify programmatically (run the relevant unit/integration/eval test or grep the implementing code); record the checklist result in `specs/router-modernization/.progress.md`
  - **Verify**: Every AC maps to a passing automated check; `python3 -m unittest discover tests -v && bash tests/test-hook.sh && python3 tests/eval/run_eval.py` exit 0
  - **Done when**: All acceptance criteria confirmed met via automated checks
  - **Commit**: None

## Phase 5: PR Lifecycle

- [ ] 5.1 CI monitoring loop
  - **Do**: Monitor `gh pr checks`; on any failure: read logs, fix locally, run V4 suite, push; repeat until green (max 20 cycles)
  - **Verify**: `gh pr checks` all green
  - **Done when**: CI stable green on latest push
  - **Commit**: `fix(router): address CI failures` (per fix, if needed)

- [ ] 5.2 Resolve review comments
  - **Do**: `gh pr view --comments` and `gh api` review threads; address each actionable comment with a fix commit; reply/resolve; re-run V4 suite before each push
  - **Verify**: `gh pr view --json reviewDecision` not CHANGES_REQUESTED; no unresolved actionable threads
  - **Done when**: All review comments addressed
  - **Commit**: `fix(router): address review feedback` (per fix, if needed)

- [ ] 5.3 Final validation
  - **Do**:
    1. Confirm zero regressions: full local suite green; all tasks above checked.
    2. Confirm invariants one last time: no mythos string in any emitting code path, haiku never paired with effort, all error paths exit 0.
    3. Update `specs/router-modernization/.progress.md` with completion summary.
  - **Verify**: `! grep -rn 'mythos' plugins/claude-model-router-hook/hooks/router/ladder.py | grep -v 'not in\|assert\|raise' ; python3 -m unittest discover tests -v && bash tests/test-hook.sh && python3 tests/eval/run_eval.py && python3 scripts/sync_docs.py --check && echo DONE`
  - **Done when**: All completion criteria met, PR mergeable
  - **Commit**: `chore(router-modernization): finalize spec execution`

## Unresolved Questions

- Multi-hook `updatedInput` merge order is undocumented platform behavior; handled as documented limitation (README), nothing actionable in tasks.
- Eval thresholds locked only after 4.3 baseline; 4.4 must not be reordered before 4.3.

## Notes

- POC shortcuts: Phase 1 config is defaults + shallow merge only (full v1 migration/merge lands 2.5/2.6); no CLI fallback, no PreToolUse, no autoswitch until Phase 2.
- Phase distribution deviates from standard POC split by delegation instruction: minimal Phase 1 slice, heavy Phase 2 feature build.
- Ordering constraints honored: ladder+hookio+config before taxonomy/policy; package before entrypoints; entrypoints before hooks.json rewire and v1 deletion; test_config refactor (2.25) and test-hook.sh update (2.26) before v1 deletion (2.27) because tests/test_config.py imports model_router directly; agents variants (2.15/2.16) before PreToolUse integration tests (3.12); eval baseline (4.3) before threshold lock (4.4); sync_docs.py (4.6) before regenerated docs (4.7/4.8); manifests+CHANGELOG last before final gates.
- E2E: no VE1/VE2/VE3 live-platform tasks (user decision); test-hook.sh suites + eval gate are the E2E surface.
- CLI fallback OFF in every scripted test and in eval (deterministic); it is exercised only via mocked subprocess in unit tests.
- No AI attribution in any commit message.
