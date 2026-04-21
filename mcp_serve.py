"""Gabru MCP stdio server.

Exposes Gabru-Agent's tool registry (file ops, terminal, code execution,
delegate, memory, todo, skills, session search, RL training, etc.) as MCP
tools over stdio. Any MCP client (Claude Code, Claude Desktop, Cursor,
Codex) can connect and call the tools directly; in this mode the MCP
client IS the model — there is no Python-side LLM loop.

Run it:

    gabru mcp-serve
    # or directly:
    python -m mcp_serve

Wire it into Claude Desktop by adding to the user's MCP config:

    {
      "mcpServers": {
        "gabru": {
          "command": "gabru",
          "args": ["mcp-serve"]
        }
      }
    }

The set of exposed tools is discovered dynamically from ``tools.registry``;
anything registered there shows up here automatically.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional

logger = logging.getLogger("gabru.mcp_serve")


# ---------------------------------------------------------------------------
# Lazy MCP SDK import — we want `--help` and discovery to work without mcp.
# ---------------------------------------------------------------------------

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import (
        TextContent,
        Tool,
    )

    _MCP_AVAILABLE = True
except ImportError:
    _MCP_AVAILABLE = False
    Server = None  # type: ignore[assignment,misc]
    stdio_server = None  # type: ignore[assignment,misc]
    TextContent = None  # type: ignore[assignment,misc]
    Tool = None  # type: ignore[assignment,misc]


def _load_tool_registry():
    """Trigger registry auto-discovery and return the registry instance."""
    # Importing model_tools pulls in the tool modules that self-register.
    import model_tools  # noqa: F401  # side-effect import
    from tools.registry import registry

    return registry


def _tool_schema_to_mcp(name: str, schema: Dict[str, Any]) -> Any:
    """Convert an OpenAI-style tool schema to an mcp.types.Tool.

    Registry schemas look like::

        {"name": "read_file",
         "description": "...",
         "parameters": {"type": "object", "properties": {...}, "required": [...]}}
    """
    description = schema.get("description") or f"Gabru tool: {name}"
    parameters = schema.get("parameters") or {"type": "object", "properties": {}}
    # Some older schemas wrap in {"type": "function", "function": {...}}
    if "function" in schema and isinstance(schema["function"], dict):
        inner = schema["function"]
        description = inner.get("description") or description
        parameters = inner.get("parameters") or parameters
    return Tool(name=name, description=description, inputSchema=parameters)


async def _dispatch_tool(registry: Any, name: str, arguments: Dict[str, Any]) -> str:
    """Run a registry tool and return its JSON-string result.

    The registry handlers are synchronous, so we offload them to a thread
    to keep the asyncio event loop responsive.
    """
    def _call() -> str:
        try:
            result = registry.dispatch(name, arguments or {})
        except Exception as exc:  # registry errors bubble up as strings
            logger.exception("tool %s raised", name)
            return json.dumps({"error": f"{type(exc).__name__}: {exc}"})
        if isinstance(result, (bytes, bytearray)):
            try:
                result = result.decode("utf-8", errors="replace")
            except Exception:
                result = repr(result)
        if not isinstance(result, str):
            try:
                result = json.dumps(result, default=str)
            except Exception:
                result = repr(result)
        return result

    return await asyncio.to_thread(_call)


def _build_server() -> Any:
    if not _MCP_AVAILABLE:
        raise RuntimeError(
            "The `mcp` package is not installed. "
            "Install it with `uv pip install -e \".[mcp]\"` and rerun."
        )
    registry = _load_tool_registry()
    server = Server("gabru-agent")

    @server.list_tools()
    async def handle_list_tools() -> List[Any]:
        tools: List[Any] = []
        for tool_name in sorted(registry.get_all_tool_names()):
            try:
                if not registry.check_tool_availability(tool_name):
                    continue
            except Exception:
                # If availability check crashes, fall through and expose it.
                pass
            schema = registry.get_schema(tool_name) or {}
            try:
                tools.append(_tool_schema_to_mcp(tool_name, schema))
            except Exception as exc:
                logger.warning("skipping tool %s (bad schema): %s", tool_name, exc)
        return tools

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: Optional[Dict[str, Any]]) -> List[Any]:
        result = await _dispatch_tool(registry, name, arguments or {})
        return [TextContent(type="text", text=result)]

    return server


async def _run() -> int:
    server = _build_server()
    async with stdio_server() as (read_stream, write_stream):
        init_options = server.create_initialization_options()
        await server.run(read_stream, write_stream, init_options)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """Entry point for ``gabru mcp-serve`` and ``python -m mcp_serve``."""
    # argv accepted for compatibility with console-scripts that pass it;
    # we don't currently need flags beyond what the env provides.
    del argv
    level_env = os.environ.get("GABRU_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level_env, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,  # never write to stdout — stdout is MCP transport
    )
    if not _MCP_AVAILABLE:
        sys.stderr.write(
            "error: the `mcp` package is not installed.\n"
            'Install with: uv pip install -e ".[mcp]"\n'
        )
        return 1
    try:
        return asyncio.run(_run())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
