"""Unit tests for the stall-detecting `lib.ffmpeg_wrap.run_ffmpeg` wrapper.

Covers the three guarantees the rest of the codebase relies on:

  1. Happy path -- runs ffmpeg to completion, returns cleanly, the optional
     `progress` callback fires at least once with monotonically increasing
     `out_sec` values.

  2. Stall detection -- a subprocess that produces no output for longer than
     `stall_threshold_sec` is killed and surfaces as `FFmpegError("stalled")`.
     We exercise the inner monitor directly with a non-ffmpeg sleeper so the
     test is fast and reliable.

  3. Error path -- ffmpeg invoked with a bad argument exits non-zero and
     the raised `FFmpegError` contains the captured stderr tail.

Run: `py tests/ffmpeg_wrap_unit.py`
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.path.insert(0, str(REPO_ROOT))

from lib import ffmpeg_wrap as fw


def _need_ffmpeg() -> bool:
    if not fw.have_ffmpeg():
        print("[ffmpeg_wrap] SKIP: ffmpeg not on PATH")
        return False
    return True


def test_happy_path_progress_callback() -> None:
    """A 1-second lavfi color encode succeeds and emits at least one progress event."""
    if not _need_ffmpeg():
        return
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "happy.mp4"
        events: list[tuple[int, int, str]] = []

        def cb(cur: int, tot: int, msg: str) -> None:
            events.append((cur, tot, msg))

        fw.run_ffmpeg(
            [
                "-f", "lavfi",
                "-i", "color=c=red:s=320x240:r=30:d=1.0",
                "-f", "lavfi",
                "-i", "anullsrc=r=48000:cl=stereo:d=1.0",
                "-shortest",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k",
                str(out),
            ],
            progress=cb,
            target_duration_sec=1.0,
            coalesce_interval_sec=0.05,  # don't coalesce away the single short event
        )

        assert out.exists(), "output file was not created"
        assert out.stat().st_size > 0, "output file is empty"
        # A 1s encode at 30fps should emit at least one progress block
        # (and definitely the terminal `progress=end` block).
        assert len(events) >= 1, f"expected >=1 progress event, got {len(events)}"
        # `cur` is monotonic non-decreasing.
        cur_values = [e[0] for e in events]
        assert cur_values == sorted(cur_values), f"progress not monotonic: {cur_values}"
        # Message format includes both numbers when target is known.
        last_msg = events[-1][2]
        assert "encoding" in last_msg, f"unexpected message format: {last_msg!r}"
        assert "/" in last_msg, f"target should appear in message: {last_msg!r}"
    print("[ffmpeg_wrap] happy_path_progress_callback                 PASS")


def test_stall_detection_kills_silent_subprocess() -> None:
    """Inner monitor detects a subprocess that produces no output and kills it."""
    sleeper_cmd = [
        sys.executable,
        "-c",
        # Just sleep -- never emits to stdout or stderr.
        "import time; time.sleep(30)",
    ]
    start = time.monotonic()
    try:
        fw._spawn_with_stall_detection(
            sleeper_cmd,
            progress=None,
            target_duration_sec=None,
            stall_threshold_sec=1.0,
            coalesce_interval_sec=0.5,
            parse_progress_blocks=False,
        )
    except fw.FFmpegError as exc:
        elapsed = time.monotonic() - start
        # Should fire within ~1s + small grace; definitely under 5s.
        assert elapsed < 5.0, f"stall detection too slow: {elapsed:.2f}s"
        assert "stalled" in str(exc).lower(), f"missing 'stalled' in message: {exc}"
        print(
            f"[ffmpeg_wrap] stall_detection_kills_silent_subprocess     PASS"
            f"  (killed after {elapsed:.2f}s)"
        )
        return
    raise AssertionError("expected FFmpegError(stalled) but none was raised")


def test_stall_detection_does_not_kill_chatty_subprocess() -> None:
    """A subprocess that prints every 100ms must NOT trip the stall detector."""
    chatty_cmd = [
        sys.executable,
        "-c",
        # Print 30 lines over ~3 seconds; flush each one so the reader sees it.
        "import sys, time\n"
        "for i in range(30):\n"
        "    print(f'tick {i}', flush=True)\n"
        "    time.sleep(0.1)",
    ]
    rc, stdout_lines, _stderr = fw._spawn_with_stall_detection(
        chatty_cmd,
        progress=None,
        target_duration_sec=None,
        stall_threshold_sec=1.0,  # Even with 1s threshold, the 100ms ticks keep it alive.
        coalesce_interval_sec=0.5,
        parse_progress_blocks=False,
    )
    assert rc == 0, f"chatty subprocess exited rc={rc}"
    assert len(stdout_lines) == 30, f"expected 30 lines, got {len(stdout_lines)}"
    print("[ffmpeg_wrap] stall_detection_does_not_kill_chatty           PASS")


def test_error_path_includes_stderr_tail() -> None:
    """An invalid ffmpeg invocation surfaces stderr in the FFmpegError message."""
    if not _need_ffmpeg():
        return
    try:
        fw.run_ffmpeg(["-i", "nonexistent_file_for_test_xyzzy.mp4", "out.mp4"])
    except fw.FFmpegError as exc:
        msg = str(exc)
        assert "ffmpeg failed" in msg, f"missing 'ffmpeg failed' header: {msg!r}"
        # ffmpeg will reference the input filename somewhere in stderr.
        assert "nonexistent_file_for_test_xyzzy" in msg, (
            f"stderr tail should include filename: {msg!r}"
        )
        print("[ffmpeg_wrap] error_path_includes_stderr_tail             PASS")
        return
    raise AssertionError("expected FFmpegError but none was raised")


def main() -> int:
    failures = 0
    for fn in (
        test_happy_path_progress_callback,
        test_stall_detection_kills_silent_subprocess,
        test_stall_detection_does_not_kill_chatty_subprocess,
        test_error_path_includes_stderr_tail,
    ):
        try:
            fn()
        except AssertionError as exc:
            failures += 1
            print(f"[ffmpeg_wrap] {fn.__name__}  FAIL: {exc}")
        except Exception as exc:
            failures += 1
            print(f"[ffmpeg_wrap] {fn.__name__}  ERROR: {type(exc).__name__}: {exc}")
    if failures:
        print(f"[ffmpeg_wrap] {failures} failure(s)")
        return 1
    print("[ffmpeg_wrap] all tests PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
