# Gabru-Agent — Development Guide

Instructions for AI coding assistants and humans working on this repo.

## Identity

**Gabru-Agent** — Generative Agent for Build, Review & Unit-test.
A rebranded, substantially pruned derivative of Hermes Agent (Nous Research, MIT).
Upstream attribution lives in `LICENSE` and `NOTICE`.

## Dev setup

```bash
git clone <this-repo> gabru-agent && cd gabru-agent
uv venv venv --python 3.11
source venv/bin/activate      # Windows: venv\Scripts\activate
uv pip install -e ".[dev,mcp]"
cp .env.example .env          # paste your OPENROUTER_API_KEY
```

## Commands

```bash
gabru --help                   # CLI usage
gabru --task "..."             # OpenRouter-backed single-agent run
gabru mcp-serve                # expose the tool registry over MCP stdio

python -m pytest tests/ -q -n 4   # run the suite
ruff check .                       # lint
ruff format .                      # format
```

## Dual-mode architecture

Gabru can run as either:

1. **CLI agent (OpenRouter-backed):** `gabru --task "..."` drives the synchronous
   agent loop in `run_agent.py`, using an OpenAI-compatible client pointed at
   OpenRouter. The LLM makes tool calls; the registry dispatches; the loop continues
   until a text response ends the turn.

2. **MCP server:** `gabru mcp-serve` (impl in `mcp_serve.py`) serves the same tool
   registry over MCP stdio. Any MCP client — Claude Code, Claude Desktop, Cursor,
   custom — connects and IS the model. No Python-side LLM loop in this mode;
   the client drives every tool call.

Both modes share `tools/registry.py`, so a tool written once shows up in both places.

## Project layout

```
gabru-agent/
├── run_agent.py              # AIAgent class — core conversation loop (CLI mode)
├── mcp_serve.py              # MCP server — tool registry over stdio (MCP mode)
├── model_tools.py            # Tool orchestration, discover_builtin_tools()
├── toolsets.py               # Toolset groupings + presets
├── gabru_state.py            # SQLite session DB with FTS5
├── gabru_constants.py        # Paths, env vars, base URLs
├── gabru_logging.py          # Logger config
├── gabru_time.py             # Timezone helpers
├── agent/                    # Context, prompt, memory, retry, display internals
│   ├── prompt_builder.py         # System prompt assembly
│   ├── context_compressor.py     # Auto compression near token limits
│   ├── prompt_caching.py         # Anthropic prompt caching passthrough
│   ├── memory_manager.py         # Persistent memory
│   └── ...
├── tools/                    # Self-registering tools (one file per tool)
│   ├── registry.py               # Central registry — register/dispatch/schemas
│   ├── file_operations.py        # read_file, write_file, patch, search
│   ├── terminal_tool.py          # Terminal execution
│   ├── code_execution_tool.py    # Python sandbox
│   ├── delegate_tool.py          # Subagent spawning (future 3-agent orchestrator)
│   ├── mixture_of_agents_tool.py # Multi-agent primitive (will be adapted)
│   ├── mcp_tool.py               # MCP CLIENT (for calling external MCP servers)
│   ├── osv_check.py              # CVE lookups (Vuln-Hunter)
│   ├── tirith_security.py        # Static security analysis (Vuln-Hunter)
│   ├── skills_tool.py + manager/hub/sync/guard  # Skills system
│   └── environments/local.py     # Local execution backend only
├── gabru_cli/                # CLI subcommands + setup
├── skills/                   # Bundled procedural-memory skill packs (pruned)
│   ├── software-development/ · github/ · red-teaming/ · devops/ · mcp/ · index-cache/
├── optional-skills/          # Official optional skills (pruned)
│   └── security/ · mcp/
└── tests/                    # Pytest suite (trimmed to retained surface)
```

## Hard rules

### 1. OpenRouter-only in CLI mode
The provider abstraction supports only OpenRouter (an OpenAI-compatible endpoint).
Do NOT re-add Anthropic/Gemini/Bedrock/Mistral/Codex/Copilot/Nous-Portal adapters.
If a user wants Claude, they get Claude via OpenRouter's `anthropic/*` slugs.

### 2. `GABRU_HOME` paths, not `~/.gabru` hardcoded
Use `get_gabru_home()` from `gabru_constants` for code paths. Use
`display_gabru_home()` for user-facing log/print. Hardcoding breaks profile isolation.

### 3. Preserve upstream attribution
`LICENSE` and `NOTICE` reference Hermes Agent and Nous Research. MIT requires
those notices be retained. Never scrub them.

### 4. Tools self-register
Each `tools/*.py` calls `registry.register(name, toolset, schema, handler, check_fn)`
at import time. `model_tools.py` triggers discovery. Handlers return a JSON string.

### 5. Both modes share the registry
If you add a tool, it must work in both `gabru --task` (called by the OpenRouter
loop) and `gabru mcp-serve` (called by an MCP client). Avoid CLI-only side effects
inside tool handlers.

## Adding a tool

1. Create `tools/my_tool.py`. Define a handler returning `json.dumps({...})`.
2. Call `registry.register(name=..., toolset=..., schema=..., handler=...)` at module
   top level. Schema follows OpenAI function-calling format.
3. Add the tool name to the relevant toolset in `toolsets.py`.
4. Write a test under `tests/tools/test_my_tool.py`.

Auto-discovery picks up the file. No manual import list to maintain.

## Adding a CLI flag

Slash commands and CLI flags flow from `gabru_cli/commands.py`. See the `CommandDef`
entries and `resolve_command()` pattern.

## Testing

`tests/conftest.py` redirects `GABRU_HOME` to a tmp dir via autouse fixture —
**tests must never touch `~/.gabru/`**.

```bash
python -m pytest tests/ -q -n 4                   # full suite (4 xdist workers)
python -m pytest tests/tools/test_file_ops.py -v  # one file
ruff check .                                       # lint (same rules as CI)
```

## The future: 3-agent orchestrator (roadmap)

Gabru-Agent's north star is a Coder + Tester + Vuln-Hunter pipeline driven by
GitHub issues. The single-agent runtime in `run_agent.py` is the foundation.
The orchestrator will be adapted from `tools/mixture_of_agents_tool.py`.

When implementing:
- `agents/coder.py`, `agents/tester.py`, `agents/hunter.py` — role-specific system
  prompts and tool bundles.
- `orchestrator.py` — sequential Coder → Tester → Hunter pipeline.
- Hunter wires to `osv_check`, `tirith_security`, plus `bandit` and `semgrep`
  via MCP or direct CLI.
- Eval harness: `eval/run.py` against synthetic GitHub-issue fixtures with
  LLM-judge scoring.
