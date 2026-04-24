# presentation-content.md — on-stage script

> Compact script for the live presentation. Speak sections **bolded**, paraphrase the rest. Total target: **5–7 minutes** presentation + **3–5 minutes** live demo + **2–3 minutes** Q&A.

---

## Opening (30 seconds)

> **"Writing good code isn't one skill — it's three. You implement, you test, you review. Single-agent AI coders squash all three into one loop, which means the same model is the author AND the reviewer of its own work. That's like asking the person who wrote a patch to also be the security reviewer. It works on toy tasks. It breaks in production."**
>
> **"Our project is Gabru-Agent — G.A.B.R.U., *Generative Agent for Build, Review and Unit-test*. It's a three-agent system where a Coder writes the change, a Tester writes and runs pytest on it, and a Vulnerability-Hunter audits for edge cases and security issues. All three roles share one tool registry, all three are enforced by code — not by prompt — and all three run inside your IDE with zero additional LLM spend."**

## The problem we solve (45 seconds)

> **"Three problems with the single-agent status quo."**
>
> 1. **Context contamination** — the reviewer can see the coder's internal reasoning. That biases the audit. A clean review needs to see *only the output*, not the monologue.
> 2. **Tool-access pollution** — a coder with security-scan tools wastes tokens running them on speculation. A reviewer with `write_file` rewrites things it should only *report*.
> 3. **Prompt drift** — long single-agent conversations lose role discipline. Three focused conversations stay sharp.
>
> **"We fix this by giving each role its own restricted set of tools. The Coder literally cannot call the CVE scanner. The Hunter literally cannot write files. That's not a prompt instruction — it's a Python list. This is the core architectural claim: role discipline is a data structure, not a vibe."**

## The system (1 minute)

> **"Gabru runs in three modes from a single tool registry."**
>
> 1. **CLI agent** — `gabru --task` — runs a single-role loop against OpenRouter. The foundation.
> 2. **Three-agent pipeline** — `gabru-pipeline` — runs Coder → Tester → Hunter sequentially, chaining each stage's output into the next.
> 3. **MCP stdio server** — `gabru mcp-serve` — exposes the same tools over the Model Context Protocol, so any MCP-capable client becomes the model. This is what you're about to see.
>
> **"Here's the important bit. For the demo, we're not spending a single OpenRouter call. Claude Code is already an LLM. So we designed a 'manifest pattern' — Gabru ships one special tool called `get_pipeline_stages`. You give it a task, it returns a structured JSON blueprint: three role system prompts, context-chaining templates, per-role tool allow-lists, and a remediation-loop contract. Claude Code reads the manifest and executes each stage with the right tools. Gabru owns the *plan*. Claude Code does the *thinking*. Neither works without the other."**

## The remediation loop (30 seconds)

> **"One more piece. The Hunter ends its report with a structured JSON findings block — file, line, severity, category. If there are HIGH or CRITICAL findings, we automatically loop back to the Coder to fix them. Capped at two iterations — if two passes can't close it, a human looks. That's how a linear pipeline becomes a real closed-loop agent."**

## Live demo (3–5 minutes)

> **"Let me show you. I'm going to give Claude Code a task live — I'd actually like one of you to dictate it."**
>
> *[Judge provides a task like "Add a function reverse_str(s) to demo_sandbox/utils.py that reverses a string with type hints and a docstring."]*
>
> **"Watch what happens."**
>
> *[Claude Code invokes `mcp__gabru__get_pipeline_stages(task=...)`.]*
>
> **"That's Gabru returning the manifest. You can see the three stages laid out with their role prompts. Now Claude Code starts executing."**
>
> *[Stage 1 header appears: "## Stage 1: Coder — implementing..."]*
>
> **"Stage 1, the Coder. It's reading the directory, writing the file, and running it in the terminal to verify it actually works. That's one of our operating principles — actually verify your work ran. Imports cleanly and runs without exceptions beats 'looks right' every time."**
>
> *[Stage 2 starts.]*
>
> **"Stage 2, the Tester. Different role, different context — the Tester sees the task and the Coder's summary, not the Coder's internal reasoning. It's writing pytest tests now, and running them."**
>
> *[Pass count shows: "4 passed in 0.08s".]*
>
> *[Stage 3 starts.]*
>
> **"Stage 3, the Hunter. Adversarial audit. It's searching every call site, looking for edge cases the tests didn't cover and security patterns that could bite. At the end it emits a JSON findings block — that's the contract that drives the remediation loop."**
>
> *[Final pipeline report renders.]*
>
> **"And there's the final report. In about fifteen seconds we went from a spoken task to tested, audited code."**

*(If time permits, run the security-loop demo with `run_cmd(cmd)` → shell=True finding → Coder remediation → Hunter re-audit clean.)*

## Why this is technically interesting (1 minute)

> **"Three things make this defensible."**
>
> 1. **One tool registry, three run modes.** A tool written once — say, `osv_check` for CVE scanning — works in CLI mode, in the pipeline, and over MCP. No per-mode re-implementation.
> 2. **Self-registering tools.** We AST-scan the `tools/` directory for registration calls. Adding a new capability is one file — no manifest, no import list, no registry edits.
> 3. **Hunter's JSON contract.** Our remediation loop triggers on a structured findings block, not prose parsing. That means the loop can't drift when Hunter phrases things differently. The contract *is* the signal.
>
> **"And under the hood, we have: Anthropic prompt-cache passthrough on OpenRouter's `anthropic/*` slugs — so we don't lose cache savings; auto-compression when context fills up; provider-error classification with exponential backoff; a SQLite-plus-FTS5 session DB for persistent memory; and a senior-QA harness that drives our MCP server over stdio end-to-end — forty-two of forty-five checks pass."**

## Closing (30 seconds)

> **"We're not trying to replace your IDE. We're the thing you hand a GitHub issue to."**
>
> **"The wedge is the enforced review loop. Single-agent coders can't reliably self-review — they have structural blind spots. Gabru makes review a first-class, tool-isolated agent, with a closed loop back to the Coder when it finds something bad. That's the quality ceiling neither single-agent coders nor loose multi-agent swarms can reach."**
>
> **"Claude is the intelligence. Gabru is the body. Neither ships without the other — and neither does real code."**
>
> **"Happy to answer questions, dig into architecture, or run another live task."**

---

## Q&A prep — likely questions + crisp answers

**Q: "Isn't this just one Claude model with three system prompts?"**
> A: No. Role isolation is enforced by the per-stage tool allow-list in the manifest — it's a plain Python list of tool names. The Coder *cannot call* `osv_check`; the Hunter *cannot call* `write_file`. The separation is functional, not just linguistic.

**Q: "Why not use separate subprocesses for true context isolation?"**
> A: We evaluated that — it's Approach B in our plan doc. The technical claim is strongest there, but the live demo loses visibility — judges watch subprocess logs scroll in silence. We went with Approach C because the manifest pattern is both demo-legible AND gives us a clean upgrade path: same manifest, swap the executor for an ACP subprocess, done. The plumbing for that is already in `tools/delegate_tool.py`.

**Q: "What if the LLM ignores the tool allow-list?"**
> A: It can't — the host only exposes the allow-listed tools for that stage. If the model tries to call `write_file` in the Hunter stage, the tool isn't in the list; the call fails at the dispatch layer.

**Q: "How do you handle remediation cycles?"**
> A: Hunter emits a fenced JSON findings block at the end of its output. If any finding has severity HIGH or CRITICAL, and we haven't hit the loop cap of two iterations, we re-run Coder with a filtered context that includes only those HIGH findings. Tester re-runs. Hunter re-audits. Clean or cap-hit, we stop.

**Q: "What's your eval strategy?"**
> A: Today: 45-check senior-QA harness driving the MCP server end-to-end. Next 90 days: synthetic GitHub-issue fixtures with LLM-judge scoring. The harness is the regression signal for every prompt change.

**Q: "Costs?"**
> A: Zero external LLM calls on stage — Claude Code is the model. CLI mode uses OpenRouter with Anthropic prompt caching passed through, so cached calls are massively cheaper. The 3-agent pipeline is three OpenRouter sessions, but each uses `skip_memory=True` and `skip_context_files=True` to stay tight.

**Q: "How does this compare to Cursor / Aider / Cline?"**
> A: Those are single-agent IDE companions. Gabru's wedge is the *enforced three-role review loop* — specifically the adversarial Hunter with structured findings and closed-loop remediation. Cursor can help you write code; Gabru decides whether the code is safe enough to ship.

**Q: "What's next?"**
> A: GitHub-issue ingestion adapter, Hunter wired to `bandit` and `semgrep`, and an eval harness with synthetic fixtures. The enterprise wedge is the audit trail — we already have the signal, we need the UI.
