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
<p class="text-xl opacity-60 mt-6">Model routing for Claude Code, heuristics-first, no API key required</p>
<p class="text-sm opacity-30 mt-12">github.com/tzachbon/claude-model-router-hook</p>
</div>

<!--
Welcome! I'm going to walk you through a hook I built for Claude Code that routes across Haiku, Sonnet, Opus, and Fable based on what you're asking it to do. Classification is heuristics-first with an optional headless Claude CLI fallback, so no API key is needed. By default it warns; autoswitch is opt-in.
-->

---
layout: center
---

<h2 class="text-3xl font-bold text-amber-400 mb-6">The Problem</h2>

<p v-click class="text-base opacity-80 mb-3">Opus is overkill for <code>git commit</code>, <code>rename</code>, <code>lint</code> — slow and expensive</p>

<p v-click class="text-base opacity-70 mb-3">Haiku is too weak for architecture decisions and complex refactors</p>

<p v-click class="text-base opacity-60 mb-3">Remembering <em>when</em> to switch models is cognitive overhead you shouldn't carry</p>

<p v-click class="text-base opacity-50 mb-3">Sub-agents inherit the wrong tier — Opus spawns Opus for trivial file searches</p>

<p v-click class="text-base font-bold opacity-90 mt-6">You need a router, not a toggle.</p>

<!--
These are real pain points from daily Claude Code usage. You have to remember which model fits each task, or you forget and burn Opus tokens on a git commit. And sub-agents inherit the parent tier, so one Opus session snowballs into Opus everywhere.
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
<p class="opacity-70 text-sm leading-relaxed">Classifies each prompt heuristics-first (keyword + regex), compares against current model, and warns on a mismatch. Autoswitch is opt-in and writes settings for new sessions only.</p>
</div>
</div>

<!--
Two hooks, that's it. The first one fires at session start and injects tier rules so sub-agents know which model to pick, and a PreToolUse hook enforces the tier on spawned sub-agents. The second fires on every prompt. It classifies what you're asking, checks the current model, and warns if there's a mismatch. Warn is the default; autoswitch is opt-in and only affects new sessions. Classification is heuristics-first with an optional headless Claude CLI fallback that you can disable; no API key is used.
-->

---
layout: center
---

<h2 class="text-3xl font-bold text-amber-400 mb-6 text-center">Classification Tiers</h2>

<div class="grid grid-cols-4 gap-4 max-w-6xl">
<div v-click class="bg-white/5 border border-white/10 rounded-2xl p-4">
<h3 class="text-cyan-400 text-base font-semibold mb-2">Haiku</h3>
<p class="opacity-60 text-xs leading-relaxed"><code>git commit</code> · <code>rename</code> · <code>lint</code> · <code>format</code> · <code>delete file</code> · <code>add import</code> · <code>update version</code></p>
<p class="opacity-40 text-xs mt-2">short mechanical prompts</p>
</div>
<div v-click class="bg-white/5 border border-white/10 rounded-2xl p-4">
<h3 class="text-amber-400 text-base font-semibold mb-2">Sonnet</h3>
<p class="opacity-60 text-xs leading-relaxed"><code>build</code> · <code>implement</code> · <code>fix</code> · <code>debug</code> · <code>add feature</code> · <code>test</code> · <code>refactor</code> · <code>api</code></p>
<p class="opacity-40 text-xs mt-2">default for feature work</p>
</div>
<div v-click class="bg-white/5 border border-white/10 rounded-2xl p-4">
<h3 class="text-purple-400 text-base font-semibold mb-2">Opus</h3>
<p class="opacity-60 text-xs leading-relaxed"><code>architect</code> · <code>deep dive</code> · <code>multi-system</code> · <code>complex refactor</code> · <code>plan mode</code> · <code>analyze</code> · <code>strategy</code></p>
<p class="opacity-40 text-xs mt-2">longer, higher-stakes prompts</p>
</div>
<div v-click class="bg-white/5 border border-white/10 rounded-2xl p-4">
<h3 class="text-rose-400 text-base font-semibold mb-2">Fable</h3>
<p class="opacity-60 text-xs leading-relaxed">top of the ladder for the most demanding work; autoswitch is gated behind <code>allow_fable_autoswitch</code></p>
<p class="opacity-40 text-xs mt-2">opt-in top tier</p>
</div>
</div>

<p v-click class="text-center mt-6 opacity-70 text-sm">
<span class="text-cyan-400 font-semibold">Four-tier ladder with effort levels</span>: Haiku → Sonnet → Opus → Fable, each with an effort floor
</p>

<p v-click class="text-center mt-3 opacity-60 text-sm">
<span class="text-amber-400 font-semibold">Fully customizable</span> — override keywords, patterns & thresholds via <code>model-router.json</code>
</p>

<!--
A four-tier ladder: Haiku, Sonnet, Opus, Fable, each with an effort floor. Classification is heuristics-first with keyword and regex matching, plus an optional headless Claude CLI fallback you can disable. Haiku triggers on short, mechanical prompts matching git/rename/format patterns. Sonnet is the middle ground for feature work. Opus handles architecture and higher-stakes work. Fable sits at the top for the most demanding work, and autoswitching to it is gated behind allow_fable_autoswitch.
-->

---
layout: center
---

<h2 class="text-2xl font-bold text-amber-400 mb-4 text-center">Demo</h2>

<div class="flex flex-row gap-6 items-center justify-center">
<img src="/sub-agent-routing.png" class="rounded-xl border border-white/10 shadow-2xl" style="max-height: 52vh; max-width: 45%;" />
<video src="/model-router.mov" controls class="rounded-xl border border-white/10 shadow-2xl" style="max-height: 52vh; max-width: 45%;" />
</div>

<!--
On the left: sub-agents spawned with the correct model tier, injected by the SessionStart hook and enforced by the PreToolUse hook. On the right: the prompt router warning on a mismatch, or switching when autoswitch is opted in. Heuristics-first classification, no API key required.
-->

---
layout: center
---

<h2 class="text-3xl font-bold text-amber-400 mb-8 text-center">What's Next</h2>

<div class="flex flex-col gap-4 max-w-2xl mx-auto">
<div v-click class="bg-white/5 border border-white/10 rounded-2xl p-5">
<h3 class="text-cyan-400 text-base font-semibold mb-2">Model Middleware</h3>
<p class="opacity-70 text-sm leading-relaxed">Automatic detection — a lightweight middleware layer that classifies prompts for you, no manual patterns needed.</p>
</div>
</div>

<!--
One thing left on the roadmap: a model middleware layer that does prompt classification automatically — so you don't need to define any patterns at all. User-configurable keywords and thresholds already shipped via model-router.json.
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
<code class="text-xs opacity-80">git clone https://github.com/tzachbon/claude-model-router-hook.git && bash claude-model-router-hook/install.sh</code>
</div>
</div>
<p class="mt-8 opacity-40 text-sm">github.com/tzachbon/claude-model-router-hook</p>
</div>

<!--
Marketplace install is the easiest — one command and you're done. The curl one-liner works too if you prefer. Or clone and copy the hooks manually. All three get you the same result: automatic model routing on every prompt.
-->
