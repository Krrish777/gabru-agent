# Gabru-Agent

**G.A.B.R.U.** — **G**enerative **A**gent for **B**uild, **R**eview & **U**nit-test.

Gabru-Agent is a specialized multi-agent system for autonomous software
engineering. A **Coder** agent writes code, a **Tester** agent writes unit
tests, and a **Vuln-Hunter** agent searches for edge cases and security
issues. Together they take a task description (typically a GitHub issue)
and produce a tested, security-reviewed change.

## Three modes

Gabru runs in three modes from the same tool registry:

```bash
# 1. Single-agent CLI — OpenRouter-backed, drives its own tool loop
gabru --task "write a fibonacci function in python and save it to /tmp/fib.py"

# 2. Three-agent pipeline — Coder -> Tester -> Vuln-Hunter, sequential
gabru-pipeline "Add reverse_str(s) to utils.py that reverses a string."

# 3. MCP stdio server — Claude Code (or any MCP client) is the model
gabru mcp-serve
```

## Status

Foundation + scaffolded 3-agent pipeline. Currently:

- **Foundation**: stripped tool registry (26 tools), OpenRouter-backed
  single-agent runtime, MCP server mode, SQLite+FTS5 session DB, pruned
  skills system, bundled skill packs (software-development, github,
  red-teaming, devops, mcp, security).
- **3-agent pipeline**: `agents.coder`, `agents.tester`, `agents.hunter`
  with role-specific system prompts and tool bundles, composed by a
  sequential `orchestrator.run_pipeline()`. Ships working.
- **On the roadmap**: GitHub-issue ingestion adapter, Hunter wired to
  OSV/semgrep/bandit/tirith, eval harness with synthetic fixtures, a
  frontend UI.

Senior-QA acceptance: 42/45 checks pass (3 SKIP on Windows without
ripgrep). See [`QA_COVERAGE_REPORT.md`](./QA_COVERAGE_REPORT.md) for
the white-box + black-box breakdown.

## Install

```bash
git clone <this-repo> gabru-agent
cd gabru-agent
uv venv .venv --python 3.11
source .venv/bin/activate     # Windows: .venv\Scripts\activate
uv pip install -e ".[dev,mcp]"
cp .env.example .env          # then paste your OpenRouter key
```

## Connect to Claude Code (MCP mode)

```bash
claude mcp add gabru -s user -- /path/to/.venv/bin/gabru mcp-serve
```

All 26 tools show up in your next Claude Code session.

## Run the senior-QA harness

```bash
python scripts/gabru_qa.py
```

The harness drives `gabru mcp-serve` over stdio and asserts:
- schema integrity of every registered tool
- required-args enforcement + malformed-args handling
- unknown-tool clean error
- Coder role (write + run + read)
- Tester role (write test + run pytest + parse pass/fail signal)
- Vuln-Hunter role (write + search + read)
- Patch round-trip
- Memory, todo, skills_list functional round-trips

## Layout

```
gabru-agent/
├── run_agent.py         # AIAgent — core conversation loop (CLI mode)
├── mcp_serve.py         # MCP stdio server — tool registry over stdio
├── orchestrator.py      # Coder -> Tester -> Hunter pipeline
├── agents/              # role-specific prompts + factories
│   ├── coder.py
│   ├── tester.py
│   └── hunter.py
├── model_tools.py       # tool orchestration layer
├── toolsets.py          # toolset groupings
├── tools/               # self-registering tool implementations (~40 files)
├── agent/               # context, prompt, memory, retry internals
├── gabru_cli/           # CLI subcommands + setup
├── skills/              # bundled skill packs
└── scripts/
    ├── gabru_qa.py      # senior-QA harness (white-box + black-box)
    ├── mcp_e2e.py       # lighter-weight workflow harness
    └── run_tests.sh     # CI-parity pytest wrapper
```

## License

MIT. Portions derived from [Hermes Agent](https://github.com/NousResearch/hermes-agent)
(MIT, Copyright © Nous Research). See `LICENSE` and `NOTICE` for details.
