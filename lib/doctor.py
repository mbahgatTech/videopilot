"""`videopilot doctor` -- check prerequisites and print a status report."""

from __future__ import annotations

import importlib.metadata
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


def _pkg_version(dist_name: str) -> str:
    """Return the installed version of a distribution without importing it.

    Reading version from package metadata (PKG-INFO / METADATA) is fast and
    side-effect-free. The previous implementation called
    `importlib.import_module(...)` here, which forced a full module import --
    fine for pure-Python libs (edge-tts) but catastrophic for libraries with
    heavy native extensions (faster-whisper pulls in CTranslate2 + onnxruntime
    + tokenizers DLLs). When called from the MCP worker thread on a fresh
    process, that import can stall for >15s and trip the client timeout.
    """
    try:
        return importlib.metadata.version(dist_name)
    except importlib.metadata.PackageNotFoundError:
        return "?"


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
    # Pairs of (module-import-name, distribution-name on PyPI).
    # find_spec() answers "is the module importable?" using only the importer
    # and metadata.version() answers "what version was installed?" without
    # actually importing the module -- so heavy native libs (faster-whisper)
    # never have to execute their __init__ in a redirected/threaded context.
    for pkg, dist in [
        ("edge_tts", "edge-tts"),
        ("faster_whisper", "faster-whisper"),
    ]:
        if _have_pkg(pkg):
            _ok(f"{dist} ({_pkg_version(dist)})")
        else:
            _bad(f"{dist} not installed. `pip install -r requirements.txt`")
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
            # Bounded timeout: `ffmpeg -version` normally returns in <100ms.
            # The 10s cap prevents a wedged / broken binary from stalling the
            # MCP `doctor` call indefinitely (a heartbeat keeps the client
            # alive, but it shouldn't mask a real hang forever).
            out = subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            first = (out.stdout or "").splitlines()[0] if out.stdout else "?"
            _ok(first)
        except subprocess.TimeoutExpired:
            _warn("`ffmpeg -version` did not return within 10s (binary may be hung)")
        except Exception as exc:
            _warn(f"ffmpeg present but `-version` failed: {exc}")

    print()
    if failures:
        print(f"{failures} check(s) failed. Fix the [FAIL] items above and re-run.")
        return 1
    print("All required checks passed. You're good to go.")
    return 0
