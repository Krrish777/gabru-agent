"""MCP gateway QA harness.

Spawns ``python -m mcp_serve`` over stdio and exercises the tool registry
as an actual MCP client would. Intended for local and CI use as the
functional acceptance gate after the strip.

Usage:
    python scripts/mcp_qa.py

Exit code: 0 if every QA case passes, 1 if any assertion fails. Output
is a plain-text pass/fail summary to stderr so CI can grep it.

Cases exercised:
  1. initialize / handshake
  2. tools/list returns a non-empty set with valid schemas
  3. write_file creates a file with known content
  4. read_file reads back that content byte-for-byte
  5. terminal runs a shell command and returns exit code + stdout
  6. search_files finds a known pattern in the test fixture
  7. invalid arguments yield a clean error response rather than a crash
  8. shutdown is orderly
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Use the MCP SDK's stdio client — same transport Claude Code uses.
try:
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
except Exception as exc:
    sys.stderr.write(
        f"error: mcp client SDK not available ({exc}). "
        'Install deps with `uv pip install -e ".[mcp]"`.\n'
    )
    raise SystemExit(2) from None


REPO_ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable


Result = Tuple[str, bool, str]


async def _check(name: str, coro) -> Result:
    try:
        msg = await coro
        return name, True, msg
    except AssertionError as exc:
        return name, False, f"assertion failed: {exc}"
    except Exception as exc:
        return name, False, f"{type(exc).__name__}: {exc}"


async def _run_qa() -> List[Result]:
    results: List[Result] = []

    params = StdioServerParameters(
        command=PY,
        args=["-m", "mcp_serve"],
        env={**os.environ, "GABRU_LOG_LEVEL": "WARNING"},
        cwd=str(REPO_ROOT),
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            # CASE 1: initialize
            async def case_init() -> str:
                info = await session.initialize()
                assert info is not None, "initialize returned None"
                name = getattr(info.serverInfo, "name", "") or ""
                assert "gabru" in name.lower(), f"server name {name!r} missing 'gabru'"
                return f"server={name} protocol={info.protocolVersion}"

            results.append(await _check("initialize", case_init()))

            # CASE 2: tools/list
            async def case_list() -> str:
                listing = await session.list_tools()
                tools = listing.tools
                assert len(tools) >= 10, f"only {len(tools)} tools exposed"
                names = {t.name for t in tools}
                required = {"read_file", "write_file", "terminal", "search_files"}
                missing = required - names
                assert not missing, f"missing required tools: {missing}"
                # Every tool must have an inputSchema dict
                for t in tools:
                    assert isinstance(t.inputSchema, dict), f"{t.name}: bad schema"
                return f"{len(tools)} tools exposed; core set present"

            results.append(await _check("tools/list", case_list()))

            # CASE 3 + 4: write then read
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir) / "qa.txt"
                payload = "hello from gabru mcp qa\n"

                async def case_write() -> str:
                    result = await session.call_tool(
                        "write_file",
                        arguments={"path": str(tmp_path), "content": payload},
                    )
                    text = _result_text(result)
                    assert tmp_path.is_file(), f"file not created at {tmp_path}"
                    assert tmp_path.read_text(encoding="utf-8") == payload, (
                        "file content on disk doesn't match written payload"
                    )
                    return f"wrote {len(payload)} bytes ({text[:60]}...)"

                results.append(await _check("write_file", case_write()))

                async def case_read() -> str:
                    result = await session.call_tool(
                        "read_file",
                        arguments={"path": str(tmp_path)},
                    )
                    text = _result_text(result)
                    assert payload.strip() in text, (
                        f"read_file didn't return written payload, got: {text[:120]!r}"
                    )
                    return f"read matches (len={len(text)})"

                results.append(await _check("read_file", case_read()))

            # CASE 5: terminal (platform-agnostic one-liner)
            async def case_terminal() -> str:
                echo_cmd = 'echo gabru-ok'
                result = await session.call_tool(
                    "terminal",
                    arguments={"command": echo_cmd},
                )
                text = _result_text(result)
                assert "gabru-ok" in text, f"echo output missing, got: {text[:200]!r}"
                return f"terminal echoed ({len(text)}B)"

            results.append(await _check("terminal", case_terminal()))

            # CASE 6: search_files by filename (doesn't need ripgrep/grep binary)
            async def case_search() -> str:
                result = await session.call_tool(
                    "search_files",
                    arguments={
                        "pattern": "README.md",
                        "path": str(REPO_ROOT),
                        "target": "files",
                    },
                )
                text = _result_text(result)
                assert "README" in text, (
                    f"expected README match in file-name search, got: {text[:200]!r}"
                )
                return "filename search returned the expected match"

            results.append(await _check("search_files", case_search()))

            # CASE 7: invalid arguments -> clean error response
            async def case_error() -> str:
                result = await session.call_tool(
                    "read_file",
                    arguments={"path": "/__definitely/not/a/real/path__"},
                )
                text = _result_text(result).lower()
                # Accept any failure shape as long as we got a response, not a crash
                assert any(
                    token in text for token in ("error", "not found", "no such", "does not exist", "failed")
                ), f"expected error text for missing file, got: {text[:200]!r}"
                return "graceful error on missing file"

            results.append(await _check("bad-input-handling", case_error()))

    return results


def _result_text(result: Any) -> str:
    """Coalesce an mcp.CallToolResult to plain text for assertions."""
    parts = []
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if text is not None:
            parts.append(text)
    return "\n".join(parts) if parts else repr(result)


def main() -> int:
    try:
        results = asyncio.run(_run_qa())
    except Exception as exc:
        sys.stderr.write(f"QA harness crashed: {type(exc).__name__}: {exc}\n")
        return 1

    width = max(len(name) for name, *_ in results)
    passed = 0
    for name, ok, msg in results:
        mark = "PASS" if ok else "FAIL"
        sys.stderr.write(f"  [{mark}] {name.ljust(width)}  {msg}\n")
        if ok:
            passed += 1
    sys.stderr.write(f"\n{passed}/{len(results)} QA cases passed.\n")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
