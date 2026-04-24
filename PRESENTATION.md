# Gabru-Agent — Technical Presentation Master Document

> **G.A.B.R.U.** — **G**enerative **A**gent for **B**uild, **R**eview & **U**nit-test.
>
> A specialized multi-agent system for autonomous software engineering. Built for the Smart AI 2.0 / Autonomous-Dev track hackathon, derived from Hermes Agent (Nous Research, MIT).

This file is the **one-stop entry point** for technical judges. It gives the full picture in a single read and points into the `docs/` folder for deep dives.

| If you want… | Read |
|---|---|
| The 60-second elevator pitch | `presentation-content.md` (on-stage script) |
| Why we built this + market framing | [`docs/01-vision-and-business.md`](docs/01-vision-and-business.md) |
| The complete architecture | [`docs/02-architecture.md`](docs/02-architecture.md) |
| The 3-agent pipeline deep dive | [`docs/03-agent-pipeline.md`](docs/03-agent-pipeline.md) |
| The shared tool registry + MCP surface | [`docs/04-tooling-and-mcp.md`](docs/04-tooling-and-mcp.md) |
| Every architectural decision + why | [`docs/05-decisions.md`](docs/05-decisions.md) |
| QA evidence + live demo script | [`docs/06-qa-and-demo.md`](docs/06-qa-and-demo.md) |
| Roadmap + open questions | [`docs/07-roadmap.md`](docs/07-roadmap.md) |

---

## 1. What it is — in one paragraph

Gabru-Agent turns a natural-language software task into a tested, security-reviewed change. It does this by orchestrating **three specialized agent roles** — a **Coder** that writes code, a **Tester** that writes and runs pytest, and a **Vuln-Hunter** that audits for edge cases and security issues — all sharing a single tool registry that is exposed simultaneously as a CLI agent, a 3-agent pipeline, and an MCP stdio server.

## 2. The three run modes (same tools, same roles, different host)

```
┌─────────────────────────────────────────────────────────────────────────┐
│  ONE TOOL REGISTRY  (tools/registry.py — ~40 self-registering tools)    │
│   read_file · write_file · patch · search_files · terminal · process    │
│   code_execution · osv_check · tirith_security · memory · todo · …      │
└─────────────────┬───────────────────┬───────────────────────┬───────────┘
                  │                   │                       │
          ┌───────▼─────────┐  ┌──────▼──────────┐  ┌─────────▼─────────┐
          │ Mode 1          │  │ Mode 2          │  │ Mode 3            │
          │ CLI Agent       │  │ 3-Agent Pipeline│  │ MCP stdio Server  │
          │ gabru --task    │  │ gabru-pipeline  │  │ gabru mcp-serve   │
          │ (OpenRouter)    │  │ (OpenRouter x3) │  │ (Claude Code IS   │
          │                 │  │ Coder→Tester→   │  │  the model)       │
          │                 │  │  Hunter         │  │                   │
          └─────────────────┘  └─────────────────┘  └───────────────────┘
```

A tool written once works in **all three modes** — this is the single most important engineering claim we make.

## 3. The killer architectural insight (Approach C)

For the live judge demo we do **not** spin up three OpenRouter API calls. We use the **Manifest + Guided-Execution** pattern:

1. Gabru exposes one MCP tool called `get_pipeline_stages(task)` that returns a **structured JSON manifest**: three role system prompts, context chaining templates, per-role tool allow-lists, and a remediation loop contract.
2. Claude Code (the judge-facing host) calls that tool, receives the manifest, and executes each stage sequentially — calling **only the tools each role is allowed**, announcing each role transition in the transcript, and chaining output between stages.
3. Hunter emits a fenced JSON findings block; Claude parses it; if HIGH-severity findings > 0 AND loop_count < 2, the remediation loop re-runs Coder → Tester → Hunter until clean.

**Why this is the right call:**
- **Zero OpenRouter spend** during the demo — cost story on the slide.
- **Visible multi-agent story** — judges literally see the manifest come back and the three "Stage N: Role" announcements.
- **Role isolation is real, not decorative** — each stage's `gabru_tools` list is enforced; Coder genuinely cannot call `osv_check`, Hunter genuinely cannot call `write_file`.
- **Clean upgrade path** — the same manifest can later be executed by an ACP subprocess with true context isolation, without changing the manifest shape.

Full analysis of Approaches A / B / C and why C wins: see [`PIPELINE_PLAN.md`](PIPELINE_PLAN.md) and [`docs/05-decisions.md`](docs/05-decisions.md).

## 4. What we actually built (concretely)

| Layer | Files | What it does |
|---|---|---|
| **Core runtime** | `run_agent.py` (AIAgent class), `model_tools.py`, `utils.py` | Conversation loop, OpenRouter client, tool dispatch, retries, prompt caching passthrough |
| **Context & prompts** | `agent/prompt_builder.py`, `agent/context_compressor.py`, `agent/prompt_caching.py`, `agent/memory_manager.py` | System prompt assembly, auto-compression near token limits, Anthropic prompt-caching header passthrough on `anthropic/*` slugs, persistent memory |
| **Tool registry** | `tools/registry.py` + ~40 tool modules | Self-registering tools; each module calls `registry.register(name, schema, handler)` at import time. Auto-discovered via AST scan of `tools/` |
| **Toolsets** | `toolsets.py` | Composable bundles (`web`, `search`, `terminal`, `file`, `pipeline`, `browser`, `rl`, …) so roles see only what they need |
| **3-agent pipeline** | `orchestrator.py`, `agents/coder.py`, `agents/tester.py`, `agents/hunter.py` | Sequential Coder → Tester → Hunter with role-scoped system prompts + tool allow-lists; OpenRouter-backed; CLI entry `gabru-pipeline` |
| **MCP pipeline manifest** | `tools/pipeline_tool.py` | `get_pipeline_stages(task)` tool — returns the structured manifest that Claude Code executes live |
| **MCP server** | `mcp_serve.py` | Exposes the whole registry over MCP stdio; initialized protocol `2025-11-25`; 26 tools exposed |
| **CLI** | `gabru_cli/` (commands, providers, config, auth), entry `gabru` | `gabru --task`, `gabru mcp-serve`, `gabru-pipeline` |
| **State** | `gabru_state.py` | SQLite + FTS5 session/history DB |
| **Paths** | `gabru_constants.py` | `get_gabru_home()` — `GABRU_HOME` env override; tests autouse a tmp-dir override |
| **Skills** | `skills/` (bundled packs: software-development, github, red-teaming, devops, mcp, index-cache) + `optional-skills/` (security, mcp) | Procedural-memory skill packs — role-agnostic operating knowledge |
| **QA harness** | `scripts/gabru_qa.py`, `scripts/mcp_e2e.py` | Drives `gabru mcp-serve` over stdio end-to-end; 45-check senior-QA suite |
| **Tests** | `tests/` (~5,500 pytest tests) | Core runtime, tools, agents, CLI, MCP, retry, pricing, packaging |

## 5. Headline numbers (as of this commit)

- **26 tools** exposed over MCP (initialized protocol `2025-11-25`)
- **42 of 45** senior-QA checks pass (3 SKIP on Windows without `ripgrep`)
- **5,517** pytest tests collected, 0 collection errors
- **3 run modes** from one registry
- **0** external LLM calls in the on-stage demo (manifest is pure data; Claude Code is the model)
- **Remediation loop capped at 2** iterations — bounded, no infinite loops

## 6. Hard rules that shaped the codebase

1. **OpenRouter-only** in CLI mode. No Anthropic / Gemini / Bedrock / Mistral / Codex / Copilot / Nous-Portal adapters get re-added. For Claude, use OpenRouter `anthropic/*` slugs. (Rationale: one provider, one auth path, one billing story.)
2. **Use `get_gabru_home()`** everywhere — never hardcode `~/.gabru`. Tests autouse a fixture that redirects to tmp; **tests must never touch the real home dir**, and this is enforced in `tests/conftest.py`, not just by convention.
3. **Preserve upstream attribution** in `LICENSE` and `NOTICE` (Hermes Agent, Nous Research, MIT).
4. **Tools self-register** via `registry.register()` at module import — no manual import list.
5. **Both modes share the registry** — handlers must be self-contained, no CLI-only side effects.

## 7. The pitch in one line

> **"Claude is the intelligence. Gabru is the body. Neither ships without the other — and neither does real code."**

---

Detailed docs continue in [`docs/`](docs/). The on-stage script is in [`presentation-content.md`](presentation-content.md).
