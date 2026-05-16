"""`cut` — apply cut-plan.json: emit clips/<id>.mp4 + clips/manifest.json."""

from __future__ import annotations

import json
from pathlib import Path

from . import ffmpeg_wrap


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def run(
    root: Path,
    slug: str,
    *,
    only: list[str] | None = None,
    force: bool = False,
    stream_copy: bool = False,
) -> int:
    proj = root / slug
    plan_path = proj / "cut-plan.json"
    if not plan_path.exists():
        raise SystemExit(f"cut-plan.json missing in {proj}")
    plan = _load_json(plan_path)
    clips = plan.get("clips", []) or []
    if not clips:
        print("cut-plan.json has no clips; nothing to do.")
        return 0

    project = _load_json(proj / "project.json")
    sources_by_id = {s["id"]: s for s in project.get("sources", [])}

    out_dir = proj / "clips"
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.json"
    manifest = _load_json(manifest_path) if manifest_path.exists() else {"clips": []}
    existing = {c["id"]: c for c in manifest.get("clips", [])}

    only_set = set(only or [])
    todo = [c for c in clips if (not only_set or c["id"] in only_set)]
    print(f"Cutting {len(todo)} clip(s) (mode: {'stream-copy' if stream_copy else 're-encode'})")

    new_entries: dict[str, dict] = {}
    for clip in todo:
        cid = clip["id"]
        src_id = clip["source"]
        if src_id not in sources_by_id:
            raise SystemExit(f"clip '{cid}': unknown source '{src_id}'")
        src = sources_by_id[src_id]
        src_path = proj / src["path"]
        if not src_path.exists():
            raise SystemExit(f"clip '{cid}': source file missing: {src_path}")

        start = float(clip["start"])
        end = float(clip["end"])
        if end <= start:
            raise SystemExit(f"clip '{cid}': end ({end}) must be > start ({start})")
        duration = end - start
        out_path = out_dir / f"{cid}.mp4"

        if out_path.exists() and not force:
            print(f"  [skip] {cid} (exists; pass --force to regenerate)")
            continue

        print(f"  [{cid}] {src_id} {start:.2f}-{end:.2f}s -> {out_path.name}")

        if stream_copy:
            args = [
                "-ss", f"{start:.3f}",
                "-i", str(src_path),
                "-t", f"{duration:.3f}",
                "-c", "copy",
                "-avoid_negative_ts", "make_zero",
                str(out_path),
            ]
        else:
            args = [
                "-ss", f"{start:.3f}",
                "-i", str(src_path),
                "-t", f"{duration:.3f}",
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "20",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "192k",
                "-ar", "48000",
                "-ac", "2",
                "-movflags", "+faststart",
                str(out_path),
            ]
        ffmpeg_wrap.run_ffmpeg(args)

        info = ffmpeg_wrap.probe(out_path)
        new_entries[cid] = {
            "id": cid,
            "source": src_id,
            "path": f"clips/{out_path.name}",
            "source_start": round(start, 3),
            "source_end": round(end, 3),
            "duration_sec": round(info.duration_sec, 3),
            "label": clip.get("label", ""),
        }

    merged: list[dict] = []
    for clip in clips:
        cid = clip["id"]
        if cid in new_entries:
            merged.append(new_entries[cid])
        elif cid in existing:
            merged.append(existing[cid])
    _write_json(manifest_path, {"clips": merged})
    print(f"Wrote {manifest_path}")
    return 0
