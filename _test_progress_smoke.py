"""Smoke test for lib/ progress callbacks.

Run from the repo root:
    py _test_progress_smoke.py

This is intentionally not under a test framework -- it exercises the public
contract changes end-to-end against a real ffmpeg invocation.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from lib import compose as compose_mod  # noqa: E402
from lib import tts as tts_mod  # noqa: E402


def main() -> int:
    tmp_root = Path(tempfile.mkdtemp(prefix="vp_smoke_"))
    slug = "smoke"
    proj = tmp_root / slug
    proj.mkdir(parents=True, exist_ok=True)

    # 2) Minimal project.json + compose-plan.json with two slide items
    #    (one with body, one without).
    (proj / "project.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "name": "smoke",
                "sources": [],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    compose_plan = {
        "output": {
            "filename": "final.mp4",
            "resolution": "640x360",
            "fps": 24,
            "video_bitrate": "1M",
            "audio_bitrate": "96k",
        },
        "timeline": [
            {
                "type": "slide",
                "title": "Hello",
                "subtitle": "first slide",
                "duration_sec": 1.0,
                "background_color": "#202040",
            },
            {
                "type": "slide",
                "title": "Plain",
                "subtitle": "second slide",
                "duration_sec": 1.0,
                "background_color": "#404020",
            },
        ],
    }
    (proj / "compose-plan.json").write_text(
        json.dumps(compose_plan, indent=2), encoding="utf-8"
    )

    # 3) Optional: synthesize a tiny tts segment to exercise tts progress.
    #    Skip silently if network or edge-tts is unavailable.
    try:
        (proj / "script.json").write_text(
            json.dumps(
                {
                    "voice_defaults": {
                        "engine": "edge-tts",
                        "voice": "en-US-AriaNeural",
                    },
                    "segments": [
                        {"id": "vo-smoke", "text": "hi"},
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        tts_calls: list[tuple[int, int, str]] = []
        tts_mod.run(
            tmp_root,
            slug,
            progress=lambda c, t, m: tts_calls.append((c, t, m)),
        )
        assert any(
            m.startswith("synth vo-smoke") for _, _, m in tts_calls
        ), f"tts progress missing per-segment call; got {tts_calls!r}"
        print(f"[smoke] tts progress calls: {len(tts_calls)} -> {tts_calls}")
    except Exception as exc:  # network / azure / etc.
        print(f"[smoke] tts step skipped: {exc!r}")

    # 4) Full compose with progress collector.
    calls: list[tuple[int, int, str]] = []

    def collect(current: int, total: int, message: str) -> None:
        calls.append((current, total, message))

    rc = compose_mod.run(tmp_root, slug, progress=collect)
    assert rc == 0, f"compose.run returned {rc}"
    assert len(calls) >= 3, f"expected >=3 progress calls, got {len(calls)}: {calls!r}"
    print(f"[smoke] compose progress calls: {len(calls)} -> {calls}")

    # 6) Final video exists.
    final_path = proj / "out" / "final.mp4"
    assert final_path.exists() and final_path.stat().st_size > 0, (
        f"expected {final_path} to exist and be non-empty"
    )
    print(f"[smoke] final.mp4 size: {final_path.stat().st_size} bytes")

    # 7) Cleanup on success.
    shutil.rmtree(tmp_root, ignore_errors=True)
    print("[smoke] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
