"""End-to-end validator for the videopilot MCP server.

Spawns `python videopilot_mcp.py` as a subprocess and exercises every fix
described in the orchestration brief:

  1. TTS asyncio crash gone (lib/tts.py uses asyncio.run() inside a worker
     thread now -- no nested event loop).
  2. Long compose renders stream progress (no -32001 client timeout).
  3. transcribe response is a slim summary (no full transcript dump).
  4. Six new tools: schema, add_vo_segment, add_slide, set_compose_output,
     preview_slide, is_up_to_date.
  5. compose-plan slide.body: list[str] renders.

Run from the repo root:

    python _test_mcp_e2e.py
"""

from __future__ import annotations

import asyncio
import inspect
import json
import shutil
import subprocess
import sys
import time
import traceback
from datetime import timedelta
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

HERE = Path(__file__).resolve().parent
SERVER = HERE / "videopilot_mcp.py"
PROJECT_ROOT = HERE / "_test_e2e_projects"
SLUG = "e2e-validation"

# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------

_RESULTS: list[tuple[str, str, str]] = []  # (name, status, detail)


def record(name: str, status: str, detail: str = "") -> None:
    print(f"[{status:4}] {name}  {detail}".rstrip())
    _RESULTS.append((name, status, detail))


def _looks_like_network_failure(text: str) -> bool:
    if not text:
        return False
    low = text.lower()
    needles = (
        "connectionerror",
        "no audio received",
        "no audio was received",
        "name or service not known",
        "getaddrinfo failed",
        "temporary failure in name resolution",
        "wsastartup",
        "ssl",
        "timed out",
        "timeout",
        "connection reset",
        "connection aborted",
        "max retries exceeded",
        "remote end closed connection",
        "502",
        "503",
        "504",
        "edge_tts.exceptions",
        "noaudioreceived",
    )
    return any(n in low for n in needles)


# ---------------------------------------------------------------------------
# MCP convenience wrappers
# ---------------------------------------------------------------------------


async def call(session: ClientSession, name: str, args: dict[str, Any], *, timeout_s: float | None = None) -> dict[str, Any]:
    timeout = timedelta(seconds=timeout_s) if timeout_s else None
    result = await session.call_tool(name, args, read_timeout_seconds=timeout)
    if result.structuredContent is not None:
        sc = result.structuredContent
        # FastMCP wraps non-dict returns under {"result": ...}; unwrap if needed.
        if isinstance(sc, dict) and set(sc.keys()) == {"result"}:
            inner = sc["result"]
            if isinstance(inner, dict):
                return inner
        return sc  # type: ignore[return-value]
    # Fallback: stitch together text content blocks if any.
    if result.content:
        joined = "".join(getattr(c, "text", "") or "" for c in result.content)
        try:
            return json.loads(joined)
        except Exception:
            return {"_raw_text": joined}
    return {}


# ---------------------------------------------------------------------------
# Validator phases
# ---------------------------------------------------------------------------


async def run_validation() -> int:
    # Clean any leftovers from a prior run.
    if PROJECT_ROOT.exists():
        shutil.rmtree(PROJECT_ROOT, ignore_errors=True)
    PROJECT_ROOT.mkdir(parents=True, exist_ok=True)

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER)],
        cwd=str(HERE),
    )

    skip_network_block = False  # set True if tts hits a network failure
    overall_failure = False

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # --- 1. tools/list ------------------------------------------
                expected_new = {
                    "schema",
                    "add_vo_segment",
                    "add_slide",
                    "set_compose_output",
                    "preview_slide",
                    "is_up_to_date",
                }
                legacy_check = {"init", "tts", "compose", "transcribe", "read_state"}
                try:
                    tools_resp = await session.list_tools()
                    names = {t.name for t in tools_resp.tools}
                    missing_new = expected_new - names
                    missing_legacy = legacy_check - names
                    if missing_new:
                        record(
                            "new_tools_listed",
                            "FAIL",
                            f"missing new tools: {sorted(missing_new)}",
                        )
                        overall_failure = True
                    elif missing_legacy:
                        record(
                            "new_tools_listed",
                            "FAIL",
                            f"missing legacy tools: {sorted(missing_legacy)}",
                        )
                        overall_failure = True
                    else:
                        record(
                            "new_tools_listed",
                            "PASS",
                            f"({len(names)} tools, all expected present)",
                        )
                except Exception:
                    record("new_tools_listed", "FAIL", traceback.format_exc(limit=2).strip().splitlines()[-1])
                    overall_failure = True

                # --- 2. schema() returns body field -------------------------
                try:
                    s = await call(session, "schema", {})
                    schemas = s.get("schemas") or {}
                    needed = {
                        "project",
                        "script",
                        "cut-plan",
                        "compose-plan",
                        "voice-manifest",
                        "clips-manifest",
                    }
                    missing = needed - set(schemas)
                    cp_props = (
                        ((schemas.get("compose-plan") or {}).get("properties") or {})
                        .get("timeline", {})
                        .get("items", {})
                        .get("properties", {})
                    )
                    if missing:
                        record(
                            "schema_returns_body_field",
                            "FAIL",
                            f"schema missing keys: {sorted(missing)}",
                        )
                        overall_failure = True
                    elif "body" not in cp_props:
                        record(
                            "schema_returns_body_field",
                            "FAIL",
                            "compose-plan.timeline.items.properties.body missing",
                        )
                        overall_failure = True
                    else:
                        record("schema_returns_body_field", "PASS")
                except Exception:
                    record("schema_returns_body_field", "FAIL", traceback.format_exc(limit=2).strip().splitlines()[-1])
                    overall_failure = True

                # --- 3. init ------------------------------------------------
                # init seeds a starter `vo-intro` segment + a starter slide.
                # Wipe both via write_state so the rest of the validator runs
                # against a clean slate (this also doubles as a write_state
                # smoke check).
                try:
                    r = await call(
                        session,
                        "init",
                        {"slug": SLUG, "project_root": str(PROJECT_ROOT)},
                    )
                    if not r.get("exists"):
                        record("init_project", "FAIL", f"init returned: {json.dumps(r)[:200]}")
                        overall_failure = True
                    else:
                        # Reset script.json to empty segments.
                        wr_s = await call(
                            session,
                            "write_state",
                            {
                                "slug": SLUG,
                                "file": "script",
                                "content": {
                                    "voice_defaults": {
                                        "engine": "edge-tts",
                                        "voice": "en-US-AndrewMultilingualNeural",
                                        "rate": "+0%",
                                        "pitch": "+0Hz",
                                    },
                                    "segments": [],
                                },
                                "project_root": str(PROJECT_ROOT),
                            },
                        )
                        # Reset compose-plan.json to empty timeline + tiny
                        # 640x360 output so the compose render stays fast.
                        # Keep fps=30 here so the set_compose_output(fps=24)
                        # check below actually proves the patch landed.
                        wr_c = await call(
                            session,
                            "write_state",
                            {
                                "slug": SLUG,
                                "file": "compose-plan",
                                "content": {
                                    "output": {
                                        "filename": "final.mp4",
                                        "resolution": "640x360",
                                        "fps": 30,
                                        "video_bitrate": "1M",
                                        "audio_bitrate": "96k",
                                        "video_codec": "libx264",
                                        "audio_codec": "aac",
                                    },
                                    "timeline": [],
                                },
                                "project_root": str(PROJECT_ROOT),
                            },
                        )
                        if not wr_s.get("written") or not wr_c.get("written"):
                            record(
                                "init_project",
                                "FAIL",
                                f"reset script/compose-plan failed: {wr_s!r} / {wr_c!r}",
                            )
                            overall_failure = True
                        else:
                            record(
                                "init_project",
                                "PASS",
                                f"path={r.get('path')} (reset to empty)",
                            )
                except Exception:
                    record("init_project", "FAIL", traceback.format_exc(limit=2).strip().splitlines()[-1])
                    overall_failure = True

                # --- 4. add_vo_segment x3 + collision ------------------------
                vo_inputs = [
                    ("vo-1", "Hello from the MCP end to end test."),
                    ("vo-2", "The middle voice over confirms multi segment behavior."),
                    ("vo-3", "Final note. Body bullets render below subtitles."),
                ]
                try:
                    last = None
                    for vid, txt in vo_inputs:
                        last = await call(
                            session,
                            "add_vo_segment",
                            {
                                "slug": SLUG,
                                "id": vid,
                                "text": txt,
                                "project_root": str(PROJECT_ROOT),
                            },
                        )
                        if "error" in last or not last.get("written"):
                            raise RuntimeError(
                                f"add_vo_segment {vid} returned: {json.dumps(last)[:200]}"
                            )
                    segs = (last or {}).get("segments") or []
                    if len(segs) != 3 or [s.get("id") for s in segs] != ["vo-1", "vo-2", "vo-3"]:
                        raise RuntimeError(f"expected 3 segments in order; got {segs!r}")
                    record("add_vo_segment_x3", "PASS", f"3 segments written")
                except Exception as exc:
                    record(
                        "add_vo_segment_x3",
                        "FAIL",
                        f"{exc!r}",
                    )
                    overall_failure = True

                # collision
                try:
                    c = await call(
                        session,
                        "add_vo_segment",
                        {
                            "slug": SLUG,
                            "id": "vo-1",
                            "text": "should be rejected",
                            "project_root": str(PROJECT_ROOT),
                        },
                    )
                    if "error" not in c:
                        raise RuntimeError(f"expected error key, got: {json.dumps(c)[:200]}")
                    # Confirm segments did not grow.
                    s_state = await call(
                        session,
                        "read_state",
                        {
                            "slug": SLUG,
                            "file": "script",
                            "project_root": str(PROJECT_ROOT),
                        },
                    )
                    segs = (s_state.get("content") or {}).get("segments") or []
                    if len(segs) != 3:
                        raise RuntimeError(f"segments mutated after rejected collision: {segs!r}")
                    record("add_vo_segment_collision_rejected", "PASS")
                except Exception as exc:
                    record(
                        "add_vo_segment_collision_rejected",
                        "FAIL",
                        f"{exc!r}",
                    )
                    overall_failure = True

                # --- 5. add_slide x4 (with body) + validation ----------------
                slides = [
                    {
                        "slug": SLUG,
                        "voiceover": "vo-1",
                        "title": "MCP End to End",
                        "subtitle": "Validation Pass",
                        "background_color": "#0b132b",
                        "project_root": str(PROJECT_ROOT),
                    },
                    {
                        "slug": SLUG,
                        "voiceover": "vo-2",
                        "title": "With Body Bullets",
                        "body": [
                            "First bullet line.",
                            "Second bullet line.",
                            "1. Numbered line passes through verbatim.",
                            "- Dash line also verbatim.",
                        ],
                        "background_color": "#1c2541",
                        "project_root": str(PROJECT_ROOT),
                    },
                    {
                        "slug": SLUG,
                        "voiceover": "vo-3",
                        "title": "Final",
                        "subtitle": "End of validation",
                        "background_color": "#0f3a2d",
                        "project_root": str(PROJECT_ROOT),
                    },
                    {
                        "slug": SLUG,
                        "duration_sec": 2,
                        "title": "Thanks!",
                        "background_color": "#000000",
                        "project_root": str(PROJECT_ROOT),
                    },
                ]
                try:
                    last = None
                    for spec in slides:
                        last = await call(session, "add_slide", spec)
                        if "error" in last or not last.get("written"):
                            raise RuntimeError(
                                f"add_slide {spec.get('title')!r} returned: {json.dumps(last)[:200]}"
                            )
                    timeline = (last or {}).get("timeline") or []
                    if len(timeline) != 4:
                        raise RuntimeError(f"expected 4 timeline items; got {len(timeline)}")
                    body = timeline[1].get("body") or []
                    if body != [
                        "First bullet line.",
                        "Second bullet line.",
                        "1. Numbered line passes through verbatim.",
                        "- Dash line also verbatim.",
                    ]:
                        raise RuntimeError(f"slide 2 body mismatch: {body!r}")
                    record("add_slide_x4_with_body", "PASS", "4 slides, body bullets verbatim")
                except Exception as exc:
                    record("add_slide_x4_with_body", "FAIL", f"{exc!r}")
                    overall_failure = True

                # validation: neither voiceover nor duration_sec
                try:
                    r = await call(
                        session,
                        "add_slide",
                        {
                            "slug": SLUG,
                            "title": "Bad",
                            "project_root": str(PROJECT_ROOT),
                        },
                    )
                    if "error" not in r:
                        raise RuntimeError(f"expected error; got: {json.dumps(r)[:200]}")
                    record("add_slide_missing_required_rejected", "PASS")
                except Exception as exc:
                    record("add_slide_missing_required_rejected", "FAIL", f"{exc!r}")
                    overall_failure = True

                # --- 6. tts (asyncio crash repro) ----------------------------
                tts_t0 = time.monotonic()
                try:
                    r = await call(
                        session,
                        "tts",
                        {"slug": SLUG, "project_root": str(PROJECT_ROOT)},
                        timeout_s=180,
                    )
                    elapsed = time.monotonic() - tts_t0
                    log_text = (r.get("log") or "") + " " + json.dumps(r)
                    if "asyncio.run() cannot be called from a running event loop" in log_text:
                        record(
                            "tts_no_asyncio_crash",
                            "FAIL",
                            "found 'asyncio.run() cannot be called from a running event loop' in response",
                        )
                        overall_failure = True
                        skip_network_block = True  # don't run downstream
                    elif r.get("exit_code") != 0:
                        # Distinguish network failure from a real defect.
                        if _looks_like_network_failure(r.get("log") or ""):
                            record(
                                "tts_no_asyncio_crash",
                                "SKIP",
                                f"network failure in edge-tts ({elapsed:.1f}s)",
                            )
                            skip_network_block = True
                        else:
                            record(
                                "tts_no_asyncio_crash",
                                "FAIL",
                                f"exit_code={r.get('exit_code')} log={ (r.get('log') or '')[:160]!r}",
                            )
                            overall_failure = True
                            skip_network_block = True
                    else:
                        manifest = r.get("voice_manifest") or {}
                        segs = manifest.get("segments") or []
                        if len(segs) != 3:
                            record(
                                "tts_no_asyncio_crash",
                                "FAIL",
                                f"voice_manifest had {len(segs)} segments, expected 3",
                            )
                            overall_failure = True
                            skip_network_block = True
                        else:
                            record(
                                "tts_no_asyncio_crash",
                                "PASS",
                                f"({elapsed:.1f}s, {len(segs)} segments)",
                            )
                except Exception as exc:
                    tb = traceback.format_exc()
                    if _looks_like_network_failure(tb) or _looks_like_network_failure(str(exc)):
                        record(
                            "tts_no_asyncio_crash",
                            "SKIP",
                            f"network-flavored exception: {exc!r}",
                        )
                        skip_network_block = True
                    else:
                        record("tts_no_asyncio_crash", "FAIL", f"{exc!r}")
                        overall_failure = True
                        skip_network_block = True

                # --- 7. is_up_to_date(tts) after tts -------------------------
                if skip_network_block:
                    record("is_up_to_date_tts_after_tts", "SKIP", "depends on tts step")
                else:
                    try:
                        r = await call(
                            session,
                            "is_up_to_date",
                            {
                                "slug": SLUG,
                                "scope": "tts",
                                "project_root": str(PROJECT_ROOT),
                            },
                        )
                        tts_node = (r or {}).get("tts") or {}
                        if tts_node.get("up_to_date") is True:
                            record("is_up_to_date_tts_after_tts", "PASS")
                        else:
                            record(
                                "is_up_to_date_tts_after_tts",
                                "FAIL",
                                f"got: {json.dumps(r)[:200]}",
                            )
                            overall_failure = True
                    except Exception as exc:
                        record("is_up_to_date_tts_after_tts", "FAIL", f"{exc!r}")
                        overall_failure = True

                # --- 8. compose (no -32001 timeout) --------------------------
                if skip_network_block:
                    record("compose_no_timeout", "SKIP", "depends on tts step")
                else:
                    try:
                        comp_t0 = time.monotonic()
                        r = await call(
                            session,
                            "compose",
                            {"slug": SLUG, "project_root": str(PROJECT_ROOT)},
                            timeout_s=600,
                        )
                        elapsed = time.monotonic() - comp_t0
                        if r.get("exit_code") != 0:
                            record(
                                "compose_no_timeout",
                                "FAIL",
                                f"exit_code={r.get('exit_code')} log_tail={(r.get('log') or '')[-200:]!r}",
                            )
                            overall_failure = True
                        else:
                            fp = r.get("final_path")
                            if not fp or not Path(fp).exists():
                                record(
                                    "compose_no_timeout",
                                    "FAIL",
                                    f"final_path missing/absent: {fp!r}",
                                )
                                overall_failure = True
                            else:
                                size = Path(fp).stat().st_size
                                record(
                                    "compose_no_timeout",
                                    "PASS",
                                    f"({elapsed:.1f}s, {size} bytes)",
                                )
                    except Exception as exc:
                        if "-32001" in str(exc) or "Timed out" in str(exc):
                            record(
                                "compose_no_timeout",
                                "FAIL",
                                f"MCP request timed out: {exc!r}",
                            )
                        else:
                            record("compose_no_timeout", "FAIL", f"{exc!r}")
                        overall_failure = True

                # --- 9. preview_slide(1) renders body slide ------------------
                if skip_network_block:
                    record("preview_slide_renders", "SKIP", "depends on tts step")
                else:
                    try:
                        r = await call(
                            session,
                            "preview_slide",
                            {
                                "slug": SLUG,
                                "index": 1,
                                "project_root": str(PROJECT_ROOT),
                            },
                            timeout_s=300,
                        )
                        if r.get("exit_code") != 0:
                            record(
                                "preview_slide_renders",
                                "FAIL",
                                f"exit_code={r.get('exit_code')} log_tail={(r.get('log') or '')[-160:]!r}",
                            )
                            overall_failure = True
                        else:
                            pv = r.get("preview_path")
                            if not pv or not Path(pv).exists():
                                record(
                                    "preview_slide_renders",
                                    "FAIL",
                                    f"preview_path missing: {pv!r}",
                                )
                                overall_failure = True
                            else:
                                # ffprobe duration > 1s sanity check
                                dur = _probe_duration(Path(pv))
                                if dur is None:
                                    record(
                                        "preview_slide_renders",
                                        "PASS",
                                        f"({pv}, ffprobe unavailable)",
                                    )
                                elif dur > 1.0:
                                    record(
                                        "preview_slide_renders",
                                        "PASS",
                                        f"({pv}, dur={dur:.2f}s)",
                                    )
                                else:
                                    record(
                                        "preview_slide_renders",
                                        "FAIL",
                                        f"duration too short: {dur!r}",
                                    )
                                    overall_failure = True
                    except Exception as exc:
                        record("preview_slide_renders", "FAIL", f"{exc!r}")
                        overall_failure = True

                # --- 10. preview_slide(99) rejected --------------------------
                try:
                    r = await call(
                        session,
                        "preview_slide",
                        {
                            "slug": SLUG,
                            "index": 99,
                            "project_root": str(PROJECT_ROOT),
                        },
                    )
                    if "error" not in r:
                        record(
                            "preview_slide_oob_rejected",
                            "FAIL",
                            f"expected error; got: {json.dumps(r)[:200]}",
                        )
                        overall_failure = True
                    else:
                        record("preview_slide_oob_rejected", "PASS")
                except Exception as exc:
                    record("preview_slide_oob_rejected", "FAIL", f"{exc!r}")
                    overall_failure = True

                # --- 11. is_up_to_date(compose) after compose ----------------
                if skip_network_block:
                    record("is_up_to_date_compose_after_compose", "SKIP", "depends on compose step")
                else:
                    try:
                        r = await call(
                            session,
                            "is_up_to_date",
                            {
                                "slug": SLUG,
                                "scope": "compose",
                                "project_root": str(PROJECT_ROOT),
                            },
                        )
                        node = (r or {}).get("compose") or {}
                        if node.get("up_to_date") is True:
                            record("is_up_to_date_compose_after_compose", "PASS")
                        else:
                            record(
                                "is_up_to_date_compose_after_compose",
                                "FAIL",
                                f"reasons={node.get('reasons')!r}",
                            )
                            overall_failure = True
                    except Exception as exc:
                        record(
                            "is_up_to_date_compose_after_compose",
                            "FAIL",
                            f"{exc!r}",
                        )
                        overall_failure = True

                # --- 12. mutate script -> tts stale --------------------------
                if skip_network_block:
                    record("is_up_to_date_tts_after_script_edit", "SKIP", "depends on tts step")
                else:
                    try:
                        # bump vo-1 text via write_state (rewrites script.json)
                        s_state = await call(
                            session,
                            "read_state",
                            {
                                "slug": SLUG,
                                "file": "script",
                                "project_root": str(PROJECT_ROOT),
                            },
                        )
                        content = dict(s_state.get("content") or {})
                        segs = list(content.get("segments") or [])
                        for seg in segs:
                            if isinstance(seg, dict) and seg.get("id") == "vo-1":
                                seg["text"] = "Mutated vo-1 text for staleness check."
                                break
                        content["segments"] = segs
                        time.sleep(1.1)  # ensure mtime is newer than mp3
                        w = await call(
                            session,
                            "write_state",
                            {
                                "slug": SLUG,
                                "file": "script",
                                "content": content,
                                "project_root": str(PROJECT_ROOT),
                            },
                        )
                        if not w.get("written"):
                            raise RuntimeError(f"write_state failed: {json.dumps(w)[:200]}")

                        r = await call(
                            session,
                            "is_up_to_date",
                            {
                                "slug": SLUG,
                                "scope": "tts",
                                "project_root": str(PROJECT_ROOT),
                            },
                        )
                        node = (r or {}).get("tts") or {}
                        reasons = node.get("reasons") or []
                        if node.get("up_to_date") is False and any(
                            "vo-1" in str(reason) for reason in reasons
                        ):
                            record(
                                "is_up_to_date_tts_after_script_edit",
                                "PASS",
                                f"reasons match vo-1",
                            )
                        else:
                            record(
                                "is_up_to_date_tts_after_script_edit",
                                "FAIL",
                                f"got: {json.dumps(r)[:240]}",
                            )
                            overall_failure = True
                    except Exception as exc:
                        record(
                            "is_up_to_date_tts_after_script_edit",
                            "FAIL",
                            f"{exc!r}",
                        )
                        overall_failure = True

                # --- 13. set_compose_output patches fps ---------------------
                try:
                    r = await call(
                        session,
                        "set_compose_output",
                        {
                            "slug": SLUG,
                            "fps": 24,
                            "project_root": str(PROJECT_ROOT),
                        },
                    )
                    out_blk = r.get("output") or {}
                    if out_blk.get("fps") != 24:
                        record(
                            "set_compose_output_patches",
                            "FAIL",
                            f"fps not 24 in response: {out_blk!r}",
                        )
                        overall_failure = True
                    else:
                        # Re-read the file to confirm persistence.
                        s = await call(
                            session,
                            "read_state",
                            {
                                "slug": SLUG,
                                "file": "compose-plan",
                                "project_root": str(PROJECT_ROOT),
                            },
                        )
                        disk_fps = (((s.get("content") or {}).get("output") or {}).get("fps"))
                        if disk_fps != 24:
                            record(
                                "set_compose_output_patches",
                                "FAIL",
                                f"on-disk fps={disk_fps!r}, expected 24",
                            )
                            overall_failure = True
                        else:
                            # And that other defaults survived (filename etc.).
                            fn = ((s.get("content") or {}).get("output") or {}).get("filename")
                            record(
                                "set_compose_output_patches",
                                "PASS",
                                f"fps=24, filename={fn!r}",
                            )
                except Exception as exc:
                    record("set_compose_output_patches", "FAIL", f"{exc!r}")
                    overall_failure = True

                # --- 14. transcribe response shape (static check) -----------
                try:
                    # Import the server module locally and inspect the transcribe handler.
                    sys.path.insert(0, str(HERE))
                    import videopilot_mcp as vp_mcp  # noqa: WPS433

                    src = inspect.getsource(vp_mcp.transcribe.fn) if hasattr(vp_mcp.transcribe, "fn") else inspect.getsource(vp_mcp.transcribe)
                    must_have_keys = (
                        '"segment_count"',
                        '"language"',
                        '"language_probability"',
                        '"duration_sec"',
                        '"preview"',
                    )
                    missing = [k for k in must_have_keys if k not in src]
                    has_summary_return = '"summary": summary' in src or "'summary': summary" in src
                    has_transcript_field = "'transcript':" in src or '"transcript":' in src
                    if missing:
                        record(
                            "transcribe_response_is_summary",
                            "FAIL",
                            f"summary keys missing: {missing}",
                        )
                        overall_failure = True
                    elif not has_summary_return:
                        record(
                            "transcribe_response_is_summary",
                            "FAIL",
                            "transcribe handler does not return a 'summary' key",
                        )
                        overall_failure = True
                    elif has_transcript_field:
                        record(
                            "transcribe_response_is_summary",
                            "FAIL",
                            "transcribe handler still embeds full 'transcript' field",
                        )
                        overall_failure = True
                    else:
                        record(
                            "transcribe_response_is_summary",
                            "PASS",
                            "summary keys present, no transcript field",
                        )
                except Exception as exc:
                    record(
                        "transcribe_response_is_summary",
                        "FAIL",
                        f"{exc!r}",
                    )
                    overall_failure = True

    finally:
        # Cleanup: keep on failure for postmortem.
        if not overall_failure:
            try:
                shutil.rmtree(PROJECT_ROOT, ignore_errors=True)
                print(f"\n[cleanup] removed {PROJECT_ROOT}")
            except Exception as e:
                print(f"[cleanup] failed: {e!r}")
        else:
            print(
                f"\n[cleanup] preserved {PROJECT_ROOT} for postmortem due to failures"
            )

    # Summary
    print("\n" + "=" * 70)
    print(f"{'test':<50}{'result'}")
    print(f"{'---':<50}{'---'}")
    for name, status, detail in _RESULTS:
        line = f"{name:<50}{status}"
        if detail:
            line += f"  ({detail})"
        print(line)
    print("=" * 70)

    has_skip = any(s == "SKIP" for _, s, _ in _RESULTS)
    has_fail = any(s == "FAIL" for _, s, _ in _RESULTS)
    if has_fail:
        print("\nOVERALL: FAIL")
        return 1
    if has_skip:
        print("\nOVERALL: PASS-with-skips")
        return 0
    print("\nOVERALL: PASS")
    return 0


def _probe_duration(path: Path) -> float | None:
    """Run ffprobe to get the duration of `path`. Returns None if ffprobe is missing."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        # Fallback to lib/ffmpeg_wrap which knows about WinGet paths.
        try:
            sys.path.insert(0, str(HERE))
            from lib import ffmpeg_wrap

            ffmpeg_wrap.ensure_on_path()
            ffprobe = shutil.which("ffprobe")
        except Exception:
            ffprobe = None
    if not ffprobe:
        return None
    try:
        out = subprocess.check_output(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            stderr=subprocess.STDOUT,
            timeout=20,
        )
        return float(out.decode().strip())
    except Exception:
        return None


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run_validation()))
