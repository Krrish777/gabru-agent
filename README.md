# Gabru-Agent

**G.A.B.R.U.** — **G**enerative **A**gent for **B**uild, **R**eview & **U**nit-test.

Gabru-Agent is a specialized multi-agent system for autonomous software
engineering. A **Coder** agent writes code, a **Tester** agent writes unit
tests, and a **Vuln-Hunter** agent searches for edge cases and security
issues. Together they take a GitHub issue and produce a tested,
security-reviewed change.

This repository currently contains the **foundation**: a single-agent
runtime with tool-calling, session persistence, a pruned skills system,
MCP support, and an OpenRouter-backed LLM client. The three specialized
agents and their orchestrator are built on top of this foundation.

## Status

Early-stage. Foundation is stripped and runnable; Coder / Tester /
Vuln-Hunter agents are on the roadmap.

## Install

```bash
git clone <this-repo> gabru-agent
cd gabru-agent
uv venv venv --python 3.11
source venv/bin/activate     # Windows: venv\Scripts\activate
uv pip install -e ".[dev]"
cp .env.example .env         # then paste your OpenRouter key
```

## Quickstart

```bash
gabru --task "write a fibonacci function in python and save it to /tmp/fib.py"
```

## Roadmap

1. **Coder agent** — reads a GitHub issue, writes the change.
2. **Tester agent** — writes unit tests against the Coder's change.
3. **Vuln-Hunter agent** — LLM reasoning + static tools (bandit, semgrep, OSV) on the change.
4. **Orchestrator** — sequential Coder → Tester → Hunter pipeline (adapted from the retained mixture-of-agents primitive).
5. **Eval harness** — 5–10 synthetic issue fixtures with LLM-judge scoring.
6. **Web UI** — designed last.

## License

MIT. Portions derived from [Hermes Agent](https://github.com/NousResearch/hermes-agent)
(MIT, Copyright © Nous Research). See `LICENSE` and `NOTICE` for details.
