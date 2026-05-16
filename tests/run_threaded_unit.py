"""Unit tests for `_run_threaded` in `videopilot_mcp.py`.

Verifies the four invariants the receive loop promises:

  1. Heartbeats fire every `_HEARTBEAT_INTERVAL_SEC` even when the wrapped
     lib function doesn't accept (or emit) `progress` events.
  2. Nested `asyncio.run(...)` inside the wrapped function succeeds (no
     "asyncio.run() cannot be called from a running event loop").
  3. The wire `progress` value emitted to MCP is strictly monotonically
     increasing, even when the lib's `current/total` numbers dip / repeat.
  4. The coroutine never raises -- exceptions from the wrapped fn become
     a normal `(rc=1, log)` return with the traceback appended to the log.
     This is what prevents FastMCP from swallowing the captured stdout in
     favor of a bare `Error executing tool X: <repr>` response.

These are MCP-protocol guarantees the file-level docstring promises -- if any
of them regress, edge-tts / doctor / cut / silence / tts / transcribe / compose
will time out (-32001) or get rejected by stricter MCP clients.

Run from repo root:
    py tests/run_threaded_unit.py
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.path.insert(0, str(REPO_ROOT))

import videopilot_mcp as vp_mcp


class _FakeCtx:
    """Minimal stand-in for `mcp.server.fastmcp.Context`.

    Records every `report_progress(...)` call so the test can assert against
    them. Mimics the real Context's awaitable signature.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[float, float | None, str | None]] = []

    async def report_progress(
        self,
        progress: float,
        total: float | None = None,
        message: str | None = None,
    ) -> None:
        self.calls.append((progress, total, message))


def _slow_no_progress(duration_sec: float) -> int:
    """Sync lib-style function that doesn't accept `progress`. Used to verify
    that heartbeats fire even without a lib-level progress callback."""
    time.sleep(duration_sec)
    return 0


def _slow_nested_asyncio() -> int:
    """Sync function that nests `asyncio.run(...)` -- the exact pattern that
    crashed `voices` on FastMCP's request loop."""

    async def inner() -> int:
        await asyncio.sleep(0.05)
        return 7

    return asyncio.run(inner())


def _noisy_progress(*, progress) -> int:
    """Emits non-monotonic / duplicate `current` values to stress the
    monotonicity guarantee on the wire."""
    progress(1, 3, "starting")
    progress(2, 3, "middle")
    progress(2, 3, "middle again")  # duplicate
    progress(1, 3, "regressed")  # regression
    progress(3, 3, "done")
    return 0


async def test_heartbeats_without_progress() -> None:
    """Worker that sleeps > heartbeat interval -> we see >=2 emits.

    Shrink the interval to keep the test fast; the real default (5s) would
    make the suite take 10+ seconds.
    """
    original = vp_mcp._HEARTBEAT_INTERVAL_SEC
    vp_mcp._HEARTBEAT_INTERVAL_SEC = 0.2
    try:
        ctx = _FakeCtx()
        rc, log = await vp_mcp._run_threaded(_slow_no_progress, 0.7, ctx=ctx)
        assert rc == 0, f"exit_code {rc}, log={log!r}"
        # 0.7s with 0.2s heartbeat -> initial 'starting' + ~3 heartbeats.
        # Allow some slack for scheduler jitter.
        assert len(ctx.calls) >= 3, (
            f"expected >=3 progress emits, got {len(ctx.calls)}: {ctx.calls!r}"
        )
        first_message = ctx.calls[0][2]
        assert first_message == "starting", (
            f"first emit should be the 'starting' tick; got {first_message!r}"
        )
        heartbeat_msgs = [m for _, _, m in ctx.calls if "still working" in (m or "")]
        assert heartbeat_msgs, (
            f"expected at least one heartbeat message; got messages "
            f"{[m for _,_,m in ctx.calls]!r}"
        )
    finally:
        vp_mcp._HEARTBEAT_INTERVAL_SEC = original
    print("[run_threaded] heartbeats_without_progress  PASS")


async def test_nested_asyncio_run_succeeds() -> None:
    """`asyncio.run(...)` inside the wrapped fn must NOT raise
    "cannot be called from a running event loop" -- this is the
    bug that broke `voices` on FastMCP."""
    ctx = _FakeCtx()
    rc, log = await vp_mcp._run_threaded(_slow_nested_asyncio, ctx=ctx)
    assert rc == 7, f"exit_code {rc}, log={log!r}"
    bad = "cannot be called from a running event loop"
    assert bad not in log, f"nested asyncio.run leaked into log: {log!r}"
    print("[run_threaded] nested_asyncio_run_succeeds  PASS")


async def test_wire_progress_monotonic() -> None:
    """Non-monotonic / duplicate lib progress -> wire progress strictly
    increases. The lib's cur/total is preserved as part of the message."""
    original = vp_mcp._HEARTBEAT_INTERVAL_SEC
    vp_mcp._HEARTBEAT_INTERVAL_SEC = 5.0  # heartbeat shouldn't fire in this fast test
    try:
        ctx = _FakeCtx()
        rc, log = await vp_mcp._run_threaded(_noisy_progress, ctx=ctx)
        assert rc == 0, f"exit_code {rc}, log={log!r}"
        values = [p for p, _, _ in ctx.calls]
        assert all(
            b > a for a, b in zip(values, values[1:])
        ), f"wire progress not strictly increasing: {values!r}"
        # Wire total is always None per the docstring.
        totals = [t for _, t, _ in ctx.calls]
        assert all(t is None for t in totals), (
            f"wire total should always be None; got {totals!r}"
        )
        # Lib's cur/total info should appear in messages.
        all_msgs = " | ".join(m or "" for _, _, m in ctx.calls)
        for needle in ("starting", "middle", "regressed", "done", "(1/3)", "(3/3)"):
            assert needle in all_msgs, (
                f"expected {needle!r} in messages; got {all_msgs!r}"
            )
    finally:
        vp_mcp._HEARTBEAT_INTERVAL_SEC = original
    print("[run_threaded] wire_progress_monotonic  PASS")


async def test_ctx_none_is_safe() -> None:
    """Calling without ctx (e.g. from a future CLI helper) must not crash."""
    rc, log = await vp_mcp._run_threaded(_slow_no_progress, 0.05, ctx=None)
    assert rc == 0, f"exit_code {rc}, log={log!r}"
    print("[run_threaded] ctx_none_is_safe              PASS")


def _prints_then_raises() -> int:
    """Lib-style function that prints diagnostic output and then raises.

    Mimics tts_mod.run() after the FFmpegError site: a few `print()` calls
    succeed, then a downstream helper raises -- the agent needs both the
    captured output AND the traceback to figure out what to do next.
    """
    print("Synthesizing 1 segment(s)")
    print("  [edge-tts] vo-1 -> vo-1.mp3")
    raise RuntimeError("ffprobe not found on PATH. Run `videopilot doctor`.")


def _systemexit_with_message() -> int:
    """Lib-style function that uses `raise SystemExit('text')` for failures."""
    print("starting")
    raise SystemExit("missing voice_defaults.voice")


async def test_exception_returns_log_with_traceback() -> None:
    """`_run_threaded` must never raise. Exceptions become (rc=1, log+tb)
    so the agent sees the captured diagnostic output instead of FastMCP's
    bare 'Error executing tool X: <repr>' response."""
    ctx = _FakeCtx()
    # Should NOT raise even though the wrapped fn raises RuntimeError.
    rc, log = await vp_mcp._run_threaded(_prints_then_raises, ctx=ctx)
    assert rc == 1, f"expected rc=1 on exception, got rc={rc}"
    # Captured stdout from before the raise is preserved.
    assert "Synthesizing 1 segment(s)" in log, f"missing captured stdout: {log!r}"
    assert "vo-1 -> vo-1.mp3" in log, f"missing captured stdout: {log!r}"
    # Traceback is appended.
    assert "traceback" in log.lower(), f"missing traceback: {log!r}"
    assert "ffprobe not found" in log, f"exception message missing: {log!r}"
    assert "RuntimeError" in log, f"exception type missing: {log!r}"
    print("[run_threaded] exception_returns_log_with_traceback  PASS")


async def test_systemexit_string_code_returns_rc1() -> None:
    """`raise SystemExit('msg')` is the lib idiom for clean failures with a
    human-readable message. Code is a str, not int, so rc becomes 1 and the
    message text lands in the captured log."""
    rc, log = await vp_mcp._run_threaded(_systemexit_with_message, ctx=None)
    assert rc == 1, f"expected rc=1 for SystemExit('text'), got rc={rc}"
    assert "starting" in log, f"missing pre-exit stdout: {log!r}"
    assert "missing voice_defaults.voice" in log, (
        f"SystemExit message must reach the log; got {log!r}"
    )
    print("[run_threaded] systemexit_string_code_returns_rc1    PASS")


async def main() -> int:
    await test_heartbeats_without_progress()
    await test_nested_asyncio_run_succeeds()
    await test_wire_progress_monotonic()
    await test_ctx_none_is_safe()
    await test_exception_returns_log_with_traceback()
    await test_systemexit_string_code_returns_rc1()
    print("\n[run_threaded] all tests PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
