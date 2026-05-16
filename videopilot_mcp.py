"""videopilot MCP server.

Exposes the videopilot engine as MCP tools so an agent host (Copilot, Claude,
Cursor, Continue.dev, ...) can drive video creation through typed tool calls
instead of shelling out to the CLI.

Launch (after `pip install videopilot` or via `uvx`):

    videopilot-mcp

The companion plugin's `.mcp.json` registers this command for the agent host.

Tools mirror the CLI subcommands. Long-running tools (`tts`, `transcribe`,
`compose`, `cut`, `silence`) run on a worker thread so they neither block the
FastMCP request loop nor crash on nested `asyncio.run()` calls inside lib
modules, and they stream `Context.report_progress` heartbeats so MCP clients
don't time out (-32001). Helper tools (`read_state`, `write_state`) let the
agent author the per-project JSON state files.
"""

from __future__ import annotations

import asyncio
import inspect
import io
import json
import os
import sys
import threading
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Callable, Optional

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from lib import (  # noqa: E402  (must happen after sys.path tweak)
    compose as compose_mod,
    cut as cut_mod,
    doctor as doctor_mod,
    export as export_mod,
    init_cmd,
    silence as silence_mod,
    transcribe as transcribe_mod,
    tts as tts_mod,
    voices as voices_mod,
)

try:
    from mcp.server.fastmcp import Context, FastMCP
except ImportError:
    sys.stderr.write(
        "videopilot-mcp requires the 'mcp' Python package.\n"
        "Install with:  pip install --user 'mcp>=1.0'\n"
        "or run via:    uvx videopilot-mcp\n"
    )
    raise


_STATE_FILES = {
    "project": "project.json",
    "script": "script.json",
    "cut-plan": "cut-plan.json",
    "compose-plan": "compose-plan.json",
}

_WRITABLE_STATE = {"script", "cut-plan", "compose-plan"}


def _projects_root(override: Optional[str]) -> Path:
    """Resolve the projects/ directory.

    Precedence: explicit arg -> $VIDEOPILOT_PROJECTS env var -> ./projects.
    """
    if override:
        return Path(override).expanduser().resolve()
    env = os.environ.get("VIDEOPILOT_PROJECTS")
    if env:
        return Path(env).expanduser().resolve()
    return (Path.cwd() / "projects").resolve()


def _project_dir(root: Path, slug: str) -> Path:
    return root / slug


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return {"__parse_error__": str(e)}


def _capture(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> tuple[int, str]:
    """Run a sync lib `.run()` function while capturing stdout+stderr."""
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(buf):
        try:
            rc = fn(*args, **kwargs)
        except SystemExit as e:
            rc = int(e.code or 0)
    return int(rc or 0), buf.getvalue()


async def _run_threaded(
    fn: Callable[..., Any],
    *args: Any,
    ctx: Optional[Context] = None,
    **kwargs: Any,
) -> tuple[int, str]:
    """Run a sync lib `.run()` on a worker thread, bridging its `progress`
    callback to `ctx.report_progress` so MCP clients keep the request alive.

    The helper inspects ``fn``'s signature: if it accepts ``progress``, a
    thread-safe callback is injected. Otherwise the call is forwarded as-is.
    Stdout + stderr are captured and returned alongside the exit code.
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[Any, ...]] = asyncio.Queue()

    def thread_progress(current: int, total: int, message: str = "") -> None:
        loop.call_soon_threadsafe(
            queue.put_nowait, ("progress", current, total, message)
        )

    sig = inspect.signature(fn)
    accepts_progress = "progress" in sig.parameters

    def worker() -> None:
        buf = io.StringIO()
        rc = 0
        try:
            with redirect_stdout(buf), redirect_stderr(buf):
                call_kwargs = dict(kwargs)
                if accepts_progress:
                    call_kwargs["progress"] = thread_progress
                rc = fn(*args, **call_kwargs) or 0
        except SystemExit as e:
            rc = int(e.code or 0)
        except BaseException as e:  # noqa: BLE001
            loop.call_soon_threadsafe(
                queue.put_nowait, ("error", e, buf.getvalue())
            )
            return
        loop.call_soon_threadsafe(
            queue.put_nowait, ("done", int(rc), buf.getvalue())
        )

    threading.Thread(target=worker, daemon=True).start()

    while True:
        evt = await queue.get()
        kind = evt[0]
        if kind == "progress":
            _, cur, total, msg = evt
            if ctx is not None:
                try:
                    await ctx.report_progress(
                        progress=float(cur),
                        total=float(total) if total else None,
                        message=msg or None,
                    )
                except Exception:  # noqa: BLE001 -- never let a flaky client kill a render
                    pass
        elif kind == "done":
            _, rc, log = evt
            return int(rc), log
        elif kind == "error":
            _, exc, log = evt
            # Surface captured output before re-raising so the agent has context.
            sys.stderr.write(log)
            raise exc


def _status(slug: str, project_root: Optional[str]) -> dict:
    root = _projects_root(project_root)
    proj = _project_dir(root, slug)
    if not proj.exists():
        return {"exists": False, "slug": slug, "path": str(proj)}

    state = {key: _read_json(proj / fname) for key, fname in _STATE_FILES.items()}
    voice_manifest = _read_json(proj / "voice" / "manifest.json")
    clips_manifest = _read_json(proj / "clips" / "manifest.json")
    final = proj / "out" / "final.mp4"

    return {
        "exists": True,
        "slug": slug,
        "path": str(proj),
        "state": state,
        "voice_manifest": voice_manifest,
        "clips_manifest": clips_manifest,
        "final_path": str(final) if final.exists() else None,
    }


mcp = FastMCP("videopilot")


@mcp.tool()
def doctor() -> dict:
    """Verify that ffmpeg, ffprobe, edge-tts, faster-whisper, and (optionally)
    Azure Speech credentials are available on this machine. Returns the log
    text and a boolean ok flag. Call this once before starting a project.
    """
    rc, log = _capture(doctor_mod.run)
    return {"exit_code": rc, "ok": rc == 0, "log": log}


@mcp.tool()
def voices(engine: str = "edge-tts", locale: Optional[str] = None) -> dict:
    """List available neural TTS voices.

    Args:
        engine: "edge-tts" (default, free) or "azure" (needs AZURE_SPEECH_KEY).
        locale: Optional locale filter, e.g. "en-US".
    """
    rc, log = _capture(voices_mod.run, engine=engine, locale=locale)
    return {"exit_code": rc, "log": log}


@mcp.tool()
def list_projects(project_root: Optional[str] = None) -> dict:
    """List all videopilot projects under the projects/ directory."""
    root = _projects_root(project_root)
    if not root.exists():
        return {"projects_root": str(root), "projects": []}
    projects = []
    for d in sorted(root.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        projects.append(
            {
                "slug": d.name,
                "has_script": (d / "script.json").exists(),
                "has_voices": (d / "voice").exists(),
                "has_clips": (d / "clips").exists(),
                "has_final": (d / "out" / "final.mp4").exists(),
            }
        )
    return {"projects_root": str(root), "projects": projects}


@mcp.tool()
def project_status(slug: str, project_root: Optional[str] = None) -> dict:
    """Pipeline status for one project: which JSON state files exist, which
    intermediates have been generated (voiceovers, clips), and whether the
    final video is rendered.
    """
    return _status(slug, project_root)


@mcp.tool()
def init(
    slug: str,
    source: Optional[list[str]] = None,
    name: Optional[str] = None,
    project_root: Optional[str] = None,
) -> dict:
    """Create a new project.

    Args:
        slug: Project identifier (kebab-case, no spaces).
        source: Optional list of source video paths to import as the first sources.
        name: Optional display name.
        project_root: Override the default projects/ directory.

    Returns:
        Pipeline status after init (includes paths to the empty state files
        the agent should now populate).
    """
    root = _projects_root(project_root)
    rc, log = _capture(
        init_cmd.run, root, slug, name=name, sources=source or []
    )
    out = _status(slug, project_root)
    out["exit_code"] = rc
    out["log"] = log
    return out


@mcp.tool()
def import_source(
    slug: str,
    path: str,
    source_id: Optional[str] = None,
    project_root: Optional[str] = None,
) -> dict:
    """Add another source video to an existing project."""
    root = _projects_root(project_root)
    rc, log = _capture(
        init_cmd.import_source, root, slug, path, source_id=source_id
    )
    out = _status(slug, project_root)
    out["exit_code"] = rc
    out["log"] = log
    return out


@mcp.tool()
def read_state(
    slug: str,
    file: str,
    project_root: Optional[str] = None,
) -> dict:
    """Read one of the per-project JSON state files.

    Args:
        slug: Project identifier.
        file: One of "project", "script", "cut-plan", "compose-plan".
        project_root: Override the default projects/ directory.
    """
    if file not in _STATE_FILES:
        return {
            "error": f"Unknown state file '{file}'. Use one of: {list(_STATE_FILES)}"
        }
    root = _projects_root(project_root)
    path = _project_dir(root, slug) / _STATE_FILES[file]
    return {"path": str(path), "exists": path.exists(), "content": _read_json(path)}


@mcp.tool()
def write_state(
    slug: str,
    file: str,
    content: dict,
    project_root: Optional[str] = None,
) -> dict:
    """Write one of the per-project JSON state files.

    Use this to author the voiceover script, the cut plan, or the compose
    timeline. The engine reads these files on the next tts / cut / compose call.

    Args:
        slug: Project identifier.
        file: One of "script", "cut-plan", "compose-plan". (project.json is
            read-only -- it is managed by the engine.)
        content: The full new content for the file (any prior content is
            replaced).
        project_root: Override the default projects/ directory.
    """
    if file not in _WRITABLE_STATE:
        return {
            "error": (
                f"Cannot write '{file}'. Allowed: {sorted(_WRITABLE_STATE)}. "
                "project.json is managed by the engine."
            )
        }
    root = _projects_root(project_root)
    proj = _project_dir(root, slug)
    if not proj.exists():
        return {"error": f"Project not found: {proj}. Call init first."}
    path = proj / _STATE_FILES[file]
    path.write_text(json.dumps(content, indent=2) + "\n", encoding="utf-8")
    return {"written": True, "path": str(path)}


# ---------------------------------------------------------------------------
# Long-running tools (threaded + progress-streaming)
# ---------------------------------------------------------------------------


@mcp.tool()
async def tts(
    slug: str,
    only: Optional[list[str]] = None,
    force: bool = False,
    project_root: Optional[str] = None,
    ctx: Optional[Context] = None,
) -> dict:
    """Synthesise voiceover MP3s from script.json.

    Args:
        slug: Project identifier.
        only: Limit to these script segment ids.
        force: Regenerate even if output already exists.
    """
    root = _projects_root(project_root)
    rc, log = await _run_threaded(
        tts_mod.run,
        root,
        slug,
        only=only or [],
        force=force,
        ctx=ctx,
    )
    manifest = _read_json(_project_dir(root, slug) / "voice" / "manifest.json")
    return {"exit_code": rc, "log": log, "voice_manifest": manifest}


@mcp.tool()
async def transcribe(
    slug: str,
    source_id: str,
    model: str = "base",
    language: Optional[str] = None,
    project_root: Optional[str] = None,
    ctx: Optional[Context] = None,
) -> dict:
    """Transcribe a source with faster-whisper. Emits word-level transcript
    JSON + SRT into transcripts/.

    Args:
        slug: Project identifier.
        source_id: Source id to transcribe (e.g. "raw1").
        model: faster-whisper model size: tiny | base | small | medium | large-v3.
        language: ISO code, e.g. "en". Auto-detect if omitted.
    """
    root = _projects_root(project_root)
    rc, log = await _run_threaded(
        transcribe_mod.run,
        root,
        slug,
        source_id,
        model=model,
        language=language,
        ctx=ctx,
    )
    tx_path = _project_dir(root, slug) / "transcripts" / f"{source_id}.json"
    return {
        "exit_code": rc,
        "log": log,
        "transcript_path": str(tx_path),
        "transcript": _read_json(tx_path),
    }


@mcp.tool()
async def silence(
    slug: str,
    source_id: str,
    threshold_db: float = -35.0,
    min_silence_sec: float = 1.0,
    output: Optional[str] = None,
    project_root: Optional[str] = None,
    ctx: Optional[Context] = None,
) -> dict:
    """Run ffmpeg silencedetect on a source and emit a cut-plan candidate
    that keeps only the non-silent spans."""
    root = _projects_root(project_root)
    rc, log = await _run_threaded(
        silence_mod.run,
        root,
        slug,
        source_id,
        threshold_db=threshold_db,
        min_silence_sec=min_silence_sec,
        output=output,
        ctx=ctx,
    )
    cand_path = (
        Path(output) if output else _project_dir(root, slug) / "cut-plan.candidate.json"
    )
    return {
        "exit_code": rc,
        "log": log,
        "candidate_path": str(cand_path),
        "candidate": _read_json(cand_path),
    }


@mcp.tool()
async def cut(
    slug: str,
    only: Optional[list[str]] = None,
    force: bool = False,
    stream_copy: bool = False,
    project_root: Optional[str] = None,
    ctx: Optional[Context] = None,
) -> dict:
    """Cut clips per cut-plan.json.

    Args:
        slug: Project identifier.
        only: Limit to these clip ids.
        force: Re-cut even if output already exists.
        stream_copy: Skip re-encoding (fast, but cuts snap to keyframes).
    """
    root = _projects_root(project_root)
    rc, log = await _run_threaded(
        cut_mod.run,
        root,
        slug,
        only=only or [],
        force=force,
        stream_copy=stream_copy,
        ctx=ctx,
    )
    manifest = _read_json(_project_dir(root, slug) / "clips" / "manifest.json")
    return {"exit_code": rc, "log": log, "clips_manifest": manifest}


@mcp.tool()
async def compose(
    slug: str,
    project_root: Optional[str] = None,
    ctx: Optional[Context] = None,
) -> dict:
    """Render final video per compose-plan.json. May take minutes for long videos."""
    root = _projects_root(project_root)
    rc, log = await _run_threaded(compose_mod.run, root, slug, ctx=ctx)
    final = _project_dir(root, slug) / "out" / "final.mp4"
    return {
        "exit_code": rc,
        "log": log,
        "final_path": str(final) if final.exists() else None,
    }


@mcp.tool()
def export(
    slug: str,
    edl: bool = False,
    fcpxml: bool = False,
    script: bool = False,
    project_root: Optional[str] = None,
) -> dict:
    """Emit NLE projects (EDL / FCPXML) and/or a replayable render script for
    the composed timeline.
    """
    root = _projects_root(project_root)
    rc, log = _capture(
        export_mod.run, root, slug, edl=edl, fcpxml=fcpxml, script=script
    )
    out_dir = _project_dir(root, slug) / "out"
    exports: dict[str, Optional[str]] = {
        "edl": (
            str(out_dir / "final.edl")
            if edl and (out_dir / "final.edl").exists()
            else None
        ),
        "fcpxml": (
            str(out_dir / "final.fcpxml")
            if fcpxml and (out_dir / "final.fcpxml").exists()
            else None
        ),
        "script": (
            str(out_dir / "render.ps1")
            if script and (out_dir / "render.ps1").exists()
            else None
        ),
    }
    return {"exit_code": rc, "log": log, "exports": exports}


def main() -> int:
    """Console-script entrypoint for `videopilot-mcp`.

    With no arguments, runs the MCP stdio server (the normal mode used by the
    agent host). Supports a tiny set of flags so `uvx videopilot-mcp --version`
    can pre-warm the uvx cache without blocking on stdin.
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="videopilot-mcp",
        description=(
            "videopilot MCP server -- exposes the videopilot engine "
            "(ffmpeg, edge-tts, faster-whisper) as MCP tools over stdio. "
            "Run with no arguments to start the stdio server."
        ),
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print version and exit (useful for pre-warming uvx cache).",
    )
    args = parser.parse_args()

    if args.version:
        try:
            from importlib.metadata import version as _pkg_version

            print(f"videopilot-mcp {_pkg_version('videopilot')}")
        except Exception:  # noqa: BLE001
            print("videopilot-mcp (version unknown)")
        return 0

    mcp.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
