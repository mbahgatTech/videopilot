"""Unit + integration tests for slide `motion` (zoompan) support.

Validates the contract the rest of the codebase relies on:

  1. `_build_motion_filter` emits well-formed zoompan filter strings for
     every supported motion type, with the correct math (clamped progress,
     ceil-based duration_frames, fps + size set explicitly).

  2. Invalid motion blocks fail with a clear error BEFORE reaching ffmpeg,
     so agents get actionable feedback instead of an opaque ffmpeg parse
     error 30 frames into a render.

  3. `_render_slide` end-to-end with a real bg_image + motion produces a
     non-zero-byte MP4 -- proving the filtergraph survives ffmpeg's parser
     and the H.264 encoder accepts the zoompan output.

Run: `py tests/slide_motion_unit.py`
"""

from __future__ import annotations

import math
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.path.insert(0, str(REPO_ROOT))

from lib import compose
from lib import ffmpeg_wrap


def _rp(width: int = 1920, height: int = 1080, fps: int = 30) -> compose.RenderParams:
    """Minimal RenderParams for tests; values match canonical project defaults."""
    return compose.RenderParams(
        width=width,
        height=height,
        fps=fps,
        vbitrate="8M",
        abitrate="192k",
        vcodec="libx264",
        acodec="aac",
        sr=48000,
        ac=2,
    )


# ---------------------------------------------------------------------------
# Pure-function tests for `_build_motion_filter`
# ---------------------------------------------------------------------------


def test_zoom_in_default_anchor_is_centered() -> None:
    rp = _rp()
    out = compose._build_motion_filter({"type": "zoom_in"}, 10.0, rp)
    # ceil(10 * 30) + 1 = 301 output frames; denom = 299.
    assert "d=301" in out, out
    assert "s=1920x1080" in out, out
    assert "fps=30" in out, out
    # Default zoom_in: 1.0 -> 1.15 with clamped progress.
    assert "z='1.0+(1.15-1.0)*min(on,299)/299'" in out, out
    # Centered anchor.
    assert "x='(iw-iw/zoom)/2'" in out, out
    assert "y='(ih-ih/zoom)/2'" in out, out
    print("[slide_motion] zoom_in_default_anchor_is_centered            PASS")


def test_zoom_in_top_left_anchor() -> None:
    out = compose._build_motion_filter(
        {"type": "zoom_in", "anchor": "top_left"}, 5.0, _rp()
    )
    assert "x='0'" in out, out
    assert "y='0'" in out, out
    print("[slide_motion] zoom_in_top_left_anchor                       PASS")


def test_zoom_out_defaults_reverse_zoom_in() -> None:
    out = compose._build_motion_filter({"type": "zoom_out"}, 5.0, _rp())
    # zoom_out defaults are 1.15 -> 1.0.
    assert "z='1.15+(1.0-1.15)*min(on," in out, out
    print("[slide_motion] zoom_out_defaults_reverse_zoom_in             PASS")


def test_pan_left_animates_x_from_max_to_zero() -> None:
    out = compose._build_motion_filter(
        {"type": "pan", "direction": "left"}, 4.0, _rp()
    )
    # Constant zoom (default 1.15), x traverses from max to 0, y centered.
    assert "z='1.15'" in out, out
    # `reverse` = (1 - min(on,denom)/denom) -> x starts at (iw-iw/zoom) and ends at 0.
    assert "x='(iw-iw/zoom)*(1-min(on," in out, out
    assert "y='(ih-ih/zoom)/2'" in out, out
    print("[slide_motion] pan_left_animates_x_from_max_to_zero          PASS")


def test_pan_down_animates_y_from_zero_to_max() -> None:
    out = compose._build_motion_filter(
        {"type": "pan", "direction": "down", "zoom": 1.3}, 6.0, _rp()
    )
    assert "z='1.3'" in out, out
    assert "x='(iw-iw/zoom)/2'" in out, out
    # forward progress for y: starts at 0, ends at (ih-ih/zoom).
    assert "y='(ih-ih/zoom)*min(on," in out, out
    print("[slide_motion] pan_down_animates_y_from_zero_to_max          PASS")


def test_duration_frames_ceil_plus_one() -> None:
    """The fractional-frame slide (10.05s @ 30fps) should still cover the trim window."""
    out = compose._build_motion_filter({"type": "zoom_in"}, 10.05, _rp())
    # ceil(10.05 * 30) = 302; +1 = 303.
    assert "d=303" in out, out
    print("[slide_motion] duration_frames_ceil_plus_one                 PASS")


def test_short_slide_collapses_denom_safely() -> None:
    """A 1-frame slide must not crash with divide-by-zero."""
    rp = _rp(fps=30)
    out = compose._build_motion_filter({"type": "zoom_in"}, 1.0 / 30.0, rp)
    # ceil(1/30 * 30) = 1; denom = max(0, 1) = 1.
    assert "min(on,1)/1" in out, out
    print("[slide_motion] short_slide_collapses_denom_safely            PASS")


def test_unknown_type_raises_with_actionable_message() -> None:
    try:
        compose._build_motion_filter({"type": "spin"}, 5.0, _rp())
    except SystemExit as exc:
        msg = str(exc)
        assert "spin" in msg, msg
        assert "zoom_in" in msg and "zoom_out" in msg and "pan" in msg, msg
        print("[slide_motion] unknown_type_raises_with_actionable_message  PASS")
        return
    raise AssertionError("expected SystemExit for unknown motion type")


def test_pan_missing_direction_raises() -> None:
    try:
        compose._build_motion_filter({"type": "pan"}, 5.0, _rp())
    except SystemExit as exc:
        msg = str(exc)
        assert "direction" in msg, msg
        print("[slide_motion] pan_missing_direction_raises                 PASS")
        return
    raise AssertionError("expected SystemExit for pan without direction")


def test_zoom_out_of_range_raises() -> None:
    """Values outside zoompan's [1, 10] window silently saturate; reject upfront."""
    try:
        compose._build_motion_filter({"type": "zoom_in", "to": 15.0}, 5.0, _rp())
    except SystemExit as exc:
        msg = str(exc)
        assert "10" in msg and ("to" in msg or "between" in msg), msg
        print("[slide_motion] zoom_out_of_range_raises                     PASS")
        return
    raise AssertionError("expected SystemExit for zoom > 10")


def test_zoom_below_one_raises() -> None:
    try:
        compose._build_motion_filter(
            {"type": "zoom_in", "from": 0.5}, 5.0, _rp()
        )
    except SystemExit as exc:
        assert "from" in str(exc) or "1.0" in str(exc), exc
        print("[slide_motion] zoom_below_one_raises                        PASS")
        return
    raise AssertionError("expected SystemExit for zoom < 1.0")


def test_zero_duration_raises() -> None:
    try:
        compose._build_motion_filter({"type": "zoom_in"}, 0.0, _rp())
    except SystemExit as exc:
        assert "duration" in str(exc), exc
        print("[slide_motion] zero_duration_raises                         PASS")
        return
    raise AssertionError("expected SystemExit for total<=0")


def test_unknown_anchor_raises() -> None:
    try:
        compose._build_motion_filter(
            {"type": "zoom_in", "anchor": "middle"}, 5.0, _rp()
        )
    except SystemExit as exc:
        assert "middle" in str(exc), exc
        print("[slide_motion] unknown_anchor_raises                        PASS")
        return
    raise AssertionError("expected SystemExit for unknown anchor")


# ---------------------------------------------------------------------------
# End-to-end: _render_slide actually drives ffmpeg with a motion-enabled slide
# ---------------------------------------------------------------------------


def _generate_test_png(path: Path) -> None:
    """Use ffmpeg to make a 320x240 red PNG -- avoids needing PIL in tests.

    Routes through ``ffmpeg_wrap.run_ffmpeg`` so the same PATH-discovery
    logic that powers the real renderer also applies here (WinGet's
    Gyan.FFmpeg install isn't on raw user PATH on Windows).
    """
    ffmpeg_wrap.run_ffmpeg(
        [
            "-f", "lavfi", "-i", "color=c=red:s=320x240",
            "-frames:v", "1",
            str(path),
        ],
        target_duration_sec=0.05,
    )


def test_render_slide_with_motion_end_to_end() -> None:
    """A slide with bg_image + motion renders to a valid MP4 in <5s."""
    if not ffmpeg_wrap.have_ffmpeg():
        print("[slide_motion] SKIP end-to-end: ffmpeg not on PATH")
        return
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        bg = td_path / "bg.png"
        _generate_test_png(bg)
        out = td_path / "slide.mp4"

        item = {
            "type": "slide",
            "duration_sec": 1.0,
            "background_image": "bg.png",
            "motion": {"type": "zoom_in", "from": 1.0, "to": 1.2, "anchor": "center"},
        }
        compose._render_slide(
            proj=td_path,
            item=item,
            voice_by_id={},
            rp=_rp(width=640, height=360, fps=30),
            tmp_dir=td_path,
            idx=1,
            font="",  # disables drawtext
            out_path=out,
        )
        assert out.exists(), "output not produced"
        size = out.stat().st_size
        assert size > 1000, f"output suspiciously small: {size}"

        # Sanity-check duration with ffprobe: must be close to 1.0s.
        info = ffmpeg_wrap.probe(out)
        assert 0.7 < info.duration_sec < 1.4, f"unexpected duration {info.duration_sec}"
        # Capture into locals BEFORE the tempdir __exit__ cleans up the file.
        duration_sec = info.duration_sec
    print(
        "[slide_motion] render_slide_with_motion_end_to_end           PASS  "
        f"(duration={duration_sec:.2f}s, size={size})"
    )


def test_render_slide_motion_without_bg_image_raises() -> None:
    """Motion on a solid-color slide is a no-op visually; reject up front."""
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        item = {
            "type": "slide",
            "duration_sec": 1.0,
            "background_color": "#ff0000",
            "motion": {"type": "zoom_in"},
        }
        try:
            compose._render_slide(
                proj=td_path,
                item=item,
                voice_by_id={},
                rp=_rp(),
                tmp_dir=td_path,
                idx=1,
                font="",
                out_path=td_path / "out.mp4",
            )
        except SystemExit as exc:
            assert "background_image" in str(exc), exc
            print("[slide_motion] motion_without_bg_image_raises               PASS")
            return
    raise AssertionError("expected SystemExit for motion on solid-color slide")


def main() -> int:
    failures = 0
    tests = [
        test_zoom_in_default_anchor_is_centered,
        test_zoom_in_top_left_anchor,
        test_zoom_out_defaults_reverse_zoom_in,
        test_pan_left_animates_x_from_max_to_zero,
        test_pan_down_animates_y_from_zero_to_max,
        test_duration_frames_ceil_plus_one,
        test_short_slide_collapses_denom_safely,
        test_unknown_type_raises_with_actionable_message,
        test_pan_missing_direction_raises,
        test_zoom_out_of_range_raises,
        test_zoom_below_one_raises,
        test_zero_duration_raises,
        test_unknown_anchor_raises,
        test_render_slide_with_motion_end_to_end,
        test_render_slide_motion_without_bg_image_raises,
    ]
    for fn in tests:
        try:
            fn()
        except AssertionError as exc:
            failures += 1
            print(f"[slide_motion] {fn.__name__}  FAIL: {exc}")
        except Exception as exc:
            failures += 1
            print(f"[slide_motion] {fn.__name__}  ERROR: {type(exc).__name__}: {exc}")
    if failures:
        print(f"[slide_motion] {failures} failure(s)")
        return 1
    print("[slide_motion] all tests PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
