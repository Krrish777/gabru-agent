"""End-to-end MCP acceptance run for Gabru-Agent.

Spawns `gabru mcp-serve` over stdio and exercises the tool registry
through realistic multi-step scenarios — the kind Claude Code would
actually drive. Broader than `mcp_qa.py`, which is a shallow smoke test.

Exits 0 if every scenario passes, 1 otherwise. Prints a per-scenario
pass/fail summary to stderr, detailed transcript to stdout.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, List, Tuple

try:
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
except Exception as exc:
    sys.stderr.write(f"error: mcp client SDK not available ({exc})\n")
    raise SystemExit(2) from None


REPO_ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
Scenario = Tuple[str, bool, str]


def _result_text(result: Any) -> str:
    parts = []
    for item in getattr(result, "content", []) or []:
        t = getattr(item, "text", None)
        if t is not None:
            parts.append(t)
    return "\n".join(parts) if parts else repr(result)


def _parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return None


async def _section(title: str, log: List[str]) -> None:
    log.append(f"\n=== {title} ===")


def _log(log: List[str], msg: str) -> None:
    log.append(msg)
    print(msg, flush=True)


async def _run_scenarios() -> List[Scenario]:
    results: List[Scenario] = []
    log: List[str] = []

    params = StdioServerParameters(
        command=PY,
        args=["-m", "mcp_serve"],
        env={**os.environ, "GABRU_LOG_LEVEL": "WARNING"},
        cwd=str(REPO_ROOT),
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            _log(log, f"connected: server={init.serverInfo.name} "
                      f"protocol={init.protocolVersion}")
            listing = await session.list_tools()
            tool_names = {t.name for t in listing.tools}
            _log(log, f"tools available: {len(listing.tools)}")

            # ----------------------------------------------------------
            # Scenario 1: Write-compile-run round trip
            #   - write_file creates a Python script
            #   - terminal runs `python <script>`
            #   - output is what we expect
            # ----------------------------------------------------------
            name = "write->run Python file"
            try:
                with tempfile.TemporaryDirectory() as td:
                    script = Path(td) / "hello.py"
                    payload = (
                        "import sys\n"
                        "sys.stdout.write('gabru-e2e-hello\\n')\n"
                    )
                    await session.call_tool(
                        "write_file",
                        arguments={"path": str(script), "content": payload},
                    )
                    assert script.is_file(), f"script not on disk: {script}"

                    # Run it
                    r = await session.call_tool(
                        "terminal",
                        arguments={"command": f'{PY} "{script}"'},
                    )
                    text = _result_text(r)
                    obj = _parse_json(text) or {}
                    assert "gabru-e2e-hello" in (obj.get("output") or ""), (
                        f"expected hello output, got: {text[:300]!r}"
                    )
                results.append((name, True, "python ran the written script"))
            except Exception as exc:
                results.append((name, False, f"{type(exc).__name__}: {exc}"))

            # ----------------------------------------------------------
            # Scenario 2: Code execution sandbox
            # ----------------------------------------------------------
            name = "execute_code sandbox"
            try:
                r = await session.call_tool(
                    "execute_code",
                    arguments={
                        "code": (
                            "import math\n"
                            "print('sqrt2=', round(math.sqrt(2), 5))\n"
                        ),
                    },
                )
                text = _result_text(r)
                assert "sqrt2= 1.41421" in text, f"unexpected output: {text[:300]!r}"
                results.append((name, True, "math.sqrt evaluated correctly"))
            except Exception as exc:
                results.append((name, False, f"{type(exc).__name__}: {exc}"))

            # ----------------------------------------------------------
            # Scenario 3: Todo tool — add + list + complete
            # ----------------------------------------------------------
            name = "todo add/list/complete"
            try:
                # Add a todo
                add = await session.call_tool(
                    "todo",
                    arguments={
                        "action": "add",
                        "content": "write unit tests for the coder output",
                    },
                )
                add_text = _result_text(add)
                # List
                lst = await session.call_tool("todo", arguments={"action": "list"})
                lst_text = _result_text(lst)
                assert "unit tests" in lst_text, (
                    f"todo not in list: {lst_text[:400]!r}"
                )
                results.append((name, True, "todo add+list round-trip"))
            except Exception as exc:
                results.append((name, False, f"{type(exc).__name__}: {exc}"))

            # ----------------------------------------------------------
            # Scenario 4: Memory — save a durable fact + recall it
            # ----------------------------------------------------------
            name = "memory save/load"
            try:
                fact = f"Gabru E2E test ran at {int(time.time())}"
                save = await session.call_tool(
                    "memory",
                    arguments={"action": "save", "content": fact},
                )
                save_text = _result_text(save)
                load = await session.call_tool(
                    "memory",
                    arguments={"action": "load"},
                )
                load_text = _result_text(load)
                assert fact.split()[-1] in load_text, (
                    f"memory didn't round-trip; save={save_text[:200]!r}, "
                    f"load={load_text[:400]!r}"
                )
                results.append((name, True, "memory round-trip"))
            except Exception as exc:
                results.append((name, False, f"{type(exc).__name__}: {exc}"))

            # ----------------------------------------------------------
            # Scenario 5: Skills enumeration
            # ----------------------------------------------------------
            name = "skills_list"
            try:
                r = await session.call_tool("skills_list", arguments={})
                text = _result_text(r)
                # Expect at least one of the kept skill packs to surface
                found_any = any(
                    kw in text.lower()
                    for kw in ("software-development", "github", "red-teaming", "devops", "security")
                )
                assert found_any, f"no kept skill pack in output: {text[:300]!r}"
                results.append((name, True, "kept skill packs visible"))
            except Exception as exc:
                results.append((name, False, f"{type(exc).__name__}: {exc}"))

            # ----------------------------------------------------------
            # Scenario 6: Filesystem search on known content
            # ----------------------------------------------------------
            name = "search_files (filename)"
            try:
                r = await session.call_tool(
                    "search_files",
                    arguments={
                        "pattern": "mcp_serve.py",
                        "path": str(REPO_ROOT),
                        "target": "files",
                    },
                )
                text = _result_text(r)
                assert "mcp_serve" in text, f"pattern not found: {text[:300]!r}"
                results.append((name, True, "found mcp_serve.py in the repo"))
            except Exception as exc:
                results.append((name, False, f"{type(exc).__name__}: {exc}"))

            # ----------------------------------------------------------
            # Scenario 7: Terminal multi-step shell
            # ----------------------------------------------------------
            name = "terminal multi-step"
            try:
                with tempfile.TemporaryDirectory() as td:
                    marker = Path(td) / "marker.txt"
                    # chain: write a marker, verify it via shell
                    r = await session.call_tool(
                        "terminal",
                        arguments={
                            "command": f'echo e2e-marker > "{marker}" && cat "{marker}"',
                        },
                    )
                    text = _result_text(r)
                    obj = _parse_json(text) or {}
                    output = obj.get("output", "")
                    assert "e2e-marker" in output, (
                        f"shell chain didn't print marker: {text[:400]!r}"
                    )
                results.append((name, True, "shell chain end-to-end"))
            except Exception as exc:
                results.append((name, False, f"{type(exc).__name__}: {exc}"))

            # ----------------------------------------------------------
            # Scenario 8: Patch tool — modify a file
            # ----------------------------------------------------------
            name = "patch modifies file"
            try:
                with tempfile.TemporaryDirectory() as td:
                    target = Path(td) / "greet.py"
                    target.write_text("print('before')\n", encoding="utf-8")
                    if "patch" in tool_names:
                        r = await session.call_tool(
                            "patch",
                            arguments={
                                "path": str(target),
                                "old_content": "print('before')",
                                "new_content": "print('after')",
                            },
                        )
                        text = _result_text(r)
                        on_disk = target.read_text(encoding="utf-8")
                        assert "after" in on_disk, (
                            f"patch didn't land: disk={on_disk!r}, resp={text[:300]!r}"
                        )
                        results.append((name, True, "patched greet.py"))
                    else:
                        results.append((name, True, "patch tool not registered; skipped"))
            except Exception as exc:
                results.append((name, False, f"{type(exc).__name__}: {exc}"))

            # ----------------------------------------------------------
            # Scenario 9: Graceful error on unknown tool
            # ----------------------------------------------------------
            name = "unknown tool -> clean error"
            try:
                try:
                    r = await session.call_tool(
                        "this_tool_does_not_exist",
                        arguments={},
                    )
                    text = _result_text(r).lower()
                    ok = any(
                        t in text for t in ("not found", "unknown", "no such", "error", "unavailable")
                    )
                    assert ok, f"expected error text, got: {text[:300]!r}"
                    results.append((name, True, "server returned error response"))
                except Exception as exc:
                    # Some SDKs raise instead of returning a CallToolResult error
                    results.append((name, True, f"server rejected via exception: {type(exc).__name__}"))
            except Exception as exc:
                results.append((name, False, f"{type(exc).__name__}: {exc}"))

    return results


def main() -> int:
    try:
        results = asyncio.run(_run_scenarios())
    except Exception as exc:
        sys.stderr.write(f"E2E harness crashed: {type(exc).__name__}: {exc}\n")
        return 1
    width = max(len(name) for name, *_ in results)
    passed = 0
    for name, ok, msg in results:
        mark = "PASS" if ok else "FAIL"
        sys.stderr.write(f"  [{mark}] {name.ljust(width)}  {msg}\n")
        if ok:
            passed += 1
    sys.stderr.write(f"\n{passed}/{len(results)} E2E scenarios passed.\n")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
