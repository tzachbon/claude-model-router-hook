---
theme: default
colorSchema: dark
transition: slide-left
title: Claude Model Router Hook
mdc: true
drawings:
  persist: false
info: |
  ## Claude Model Router Hook
  Automatic model switching for Claude Code.
  [github.com/tzachbon/claude-model-router-hook](https://github.com/tzachbon/claude-model-router-hook)
---

<div class="flex flex-col items-center justify-center h-full">
<h1 class="text-6xl font-bold !leading-tight">Claude Model Router</h1>
<p class="text-xl opacity-60 mt-6">Automatic model switching for Claude Code — zero API calls</p>
<p class="text-sm opacity-30 mt-12">github.com/tzachbon/claude-model-router-hook</p>
</div>

<!--
Welcome! I'm going to walk you through a hook I built for Claude Code that automatically switches between Opus, Sonnet, and Haiku based on what you're asking it to do. No API calls, no config — just pattern matching.
-->

---
layout: center
---

<h2 class="text-3xl font-bold text-amber-400 mb-6">The Problem</h2>

<p v-click class="text-base opacity-80 mb-3">Opus is overkill for <code>git commit</code>, <code>rename</code>, <code>lint</code> — slow and expensive</p>

<p v-click class="text-base opacity-70 mb-3">Haiku is too weak for architecture decisions and complex refactors</p>

<p v-click class="text-base opacity-60 mb-3">Manual <code>/model</code> switching breaks your flow every few prompts</p>

<p v-click class="text-base opacity-50 mb-3">Sub-agents inherit the wrong tier — Opus spawns Opus for trivial file searches</p>

<p v-click class="text-base font-bold opacity-90 mt-6">You need a router, not a toggle.</p>

<!--
These are real pain points from daily Claude Code usage. You're constantly context-switching between model tiers, or worse — you forget and burn Opus tokens on a git commit. And sub-agents inherit the parent tier, so one Opus session snowballs into Opus everywhere.
-->

---
layout: center
---

<h2 class="text-3xl font-bold text-amber-400 mb-8 text-center">How It Works</h2>

<div class="grid grid-cols-2 gap-10 max-w-4xl">
<div v-click class="bg-white/5 border border-white/10 rounded-2xl p-6">
<h3 class="text-cyan-400 text-lg font-semibold mb-3">SessionStart</h3>
<p class="opacity-70 text-sm leading-relaxed">Injects tier rules as a system message into every session — sub-agents learn which model to use for each task type.</p>
</div>
<div v-click class="bg-white/5 border border-white/10 rounded-2xl p-6">
<h3 class="text-cyan-400 text-lg font-semibold mb-3">UserPromptSubmit</h3>
<p class="opacity-70 text-sm leading-relaxed">Classifies each prompt with keyword + regex matching, compares against current model, and suggests a switch if mismatched.</p>
</div>
</div>

<!--
Two hooks, that's it. The first one fires at session start and injects tier rules so sub-agents know which model to pick. The second fires on every prompt — it classifies what you're asking, checks the current model, and suggests a switch if there's a mismatch. No API calls, no external services.
-->

---
layout: center
---

<h2 class="text-3xl font-bold text-amber-400 mb-6 text-center">Classification Tiers</h2>

<div class="grid grid-cols-3 gap-4 max-w-5xl">
<div v-click class="bg-white/5 border border-white/10 rounded-2xl p-4">
<h3 class="text-purple-400 text-base font-semibold mb-2">Opus</h3>
<p class="opacity-60 text-xs leading-relaxed"><code>architect</code> · <code>deep dive</code> · <code>multi-system</code> · <code>complex refactor</code> · <code>plan mode</code> · <code>analyze</code> · <code>strategy</code></p>
<p class="opacity-40 text-xs mt-2">or prompt &gt; 200 words</p>
</div>
<div v-click class="bg-white/5 border border-white/10 rounded-2xl p-4">
<h3 class="text-amber-400 text-base font-semibold mb-2">Sonnet</h3>
<p class="opacity-60 text-xs leading-relaxed"><code>build</code> · <code>implement</code> · <code>fix</code> · <code>debug</code> · <code>add feature</code> · <code>test</code> · <code>refactor</code> · <code>api</code></p>
<p class="opacity-40 text-xs mt-2">default for feature work</p>
</div>
<div v-click class="bg-white/5 border border-white/10 rounded-2xl p-4">
<h3 class="text-cyan-400 text-base font-semibold mb-2">Haiku</h3>
<p class="opacity-60 text-xs leading-relaxed"><code>git commit</code> · <code>rename</code> · <code>lint</code> · <code>format</code> · <code>delete file</code> · <code>add import</code> · <code>update version</code></p>
<p class="opacity-40 text-xs mt-2">short prompts &lt; 60 words</p>
</div>
</div>

<p v-click class="text-center mt-6 opacity-70 text-sm">
<span class="text-cyan-400 font-semibold">Zero latency</span> — ~5ms pattern matching, not seconds
</p>

<!--
Pure regex and keyword matching, no LLM involved. That's the key insight — you don't need AI to classify "git commit all changes" as a simple task. Opus triggers on architecture keywords or very long prompts. Haiku triggers on short, mechanical prompts matching git/rename/format patterns. Sonnet is the middle ground for feature work.
-->

---
layout: center
---

<h2 class="text-3xl font-bold text-amber-400 mb-4 text-center">Code Walkthrough</h2>

<div class="grid grid-cols-2 gap-6 max-w-5xl">
<div>
<h3 class="text-sm opacity-50 mb-3 font-mono">Classification Patterns</h3>

```python {1-7|8-14|15-20}
opus_keywords = [
    "architect", "architecture",
    "evaluate", "tradeoff", "strategy",
    "compare approaches", "deep dive",
    "redesign", "across the codebase",
    "multi-system", "complex refactor",
    "analyze", "plan mode", "rethink",
]
haiku_patterns = [
    r"\bgit\s+(commit|push|pull|status)\b",
    r"\brename\b", r"\bmove\s+file\b",
    r"\bformat\b", r"\blint\b",
    r"\bremove\s+(unused|dead)\b",
    # ... 7 more patterns
]
sonnet_patterns = [
    r"\bbuild\b", r"\bimplement\b",
    r"\bfix\b", r"\bdebug\b",
    r"\badd\s+feature\b", r"\btest\b",
    r"\brefactor\b", r"\bapi\b",
]
```

</div>
<div>
<h3 class="text-sm opacity-50 mb-3 font-mono">Decision Logic</h3>

```python {1-4|5-9|10-15}
has_opus_signal = any(
    kw in prompt_lower
    for kw in opus_keywords
)
if (has_opus_signal
    or (word_count > 100 and "?" in prompt)
    or word_count > 200):
    recommendation = "opus"
else:
    is_haiku_task = (
        word_count < 60 and any(
            re.search(p, prompt_lower)
            for p in haiku_patterns)
    )
    if is_haiku_task:
        recommendation = "haiku"
    elif any(re.search(p, prompt_lower)
             for p in sonnet_patterns):
        recommendation = "sonnet"
    else:
        recommendation = None
```

</div>
</div>

<!--
Here's the actual code. On the left, the three pattern lists — opus keywords are plain string matches, haiku and sonnet use regex for more flexibility. On the right, the decision logic: opus wins if any keyword matches OR the prompt is long and contains a question mark OR over 200 words. Then haiku checks for short mechanical tasks, sonnet catches feature work, and if nothing matches we don't recommend a switch.
-->

---
layout: center
---

<h2 class="text-3xl font-bold text-amber-400 mb-8 text-center">Demo</h2>

<div class="flex flex-col gap-3 max-w-2xl mx-auto">
<div v-click class="bg-white/5 border border-white/10 rounded-2xl p-5">
<code class="text-sm opacity-80">git commit all changes</code>
<p class="text-cyan-400 font-semibold mt-2 text-sm">→ Suggest /model haiku</p>
</div>
<div v-click class="bg-white/5 border border-white/10 rounded-2xl p-5">
<code class="text-sm opacity-80">architect a plugin system with dependency injection</code>
<p class="text-purple-400 font-semibold mt-2 text-sm">→ Suggest /model opus</p>
</div>
<div v-click class="bg-white/5 border border-white/10 rounded-2xl p-5 opacity-50">
<code class="text-sm opacity-80">~ just do it</code>
<p class="font-semibold mt-2 text-sm">→ Bypass — tilde prefix skips all checks</p>
</div>
</div>

<!--
Three examples. A simple git commit gets routed to Haiku — no need for Sonnet tokens. An architecture prompt triggers Opus immediately via keyword match. And if you prefix with a tilde, classification is bypassed entirely — useful when you know what you want. You can check the log file at ~/.claude/hooks/model-router-hook.log to see every classification decision.
-->

---
layout: center
class: text-center
---

<div class="flex flex-col items-center justify-center h-full">
<h1 class="text-4xl font-bold !leading-tight mb-8">Get Started</h1>
<div class="flex flex-col gap-3 max-w-2xl text-left">
<div v-click class="bg-white/5 border border-white/10 rounded-2xl p-5">
<p class="text-amber-400 font-semibold text-sm mb-1">Plugin Marketplace</p>
<code class="text-xs opacity-80">claude plugin marketplace add tzachbon/claude-model-router-hook</code>
</div>
<div v-click class="bg-white/5 border border-white/10 rounded-2xl p-5">
<p class="text-amber-400 font-semibold text-sm mb-1">One-liner</p>
<code class="text-xs opacity-80">curl -fsSL https://raw.githubusercontent.com/tzachbon/claude-model-router-hook/main/install.sh | bash</code>
</div>
<div v-click class="bg-white/5 border border-white/10 rounded-2xl p-5">
<p class="text-amber-400 font-semibold text-sm mb-1">Manual</p>
<code class="text-xs opacity-80">git clone → cp hooks/* ~/.claude/hooks/</code>
</div>
</div>
<p class="mt-8 opacity-40 text-sm">github.com/tzachbon/claude-model-router-hook</p>
</div>

<!--
Marketplace install is the easiest — one command and you're done. The curl one-liner works too if you prefer. Or clone and copy the hooks manually. All three get you the same result: automatic model routing on every prompt.
-->
