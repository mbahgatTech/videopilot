"""videopilot MCP server.

Exposes the videopilot engine as MCP tools so an agent host (Copilot, Claude,
Cursor, Continue.dev, ...) can drive video creation through typed tool calls
instead of shelling out to the CLI.

Launch (after `pip install videopilot` or via `uvx`):

    videopilot-mcp

The companion plugin's `.mcp.json` registers this command for the agent host.

Tools mirror the CLI subcommands. Every tool that drives a lib `.run()`
function -- short or long, pure-Python or `asyncio.run()`-using or
subprocess-shelling -- executes on a worker thread via `_run_threaded`. This
gives every tool four properties for free:

  1. Nested `asyncio.run(...)` inside the lib (edge-tts, voices) succeeds
     because the worker thread has no pre-existing event loop.
  2. Long-running lib work (tts, compose, transcribe, large file copies in
     `import_source`) never blocks FastMCP's request loop -- the loop stays
     free to handle other requests and pump notifications.
  3. The MCP client receives a `Context.report_progress` heartbeat every
     ``_HEARTBEAT_INTERVAL_SEC`` seconds for the lifetime of the worker, so
     long calls survive the client's -32001 idle timeout.
  4. Exceptions inside the lib are caught and returned as `(rc=1, log+tb)`
     instead of being re-raised. FastMCP's default exception handler would
     otherwise discard the captured stdout in favor of a bare "Error
     executing tool X: <repr>", hiding the diagnostic output the agent
     needs to recover.

Helper tools (`read_state`, `write_state`, `add_vo_segment`, `add_slide`,
`set_compose_output`) let the agent author the per-project JSON state files.
`schema()`, `preview_slide()`, and `is_up_to_date()` round out the surface for
discovery, fast feedback, and idempotency probing.
"""

from __future__ import annotations

import asyncio
import inspect
import io
import traceback
import json
import os
import sys
import threading
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from lib import (
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

_DEFAULT_VOICE_DEFAULTS: dict[str, str] = {
    "engine": "edge-tts",
    "voice": "en-US-AndrewMultilingualNeural",
    "rate": "+0%",
    "pitch": "+0Hz",
}

_DEFAULT_COMPOSE_OUTPUT: dict[str, Any] = {
    "filename": "final.mp4",
    "resolution": "1920x1080",
    "fps": 30,
    "video_bitrate": "8M",
    "audio_bitrate": "192k",
    "video_codec": "libx264",
    "audio_codec": "aac",
}


# ---------------------------------------------------------------------------
# Path / IO helpers
# ---------------------------------------------------------------------------


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


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _mtime(path: Path) -> Optional[float]:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Sync + threaded execution helpers
# ---------------------------------------------------------------------------

# Wall-clock interval between MCP `report_progress` heartbeats emitted by
# `_run_threaded` when the wrapped lib function isn't generating its own
# progress events. The MCP request timeout (-32001) defaults to ~30-60s in
# typical clients (Copilot, Claude, Continue.dev), so 5s gives a comfortable
# 6-12x safety margin -- chatty enough to keep keep-alive happy, sparse enough
# not to flood the client's progress UI.
_HEARTBEAT_INTERVAL_SEC = 5.0

# `redirect_stdout` / `redirect_stderr` swap the *process-global* `sys.stdout`
# and `sys.stderr`. The MCP stdio transport also writes its framed JSON-RPC
# messages to `sys.stdout`, so two captured-output tool calls running in
# parallel could:
#   - interleave each other's captured logs, OR
#   - leak lib `print()` output into the MCP transport and break framing.
# A single module-level lock serialises any stdout/stderr capture across all
# `_run_threaded` workers. The performance cost is bounded by typical agent
# behaviour (tool calls already happen sequentially).
_CAPTURE_LOCK = threading.Lock()


async def _run_threaded(
    fn: Callable[..., Any],
    *args: Any,
    ctx: Optional[Context] = None,
    **kwargs: Any,
) -> tuple[int, str]:
    """Run a sync lib `.run()` on a worker thread, streaming MCP progress.

    Four invariants hold for every caller:

    1. The wrapped function runs on a freshly-spawned `threading.Thread`, so
       any nested `asyncio.run(...)` it does (edge-tts, voices, ...) sees an
       empty event-loop slot and succeeds. This is the original "no nested
       event loop" fix.

    2. The MCP client receives a `ctx.report_progress` notification at least
       every ``_HEARTBEAT_INTERVAL_SEC`` seconds for as long as the worker is
       alive. If ``fn`` accepts a ``progress`` keyword argument, its
       structured events ride alongside the heartbeats; otherwise the
       heartbeat is the only signal -- which is exactly what we need for
       lib functions that pre-date the `progress` contract (``cut``,
       ``silence``, ``voices``, ``doctor``, ...).

    3. The wire `progress` value emitted to MCP is monotonically increasing
       (a private ``tick`` counter incremented on every emit). The lib's own
       ``current / total`` numbers may dip / repeat / overshoot -- they get
       embedded in the human-readable message instead, so the MCP spec's
       monotonicity rule is never violated.

    4. This coroutine **never raises**: it always returns ``(rc, log)``. When
       ``fn`` raises, ``rc`` is set to ``1`` and the traceback is appended to
       the captured ``log``. This is critical for agent UX -- FastMCP's
       default exception handler discards the captured stdout/stderr and
       replaces the response with ``"Error executing tool X: <repr>"``, which
       hides the diagnostic output the agent needs to recover (e.g. tts
       prints "Synthesizing 3 segments... vo-1 done... ffprobe missing" --
       the agent should see all of that, not just the final raise).

    `wire total` is always `None`: pairing a synthetic monotonic tick with
    the lib's `total` would make tick blow past total (e.g. tts total=1,
    heartbeats keep ticking 2, 3, 4...) and some clients enforce
    `progress <= total`. The lib's `cur/total` lives in the message instead.

    Stdout + stderr are captured behind `_CAPTURE_LOCK` and returned alongside
    the exit code.
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
            with _CAPTURE_LOCK:
                with redirect_stdout(buf), redirect_stderr(buf):
                    call_kwargs = dict(kwargs)
                    if accepts_progress:
                        call_kwargs["progress"] = thread_progress
                    try:
                        rc = fn(*args, **call_kwargs) or 0
                    except SystemExit as e:
                        # Libs use `raise SystemExit("message")` for clean
                        # failures with a non-zero code. Surface the code AND
                        # the message text in the captured log.
                        rc = int(e.code) if isinstance(e.code, int) else 1
                        if e.code and not isinstance(e.code, int):
                            print(f"\n{e.code}", file=sys.stderr)
                    except Exception:
                        # Any other exception -- record traceback in the log
                        # and fail with rc=1. The async receive loop turns
                        # this into a normal `(rc, log)` return so the agent
                        # sees the full captured diagnostic.
                        rc = 1
                        print(
                            "\n--- traceback ---\n" + traceback.format_exc(),
                            file=sys.stderr,
                        )
        except BaseException:
            # Anything that escapes the redirect block -- e.g. the lock
            # acquire was interrupted -- still has to deliver a structured
            # result. Re-raising into the asyncio loop would freeze the
            # coroutine indefinitely.
            rc = 1
            buf.write("\n--- worker-level traceback ---\n")
            buf.write(traceback.format_exc())
        loop.call_soon_threadsafe(
            queue.put_nowait, ("done", int(rc), buf.getvalue())
        )

    threading.Thread(target=worker, daemon=True).start()

    tick = 0
    last_lib_message = "working"
    start = loop.time()

    async def emit(message: str) -> None:
        nonlocal tick
        tick += 1
        if ctx is None:
            return
        try:
            await ctx.report_progress(
                progress=float(tick),
                total=None,
                message=message,
            )
        except Exception:
            # Never let a flaky client kill a render: progress notifications
            # are best-effort heartbeats, not part of the tool's contract.
            pass

    # Immediate "we're alive" tick so clients with very aggressive keep-alives
    # don't go a full heartbeat interval seeing nothing.
    await emit("starting")

    while True:
        try:
            evt = await asyncio.wait_for(
                queue.get(), timeout=_HEARTBEAT_INTERVAL_SEC
            )
        except asyncio.TimeoutError:
            elapsed = int(loop.time() - start)
            await emit(f"{last_lib_message} (still working, {elapsed}s elapsed)")
            continue

        kind = evt[0]
        if kind == "progress":
            _, cur, total, msg = evt
            if msg:
                last_lib_message = msg
            detail = msg or "progress"
            if total:
                detail = f"{detail} ({cur}/{total})"
            await emit(detail)
        elif kind == "done":
            _, rc, log = evt
            return int(rc), log


# ---------------------------------------------------------------------------
# Status snapshot
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Short tools (kept on the request thread; threaded only where the lib calls
# `asyncio.run()` internally or invokes blocking subprocesses)
# ---------------------------------------------------------------------------


@mcp.tool()
async def doctor(ctx: Optional[Context] = None) -> dict:
    """Verify that ffmpeg, ffprobe, edge-tts, faster-whisper, and (optionally)
    Azure Speech credentials are available on this machine. Returns the log
    text and a boolean ok flag. Call this once before starting a project.

    Runs on a worker thread because it shells out to `ffmpeg -version` -- on
    a slow / missing-PATH machine that subprocess can stall briefly, and
    blocking the FastMCP event loop trips the client's -32001 request
    timeout. The thread also unlocks heartbeat streaming via `_run_threaded`.
    """
    rc, log = await _run_threaded(doctor_mod.run, ctx=ctx)
    return {"exit_code": rc, "ok": rc == 0, "log": log}


@mcp.tool()
async def voices(
    engine: str = "edge-tts",
    locale: Optional[str] = None,
    ctx: Optional[Context] = None,
) -> dict:
    """List available neural TTS voices.

    Args:
        engine: "edge-tts" (default, free) or "azure" (needs AZURE_SPEECH_KEY).
        locale: Optional locale filter, e.g. "en-US".

    Runs on a worker thread because `lib/voices.py` calls
    `asyncio.run(edge_tts.list_voices())` internally; doing that on the
    FastMCP request loop raises "asyncio.run() cannot be called from a
    running event loop". The worker thread has no event loop of its own, so
    the nested `asyncio.run` works as designed.
    """
    rc, log = await _run_threaded(
        voices_mod.run, ctx=ctx, engine=engine, locale=locale
    )
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
async def init(
    slug: str,
    source: Optional[list[str]] = None,
    name: Optional[str] = None,
    project_root: Optional[str] = None,
    ctx: Optional[Context] = None,
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
    rc, log = await _run_threaded(
        init_cmd.run, root, slug, name=name, sources=source or [], ctx=ctx
    )
    out = _status(slug, project_root)
    out["exit_code"] = rc
    out["log"] = log
    return out


@mcp.tool()
async def import_source(
    slug: str,
    path: str,
    source_id: Optional[str] = None,
    project_root: Optional[str] = None,
    ctx: Optional[Context] = None,
) -> dict:
    """Add another source video to an existing project.

    Runs on a worker thread because `shutil.copy2` of a multi-GB source file
    can take several seconds, and any blocking call on FastMCP's event loop
    silently freezes every other request until the MCP client gives up with
    a -32001 timeout. Heartbeats keep the request alive for the duration.
    """
    root = _projects_root(project_root)
    rc, log = await _run_threaded(
        init_cmd.import_source, root, slug, path, source_id=source_id, ctx=ctx
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

    Returns a SUMMARY of the transcript -- the full segment list can be huge
    (hundreds of KB) so it is intentionally not inlined. Read the file at
    ``transcript_path`` if you need every word.
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
    proj = _project_dir(root, slug)
    tx_path = proj / "transcripts" / f"{source_id}.json"
    srt_path = proj / "transcripts" / f"{source_id}.srt"
    data = _read_json(tx_path) or {}
    segments_list = data.get("segments", []) if isinstance(data, dict) else []
    preview = [
        (s.get("text") or "").strip()
        for s in segments_list[:3]
        if isinstance(s, dict)
    ]
    summary = {
        "segment_count": len(segments_list),
        "language": data.get("language") if isinstance(data, dict) else None,
        "language_probability": (
            data.get("language_probability") if isinstance(data, dict) else None
        ),
        "duration_sec": data.get("duration_sec") if isinstance(data, dict) else None,
        "preview": preview,
    }
    return {
        "exit_code": rc,
        "log": log,
        "transcript_path": str(tx_path),
        "srt_path": str(srt_path) if srt_path.exists() else None,
        "summary": summary,
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
async def export(
    slug: str,
    edl: bool = False,
    fcpxml: bool = False,
    script: bool = False,
    project_root: Optional[str] = None,
    ctx: Optional[Context] = None,
) -> dict:
    """Emit NLE projects (EDL / FCPXML) and/or a replayable render script for
    the composed timeline.
    """
    root = _projects_root(project_root)
    rc, log = await _run_threaded(
        export_mod.run, root, slug, edl=edl, fcpxml=fcpxml, script=script, ctx=ctx
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


# ---------------------------------------------------------------------------
# Schema discovery
# ---------------------------------------------------------------------------


@mcp.tool()
def schema() -> dict:
    """Return JSON schemas (hand-rolled, agent-facing) for every state file
    the engine reads or writes. Use this to validate / generate state without
    spelunking the codebase. Includes the new compose-plan ``slide.body``
    field (list of strings rendered below the subtitle).
    """
    schemas: dict[str, dict] = {
        "project": {
            "description": "Engine-managed project manifest. DO NOT edit by hand.",
            "required": ["name", "slug", "created_at", "sources"],
            "properties": {
                "name": {"type": "string"},
                "slug": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]{0,63}$"},
                "created_at": {"type": "string", "format": "date-time"},
                "sources": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["id", "path"],
                        "properties": {
                            "id": {"type": "string", "example": "raw1"},
                            "path": {
                                "type": "string",
                                "description": "Relative to the project dir.",
                            },
                            "duration_sec": {"type": "number"},
                            "width": {"type": "integer"},
                            "height": {"type": "integer"},
                            "fps": {"type": "number"},
                        },
                    },
                },
            },
        },
        "script": {
            "description": "Voiceover script. Each segment becomes voice/<id>.mp3.",
            "required": ["segments"],
            "properties": {
                "voice_defaults": {
                    "type": "object",
                    "properties": {
                        "engine": {"enum": ["edge-tts", "azure"]},
                        "voice": {"type": "string"},
                        "rate": {"type": "string", "example": "+0%"},
                        "pitch": {"type": "string", "example": "+0Hz"},
                    },
                },
                "segments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["id", "text"],
                        "properties": {
                            "id": {"type": "string", "example": "vo-intro"},
                            "text": {"type": "string"},
                            "voice": {"type": "string"},
                            "rate": {"type": "string"},
                            "pitch": {"type": "string"},
                            "engine": {"enum": ["edge-tts", "azure"]},
                            "pause_after_ms": {"type": "integer"},
                        },
                    },
                },
            },
        },
        "cut-plan": {
            "description": "Clip selection. Each clip becomes clips/<id>.mp4.",
            "required": ["clips"],
            "properties": {
                "clips": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["id", "source", "start", "end"],
                        "properties": {
                            "id": {"type": "string"},
                            "source": {
                                "type": "string",
                                "description": "References project.json::sources[].id",
                            },
                            "start": {"type": "number", "description": "seconds"},
                            "end": {"type": "number", "description": "seconds"},
                            "label": {"type": "string"},
                        },
                    },
                }
            },
        },
        "compose-plan": {
            "description": "Final-render timeline.",
            "required": ["timeline"],
            "properties": {
                "output": {
                    "type": "object",
                    "properties": {
                        "filename": {"type": "string", "default": "final.mp4"},
                        "resolution": {"type": "string", "default": "1920x1080"},
                        "fps": {"type": "integer", "default": 30},
                        "video_bitrate": {"type": "string", "default": "8M"},
                        "audio_bitrate": {"type": "string", "default": "192k"},
                        "video_codec": {"type": "string", "default": "libx264"},
                        "audio_codec": {"type": "string", "default": "aac"},
                    },
                },
                "background_music": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "volume_db": {"type": "number"},
                    },
                },
                "timeline": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["type"],
                        "properties": {
                            "type": {"enum": ["slide", "clip"]},
                            "voiceover": {
                                "type": "string",
                                "description": "References script.json::segments[].id",
                            },
                            "clip": {
                                "type": "string",
                                "description": "References cut-plan.json::clips[].id",
                            },
                            "duration_sec": {"type": "number"},
                            "pad_after_sec": {"type": "number"},
                            "background_color": {"type": "string", "example": "#0b132b"},
                            "background_image": {"type": "string"},
                            "title": {"type": "string"},
                            "subtitle": {"type": "string"},
                            "body": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": (
                                    "Bullets / body lines rendered below the "
                                    "subtitle. Each list entry is one line."
                                ),
                            },
                        },
                    },
                },
            },
            "constraints": [
                "Every slide item must have either `voiceover` OR `duration_sec`.",
                "Every clip item must have a `clip` id that exists in cut-plan.json.",
            ],
        },
        "voice-manifest": {
            "description": "Engine-managed. Written by tts. Read by compose.",
            "required": ["segments"],
            "properties": {
                "segments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["id", "path"],
                        "properties": {
                            "id": {"type": "string"},
                            "path": {"type": "string", "example": "voice/vo-intro.mp3"},
                            "duration_sec": {"type": "number"},
                            "engine": {"type": "string"},
                            "voice": {"type": "string"},
                        },
                    },
                }
            },
        },
        "clips-manifest": {
            "description": "Engine-managed. Written by cut. Read by compose.",
            "required": ["clips"],
            "properties": {
                "clips": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["id", "path"],
                        "properties": {
                            "id": {"type": "string"},
                            "path": {"type": "string", "example": "clips/c1.mp4"},
                            "duration_sec": {"type": "number"},
                            "start": {"type": "number"},
                            "end": {"type": "number"},
                            "source": {"type": "string"},
                        },
                    },
                }
            },
        },
    }
    notes = (
        "Author script.json + cut-plan.json + compose-plan.json. "
        "tts reads script.json -> writes voice/manifest.json. "
        "cut reads cut-plan.json + project.json::sources -> writes clips/manifest.json. "
        "compose reads compose-plan.json + voice/manifest.json + clips/manifest.json -> writes out/<filename>. "
        "Slide items reference voiceover segments by id; clip items reference cut-plan clips by id. "
        "Use is_up_to_date(scope=...) to detect when an upstream edit has invalidated a downstream artifact."
    )
    return {"schemas": schemas, "notes": notes}


# ---------------------------------------------------------------------------
# State builder helpers
# ---------------------------------------------------------------------------


def _ensure_script(proj: Path) -> dict:
    """Return existing script.json content or seed a sensible default."""
    path = proj / "script.json"
    if path.exists():
        existing = _read_json(path)
        if isinstance(existing, dict):
            return existing
    return {"voice_defaults": dict(_DEFAULT_VOICE_DEFAULTS), "segments": []}


def _ensure_compose_plan(proj: Path) -> dict:
    """Return existing compose-plan.json content or seed a sensible default."""
    path = proj / "compose-plan.json"
    if path.exists():
        existing = _read_json(path)
        if isinstance(existing, dict):
            return existing
    return {"output": dict(_DEFAULT_COMPOSE_OUTPUT), "timeline": []}


@mcp.tool()
def add_vo_segment(
    slug: str,
    id: str,
    text: str,
    voice: Optional[str] = None,
    rate: Optional[str] = None,
    pitch: Optional[str] = None,
    engine: Optional[str] = None,
    pause_after_ms: Optional[int] = None,
    position: Optional[int] = None,
    project_root: Optional[str] = None,
) -> dict:
    """Append (or insert at ``position``) a voiceover segment in script.json.

    If ``id`` collides with an existing segment, returns an error WITHOUT
    overwriting. If script.json is missing, it is created with sensible
    ``voice_defaults`` (engine: edge-tts, voice: en-US-AndrewMultilingualNeural).
    """
    root = _projects_root(project_root)
    proj = _project_dir(root, slug)
    if not proj.exists():
        return {"error": f"Project not found: {proj}. Call init first."}

    script = _ensure_script(proj)
    segments = list(script.get("segments") or [])

    if any(isinstance(s, dict) and s.get("id") == id for s in segments):
        return {
            "error": (
                f"Segment id '{id}' already exists in script.json. "
                "Pick a different id or edit the existing segment via write_state."
            )
        }

    seg: dict[str, Any] = {"id": id, "text": text}
    if voice is not None:
        seg["voice"] = voice
    if rate is not None:
        seg["rate"] = rate
    if pitch is not None:
        seg["pitch"] = pitch
    if engine is not None:
        seg["engine"] = engine
    if pause_after_ms is not None:
        seg["pause_after_ms"] = int(pause_after_ms)

    if position is None or position >= len(segments):
        segments.append(seg)
    else:
        segments.insert(max(0, int(position)), seg)

    script["segments"] = segments
    _write_json(proj / "script.json", script)
    return {
        "written": True,
        "path": str(proj / "script.json"),
        "segments": segments,
    }


@mcp.tool()
def add_slide(
    slug: str,
    voiceover: Optional[str] = None,
    background_color: Optional[str] = None,
    background_image: Optional[str] = None,
    title: Optional[str] = None,
    subtitle: Optional[str] = None,
    body: Optional[list[str]] = None,
    duration_sec: Optional[float] = None,
    pad_after_sec: Optional[float] = None,
    position: Optional[int] = None,
    project_root: Optional[str] = None,
) -> dict:
    """Append (or insert at ``position``) a ``slide`` item in compose-plan.json.

    A slide must carry either ``voiceover`` (id from script.json) OR
    ``duration_sec`` -- otherwise compose has no way to decide how long the
    slide should live on screen. ``body`` is the new compose-plan field for
    bullets/body lines rendered below the subtitle.

    If compose-plan.json is missing, it is created with a default 1920x1080
    @30fps libx264/aac output block.
    """
    if not voiceover and duration_sec is None:
        return {
            "error": (
                "Slide needs either `voiceover` (script segment id) or "
                "`duration_sec`. Both omitted; refusing to add an unresolvable slide."
            )
        }

    root = _projects_root(project_root)
    proj = _project_dir(root, slug)
    if not proj.exists():
        return {"error": f"Project not found: {proj}. Call init first."}

    plan = _ensure_compose_plan(proj)
    timeline = list(plan.get("timeline") or [])

    item: dict[str, Any] = {"type": "slide"}
    if voiceover is not None:
        item["voiceover"] = voiceover
    if background_color is not None:
        item["background_color"] = background_color
    if background_image is not None:
        item["background_image"] = background_image
    if title is not None:
        item["title"] = title
    if subtitle is not None:
        item["subtitle"] = subtitle
    if body is not None:
        item["body"] = list(body)
    if duration_sec is not None:
        item["duration_sec"] = float(duration_sec)
    if pad_after_sec is not None:
        item["pad_after_sec"] = float(pad_after_sec)

    if position is None or position >= len(timeline):
        timeline.append(item)
    else:
        timeline.insert(max(0, int(position)), item)

    plan["timeline"] = timeline
    _write_json(proj / "compose-plan.json", plan)
    return {
        "written": True,
        "path": str(proj / "compose-plan.json"),
        "timeline": timeline,
    }


@mcp.tool()
def set_compose_output(
    slug: str,
    filename: Optional[str] = None,
    resolution: Optional[str] = None,
    fps: Optional[int] = None,
    video_bitrate: Optional[str] = None,
    audio_bitrate: Optional[str] = None,
    video_codec: Optional[str] = None,
    audio_codec: Optional[str] = None,
    project_root: Optional[str] = None,
) -> dict:
    """Patch compose-plan.json::output, leaving unspecified keys intact.

    Pass only the keys you want to change. Returns the new output block.
    """
    root = _projects_root(project_root)
    proj = _project_dir(root, slug)
    if not proj.exists():
        return {"error": f"Project not found: {proj}. Call init first."}

    plan = _ensure_compose_plan(proj)
    output = dict(plan.get("output") or {})

    updates: dict[str, Any] = {
        "filename": filename,
        "resolution": resolution,
        "fps": fps,
        "video_bitrate": video_bitrate,
        "audio_bitrate": audio_bitrate,
        "video_codec": video_codec,
        "audio_codec": audio_codec,
    }
    for k, v in updates.items():
        if v is not None:
            output[k] = v

    plan["output"] = output
    _write_json(proj / "compose-plan.json", plan)
    return {
        "written": True,
        "path": str(proj / "compose-plan.json"),
        "output": output,
    }


# ---------------------------------------------------------------------------
# Preview render
# ---------------------------------------------------------------------------


@mcp.tool()
async def preview_slide(
    slug: str,
    index: int,
    project_root: Optional[str] = None,
    ctx: Optional[Context] = None,
) -> dict:
    """Render ONE timeline item to ``out/preview-NNN.mp4`` for fast feedback.

    Calls compose with ``only_index=index``, bypassing the full timeline
    concatenation. Returns the preview path. Validates that
    compose-plan.json exists and that ``index`` is in range first.
    """
    root = _projects_root(project_root)
    proj = _project_dir(root, slug)
    plan_path = proj / "compose-plan.json"
    if not plan_path.exists():
        return {"error": f"compose-plan.json missing in {proj}. Author it first."}

    plan = _read_json(plan_path)
    timeline = (plan or {}).get("timeline") or []
    if not timeline:
        return {"error": "compose-plan.json::timeline is empty; nothing to preview."}
    if not isinstance(index, int) or index < 0 or index >= len(timeline):
        return {
            "error": (
                f"index {index} out of range; timeline has {len(timeline)} item(s) "
                f"(valid indices: 0..{len(timeline) - 1})."
            )
        }

    rc, log = await _run_threaded(
        compose_mod.run,
        root,
        slug,
        only_index=index,
        ctx=ctx,
    )
    preview = proj / "out" / f"preview-{index:03d}.mp4"
    return {
        "exit_code": rc,
        "log": log,
        "preview_path": str(preview) if preview.exists() else None,
        "index": index,
    }


# ---------------------------------------------------------------------------
# Idempotency probe
# ---------------------------------------------------------------------------

_SCOPES = ("tts", "cut", "compose", "transcribe")


def _check_tts(proj: Path) -> dict:
    script_path = proj / "script.json"
    if not script_path.exists():
        return {
            "up_to_date": False,
            "reasons": ["script.json missing -- nothing to synthesize."],
        }
    script = _read_json(script_path) or {}
    segments = script.get("segments") or []
    if not segments:
        return {"up_to_date": True, "reasons": []}

    script_mtime = _mtime(script_path) or 0.0
    reasons: list[str] = []
    for seg in segments:
        if not isinstance(seg, dict) or "id" not in seg:
            continue
        sid = seg["id"]
        mp3 = proj / "voice" / f"{sid}.mp3"
        mp3_mtime = _mtime(mp3)
        if mp3_mtime is None:
            reasons.append(f"voice/{sid}.mp3 missing")
            continue
        if mp3_mtime < script_mtime:
            reasons.append(
                f"script.json (modified {_iso(script_mtime)}) is newer than "
                f"voice/{sid}.mp3 ({_iso(mp3_mtime)})"
            )
    return {"up_to_date": not reasons, "reasons": reasons}


def _check_cut(proj: Path) -> dict:
    cut_path = proj / "cut-plan.json"
    project_path = proj / "project.json"
    if not cut_path.exists():
        return {"up_to_date": False, "reasons": ["cut-plan.json missing."]}
    plan = _read_json(cut_path) or {}
    clips = plan.get("clips") or []
    if not clips:
        return {"up_to_date": True, "reasons": []}

    cut_mtime = _mtime(cut_path) or 0.0
    project = _read_json(project_path) or {}
    sources = {s["id"]: s for s in project.get("sources", []) if isinstance(s, dict)}

    reasons: list[str] = []
    for clip in clips:
        if not isinstance(clip, dict) or "id" not in clip:
            continue
        cid = clip["id"]
        out = proj / "clips" / f"{cid}.mp4"
        out_mtime = _mtime(out)
        if out_mtime is None:
            reasons.append(f"clips/{cid}.mp4 missing")
            continue
        if out_mtime < cut_mtime:
            reasons.append(
                f"cut-plan.json (modified {_iso(cut_mtime)}) is newer than "
                f"clips/{cid}.mp4 ({_iso(out_mtime)})"
            )
        src_id = clip.get("source")
        src_entry = sources.get(src_id) if src_id else None
        if src_entry and "path" in src_entry:
            src_path = proj / src_entry["path"]
            src_mtime = _mtime(src_path)
            if src_mtime is not None and out_mtime < src_mtime:
                reasons.append(
                    f"source {src_id} ({_iso(src_mtime)}) is newer than "
                    f"clips/{cid}.mp4 ({_iso(out_mtime)})"
                )
    return {"up_to_date": not reasons, "reasons": reasons}


def _check_compose(proj: Path) -> dict:
    plan_path = proj / "compose-plan.json"
    if not plan_path.exists():
        return {"up_to_date": False, "reasons": ["compose-plan.json missing."]}
    plan = _read_json(plan_path) or {}
    out_name = ((plan.get("output") or {}).get("filename")) or "final.mp4"
    final = proj / "out" / out_name
    final_mtime = _mtime(final)
    if final_mtime is None:
        return {"up_to_date": False, "reasons": [f"out/{out_name} missing"]}

    reasons: list[str] = []
    candidate_inputs: list[Path] = [
        plan_path,
        proj / "voice" / "manifest.json",
        proj / "clips" / "manifest.json",
    ]
    for item in plan.get("timeline") or []:
        if not isinstance(item, dict):
            continue
        bg = item.get("background_image")
        if bg:
            candidate_inputs.append(proj / bg if not Path(bg).is_absolute() else Path(bg))

    for inp in candidate_inputs:
        m = _mtime(inp)
        if m is None:
            continue
        if final_mtime < m:
            reasons.append(
                f"{inp.name} ({_iso(m)}) is newer than out/{out_name} ({_iso(final_mtime)})"
            )
    return {"up_to_date": not reasons, "reasons": reasons}


def _check_transcribe(proj: Path) -> dict:
    project_path = proj / "project.json"
    if not project_path.exists():
        return {"up_to_date": False, "reasons": ["project.json missing."]}
    project = _read_json(project_path) or {}
    sources = project.get("sources") or []
    if not sources:
        return {"up_to_date": True, "reasons": []}

    reasons: list[str] = []
    for src in sources:
        if not isinstance(src, dict) or "id" not in src or "path" not in src:
            continue
        sid = src["id"]
        src_path = proj / src["path"]
        tx = proj / "transcripts" / f"{sid}.json"
        tx_mtime = _mtime(tx)
        if tx_mtime is None:
            reasons.append(f"transcripts/{sid}.json missing")
            continue
        src_mtime = _mtime(src_path)
        if src_mtime is not None and tx_mtime < src_mtime:
            reasons.append(
                f"source {sid} ({_iso(src_mtime)}) is newer than "
                f"transcripts/{sid}.json ({_iso(tx_mtime)})"
            )
    return {"up_to_date": not reasons, "reasons": reasons}


@mcp.tool()
def is_up_to_date(
    slug: str,
    scope: Optional[str] = None,
    project_root: Optional[str] = None,
) -> dict:
    """Check whether downstream artifacts are still consistent with their inputs.

    Args:
        slug: Project identifier.
        scope: One of "tts" | "cut" | "compose" | "transcribe". Omit for all.
        project_root: Override the default projects/ directory.

    For each scope, returns ``{"up_to_date": bool, "reasons": [str, ...]}``.
    Reasons name the stale artifact and what input made it stale.
    """
    if scope is not None and scope not in _SCOPES:
        return {
            "error": f"Unknown scope '{scope}'. Use one of: {list(_SCOPES)} (or omit for all)."
        }
    root = _projects_root(project_root)
    proj = _project_dir(root, slug)
    if not proj.exists():
        return {"error": f"Project not found: {proj}. Call init first."}

    checkers: dict[str, Callable[[Path], dict]] = {
        "tts": _check_tts,
        "cut": _check_cut,
        "compose": _check_compose,
        "transcribe": _check_transcribe,
    }
    scopes = [scope] if scope else list(_SCOPES)
    return {s: checkers[s](proj) for s in scopes}


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


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
        except Exception:
            print("videopilot-mcp (version unknown)")
        return 0

    mcp.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
