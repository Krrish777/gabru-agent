"""Gabru-Agent CLI entry point.

Two modes, both backed by the same tool registry:

    gabru --task "..."    single-agent OpenRouter-backed run, prints final answer
    gabru mcp-serve       launches the MCP stdio server (delegates to mcp_serve.main)

This is intentionally thin. The heavy surface (subcommands for setup wizards,
skill management, gateway control, OAuth flows, etc.) that the upstream
project shipped has been removed. Add new subcommands by extending the
argparse tree below.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Optional

__version__ = "0.1.0"
__release_date__ = "2026-04-21"


DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL_ENV = "GABRU_DEFAULT_MODEL"
DEFAULT_MODEL_FALLBACK = "anthropic/claude-sonnet-4.5"


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    level_env = os.environ.get("GABRU_LOG_LEVEL")
    if level_env:
        level = getattr(logging, level_env.upper(), level)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _load_dotenv() -> None:
    """Best-effort .env load from ~/.gabru/.env and ./"""
    try:
        from gabru_cli.env_loader import load_gabru_dotenv
        from gabru_constants import get_gabru_home
    except Exception:
        return
    try:
        load_gabru_dotenv(gabru_home=get_gabru_home(), project_env=Path.cwd() / ".env")
    except Exception as exc:
        logging.getLogger(__name__).debug("dotenv load skipped: %s", exc)


def _resolve_api_key(args: argparse.Namespace) -> str:
    key = args.api_key or os.environ.get("OPENROUTER_API_KEY") or ""
    if not key:
        sys.stderr.write(
            "error: no OpenRouter API key found.\n"
            "Set OPENROUTER_API_KEY in your environment (or ~/.gabru/.env), "
            "or pass --api-key. See .env.example for the expected file layout.\n"
        )
        raise SystemExit(2)
    return key


def _resolve_model(args: argparse.Namespace) -> str:
    return (
        args.model
        or os.environ.get(DEFAULT_MODEL_ENV)
        or DEFAULT_MODEL_FALLBACK
    )


def _run_task(args: argparse.Namespace) -> int:
    _load_dotenv()
    api_key = _resolve_api_key(args)
    model = _resolve_model(args)
    base_url = args.base_url or DEFAULT_BASE_URL

    # Lazy import — heavy module, costs seconds on first load.
    from run_agent import AIAgent

    agent = AIAgent(
        base_url=base_url,
        api_key=api_key,
        model=model,
        max_iterations=args.max_iterations,
        quiet_mode=not args.verbose,
        skip_memory=args.no_memory,
        skip_context_files=args.no_context,
    )
    reply = agent.chat(args.task)
    sys.stdout.write(reply)
    if not reply.endswith("\n"):
        sys.stdout.write("\n")
    return 0


def _run_mcp_serve(args: argparse.Namespace) -> int:
    _load_dotenv()
    # Lazy import so `gabru --help` doesn't pay the MCP dependency cost.
    import mcp_serve

    if hasattr(mcp_serve, "main"):
        return mcp_serve.main() or 0
    if hasattr(mcp_serve, "serve"):
        return mcp_serve.serve() or 0
    sys.stderr.write(
        "error: mcp_serve module is present but has no main()/serve() entry.\n"
    )
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gabru",
        description=(
            "Gabru-Agent - Generative Agent for Build, Review & Unit-test. "
            "Run as a single-agent CLI (--task) or as an MCP stdio server (mcp-serve)."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"gabru {__version__} ({__release_date__})"
    )
    parser.add_argument(
        "--task",
        metavar="PROMPT",
        help="Run a single-shot task against the OpenRouter-backed agent and print the reply.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=f"LLM slug (default: ${DEFAULT_MODEL_ENV} or {DEFAULT_MODEL_FALLBACK}).",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="OpenRouter API key (default: $OPENROUTER_API_KEY from env or .env).",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help=f"OpenAI-compatible base URL (default: {DEFAULT_BASE_URL}).",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=30,
        help="Max tool-calling iterations per task (default: 30).",
    )
    parser.add_argument(
        "--no-memory",
        action="store_true",
        help="Skip persistent memory injection for this run.",
    )
    parser.add_argument(
        "--no-context",
        action="store_true",
        help="Skip context-file injection for this run.",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Verbose logging + agent tool output."
    )

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.add_parser(
        "mcp-serve",
        help="Start the MCP stdio server exposing Gabru's tool registry.",
    )

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    if args.command == "mcp-serve":
        return _run_mcp_serve(args)
    if args.task:
        return _run_task(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
