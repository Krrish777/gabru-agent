# 02 — Architecture

## Bird's-eye view

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  USER                                                                        │
│    ├── types a task in Claude Code         (MCP mode  — live demo path)      │
│    ├── runs `gabru --task "..."`           (CLI mode  — single-agent loop)   │
│    └── runs `gabru-pipeline "..."`         (Pipeline mode — Coder→Tester→    │
│                                                            Hunter on OR)     │
│                                                                              │
└─────────┬────────────────────────┬───────────────────────┬───────────────────┘
          │                        │                       │
   ┌──────▼──────┐          ┌──────▼──────┐         ┌──────▼──────┐
   │ mcp_serve.py│          │ run_agent.py│         │orchestrator │
   │ MCP stdio   │          │ AIAgent loop│         │ .run_pipeline│
   │ (the client │          │ OpenRouter  │         │ (3x AIAgent)│
   │  IS the LLM)│          │ client      │         │              │
   └──────┬──────┘          └──────┬──────┘         └──────┬──────┘
          │                        │                       │
          └────────────┬───────────┴───────────┬───────────┘
                       │                       │
                ┌──────▼──────┐          ┌─────▼─────┐
                │model_tools  │◀─────────│ toolsets  │
                │  .discover  │ filters  │  .py      │
                │ _builtin    │ tool list│  (bundles)│
                │  _tools()   │ by role  │           │
                └──────┬──────┘          └───────────┘
                       │
                ┌──────▼──────────────────────────────┐
                │  tools/registry.py                  │
                │  ─ register(name, schema, handler)  │
                │  ─ dispatch(name, args) → JSON str  │
                │  ─ get_schema / get_all_tool_names  │
                │  ─ check_tool_availability          │
                └──────┬──────────────────────────────┘
                       │ (AST-scanned at import time)
         ┌─────────────┼──────────────────┬───────────────┐
         │             │                  │               │
    file_operations  terminal_tool   code_execution   osv_check
    read/write/      terminal +      sandbox Python   CVE scan
    patch/search     process         (nsjail/local)
                                                          ...
         │             │                  │               │
         ▼             ▼                  ▼               ▼
    tools/environments/local.py  (concrete execution backend)
    or external shell / HTTP / MCP upstream
```

## The five layers

### L1 — Host

Whoever drives the LLM. Three variants in v1:

| Host | File | Who is the model? | When it matters |
|---|---|---|---|
| CLI agent | `run_agent.py` → `AIAgent` class | OpenRouter-routed (usually `anthropic/claude-sonnet-4.5`) | Automated runs, CI, batch jobs |
| 3-agent pipeline | `orchestrator.py` → `run_pipeline()` | Three sequential OpenRouter sessions, one per role | Non-interactive end-to-end runs |
| MCP stdio server | `mcp_serve.py` | Whatever MCP client connects (Claude Code, Claude Desktop, Cursor, Codex) | On-stage demo, IDE integration |

A tool added once appears in all three hosts. The hosts are not aware of specific tools; they interrogate the registry.

### L2 — Conversation loop (CLI / Pipeline only)

`run_agent.AIAgent` is the core loop. Responsibilities:

- Build system prompt (`agent/prompt_builder.py`)
- Maintain message history, auto-compress when near token limit (`agent/context_compressor.py`)
- Call OpenRouter via `openai` SDK with an OpenAI-compatible interface
- When the model emits tool_calls → dispatch through the registry, attach tool_results, continue until a final text reply
- On Claude slugs (`anthropic/*`) pass Anthropic prompt-cache markers through (`agent/prompt_caching.py`)
- Classify provider errors + exponential backoff (`agent/retry_utils.py`, `agent/error_classifier.py`)
- Persist memory if not `skip_memory=True` (`agent/memory_manager.py`)

In MCP mode **this loop does not run**. The MCP client drives each tool call itself.

### L3 — Tool orchestration

| Module | Role |
|---|---|
| `model_tools.py` | `discover_builtin_tools()` AST-scans `tools/*.py` for top-level `registry.register(...)` calls and imports each hit. Also schemas collection, OpenAI-format conversion, tool-call argument validation helpers. |
| `toolsets.py` | Named bundles (`file`, `web`, `terminal`, `browser`, `pipeline`, `rl`, …). Roles reference bundle names so that per-role allow-lists stay small and composable. |
| `agents/{coder,tester,hunter}.py` | Role-specific `*_TOOLS: List[str]` that narrows the registry surface the role sees. Coder has no `osv_check`; Hunter has no `write_file`; Tester has no vuln scanners. |

### L4 — Registry

`tools/registry.py` is the single registration point.

```python
registry.register(
    name="read_file",
    toolset="file",
    schema={...},            # OpenAI function-calling JSON schema
    handler=_handle_read,    # sync, returns json.dumps({...})
    check_fn=_available,     # optional — returns False to hide the tool
    emoji="📄",
    description="...",
)
```

Invariants:
- Handlers are **synchronous** and return a **JSON-string**. MCP server wraps them via `asyncio.to_thread`.
- `check_fn` lets tools gate themselves on runtime conditions (e.g. `ha_*` tools are hidden unless `HASS_TOKEN` is set).
- Two tools — `memory` and `todo` — receive a per-process `store` singleton via `_STORE_INJECTORS` in `mcp_serve.py`; every other tool is pure-function.

### L5 — Tool implementations

Around 40 files in `tools/`. Grouped by concern:

| Group | Tools | Notes |
|---|---|---|
| **File ops** | `read_file`, `write_file`, `patch`, `search_files` | `search_files` uses `ripgrep` on Unix; Windows SKIP without `rg` on PATH |
| **Execution** | `terminal`, `process`, `execute_code` | `execute_code` Windows-gated (platform check inside the tool) |
| **Code safety / audit** | `osv_check` (OSV.dev CVE API), `tirith_security` (static analysis), `url_safety`, `path_security`, `file_safety`, `skills_guard` | Hunter's primary toolkit |
| **Delegation** | `delegate_task`, `mixture_of_agents`, `pipeline_tool` | `delegate_task` already has ACP subprocess plumbing (`claude --acp --stdio`) for a future Approach-B upgrade |
| **Memory / planning** | `memory_tool`, `todo_tool`, `session_search_tool` | Memory backed by `gabru_state` SQLite + FTS5 |
| **Skills** | `skills_tool`, `skill_manager_tool`, `skills_hub`, `skills_sync`, `skills_guard` | Procedural-memory packs in `skills/` and `optional-skills/` |
| **Clarification / UX** | `clarify_tool`, `interrupt`, `approval` | Agent-initiated user questions; human-in-the-loop escapes |
| **RL** | `rl_training_tool` (9 sub-tools) | Reinforcement-learning orchestration (Tinker-Atropos); off-demo path |
| **Web** | `web_tools` (web_search, web_extract) | Gated on Firecrawl availability |
| **Pipeline manifest** | `pipeline_tool` → `get_pipeline_stages` | The manifest-returning MCP tool; **load-bearing for the live demo** |

## State & paths

| Concern | Mechanism |
|---|---|
| Install-global state | `~/.gabru` by default, overridable via `GABRU_HOME` env var. Always access via `gabru_constants.get_gabru_home()`. |
| Session DB | `gabru_state.py` — SQLite with FTS5 for full-text search over history |
| Secrets | `.env` file, `python-dotenv` at CLI start; `agent/credential_pool.py` + `agent/credential_sources.py` hold the routing |
| Memory | Persistent across sessions, stored under GABRU_HOME; tests autouse a tmp GABRU_HOME in `tests/conftest.py` |
| Prompt cache | Anthropic cache_control markers passed through OpenRouter on `anthropic/*` slugs (`agent/prompt_caching.py`) |

## The conversation-loop internals (CLI mode)

Heavy lifting in `run_agent.AIAgent` is split across `agent/` modules:

| File | Purpose |
|---|---|
| `agent/prompt_builder.py` | Assembles system prompt from: role prompt + memories + skills + context files |
| `agent/context_compressor.py` | Auto-halves the conversation when nearing the provider's token limit. Regression-tested in `tests/test_ctx_halving_fix.py` |
| `agent/prompt_caching.py` | Injects Anthropic `cache_control` markers into system + recent messages on `anthropic/*` slugs |
| `agent/memory_manager.py` | Persistent memory read/write, backed by `gabru_state.py` |
| `agent/retry_utils.py` + `agent/error_classifier.py` | Provider-error classification (rate limit vs. 5xx vs. bad-request) and exponential backoff |
| `agent/model_metadata.py`, `agent/models_dev.py` | Model-capability lookup (context length, tool-use support, pricing) |
| `agent/display.py`, `agent/insights.py`, `agent/trajectory.py` | Terminal rendering and trace capture |
| `agent/auxiliary_client.py` + `agent/transports/` | OpenRouter HTTP client, Anthropic-native transport (prompt caching) |

## Path isolation (non-negotiable)

```python
# DO
from gabru_constants import get_gabru_home
path = get_gabru_home() / "memory.db"

# DON'T
path = Path.home() / ".gabru" / "memory.db"   # breaks profile isolation
```

`tests/conftest.py` installs an autouse fixture that redirects `GABRU_HOME` to a tmp dir. **Tests must never touch the real home dir.** The fixture enforces this; it's not left to convention.

## What this architecture buys us

1. **A tool added once works everywhere.** Write a new file op in `tools/`; it's live in CLI, pipeline, and MCP mode without a single import line edit.
2. **Role isolation is a data structure, not a prompt.** `CODER_TOOLS`, `TESTER_TOOLS`, `HUNTER_TOOLS` are plain lists. The orchestrator filters the registry down to that list per role.
3. **MCP mode makes the host irrelevant.** Any MCP-capable LLM (Claude, GPT, Gemini via its MCP bridge) can drive Gabru. We're not married to OpenRouter in that mode.
4. **Manifest pattern buys us the live demo.** `get_pipeline_stages` returns pure data — judges see it come back, watch the stages run — without us running N× LLM calls on our dime.
