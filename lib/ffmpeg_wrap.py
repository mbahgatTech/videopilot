"""ffmpeg / ffprobe subprocess wrappers used throughout the tool."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class FFmpegError(RuntimeError):
    """ffmpeg or ffprobe returned non-zero."""


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
    result = subprocess.run(cmd, capture_output=True, text=True)
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


def run_ffmpeg(args: list[str], *, quiet: bool = True) -> None:
    """Run an ffmpeg invocation (args after the program name)."""
    if not have_ffmpeg():
        raise FFmpegError("ffmpeg not found on PATH. Run `videopilot doctor`.")
    cmd = ["ffmpeg", "-y", "-hide_banner"]
    if quiet:
        cmd += ["-loglevel", "error"]
    cmd += args
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        tail = (result.stderr or "").strip().splitlines()[-25:]
        raise FFmpegError(
            "ffmpeg failed:\n  command: "
            + " ".join(f'"{a}"' if " " in a else a for a in cmd)
            + "\n  stderr (tail):\n    "
            + "\n    ".join(tail)
        )


def run_ffmpeg_capture_stderr(args: list[str]) -> str:
    """Run ffmpeg and return its stderr (used by silencedetect parsing)."""
    if not have_ffmpeg():
        raise FFmpegError("ffmpeg not found on PATH. Run `videopilot doctor`.")
    cmd = ["ffmpeg", "-hide_banner", "-nostats"] + args
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stderr or ""
