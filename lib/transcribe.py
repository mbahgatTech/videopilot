"""`transcribe` — run faster-whisper on a project source, emit JSON + SRT."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Callable

ProgressCb = Callable[[int, int, str], None]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _format_srt_ts(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    hours = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{mins:02d}:{secs:02d},{millis:03d}"


def run(
    root: Path,
    slug: str,
    source_id: str,
    *,
    model: str = "base",
    language: str | None = None,
    progress: ProgressCb | None = None,
) -> int:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("faster-whisper not installed. `pip install -r requirements.txt`", file=sys.stderr)
        return 1

    proj = root / slug
    project = _load_json(proj / "project.json")
    src = next((s for s in project.get("sources", []) if s["id"] == source_id), None)
    if src is None:
        raise SystemExit(
            f"source id '{source_id}' not found in project. "
            f"Known ids: {[s['id'] for s in project.get('sources', [])]}"
        )
    src_path = proj / src["path"]
    if not src_path.exists():
        raise SystemExit(f"Source file missing: {src_path}")

    out_dir = proj / "transcripts"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_out = out_dir / f"{source_id}.json"
    srt_out = out_dir / f"{source_id}.srt"

    print(f"Loading faster-whisper model: {model} (first run downloads weights)")
    wm = WhisperModel(model, device="cpu", compute_type="int8")
    if progress is not None:
        progress(0, 1, "model loaded")
    print(f"Transcribing: {src_path}")
    seg_iter, info = wm.transcribe(
        str(src_path),
        language=language,
        word_timestamps=True,
        vad_filter=True,
    )

    segments: list[dict] = []
    srt_lines: list[str] = []

    for i, seg in enumerate(seg_iter, start=1):
        words = []
        if seg.words:
            for w in seg.words:
                words.append(
                    {
                        "start": round(w.start, 3),
                        "end": round(w.end, 3),
                        "word": w.word,
                        "probability": round(w.probability, 3) if w.probability is not None else None,
                    }
                )
        segments.append(
            {
                "id": i,
                "start": round(seg.start, 3),
                "end": round(seg.end, 3),
                "text": seg.text.strip(),
                "words": words,
            }
        )
        srt_lines.append(str(i))
        srt_lines.append(f"{_format_srt_ts(seg.start)} --> {_format_srt_ts(seg.end)}")
        srt_lines.append(seg.text.strip())
        srt_lines.append("")

        if (i % 20) == 0:
            print(f"  ... {i} segments")
        if progress is not None and (i % 10) == 0:
            progress(i, 0, f"transcribed {i} segments")

    _write_json(
        json_out,
        {
            "source_id": source_id,
            "source_path": str(src["path"]),
            "language": info.language,
            "language_probability": round(info.language_probability, 3),
            "model": model,
            "duration_sec": round(info.duration, 3),
            "segments": segments,
        },
    )
    srt_out.write_text("\n".join(srt_lines) + "\n", encoding="utf-8")
    print(f"Wrote {json_out}  ({len(segments)} segments)")
    print(f"Wrote {srt_out}")
    return 0
