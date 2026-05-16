"""Minimal reproduction: run `doctor` and `voices` over MCP stdio.

Skips the full mcp_e2e suite so we can iterate quickly on the threaded /
heartbeat path without the long-running tts/compose dependencies.

Run from repo root:
    py tests/mcp_short_tools.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
SERVER = REPO_ROOT / "videopilot_mcp.py"

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


async def _unwrap(result: Any) -> dict[str, Any]:
    """Pull a dict out of an MCP CallToolResult, regardless of where FastMCP
    parked the payload.

    FastMCP returns dict tool results as a TextContent block whose `text` is
    the JSON-serialized dict when the return annotation is `dict` (untyped),
    and as `structuredContent` when the annotation has a derivable schema. We
    accept either.
    """
    if result.structuredContent is not None:
        sc = result.structuredContent
        if isinstance(sc, dict) and set(sc.keys()) == {"result"}:
            inner = sc["result"]
            if isinstance(inner, dict):
                return inner
        if isinstance(sc, dict):
            return sc
    if result.content:
        joined = "".join(getattr(c, "text", "") or "" for c in result.content)
        try:
            parsed = json.loads(joined)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return {"_raw_text": joined}
    return {}


async def run() -> int:
    params = StdioServerParameters(
        command=sys.executable, args=[str(SERVER)], cwd=str(REPO_ROOT)
    )
    failures = 0
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            t0 = time.monotonic()
            try:
                result = await session.call_tool(
                    "doctor", {}, read_timeout_seconds=timedelta(seconds=30)
                )
                elapsed = time.monotonic() - t0
                sc = await _unwrap(result)
                print(f"[doctor] elapsed={elapsed:.2f}s, keys={sorted(sc.keys())}")
                print(f"[doctor] ok={sc.get('ok')!r}, exit_code={sc.get('exit_code')!r}")
                log_excerpt = (sc.get("log") or "")[:300]
                print(f"[doctor] log[:300]={log_excerpt!r}")
                if "ok" not in sc:
                    failures += 1
                    print("[doctor] FAIL: missing 'ok' key")
                else:
                    print("[doctor] PASS")
            except Exception as e:
                elapsed = time.monotonic() - t0
                print(f"[doctor] EXC after {elapsed:.2f}s: {e!r}")
                failures += 1

            t0 = time.monotonic()
            try:
                result = await session.call_tool(
                    "voices",
                    {"engine": "edge-tts", "locale": "en-US"},
                    read_timeout_seconds=timedelta(seconds=30),
                )
                elapsed = time.monotonic() - t0
                sc = await _unwrap(result)
                print(f"[voices] elapsed={elapsed:.2f}s, keys={sorted(sc.keys())}")
                print(f"[voices] exit_code={sc.get('exit_code')!r}")
                log_excerpt = (sc.get("log") or "")[:200]
                print(f"[voices] log[:200]={log_excerpt!r}")
                bad = "cannot be called from a running event loop"
                if bad in (sc.get("log") or ""):
                    failures += 1
                    print("[voices] FAIL: nested-loop crash leaked")
                else:
                    print("[voices] PASS")
            except Exception as e:
                elapsed = time.monotonic() - t0
                print(f"[voices] EXC after {elapsed:.2f}s: {e!r}")
                failures += 1

    print(f"\n[mcp_short_tools] failures={failures}")
    return failures


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
