"""MCP transport smoke test for get_pipeline_stages.

Spawns `gabru mcp-serve` as a stdio subprocess, speaks the MCP
JSON-RPC handshake, lists tools, calls get_pipeline_stages, and
prints a summary. No external MCP client library — raw stdio to
prove the transport path works.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _send(proc: subprocess.Popen, msg: dict) -> None:
    line = json.dumps(msg) + "\n"
    proc.stdin.write(line.encode("utf-8"))
    proc.stdin.flush()


def _recv(proc: subprocess.Popen) -> dict:
    raw = proc.stdout.readline()
    if not raw:
        raise RuntimeError("server closed stdout unexpectedly")
    return json.loads(raw.decode("utf-8"))


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    proc = subprocess.Popen(
        ["gabru", "mcp-serve"],
        cwd=repo,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        _send(proc, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "mcp-smoke", "version": "0.1"},
            },
        })
        init = _recv(proc)
        print("initialize ok:", "result" in init)

        _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})

        _send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = _recv(proc)
        names = [t["name"] for t in tools["result"]["tools"]]
        print("total tools exposed:", len(names))
        print("get_pipeline_stages exposed:", "get_pipeline_stages" in names)

        _send(proc, {
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {
                "name": "get_pipeline_stages",
                "arguments": {
                    "task": "Add reverse_str to demo_sandbox/utils.py."
                },
            },
        })
        call = _recv(proc)
        content = call["result"]["content"][0]["text"]
        manifest = json.loads(content)
        print("manifest pipeline label:", manifest["pipeline"])
        print("manifest stages        :",
              [s["name"] for s in manifest["stages"]])
        hunter_ctx = manifest["stages"][2]["context"]
        print("hunter json-block req  :", "```json" in hunter_ctx)
        print("remediation.max_loops  :", manifest["remediation"]["max_loops"])
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
