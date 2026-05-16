"""`videopilot doctor` — check prerequisites and print a status report."""

from __future__ import annotations

import importlib
import importlib.util
import os
import shutil

from . import ffmpeg_wrap


def _ok(msg: str) -> None:
    print(f"  [OK]    {msg}")


def _warn(msg: str) -> None:
    print(f"  [WARN]  {msg}")


def _bad(msg: str) -> None:
    print(f"  [FAIL]  {msg}")


def _have_pkg(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def run() -> int:
    print("video-creator prerequisite check")
    print("=" * 50)

    failures = 0

    # Trigger PATH augmentation (WinGet Gyan.FFmpeg auto-detect) before lookup.
    ffmpeg_wrap.have_ffmpeg()

    print("\nBinaries on PATH:")
    if shutil.which("ffmpeg"):
        _ok(f"ffmpeg: {shutil.which('ffmpeg')}")
    else:
        _bad("ffmpeg not found. Install: `winget install --id Gyan.FFmpeg -e`")
        failures += 1
    if shutil.which("ffprobe"):
        _ok(f"ffprobe: {shutil.which('ffprobe')}")
    else:
        _bad("ffprobe not found (ships with ffmpeg).")
        failures += 1

    print("\nPython packages:")
    for pkg, friendly in [
        ("edge_tts", "edge-tts"),
        ("faster_whisper", "faster-whisper"),
    ]:
        if _have_pkg(pkg):
            try:
                mod = importlib.import_module(pkg)
                ver = getattr(mod, "__version__", "?")
                _ok(f"{friendly} ({ver})")
            except Exception as exc:
                _warn(f"{friendly} importable but errored: {exc}")
        else:
            _bad(f"{friendly} not installed. `pip install -r requirements.txt`")
            failures += 1

    print("\nOptional packages:")
    if _have_pkg("azure.cognitiveservices.speech"):
        _ok("azure-cognitiveservices-speech installed (engine: azure available)")
    else:
        _warn("azure-cognitiveservices-speech not installed (only matters if you set engine: azure)")

    print("\nAzure Speech credentials (optional):")
    if os.environ.get("AZURE_SPEECH_KEY") and os.environ.get("AZURE_SPEECH_REGION"):
        _ok(f"AZURE_SPEECH_KEY set, region={os.environ['AZURE_SPEECH_REGION']}")
    else:
        _warn("AZURE_SPEECH_KEY / AZURE_SPEECH_REGION not set (edge-tts still works)")

    print("\nffmpeg quick probe:")
    if shutil.which("ffmpeg"):
        try:
            import subprocess
            out = subprocess.run(
                ["ffmpeg", "-version"], capture_output=True, text=True
            )
            first = (out.stdout or "").splitlines()[0] if out.stdout else "?"
            _ok(first)
        except Exception as exc:
            _warn(f"ffmpeg present but `-version` failed: {exc}")

    print()
    if failures:
        print(f"{failures} check(s) failed. Fix the [FAIL] items above and re-run.")
        return 1
    print("All required checks passed. You're good to go.")
    return 0
