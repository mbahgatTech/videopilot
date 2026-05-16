"""`init` and `import` — project scaffolding."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import ffmpeg_wrap

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def _validate_slug(slug: str) -> None:
    if not _SLUG_RE.match(slug):
        raise SystemExit(
            f"Invalid slug '{slug}'. Use lowercase letters, digits, hyphens; "
            "start with letter/digit; max 64 chars."
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _starter_script() -> dict:
    return {
        "voice_defaults": {
            "voice": "en-US-AndrewMultilingualNeural",
            "rate": "+0%",
            "pitch": "+0Hz",
            "engine": "edge-tts",
        },
        "segments": [
            {
                "id": "vo-intro",
                "text": "Welcome. Replace this with your real voiceover script.",
                "pause_after_ms": 400,
            }
        ],
    }


def _starter_cut_plan() -> dict:
    return {
        "clips": [
            {
                "id": "c-example",
                "source": "raw1",
                "start": 0.0,
                "end": 5.0,
                "label": "example — replace with real spans",
            }
        ]
    }


def _starter_compose_plan() -> dict:
    return {
        "output": {
            "filename": "final.mp4",
            "resolution": "1920x1080",
            "fps": 30,
            "video_bitrate": "8M",
            "audio_bitrate": "192k",
            "video_codec": "libx264",
            "audio_codec": "aac",
        },
        "timeline": [
            {
                "type": "slide",
                "duration_sec": 3.0,
                "background_color": "#0b132b",
                "title": "Replace me",
                "voiceover": "vo-intro",
            }
        ],
    }


def run(root: Path, slug: str, *, name: str | None = None, sources: list[str] | None = None) -> int:
    _validate_slug(slug)
    proj = root / slug
    if proj.exists():
        raise SystemExit(f"Project already exists: {proj}")

    for sub in ("sources", "voice", "transcripts", "clips", "tmp", "out"):
        (proj / sub).mkdir(parents=True, exist_ok=True)

    src_entries: list[dict] = []
    for i, s in enumerate(sources or [], start=1):
        sid = f"raw{i}"
        src_entries.append(_copy_source(proj, s, sid))

    project = {
        "name": name or slug,
        "slug": slug,
        "created_at": _now_iso(),
        "sources": src_entries,
    }
    _write_json(proj / "project.json", project)
    _write_json(proj / "script.json", _starter_script())
    _write_json(proj / "cut-plan.json", _starter_cut_plan())
    _write_json(proj / "compose-plan.json", _starter_compose_plan())

    print(f"Created project: {proj}")
    print("Files seeded:")
    print("  project.json      — sources inventory")
    print("  script.json       — voiceover script (edit this)")
    print("  cut-plan.json     — clip selection (edit this)")
    print("  compose-plan.json — timeline assembly (edit this)")
    for s in src_entries:
        print(f"Imported source: {s['id']} <- {s['path']} ({s['duration_sec']:.2f}s)")
    return 0


def import_source(root: Path, slug: str, path: str, *, source_id: str | None = None) -> int:
    proj = root / slug
    pj_path = proj / "project.json"
    if not pj_path.exists():
        raise SystemExit(f"Project not found: {proj}")
    project = json.loads(pj_path.read_text(encoding="utf-8"))

    existing_ids = {s["id"] for s in project.get("sources", [])}
    sid = source_id or _next_raw_id(existing_ids)
    if sid in existing_ids:
        raise SystemExit(f"Source id already used: {sid}")

    entry = _copy_source(proj, path, sid)
    project.setdefault("sources", []).append(entry)
    _write_json(pj_path, project)
    print(f"Imported source: {sid} <- {entry['path']} ({entry['duration_sec']:.2f}s)")
    return 0


def _next_raw_id(existing: set[str]) -> str:
    n = 1
    while f"raw{n}" in existing:
        n += 1
    return f"raw{n}"


def _copy_source(proj: Path, src: str, source_id: str) -> dict:
    src_path = Path(src).resolve()
    if not src_path.exists():
        raise SystemExit(f"Source file not found: {src_path}")
    dest = proj / "sources" / (source_id + src_path.suffix.lower())
    shutil.copy2(src_path, dest)
    info = ffmpeg_wrap.probe(dest)
    return {
        "id": source_id,
        "path": f"sources/{dest.name}",
        "duration_sec": round(info.duration_sec, 3),
        "width": info.width,
        "height": info.height,
        "fps": round(info.fps, 3) if info.fps else None,
    }
