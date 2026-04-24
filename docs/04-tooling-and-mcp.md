# 04 — Tooling & MCP Surface

## The registry is the spine

Every capability Gabru exposes — file ops, shell, search, security scans, memory, the pipeline manifest itself — is a **registered tool**. Nothing is special-cased. The registry (`tools/registry.py`) is the single source of truth; every host (CLI, pipeline, MCP server) reads from it.

## The full tool inventory

Tools exposed over `gabru mcp-serve`, initialized protocol `2025-11-25` — **26 tools** as of QA. Grouped for legibility:

### File ops

| Tool | Description |
|---|---|
| `read_file` | Read file contents. Idempotent; second read returns a dedup marker (see QA W6). |
| `write_file` | Write or overwrite a file. Required-args enforced (QA W2). |
| `patch` | Fuzzy find-and-replace with conflict detection. Verified on-disk (QA B4). |
| `search_files` | Content + filename search. Uses `ripgrep` on Unix. Windows SKIPs without `rg` on PATH. |

### Execution

| Tool | Description |
|---|---|
| `terminal` | Shell command execution. Used by Coder for sanity runs, Tester for `pytest`, Hunter for ad-hoc scans. |
| `process` | Background process management (start / list / kill / read output). |
| `execute_code` | Python code sandbox. Windows-gated (platform check inside the tool); passes on Linux. |

### Security + audit (Hunter's toolkit)

| Tool | Description |
|---|---|
| `osv_check` | OSV.dev CVE lookups for a package@version. |
| `tirith_security` | Static security analysis wrapper. |
| `url_safety` | URL reputation / safelist gate (used inside web tools). |
| `path_security` | Path-traversal sanitiser (used inside file ops). |
| `file_safety` | Size / type gates for write operations. |
| `skills_guard` | Blocks malicious skill imports. |

### Delegation + orchestration

| Tool | Description |
|---|---|
| `delegate_task` | Spawn a subagent (ACP subprocess plumbing present for future Approach-B). |
| `mixture_of_agents` | Multi-agent primitive (roadmap — eventual source of a more ambitious orchestrator v2). |
| `get_pipeline_stages` | **The manifest-returning tool for the on-stage demo.** See [`03-agent-pipeline.md`](03-agent-pipeline.md). |

### State + planning

| Tool | Description |
|---|---|
| `memory` | Persistent memory (add / list / search). Backed by `gabru_state.py`. QA-verified. |
| `todo` | Per-session todo list. QA-verified. |
| `session_search` | FTS5 search over past sessions. |

### Skills (procedural memory)

| Tool | Description |
|---|---|
| `skills_list` | Enumerate bundled skill packs. |
| `skill_view` | Load a skill's prose into the current turn. |
| `skill_manage` | Create/edit/delete skills. |

### Clarification + human-in-the-loop

| Tool | Description |
|---|---|
| `clarify` | Agent-initiated question to the user (used by Coder when task is ambiguous, per its system prompt). |
| `interrupt` | Emergency break from a long operation. |
| `approval` | Human approval gate for destructive actions. |

### RL (off-demo)

| Tool | Description |
|---|---|
| `rl_list_environments`, `rl_select_environment`, `rl_get_current_config`, `rl_edit_config`, `rl_start_training`, `rl_check_status`, `rl_stop_training`, `rl_get_results`, `rl_list_runs`, `rl_test_inference` | Tinker-Atropos RL orchestration. Schema-checked in QA; not exercised by demo. |

### Web (availability-gated)

| Tool | Description |
|---|---|
| `web_search` / `web_extract` | Firecrawl-backed. Hidden if Firecrawl isn't configured — not a code bug, per user direction production ships with Firecrawl. |

## How a tool is added

1. Create `tools/my_tool.py`.
2. Define a sync handler returning `json.dumps({...})`.
3. Call `registry.register(name=..., toolset=..., schema=..., handler=..., check_fn=...)` at module top level.
4. Add to a toolset in `toolsets.py` (and to a role's `*_TOOLS` in `agents/*.py` if role-scoped).
5. Write a test under `tests/tools/test_my_tool.py`.

Auto-discovery: `model_tools.discover_builtin_tools()` AST-scans `tools/` for top-level `registry.register(...)` calls and imports every hit. **No manual import list to maintain.**

## MCP server (`mcp_serve.py`)

### Initialization

```
client (Claude Code)   →  spawns `gabru mcp-serve`  →  stdio handshake (protocol 2025-11-25)
client sends initialize  →  server lists 26 tools  →  ready
```

Key invariants:
- **stdout is the MCP transport** — logs go to stderr only (line-by-line enforced in `main()`).
- **handlers run in a thread** — `asyncio.to_thread(_call)` keeps the event loop responsive while synchronous handlers execute.
- **store injection** — `memory` and `todo` receive a per-process `MemoryStore` / `TodoStore` singleton via `_STORE_INJECTORS`.
- **unknown tools** — return `{"error": "Unknown tool: <name>"}` cleanly (QA W4).

### Schema conversion

Registry schemas are OpenAI function-calling shape:
```
{"name": "...", "description": "...", "parameters": {"type": "object", "properties": {...}, "required": [...]}}
```
`_tool_schema_to_mcp` converts to `mcp.types.Tool(name, description, inputSchema)`. An older wrapper form (`{"type": "function", "function": {...}}`) is unwrapped for compatibility.

### Install to Claude Code

```bash
claude mcp add gabru -s user -- /abs/path/.venv/bin/gabru mcp-serve
```

On next Claude Code session, every gabru tool is exposed as `mcp__gabru__<tool>`.

## Toolsets (`toolsets.py`)

Named groups, composable via `includes`:

| Toolset | Tools |
|---|---|
| `file` | read_file, write_file, patch, search_files |
| `terminal` | terminal, process |
| `web` | web_search, web_extract |
| `search` | web_search (only) |
| `vision` | vision_analyze |
| `image_gen` | image_generate |
| `browser` | 11 browser_* tools + web_search |
| `skills` | skills_list, skill_view, skill_manage |
| `moa` | mixture_of_agents |
| `cronjob` | cronjob |
| `messaging` | send_message |
| `rl` | 10 rl_* tools |
| **`pipeline`** | **get_pipeline_stages** |

Role allow-lists (`CODER_TOOLS` / `TESTER_TOOLS` / `HUNTER_TOOLS`) reference tool names directly — not toolsets — because roles intentionally pick from *across* bundles (e.g. Hunter pulls `search_files` from `file` and `osv_check` from nowhere-else). This is the right granularity for role discipline.

## Skill packs (procedural memory)

Bundled under `skills/`:

| Pack | Theme |
|---|---|
| `software-development/` | General coding tasks, git workflows, PR etiquette |
| `github/` | Issue/PR ingestion, label semantics |
| `red-teaming/` | Adversarial review patterns (Hunter's implicit knowledge base) |
| `devops/` | Deploy, infra, CI/CD |
| `mcp/` | Building MCP servers/clients |
| `index-cache/` | Skill indexing cache files |

Plus `optional-skills/security` and `optional-skills/mcp` for opt-in packs. Skills differ from tools: a tool is executable; a skill is prose loaded into the system prompt when relevant.

## The `gabru_cli` subcommand layer

`gabru_cli/main.py` + `commands.py` resolves the top-level CLI surface:

| Command | Impl |
|---|---|
| `gabru --task "..."` | `run_agent.AIAgent` synchronous loop |
| `gabru-pipeline "..."` | `orchestrator.main()` — Coder → Tester → Hunter sequential |
| `gabru mcp-serve` | `mcp_serve.main()` — MCP stdio server |
| `gabru-mcp` | Alias for `mcp_serve:main` |

Slash commands in-session are also routed through `commands.py` (see `resolve_command()` + `CommandDef`).

## What the MCP surface looks like from the Claude Code side

```
Claude Code MCP panel:
  gabru
    mcp__gabru__read_file
    mcp__gabru__write_file
    mcp__gabru__patch
    mcp__gabru__search_files
    mcp__gabru__terminal
    mcp__gabru__process
    mcp__gabru__execute_code
    mcp__gabru__osv_check
    mcp__gabru__tirith_security
    mcp__gabru__get_pipeline_stages   ← the manifest tool
    mcp__gabru__memory
    mcp__gabru__todo
    mcp__gabru__skills_list
    mcp__gabru__skill_view
    mcp__gabru__skill_manage
    mcp__gabru__session_search
    mcp__gabru__clarify
    mcp__gabru__delegate_task
    mcp__gabru__mixture_of_agents
    mcp__gabru__rl_*   (9 tools)
```

Judges can literally see this list in Claude Code's tool picker. That's part of what makes the demo credible: the pipeline isn't a black box; it's a well-labeled surface.
