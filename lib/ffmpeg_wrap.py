"""ffmpeg / ffprobe subprocess wrappers used throughout the tool."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional


class FFmpegError(RuntimeError):
    """ffmpeg or ffprobe returned non-zero, or stalled and was killed."""


# Same shape as `lib/compose.ProgressCb` so the existing progress callbacks
# can be plumbed straight through from the timeline loop into the encoder.
ProgressCb = Callable[[int, int, str], None]


# How long we tolerate zero ffmpeg output before assuming the process is wedged
# and killing it. ffmpeg with `-progress pipe:1 -nostats` emits a key/value
# block roughly every 200 ms even on slow renders -- a hard 60 s silence is a
# strong signal of a deadlock (e.g. a filter graph waiting on an infinite
# lavfi source, a network input that died, an OS pipe-buffer deadlock). This
# is a stall budget, NOT an elapsed-time budget: a 2-hour 4K render that keeps
# emitting progress lines never trips it.
_DEFAULT_STALL_SEC = 60.0

# How often, at most, we forward ffmpeg's per-frame progress to the caller's
# `progress=` callback. ffmpeg fires ~5 progress blocks per second; without
# coalescing we'd spam the MCP client (and any other consumer) with 5 events
# per second per render. 2 s feels live without being noisy.
_DEFAULT_COALESCE_SEC = 2.0


def _winget_ffmpeg_dirs() -> list[str]:
    """Locate Gyan.FFmpeg WinGet install dirs (newest first)."""
    dirs: list[str] = []
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if not base.exists():
        return dirs
    for pkg in sorted(base.glob("Gyan.FFmpeg_*"), reverse=True):
        for sub in pkg.glob("ffmpeg-*"):
            bin_dir = sub / "bin"
            if bin_dir.exists():
                dirs.append(str(bin_dir))
    return dirs


def _candidate_dirs() -> list[str]:
    """Common Windows install locations to fall back to when not on PATH."""
    dirs = _winget_ffmpeg_dirs()
    for env in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        pf = os.environ.get(env)
        if pf:
            dirs.append(str(Path(pf) / "ffmpeg" / "bin"))
    dirs.append(r"C:\ffmpeg\bin")
    return dirs


def _ensure_on_path() -> None:
    """If ffmpeg/ffprobe aren't on PATH, append known install dirs to PATH."""
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return
    extra = [d for d in _candidate_dirs() if Path(d).exists()]
    if not extra:
        return
    sep = os.pathsep
    parts = os.environ.get("PATH", "").split(sep)
    parts_lc = {p.lower() for p in parts}
    for d in extra:
        if d.lower() not in parts_lc:
            parts.append(d)
    os.environ["PATH"] = sep.join(parts)


def have_ffmpeg() -> bool:
    _ensure_on_path()
    return shutil.which("ffmpeg") is not None


def have_ffprobe() -> bool:
    _ensure_on_path()
    return shutil.which("ffprobe") is not None


@dataclass
class MediaInfo:
    path: Path
    duration_sec: float
    video_codec: str | None
    audio_codec: str | None
    width: int | None
    height: int | None
    fps: float | None
    has_video: bool
    has_audio: bool


def probe(path: str | Path) -> MediaInfo:
    """Run ffprobe and parse the streams + format info we care about."""
    if not have_ffprobe():
        raise FFmpegError("ffprobe not found on PATH. Run `videopilot doctor`.")
    p = Path(path)
    if not p.exists():
        raise FFmpegError(f"File does not exist: {p}")

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(p),
    ]
    # ffprobe output is small (a single JSON document); the classic
    # `capture_output=True` pattern is safe here. Set a generous timeout so a
    # wedged ffprobe (e.g. against a stalled network input) can't block the
    # caller forever.
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise FFmpegError(f"ffprobe failed for {p}: {result.stderr.strip()}")
    data = json.loads(result.stdout)

    duration = float(data.get("format", {}).get("duration", 0.0) or 0.0)
    v_codec = a_codec = None
    width = height = None
    fps = None
    has_v = has_a = False

    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and not has_v:
            has_v = True
            v_codec = s.get("codec_name")
            width = s.get("width")
            height = s.get("height")
            r = s.get("r_frame_rate") or s.get("avg_frame_rate") or "0/1"
            try:
                num, den = r.split("/")
                fps = float(num) / float(den) if float(den) != 0 else None
            except Exception:
                fps = None
        elif s.get("codec_type") == "audio" and not has_a:
            has_a = True
            a_codec = s.get("codec_name")

    return MediaInfo(
        path=p,
        duration_sec=duration,
        video_codec=v_codec,
        audio_codec=a_codec,
        width=width,
        height=height,
        fps=fps,
        has_video=has_v,
        has_audio=has_a,
    )


# ---------------------------------------------------------------------------
# Stall-detecting subprocess runner -- the core of run_ffmpeg
# ---------------------------------------------------------------------------


def _quote_cmd(cmd: list[str]) -> str:
    """Format a command list for inclusion in error messages."""
    return " ".join(f'"{a}"' if " " in a else a for a in cmd)


def _spawn_with_stall_detection(
    cmd: list[str],
    *,
    progress: Optional[ProgressCb],
    target_duration_sec: Optional[float],
    stall_threshold_sec: float,
    coalesce_interval_sec: float,
    parse_progress_blocks: bool,
) -> tuple[int, list[str], list[str]]:
    """Run `cmd` with a background stdout/stderr reader pair and stall detector.

    Returns `(returncode, stdout_lines, stderr_lines)`. Raises `FFmpegError`
    only on stall (the caller decides what to do with a non-zero rc).

    Why two reader threads instead of `subprocess.run(capture_output=True)`:

      `subprocess.run(capture_output=True)` does not drain the pipes until the
      process exits. ffmpeg with a verbose filter graph can write enough to
      stderr to fill the OS pipe buffer (typically 64 KB on Windows), at which
      point ffmpeg's next `write()` blocks forever -- waiting for us to read,
      while we're waiting for it to exit. The two processes are deadlocked.

      Reading both streams continuously in background threads keeps the pipes
      empty, so ffmpeg never blocks on write. This is the standard fix
      documented in the Python `subprocess` module docs.

    Why stall detection instead of an elapsed-time timeout:

      A legitimate 2-hour 4K HDR render shouldn't be killed just because it
      took longer than some arbitrary cap. The right signal is "is ffmpeg
      making forward progress?". With `-progress pipe:1` ffmpeg emits a
      key/value block every ~200 ms even at 0.3 fps -- so `last_activity`
      gets bumped frequently for any healthy render. 60 s of silence is the
      stall budget; trip it and we terminate.
    """
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    stderr_lines: list[str] = []
    stdout_lines: list[str] = []
    state_lock = threading.Lock()
    last_activity = time.monotonic()
    last_emit = 0.0

    def reader_stderr() -> None:
        nonlocal last_activity
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_lines.append(line)
            with state_lock:
                last_activity = time.monotonic()

    def reader_stdout() -> None:
        nonlocal last_activity, last_emit
        assert proc.stdout is not None
        block: dict[str, str] = {}
        for line in proc.stdout:
            stdout_lines.append(line)
            with state_lock:
                last_activity = time.monotonic()

            if not parse_progress_blocks or progress is None:
                continue

            stripped = line.strip()
            if not stripped or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            block[key] = value
            if key != "progress":
                continue

            is_final = value == "end"
            now = time.monotonic()
            if not is_final and (now - last_emit) < coalesce_interval_sec:
                block = {}
                continue
            last_emit = now

            out_us = 0
            for k in ("out_time_us", "out_time_ms"):
                raw = block.get(k)
                if raw is None:
                    continue
                try:
                    out_us = int(raw)
                except ValueError:
                    continue
                break
            out_sec = out_us / 1_000_000.0

            if target_duration_sec and target_duration_sec > 0:
                msg = f"encoding ({out_sec:.1f}s / {target_duration_sec:.1f}s)"
                cur, tot = int(out_sec), int(target_duration_sec)
            else:
                msg = f"encoding ({out_sec:.1f}s)"
                cur, tot = int(out_sec), 0

            try:
                progress(cur, tot, msg)
            except Exception:
                # A flaky callback (e.g. broken MCP client) must not abort
                # the render. Progress is best-effort.
                pass
            block = {}

    t_err = threading.Thread(target=reader_stderr, daemon=True)
    t_out = threading.Thread(target=reader_stdout, daemon=True)
    t_err.start()
    t_out.start()

    try:
        while True:
            rc = proc.poll()
            if rc is not None:
                break
            with state_lock:
                stalled = (time.monotonic() - last_activity) > stall_threshold_sec
            if stalled:
                proc.terminate()
                try:
                    proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    try:
                        proc.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        pass
                t_err.join(timeout=1.0)
                t_out.join(timeout=1.0)
                raise FFmpegError(
                    f"ffmpeg stalled: no output for {stall_threshold_sec:.0f}s "
                    f"(likely deadlocked filter graph or wedged input). "
                    f"Process killed.\n  command: {_quote_cmd(cmd)}"
                )
            time.sleep(0.25)
    finally:
        # Drain readers so the threads exit cleanly. They will see EOF as
        # soon as the OS closes the pipes after process exit.
        t_err.join(timeout=2.0)
        t_out.join(timeout=2.0)

    return proc.returncode, stdout_lines, stderr_lines


def run_ffmpeg(
    args: list[str],
    *,
    quiet: bool = True,
    progress: Optional[ProgressCb] = None,
    target_duration_sec: Optional[float] = None,
    stall_threshold_sec: float = _DEFAULT_STALL_SEC,
    coalesce_interval_sec: float = _DEFAULT_COALESCE_SEC,
) -> None:
    """Run an ffmpeg invocation (args after the program name).

    Two failure modes the caller cares about, both raised as `FFmpegError`:

      * ffmpeg exits non-zero -- last 25 stderr lines included in the message.
      * ffmpeg emits no output for `stall_threshold_sec` seconds -- we kill
        it and report the stall (this catches infinite-source deadlocks,
        wedged network inputs, and pipe-buffer deadlocks).

    When `progress` is given, ffmpeg is invoked with `-progress pipe:1
    -nostats` and the callback fires at most every `coalesce_interval_sec`
    seconds with `(cur_sec, total_sec, "encoding (1.5s / 8.3s)")`. If the
    caller knows the target duration ahead of time it should pass
    `target_duration_sec`; otherwise the message contains only the elapsed
    encoded time.
    """
    if not have_ffmpeg():
        raise FFmpegError("ffmpeg not found on PATH. Run `videopilot doctor`.")
    cmd = ["ffmpeg", "-y", "-hide_banner"]
    if quiet:
        cmd += ["-loglevel", "error"]
    # `-progress pipe:1 -nostats` is the canonical way to ask ffmpeg for
    # structured progress output. Even if the caller doesn't want progress
    # callbacks we still ask for it: the steady stream of `frame=...` blocks
    # is the stall detector's heartbeat. Without it, a render that runs
    # silently at `-loglevel error` for 60 s would be killed as "stalled".
    cmd += ["-progress", "pipe:1", "-nostats"]
    cmd += args

    rc, _stdout, stderr_lines = _spawn_with_stall_detection(
        cmd,
        progress=progress,
        target_duration_sec=target_duration_sec,
        stall_threshold_sec=stall_threshold_sec,
        coalesce_interval_sec=coalesce_interval_sec,
        parse_progress_blocks=True,
    )

    if rc != 0:
        tail = "".join(stderr_lines).strip().splitlines()[-25:]
        raise FFmpegError(
            "ffmpeg failed:\n  command: "
            + _quote_cmd(cmd)
            + "\n  stderr (tail):\n    "
            + "\n    ".join(tail)
        )


def run_ffmpeg_capture_stderr(
    args: list[str],
    *,
    stall_threshold_sec: float = _DEFAULT_STALL_SEC,
) -> str:
    """Run ffmpeg and return its stderr (used by silencedetect parsing).

    Uses the same Popen + dual-reader pattern as `run_ffmpeg`: silencedetect
    emits one line per detected event for the entire input, which on a long
    video can easily exceed the OS pipe buffer and deadlock the classic
    `subprocess.run(capture_output=True)` pattern.
    """
    if not have_ffmpeg():
        raise FFmpegError("ffmpeg not found on PATH. Run `videopilot doctor`.")
    cmd = ["ffmpeg", "-hide_banner", "-nostats"] + args
    _rc, _stdout, stderr_lines = _spawn_with_stall_detection(
        cmd,
        progress=None,
        target_duration_sec=None,
        stall_threshold_sec=stall_threshold_sec,
        coalesce_interval_sec=_DEFAULT_COALESCE_SEC,
        parse_progress_blocks=False,
    )
    return "".join(stderr_lines)
