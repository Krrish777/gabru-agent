# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> Read `AGENTS.md` for the full development guide. This file is the fast-lane summary plus rules unique to working with Claude Code in this repo.

## What this project is

**Gabru-Agent** — Generative Agent for Build, Review & Unit-test. A specialized multi-agent system for autonomous software engineering, derived from Hermes Agent (Nous Research, MIT). Three run modes share a single tool registry:

1. **CLI agent** (`gabru --task "..."`) — `run_agent.py` drives a synchronous tool loop against OpenRouter.
2. **3-agent pipeline** (`gabru-pipeline "..."`) — `orchestrator.run_pipeline()` runs Coder → Tester → Hunter sequentially, chaining each stage's reply into the next stage's context.
3. **MCP stdio server** (`gabru mcp-serve`) — `mcp_serve.py` exposes the same registry over MCP; the connecting client (Claude Code, Claude Desktop, Cursor, etc.) IS the model. No Python-side LLM loop.

A tool added once shows up in all three modes via `tools/registry.py`.

## Common commands

```bash
# Setup
uv venv .venv --python 3.11
source .venv/bin/activate            # Windows: .venv\Scripts\activate
uv pip install -e ".[dev,mcp]"
cp .env.example .env                 # paste OPENROUTER_API_KEY

# Run
gabru --task "..."                   # single-agent CLI
gabru-pipeline "..."                 # Coder -> Tester -> Hunter
gabru mcp-serve                      # MCP stdio server

# Tests — ALWAYS prefer the wrapper, not raw pytest
scripts/run_tests.sh                                       # full suite, hermetic env
scripts/run_tests.sh tests/agent/                          # one directory
scripts/run_tests.sh tests/tools/test_file_ops.py -v       # one file
scripts/run_tests.sh tests/test_mcp_serve.py::test_x       # one test
python -m pytest tests/ -q -n 4                            # raw pytest (only if wrapper unavailable)

# Lint / format
ruff check .
ruff format .

# QA harnesses (drive mcp-serve over stdio end-to-end)
python scripts/gabru_qa.py           # senior-QA harness, 45 checks
python scripts/mcp_e2e.py            # lighter workflow harness
```

`scripts/run_tests.sh` is the **canonical** test command. It pins `-n 4` xdist workers (CI parity, prevents flakes that only appear with `-n auto` on multi-core workstations), sets `TZ=UTC LANG=C.UTF-8 PYTHONHASHSEED=0`, blanks every credential-shaped env var, and overrides `pyproject.toml`'s `addopts`. Raw `pytest` skips this hardening.

## Architecture: the bits that need multiple files to understand

### Shared tool registry (the load-bearing abstraction)

`tools/registry.py` is the central registry. Each `tools/*.py` calls `registry.register(name, toolset, schema, handler, check_fn)` at import time — schema is OpenAI function-calling format, handler returns a JSON string. `model_tools.discover_builtin_tools()` AST-scans `tools/` for top-level `registry.register(...)` calls and imports each matching module. There is **no manual import list**.

- `run_agent.py` (CLI mode) calls handlers from inside the OpenRouter tool loop.
- `mcp_serve.py` (MCP mode) wraps the same handlers as MCP tools.
- A handler with CLI-only side effects breaks MCP mode silently. Handlers must be self-contained.

`toolsets.py` groups tool names into composable bundles (`web`, `search`, etc.) for role-specific filtering.

### 3-agent pipeline

`orchestrator.run_pipeline()` runs three `AIAgent` instances back-to-back. Each role module under `agents/` declares:

- `*_SYSTEM_PROMPT` — role-specific operating principles (Coder: "do not write tests"; Hunter: "do not fix what you find").
- `*_TOOLS: List[str]` — the filtered subset of tool names that role gets, so the model isn't distracted by irrelevant tools (e.g. Coder doesn't see `osv_check`; Hunter doesn't see `write_file`).
- A dataclass factory (`CoderAgent`, `TesterAgent`, `HunterAgent`) that lazy-imports `run_agent.AIAgent` and constructs it with the role prompt + `skip_memory=True, skip_context_files=True`.

The orchestrator chains: Tester sees `task + coder_reply`; Hunter sees `task + coder_reply + tester_reply`. Each station crash is caught and recorded; `PipelineResult.ok` is False if any station errored. No retry/escalation logic in v1.

### Conversation-loop internals

Heavy lifting in `run_agent.py:AIAgent` is split across `agent/`:
- `prompt_builder.py` — system prompt assembly (memories, skills, context files)
- `context_compressor.py` — auto-halve conversation when nearing token limits (`test_ctx_halving_fix.py`)
- `prompt_caching.py` — Anthropic prompt-cache passthrough on OpenRouter `anthropic/*` slugs
- `memory_manager.py` — persistent memory backed by `gabru_state.py` (SQLite + FTS5)
- `retry_utils.py` — provider error classification + exponential backoff

### Path / state isolation

`gabru_constants.get_gabru_home()` resolves the `GABRU_HOME` env var (default `~/.gabru`). **Always use it** — never hardcode `~/.gabru` paths. `tests/conftest.py` autouses a fixture that redirects `GABRU_HOME` to a tmp dir; tests must never touch the real home dir, and this is enforced by the fixture, not just convention.

## Hard rules (from AGENTS.md, summarized)

1. **OpenRouter only** in CLI mode. Do not re-add Anthropic / Gemini / Bedrock / Mistral / Codex / Copilot / Nous-Portal adapters. For Claude, use OpenRouter `anthropic/*` slugs.
2. **Use `get_gabru_home()`** for code paths and `display_gabru_home()` for user-facing strings.
3. **Preserve upstream attribution** in `LICENSE` and `NOTICE` (Hermes Agent, Nous Research, MIT).
4. **Tools self-register** via `registry.register()` at module import time — no manual registration step.
5. **Both modes share the registry** — every tool must work in CLI and MCP mode.

## Adding a tool

1. Create `tools/my_tool.py` with a handler returning `json.dumps({...})`.
2. Call `registry.register(name=..., toolset=..., schema=..., handler=..., check_fn=...)` at module top level.
3. Add the tool name to the relevant bundle in `toolsets.py` (and to a role's `*_TOOLS` list in `agents/*.py` if it should be visible to that role).
4. Write a test under `tests/tools/test_my_tool.py`.

## QA & status

The senior-QA harness (`scripts/gabru_qa.py`) drives `gabru mcp-serve` over stdio and asserts schema integrity, required-args enforcement, malformed-args handling, role-flow coverage (Coder write+run+read, Tester write+pytest+parse, Hunter write+search+read), patch round-trip, and memory/todo/skills round-trips. Current state: 42/45 pass (3 SKIP on Windows without ripgrep). See `QA_COVERAGE_REPORT.md`.

## When acting as the Gabru-Agent executor (MCP mode)

When this project's `mcp__gabru__*` tools are connected and the user asks you to **write to this repository** (create files, edit files, apply a patch, run a build task), you MUST drive the work through the Gabru pipeline manifest:

1. Call `mcp__gabru__get_pipeline_stages(task=<user's request verbatim>)` first. Let the raw JSON tool result render in the transcript — that's the proof Gabru owns the plan.
2. Execute the returned stages in order. For each stage:
   - Announce it as `## Stage N: <Role> — <intent>` in the chat.
   - Adopt the stage's `system_prompt` as your operating principles for that stage only.
   - Call ONLY the `mcp__gabru__<tool>` names listed in the stage's `gabru_tools`. This is how role isolation is enforced — violating it defeats the pipeline.
   - Record wall-clock seconds, capture a 3–4 line summary at the end of the stage, and substitute it into the next stage's `{coder_output}` / `{tester_output}` placeholders.
3. After Stage 3, if Hunter reports one or more `HIGH`-severity findings AND `loop_count < manifest.remediation.max_loops` (default 2), run the remediation loop: re-invoke Coder under `remediation.context_template` (filling `{hunter_findings}` with the HIGH subset), then Tester, then Hunter again.
4. On any stage exception or unrecoverable failure, halt the pipeline — emit a Markdown error block naming the failed stage and skip later stages. Do not silently continue.
5. End with a `# Gabru-Agent Pipeline Report` heading and one `## Stage N — <Role> (Xs)` subsection per stage (including any remediation iterations), in chat only. No side-file artifacts.

Read-only tasks (explain, summarize, question, code walkthrough) bypass the pipeline — answer directly using `mcp__gabru__read_file` / `mcp__gabru__search_files`.
