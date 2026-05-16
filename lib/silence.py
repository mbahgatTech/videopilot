"""`silence` — emit a cut-plan candidate of non-silent spans using ffmpeg's silencedetect."""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import ffmpeg_wrap

_RE_START = re.compile(r"silence_start: ([0-9.]+)")
_RE_END = re.compile(r"silence_end: ([0-9.]+) \| silence_duration: ([0-9.]+)")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def run(
    root: Path,
    slug: str,
    source_id: str,
    *,
    threshold_db: float = -35.0,
    min_silence_sec: float = 1.0,
    output: str | None = None,
) -> int:
    proj = root / slug
    project = _load_json(proj / "project.json")
    src = next((s for s in project.get("sources", []) if s["id"] == source_id), None)
    if src is None:
        raise SystemExit(f"source id '{source_id}' not found in project.")
    src_path = proj / src["path"]
    duration = float(src["duration_sec"])

    print(f"Scanning silence: threshold={threshold_db}dB, min_silence={min_silence_sec}s")
    args = [
        "-i",
        str(src_path),
        "-af",
        f"silencedetect=noise={threshold_db}dB:d={min_silence_sec}",
        "-f",
        "null",
        "-",
    ]
    stderr = ffmpeg_wrap.run_ffmpeg_capture_stderr(args)

    silences: list[tuple[float, float]] = []
    pending_start: float | None = None
    for line in stderr.splitlines():
        m_start = _RE_START.search(line)
        if m_start:
            pending_start = float(m_start.group(1))
            continue
        m_end = _RE_END.search(line)
        if m_end and pending_start is not None:
            end = float(m_end.group(1))
            silences.append((pending_start, end))
            pending_start = None
    if pending_start is not None:
        silences.append((pending_start, duration))

    print(f"Detected {len(silences)} silent span(s).")

    # Invert silences to get non-silent spans.
    spans: list[tuple[float, float]] = []
    cursor = 0.0
    for (s, e) in silences:
        if s > cursor + 0.05:
            spans.append((cursor, s))
        cursor = max(cursor, e)
    if cursor < duration - 0.05:
        spans.append((cursor, duration))

    clips = [
        {
            "id": f"c-{i+1:03d}",
            "source": source_id,
            "start": round(s, 3),
            "end": round(e, 3),
            "label": "non-silent span (auto-detected)",
        }
        for i, (s, e) in enumerate(spans)
        if (e - s) >= 0.25
    ]

    out_path = proj / (output or "cut-plan.candidate.json")
    _write_json(out_path, {"clips": clips})
    total = sum(c["end"] - c["start"] for c in clips)
    print(f"Wrote {out_path}: {len(clips)} clip(s), total {total:.2f}s of {duration:.2f}s kept.")
    print("Review and copy/merge into cut-plan.json when ready.")
    return 0
