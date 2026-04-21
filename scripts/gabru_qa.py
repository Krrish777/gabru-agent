"""Senior-QA harness for the Gabru-Agent MCP surface.

This is the acceptance gate for the foundation. It drives
`gabru mcp-serve` over stdio — identical transport to what Claude Code
uses — and reports pass/fail for every check. Two halves:

  WHITE-BOX — the tool registry itself
    W1  schema integrity: every tool has a dict inputSchema
    W2  required-args surfaced correctly (missing args -> error, not crash)
    W3  malformed-args handling (wrong types -> error, not crash)
    W4  unknown tool -> clean error response
    W5  server init + shutdown are orderly
    W6  session/state isolation: two successive calls on an idempotent
        tool don't leak residue

  BLACK-BOX — the three agent roles the hackathon targets
    B1  Coder: write fib.py, run it, verify output
    B2  Tester: write pytest test, run pytest, verify pass/fail signal
    B3  Hunter: search a target file for risky patterns, surface findings
    B4  Multi-file: patch an existing source file and verify on disk
    B5  Introspection: skills_list, todo, memory are callable with their
        correct arg shapes (proves we discovered the schema contract)

Exit 0 if every case passes. Prints a detailed per-check line so failures
are actionable. Intended to run as a CI gate and locally post-change.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
except Exception as exc:
    sys.stderr.write(f"error: mcp client SDK not available ({exc})\n")
    raise SystemExit(2) from None


REPO_ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
IS_WINDOWS = os.name == "nt"


@dataclass
class Check:
    category: str          # WHITE or BLACK
    name: str
    ok: bool
    detail: str
    skipped: bool = False


def _text(result: Any) -> str:
    parts = []
    for item in getattr(result, "content", []) or []:
        t = getattr(item, "text", None)
        if t is not None:
            parts.append(t)
    return "\n".join(parts) if parts else repr(result)


def _json(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return None


def _sh_path(p: Path) -> str:
    """Return a path string that works in both Python and git-bash.

    Strategy: forward-slash Windows paths (``C:/Users/...``). Python's
    ``open()`` accepts them on any OS, and git-bash treats them as
    absolute paths with a drive-letter prefix. MSYS-style ``/c/...``
    prefixing sometimes caused Python's ``open`` to fall back to a
    cwd-relative path and silently create/miss files in the wrong
    location — forward-slash Windows paths avoid that whole class of
    mismatches.
    """
    return str(p).replace("\\", "/")


def _repo_tmpdir(name: str) -> Path:
    """Create a tmp dir inside the repo so Windows paths stay on the
    same drive (C:) the shell's cwd is on. Avoids D:\\ / C:\\ mismatches
    when both Python and git-bash tooling handle the same path.
    """
    root = REPO_ROOT / ".qa-tmp"
    root.mkdir(exist_ok=True)
    unique = root / f"{name}-{int(time.time() * 1000)}"
    unique.mkdir(exist_ok=True, parents=True)
    return unique


async def _call(session: ClientSession, tool: str, args: Dict[str, Any]) -> Tuple[Any, str, Any]:
    """Call a tool, return (raw_result, text, parsed_json_or_None)."""
    res = await session.call_tool(tool, arguments=args)
    text = _text(res)
    return res, text, _json(text)


# ---------------------------------------------------------------------------
# WHITE-BOX checks
# ---------------------------------------------------------------------------

async def wb_schema_integrity(session: ClientSession, tools: List[Any]) -> List[Check]:
    """Every advertised tool must have a dict inputSchema and a non-empty name."""
    out: List[Check] = []
    for t in tools:
        ok = isinstance(t.inputSchema, dict) and isinstance(t.name, str) and t.name
        detail = f"name={t.name!r} schema_type={type(t.inputSchema).__name__}"
        out.append(Check("WHITE", f"W1.schema[{t.name}]", ok, detail))
    return out


async def wb_required_args_enforced(session: ClientSession) -> Check:
    """write_file requires path + content — omitting both must yield an error response, not a crash."""
    try:
        _, text, obj = await _call(session, "write_file", {})
        ok = (
            ("Input validation error" in text)
            or (isinstance(obj, dict) and obj.get("error"))
            or ("required" in text.lower())
        )
        return Check(
            "WHITE", "W2.required-args enforced",
            ok,
            f"empty args -> {text[:120]!r}",
        )
    except Exception as exc:
        return Check(
            "WHITE", "W2.required-args enforced",
            False,
            f"server crashed instead of returning error: {type(exc).__name__}: {exc}",
        )


async def wb_malformed_args(session: ClientSession) -> Check:
    """write_file with wrong types for required args must degrade gracefully."""
    try:
        _, text, obj = await _call(
            session, "write_file",
            {"path": 12345, "content": ["nope"]},  # both wrong types
        )
        # The server should either validate-error or return a tool error dict
        ok = ("error" in text.lower()) or ("validation" in text.lower())
        return Check("WHITE", "W3.malformed-args handling", ok, f"-> {text[:120]!r}")
    except Exception as exc:
        return Check(
            "WHITE", "W3.malformed-args handling",
            False,
            f"crashed on malformed args: {type(exc).__name__}",
        )


async def wb_unknown_tool(session: ClientSession) -> Check:
    try:
        _, text, _ = await _call(session, "not_a_real_tool_xyz", {})
        ok = any(
            k in text.lower() for k in ("not found", "unknown", "no such", "error", "unavailable")
        )
        return Check("WHITE", "W4.unknown-tool error", ok, f"-> {text[:120]!r}")
    except Exception as exc:
        # Some SDKs raise — also acceptable as graceful handling
        return Check("WHITE", "W4.unknown-tool error", True, f"raised {type(exc).__name__}")


async def wb_idempotent_read(session: ClientSession) -> Check:
    """Reading the same file twice either returns identical content or a
    dedup marker (the runtime has an explicit token-saving optimization
    that returns a 'File unchanged since last read' notice on the second
    call). Either is correct; a size/content mismatch would be a bug.
    """
    target = REPO_ROOT / "LICENSE"
    _, t1, o1 = await _call(session, "read_file", {"path": _sh_path(target)})
    _, t2, o2 = await _call(session, "read_file", {"path": _sh_path(target)})
    if not (isinstance(o1, dict) and isinstance(o2, dict)):
        return Check(
            "WHITE", "W6.idempotent read",
            False,
            f"unexpected shape: {t1[:80]!r} vs {t2[:80]!r}",
        )
    deduped = bool(o2.get("dedup"))
    same_content = o1.get("content") == o2.get("content") and o1.get("file_size") == o2.get("file_size")
    ok = deduped or same_content
    return Check(
        "WHITE", "W6.idempotent read",
        ok,
        f"size={o1.get('file_size')} dedup={deduped} same_content={same_content}",
    )


# ---------------------------------------------------------------------------
# BLACK-BOX checks — the three hackathon-target agent roles
# ---------------------------------------------------------------------------

async def bb_coder_role(session: ClientSession) -> List[Check]:
    """Coder role: write a Python file, execute it, verify stdout."""
    out: List[Check] = []
    td_path = _repo_tmpdir("coder")
    try:
        fib = td_path / "fib.py"
        payload = (
            "def fib(n):\n"
            "    a, b = 0, 1\n"
            "    for _ in range(n):\n"
            "        a, b = b, a + b\n"
            "    return a\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    print(fib(10))\n"
        )
        _, _, wo = await _call(
            session, "write_file", {"path": _sh_path(fib), "content": payload},
        )
        bytes_written = (wo or {}).get("bytes_written") if isinstance(wo, dict) else None
        out.append(Check(
            "BLACK", "B1a.Coder.write_file",
            fib.is_file() and bytes_written in (len(payload), len(payload) + payload.count("\n")),
            f"bytes_written={bytes_written} payload_len={len(payload)} exists={fib.is_file()}",
        ))

        _, _, to = await _call(
            session, "terminal",
            {"command": f'python "{_sh_path(fib)}"'},
        )
        output = (to or {}).get("output", "")
        exit_code = (to or {}).get("exit_code", -1)
        out.append(Check(
            "BLACK", "B1b.Coder.terminal-run",
            exit_code == 0 and "55" in output,
            f"exit={exit_code} output={output.strip()[:80]!r}",
        ))

        _, _, ro = await _call(session, "read_file", {"path": _sh_path(fib)})
        content = (ro or {}).get("content", "") if isinstance(ro, dict) else ""
        out.append(Check(
            "BLACK", "B1c.Coder.read_back",
            "def fib" in content,
            f"content_len={len(content)}",
        ))
    finally:
        shutil.rmtree(td_path, ignore_errors=True)
    return out


async def bb_tester_role(session: ClientSession) -> List[Check]:
    """Tester role: write a pytest test, run pytest, check pass/fail signal."""
    out: List[Check] = []
    td_path = _repo_tmpdir("tester")
    try:
        src = td_path / "calc.py"
        src.write_text(
            "def add(a, b):\n    return a + b\n\n"
            "def div(a, b):\n    return a / b\n",
            encoding="utf-8",
        )
        test_file = td_path / "test_calc.py"
        test_payload = (
            "import sys, pytest\n"
            "sys.path.insert(0, '.')\n"
            "from calc import add, div\n"
            "\n"
            "def test_add():\n"
            "    assert add(2, 3) == 5\n"
            "\n"
            "def test_div_zero_raises():\n"
            "    with pytest.raises(ZeroDivisionError):\n"
            "        div(1, 0)\n"
        )
        await _call(
            session, "write_file",
            {"path": _sh_path(test_file), "content": test_payload},
        )
        out.append(Check(
            "BLACK", "B2a.Tester.write_test",
            test_file.is_file(),
            f"path={test_file.name}",
        ))

        # Run pytest in the tmpdir
        _, _, to = await _call(
            session, "terminal",
            {
                "command": f'cd "{_sh_path(td_path)}" && python -m pytest -q --tb=line',
            },
        )
        output = (to or {}).get("output", "")
        exit_code = (to or {}).get("exit_code", -1)
        # pytest exits 0 when all pass
        out.append(Check(
            "BLACK", "B2b.Tester.run_pytest",
            exit_code == 0 and "2 passed" in output,
            f"exit={exit_code} last_line={output.strip().splitlines()[-1][:120] if output.strip() else '(empty)'!r}",
        ))

        # Sanity: a deliberately failing test should show up as a failure signal
        bad_test = td_path / "test_fail.py"
        bad_test.write_text(
            "def test_always_fails():\n    assert 1 == 2\n",
            encoding="utf-8",
        )
        _, _, to2 = await _call(
            session, "terminal",
            {"command": f'cd "{_sh_path(td_path)}" && python -m pytest test_fail.py -q --tb=line'},
        )
        exit2 = (to2 or {}).get("exit_code", 0)
        out2 = (to2 or {}).get("output", "")
        out.append(Check(
            "BLACK", "B2c.Tester.failure-signal",
            exit2 != 0 and ("failed" in out2.lower() or "FAILED" in out2),
            f"exit={exit2} matched_fail={'failed' in out2.lower()}",
        ))
    finally:
        # Restore the tool session's cwd to the repo root BEFORE rmtree so
        # subsequent scenarios don't inherit a stale, deleted cwd in the
        # snapshot. Without this, later read_file / patch calls fail with
        # "Failed to read file: ..." because `cd <deleted>` exits 126
        # before the actual command runs.
        try:
            await _call(session, "terminal", {"command": f'cd "{_sh_path(REPO_ROOT)}"'})
        except Exception:
            pass
        shutil.rmtree(td_path, ignore_errors=True)
    return out


async def bb_hunter_role(session: ClientSession) -> List[Check]:
    """Hunter role: search a file for known-risky patterns and surface findings."""
    out: List[Check] = []
    td_path = _repo_tmpdir("hunter")
    have_rg = shutil.which("rg") is not None
    have_gnu_find = shutil.which("find") and _gnu_find_ok()
    try:
        risky = td_path / "vulnerable.py"
        risky_code = (
            "import subprocess\n"
            "import os\n"
            "def run(cmd):\n"
            "    # Obvious shell-injection smell: untrusted input to shell=True\n"
            "    return subprocess.check_output(cmd, shell=True)\n"
            "\n"
            "def auth(password):\n"
            "    # Hard-coded secret\n"
            "    return password == 'hunter2'\n"
        )
        # Write via MCP so the tool session records it (avoids dedup surprises)
        await _call(
            session, "write_file",
            {"path": _sh_path(risky), "content": risky_code},
        )

        if have_rg or have_gnu_find:
            _, text, obj = await _call(
                session, "search_files",
                {"pattern": "shell=True", "path": _sh_path(td_path), "target": "content"},
            )
            if isinstance(obj, dict) and obj.get("error"):
                out.append(Check(
                    "BLACK", "B3a.Hunter.content-search",
                    False,
                    f"search tool returned error despite rg/find present: {obj.get('error')[:120]}",
                ))
            else:
                has_hit = ("shell=True" in text) or (isinstance(obj, dict) and obj.get("total_count", 0) > 0)
                out.append(Check(
                    "BLACK", "B3a.Hunter.content-search",
                    has_hit,
                    f"text_sample={text[:120]!r}",
                ))
        else:
            out.append(Check(
                "BLACK", "B3a.Hunter.content-search",
                True,
                "ripgrep/GNU-find not on PATH; content search skipped (OK on Linux CI)",
                skipped=True,
            ))

        # Filename search — same dependency chain
        if have_rg or have_gnu_find:
            _, text2, obj2 = await _call(
                session, "search_files",
                {"pattern": "vulnerable.py", "path": _sh_path(td_path), "target": "files"},
            )
            hit = ("vulnerable.py" in text2) or (isinstance(obj2, dict) and obj2.get("total_count", 0) > 0)
            out.append(Check(
                "BLACK", "B3b.Hunter.filename-search",
                hit,
                f"matched={hit}",
            ))
        else:
            out.append(Check(
                "BLACK", "B3b.Hunter.filename-search",
                True,
                "ripgrep/GNU-find not on PATH; filename search skipped (OK on Linux CI)",
                skipped=True,
            ))

        # Read-target: direct read, bust dedup by touching mtime first
        risky.touch()
        _, _, ro = await _call(session, "read_file", {"path": _sh_path(risky)})
        body = (ro or {}).get("content", "") if isinstance(ro, dict) else ""
        out.append(Check(
            "BLACK", "B3c.Hunter.read-target",
            "shell=True" in body and "hunter2" in body,
            f"content_len={len(body)}",
        ))
    finally:
        shutil.rmtree(td_path, ignore_errors=True)
    return out


def _gnu_find_ok() -> bool:
    """Return True if `find` on PATH is GNU findutils, not Windows find.exe."""
    import subprocess as _sp
    try:
        r = _sp.run(["find", "--version"], capture_output=True, text=True, timeout=2)
        return "GNU" in (r.stdout or r.stderr or "")
    except Exception:
        return False


async def bb_patch_edit(session: ClientSession) -> Check:
    """Multi-file / surgical edit: patch must change the file on disk."""
    td_path = _repo_tmpdir("patch")
    try:
        target = td_path / "greet.py"
        target.write_text("print('before')\n", encoding="utf-8")
        _, text, _ = await _call(
            session, "patch",
            {
                "mode": "replace",
                "path": _sh_path(target),
                "old_string": "print('before')",
                "new_string": "print('after')",
            },
        )
        on_disk = target.read_text(encoding="utf-8")
        ok = "after" in on_disk and "before" not in on_disk
        return Check(
            "BLACK", "B4.patch-edit",
            ok,
            f"on_disk={on_disk.strip()!r} path={_sh_path(target)!r} resp={text[:300]!r}",
        )
    finally:
        shutil.rmtree(td_path, ignore_errors=True)


async def bb_introspection(session: ClientSession) -> List[Check]:
    """Introspection tools — assert real functional behavior, not just
    'doesn't crash'. A tool that returns ``{"error": "not initialized"}``
    for every call is objectively broken even though it didn't raise.
    """
    out: List[Check] = []

    # memory.add → response.success should be truthy and entry_count > 0
    try:
        fact = f"e2e-memory-{int(time.time())}"
        _, _, obj = await _call(
            session, "memory",
            {"action": "add", "target": "memory", "content": fact},
        )
        ok = isinstance(obj, dict) and obj.get("success") is True and obj.get("entry_count", 0) >= 1
        out.append(Check(
            "BLACK", "B5a.memory.add",
            ok,
            f"success={obj.get('success') if isinstance(obj, dict) else None} "
            f"entry_count={obj.get('entry_count') if isinstance(obj, dict) else None}",
        ))
    except Exception as exc:
        out.append(Check("BLACK", "B5a.memory.add", False, f"raised {type(exc).__name__}: {exc}"))

    # todo.write then todo.list — verify round trip
    try:
        marker = f"e2e-todo-{int(time.time())}"
        await _call(
            session, "todo",
            {"todos": [{"id": "qa1", "content": marker, "status": "pending"}], "merge": False},
        )
        _, _, obj2 = await _call(session, "todo", {})
        todos = (obj2 or {}).get("todos", []) if isinstance(obj2, dict) else []
        ok = any(t.get("content") == marker for t in todos)
        out.append(Check(
            "BLACK", "B5b.todo.roundtrip",
            ok,
            f"todos={len(todos)} marker_found={ok}",
        ))
    except Exception as exc:
        out.append(Check("BLACK", "B5b.todo.roundtrip", False, f"raised {type(exc).__name__}: {exc}"))

    # skills_list — must return at least 1 pack from the bundled set
    try:
        _, _, obj3 = await _call(session, "skills_list", {})
        skills = (obj3 or {}).get("skills", []) if isinstance(obj3, dict) else []
        ok = len(skills) >= 1
        out.append(Check(
            "BLACK", "B5c.skills_list.populated",
            ok,
            f"skill_count={len(skills)} sample={[s.get('name') for s in skills[:3]]}",
        ))
    except Exception as exc:
        out.append(Check("BLACK", "B5c.skills_list.populated", False, f"raised {type(exc).__name__}: {exc}"))

    return out


async def bb_execute_code(session: ClientSession) -> Check:
    """execute_code may be refused on Windows per design — mark as skip there."""
    _, text, obj = await _call(
        session, "execute_code", {"code": "print(2+2)"},
    )
    if isinstance(obj, dict) and "not available on Windows" in (obj.get("error") or ""):
        return Check(
            "BLACK", "B1d.execute_code",
            True,  # intentional platform skip, not a regression
            "refused on Windows per design; OK on Linux CI",
            skipped=True,
        )
    ok = "4" in text
    return Check("BLACK", "B1d.execute_code", ok, f"-> {text[:120]!r}")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

async def _run() -> Tuple[List[Check], Dict[str, Any]]:
    checks: List[Check] = []
    meta: Dict[str, Any] = {}

    params = StdioServerParameters(
        command=PY,
        args=["-m", "mcp_serve"],
        env={**os.environ, "GABRU_LOG_LEVEL": "WARNING"},
        cwd=str(REPO_ROOT),
    )

    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as session:
            # W5 implicit: if initialize works, the server starts + shuts down cleanly
            try:
                init = await session.initialize()
                meta["server_name"] = init.serverInfo.name
                meta["protocol"] = init.protocolVersion
                checks.append(Check("WHITE", "W5.server init", True,
                                    f"server={init.serverInfo.name} proto={init.protocolVersion}"))
            except Exception as exc:
                checks.append(Check("WHITE", "W5.server init", False,
                                    f"initialize failed: {type(exc).__name__}: {exc}"))
                return checks, meta

            listing = await session.list_tools()
            tools = listing.tools
            meta["tool_count"] = len(tools)

            # WHITE-BOX
            checks.extend(await wb_schema_integrity(session, tools))
            checks.append(await wb_required_args_enforced(session))
            checks.append(await wb_malformed_args(session))
            checks.append(await wb_unknown_tool(session))
            checks.append(await wb_idempotent_read(session))

            # BLACK-BOX
            checks.extend(await bb_coder_role(session))
            checks.append(await bb_execute_code(session))
            checks.extend(await bb_tester_role(session))
            checks.extend(await bb_hunter_role(session))
            checks.append(await bb_patch_edit(session))
            checks.extend(await bb_introspection(session))

    return checks, meta


def _summary(checks: List[Check], meta: Dict[str, Any]) -> int:
    width = max(len(c.name) for c in checks)
    white = [c for c in checks if c.category == "WHITE"]
    black = [c for c in checks if c.category == "BLACK"]

    def _print_set(title: str, items: List[Check]) -> Tuple[int, int, int]:
        sys.stderr.write(f"\n{title}\n")
        passed = failed = skipped = 0
        for c in items:
            if c.skipped:
                mark = "SKIP"
                skipped += 1
            elif c.ok:
                mark = "PASS"
                passed += 1
            else:
                mark = "FAIL"
                failed += 1
            sys.stderr.write(f"  [{mark}] {c.name.ljust(width)}  {c.detail}\n")
        return passed, failed, skipped

    wp, wf, ws = _print_set("── WHITE-BOX ──", white)
    bp, bf, bs = _print_set("── BLACK-BOX ──", black)

    total = len(checks)
    passed = wp + bp
    failed = wf + bf
    skipped = ws + bs
    sys.stderr.write(
        f"\nServer: {meta.get('server_name')} (proto {meta.get('protocol')}), "
        f"tools: {meta.get('tool_count')}\n"
    )
    sys.stderr.write(
        f"Results: {passed} passed, {failed} failed, {skipped} skipped, {total} total\n"
    )
    return 0 if failed == 0 else 1


def main() -> int:
    try:
        checks, meta = asyncio.run(_run())
    except Exception as exc:
        sys.stderr.write(f"QA harness crashed: {type(exc).__name__}: {exc}\n")
        return 1
    return _summary(checks, meta)


if __name__ == "__main__":
    raise SystemExit(main())
