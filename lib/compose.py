"""`compose` — render final video per compose-plan.json.

Pipeline:
  1. Render each timeline item as `tmp/seg_NNN.mp4` at canonical params.
  2. Concatenate intermediates with the ffmpeg concat demuxer.
  3. If background_music is configured, mix it under the concat result.
"""

from __future__ import annotations

import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import ffmpeg_wrap

ProgressCb = Callable[[int, int, str], None]

# Canonical fallback render parameters when compose-plan.json omits them.
_DEFAULT_RES = (1920, 1080)
_DEFAULT_FPS = 30
_DEFAULT_VBITRATE = "8M"
_DEFAULT_ABITRATE = "192k"
_DEFAULT_VCODEC = "libx264"
_DEFAULT_ACODEC = "aac"
_DEFAULT_SR = 48000
_DEFAULT_AC = 2

# zoompan motion -- allowed values for the optional `motion` slide field.
# Anchor names mirror common compositing tools (After Effects, OBS).
# Pan direction follows cinematography convention: "pan left" = the camera
# (visible window) moves toward the left edge of the image, so content
# appears to move right. Documented in the slide schema.
_VALID_MOTION_TYPES = {"zoom_in", "zoom_out", "pan"}
_VALID_ANCHORS = {"center", "top_left", "top_right", "bottom_left", "bottom_right"}
_VALID_PAN_DIRECTIONS = {"left", "right", "up", "down"}
# zoompan's `zoom` expression is internally clamped to [1, 10]; values outside
# this range silently saturate. Reject up front so the agent gets a clear
# error instead of mystery output.
_MIN_ZOOM = 1.0
_MAX_ZOOM = 10.0

_FONT_CANDIDATES = [
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/calibri.ttf",
]


@dataclass
class RenderParams:
    width: int
    height: int
    fps: int
    vbitrate: str
    abitrate: str
    vcodec: str
    acodec: str
    sr: int
    ac: int

    @classmethod
    def from_output(cls, out: dict[str, Any]) -> "RenderParams":
        res = out.get("resolution", f"{_DEFAULT_RES[0]}x{_DEFAULT_RES[1]}")
        try:
            w, h = (int(x) for x in res.lower().split("x"))
        except Exception:
            raise SystemExit(f"output.resolution invalid: {res!r}; want e.g. 1920x1080")
        return cls(
            width=w,
            height=h,
            fps=int(out.get("fps", _DEFAULT_FPS)),
            vbitrate=str(out.get("video_bitrate", _DEFAULT_VBITRATE)),
            abitrate=str(out.get("audio_bitrate", _DEFAULT_ABITRATE)),
            vcodec=str(out.get("video_codec", _DEFAULT_VCODEC)),
            acodec=str(out.get("audio_codec", _DEFAULT_ACODEC)),
            sr=int(out.get("sample_rate", _DEFAULT_SR)),
            ac=int(out.get("audio_channels", _DEFAULT_AC)),
        )

    def video_encode_args(self) -> list[str]:
        return [
            "-c:v", self.vcodec,
            "-preset", "medium",
            "-crf", "20",
            "-b:v", self.vbitrate,
            "-pix_fmt", "yuv420p",
            "-r", str(self.fps),
        ]

    def audio_encode_args(self) -> list[str]:
        return [
            "-c:a", self.acodec,
            "-b:a", self.abitrate,
            "-ar", str(self.sr),
            "-ac", str(self.ac),
        ]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _font_path() -> str:
    for f in _FONT_CANDIDATES:
        if Path(f).exists():
            # Double-escape the drive-letter colon so it survives both
            # filtergraph-level and filter-level parsing.
            return f.replace(":", r"\\:")
    print(
        "WARNING: No usable system font found; slide title/subtitle text will be skipped.",
        file=sys.stderr,
    )
    return ""


def _color_to_ffmpeg(color: str | None) -> str:
    if not color:
        return "0x000000"
    c = color.strip()
    if c.startswith("#"):
        return "0x" + c[1:]
    return c


def _escape_drawtext_value(s: str) -> str:
    # Inside drawtext, escape backslash, colon, and any chars that delimit filter args.
    return (
        s.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace(",", "\\,")
        .replace("%", "\\%")
    )


def _write_textfile(tmp_dir: Path, name: str, text: str) -> str:
    p = tmp_dir / name
    p.write_text(text, encoding="utf-8")
    # Forward slashes + double-escaped colon for the drive letter.
    return str(p).replace("\\", "/").replace(":", r"\\:")


def _scale_pad(rp: RenderParams) -> str:
    return (
        f"scale={rp.width}:{rp.height}:force_original_aspect_ratio=decrease,"
        f"pad={rp.width}:{rp.height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"setsar=1,fps={rp.fps},format=yuv420p"
    )


def _validate_zoom(value: float, field: str) -> float:
    """Reject zoom factors outside zoompan's documented [1, 10] range."""
    if not math.isfinite(value):
        raise SystemExit(f"slide motion: `{field}` must be finite, got {value!r}")
    if value < _MIN_ZOOM or value > _MAX_ZOOM:
        raise SystemExit(
            f"slide motion: `{field}` must be between {_MIN_ZOOM} and "
            f"{_MAX_ZOOM} (zoompan's documented range), got {value!r}"
        )
    return value


def _motion_anchor_xy(anchor: str) -> tuple[str, str]:
    """Return (x_expr, y_expr) for a static zoom anchor.

    Coordinates are in zoompan's input-image space: `iw`/`ih` are the input
    dimensions and `zoom` is the *current* zoom factor. The selectable range
    along each axis is `0..iw-iw/zoom`, collapsing to 0 when zoom==1.
    """
    if anchor == "center":
        return "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"
    if anchor == "top_left":
        return "0", "0"
    if anchor == "top_right":
        return "iw-iw/zoom", "0"
    if anchor == "bottom_left":
        return "0", "ih-ih/zoom"
    if anchor == "bottom_right":
        return "iw-iw/zoom", "ih-ih/zoom"
    raise SystemExit(
        f"slide motion: unknown anchor {anchor!r}. "
        f"Valid: {sorted(_VALID_ANCHORS)}"
    )


def _build_motion_filter(motion: dict, total: float, rp: RenderParams) -> str:
    """Emit a single `zoompan=...` filter string for a slide `motion` block.

    zoompan semantics that drove the math here:

    * zoompan consumes one source frame and emits `d` output frames. With a
      looped still input (`-loop 1`) the source can supply arbitrarily many
      frames, so if `d` is smaller than the trim window zoompan will start a
      *second* animation cycle -- producing a visible snap-back. Setting
      `d = ceil(total*fps) + 1` plus clamping progress with `min(on,denom)`
      guarantees the animation finishes inside the trim window AND never
      spills into a second source frame.

    * `on` is zoompan's global output frame counter (not per-source-frame),
      so `on/denom` is a valid 0..1 progress.

    * Setting `s=WxH:fps=FPS` is required: zoompan's default fps is 25
      (not the project fps) and its default size is the input size.

    * Expressions go inside single quotes; ffmpeg's filtergraph parser owns
      the quoting, no shell escaping needed.
    """
    if not isinstance(motion, dict):
        raise SystemExit(f"slide motion: must be an object, got {type(motion).__name__}")
    mtype = motion.get("type")
    if mtype not in _VALID_MOTION_TYPES:
        raise SystemExit(
            f"slide motion: unknown type {mtype!r}. "
            f"Valid: {sorted(_VALID_MOTION_TYPES)}"
        )
    if total <= 0 or not math.isfinite(total):
        raise SystemExit(f"slide motion: slide duration must be > 0, got {total!r}")
    if rp.fps <= 0:
        raise SystemExit(f"slide motion: project fps must be > 0, got {rp.fps!r}")

    visible_frames = max(1, math.ceil(total * rp.fps))
    d = visible_frames + 1
    denom = max(visible_frames - 1, 1)
    progress = f"min(on,{denom})/{denom}"
    reverse = f"(1-min(on,{denom})/{denom})"

    if mtype in ("zoom_in", "zoom_out"):
        default_from, default_to = (1.0, 1.15) if mtype == "zoom_in" else (1.15, 1.0)
        try:
            zfrom = _validate_zoom(float(motion.get("from", default_from)), "from")
            zto = _validate_zoom(float(motion.get("to", default_to)), "to")
        except (TypeError, ValueError) as exc:
            raise SystemExit(f"slide motion: `from`/`to` must be numbers: {exc}")
        anchor = motion.get("anchor", "center")
        x_expr, y_expr = _motion_anchor_xy(anchor)
        z_expr = f"{zfrom}+({zto}-{zfrom})*{progress}"
    else:
        direction = motion.get("direction")
        if direction not in _VALID_PAN_DIRECTIONS:
            raise SystemExit(
                f"slide motion: pan requires `direction` in "
                f"{sorted(_VALID_PAN_DIRECTIONS)}; got {direction!r}"
            )
        try:
            zoom_const = _validate_zoom(float(motion.get("zoom", 1.15)), "zoom")
        except (TypeError, ValueError) as exc:
            raise SystemExit(f"slide motion: `zoom` must be a number: {exc}")
        z_expr = f"{zoom_const}"
        if direction == "left":
            x_expr, y_expr = f"(iw-iw/zoom)*{reverse}", "(ih-ih/zoom)/2"
        elif direction == "right":
            x_expr, y_expr = f"(iw-iw/zoom)*{progress}", "(ih-ih/zoom)/2"
        elif direction == "up":
            x_expr, y_expr = "(iw-iw/zoom)/2", f"(ih-ih/zoom)*{reverse}"
        else:
            x_expr, y_expr = "(iw-iw/zoom)/2", f"(ih-ih/zoom)*{progress}"

    return (
        f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}':"
        f"d={d}:s={rp.width}x{rp.height}:fps={rp.fps}"
    )


def _format_body_line(line: str) -> str:
    """Apply bullet prefix unless line already starts with a list marker."""
    if re.match(r"^\d+\. ", line):
        return line
    if line.startswith("• "):
        return line
    if line.startswith("-  "):
        return line
    return "•  " + line


def _build_drawtext_filters(
    item: dict, rp: RenderParams, tmp_dir: Path, idx: int, font: str
) -> list[str]:
    if not font:
        return []
    filters: list[str] = []
    title = item.get("title")
    subtitle = item.get("subtitle")
    body = item.get("body") or []
    if title:
        tf = _write_textfile(tmp_dir, f"seg_{idx:03d}_title.txt", title)
        filters.append(
            f"drawtext=fontfile={font}:textfile={tf}:fontsize=80:fontcolor=white"
            f":box=0:x=(w-text_w)/2:y=(h/2)-100"
        )
    if subtitle:
        sf = _write_textfile(tmp_dir, f"seg_{idx:03d}_subtitle.txt", subtitle)
        filters.append(
            f"drawtext=fontfile={font}:textfile={sf}:fontsize=42:fontcolor=white"
            f":x=(w-text_w)/2:y=(h/2)+20"
        )
    if body:
        base_offset = 110
        line_height = 56
        for li, raw in enumerate(body):
            text = _format_body_line(str(raw))
            bf = _write_textfile(tmp_dir, f"seg_{idx:03d}_body_{li:02d}.txt", text)
            y_expr = f"(h/2)+{base_offset + li * line_height}"
            filters.append(
                f"drawtext=fontfile={font}:textfile={bf}:fontsize=36:fontcolor=white"
                f":x=200:y={y_expr}"
            )
    return filters


def run(
    root: Path,
    slug: str,
    *,
    progress: ProgressCb | None = None,
    only_index: int | None = None,
) -> int:
    proj = root / slug
    plan_path = proj / "compose-plan.json"
    if not plan_path.exists():
        raise SystemExit(f"compose-plan.json missing in {proj}")
    plan = _load_json(plan_path)
    timeline = plan.get("timeline", []) or []
    if not timeline:
        raise SystemExit("compose-plan.json: timeline is empty.")

    if only_index is not None and not (0 <= only_index < len(timeline)):
        raise SystemExit(
            f"only_index {only_index} out of range; timeline has {len(timeline)} item(s)"
        )

    rp = RenderParams.from_output(plan.get("output", {}) or {})
    out_cfg = plan.get("output", {}) or {}
    out_name = out_cfg.get("filename", "final.mp4")

    clips_manifest_path = proj / "clips" / "manifest.json"
    voice_manifest_path = proj / "voice" / "manifest.json"
    clips_by_id: dict[str, dict] = {}
    voice_by_id: dict[str, dict] = {}
    if clips_manifest_path.exists():
        clips_by_id = {c["id"]: c for c in _load_json(clips_manifest_path).get("clips", [])}
    if voice_manifest_path.exists():
        voice_by_id = {v["id"]: v for v in _load_json(voice_manifest_path).get("segments", [])}

    tmp_dir = proj / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    for old in tmp_dir.glob("seg_*.mp4"):
        old.unlink()
    for old in tmp_dir.glob("seg_*.txt"):
        old.unlink()

    out_dir = proj / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    final_path = out_dir / out_name

    font = _font_path()

    # Single-segment preview: render only the requested item, skip concat & bg mix.
    if only_index is not None:
        item = timeline[only_index]
        kind = item.get("type", "clip")
        preview_path = out_dir / f"preview-{only_index:03d}.mp4"
        if progress is not None:
            progress(1, 1, f"segment 1/1 ({kind})")
        if kind == "clip":
            _render_clip(proj, item, clips_by_id, voice_by_id, rp, preview_path, progress=progress)
        elif kind == "slide":
            _render_slide(
                proj, item, voice_by_id, rp, tmp_dir, only_index + 1, font, preview_path,
                progress=progress,
            )
        elif kind == "gap":
            _render_gap(item, rp, preview_path)
        else:
            raise SystemExit(f"timeline item {only_index + 1}: unknown type {kind!r}")
        print(f"Rendered preview: {preview_path}")
        return 0

    print(f"Rendering {len(timeline)} timeline item(s) at {rp.width}x{rp.height}@{rp.fps}fps")
    intermediates: list[Path] = []
    total_segs = len(timeline)
    for idx, item in enumerate(timeline, start=1):
        seg_out = tmp_dir / f"seg_{idx:03d}.mp4"
        kind = item.get("type", "clip")
        if progress is not None:
            progress(idx, total_segs, f"segment {idx}/{total_segs} ({kind})")
        if kind == "clip":
            _render_clip(proj, item, clips_by_id, voice_by_id, rp, seg_out, progress=progress)
        elif kind == "slide":
            _render_slide(proj, item, voice_by_id, rp, tmp_dir, idx, font, seg_out, progress=progress)
        elif kind == "gap":
            _render_gap(item, rp, seg_out)
        else:
            raise SystemExit(f"timeline item {idx}: unknown type {kind!r}")
        intermediates.append(seg_out)
        print(f"  [{idx:03d}] {kind:5} -> {seg_out.name}")

    if progress is not None:
        progress(total_segs, total_segs, "concat")

    concat_list = tmp_dir / "concat.txt"
    concat_list.write_text(
        "".join(f"file '{p.as_posix()}'\n" for p in intermediates),
        encoding="utf-8",
    )

    bg = plan.get("background_music")
    if bg:
        intermediate_concat = tmp_dir / "concat.mp4"
        ffmpeg_wrap.run_ffmpeg(
            [
                "-f", "concat", "-safe", "0",
                "-i", str(concat_list),
                "-c", "copy",
                str(intermediate_concat),
            ]
        )
        _mix_background_music(intermediate_concat, proj, bg, rp, final_path)
    else:
        ffmpeg_wrap.run_ffmpeg(
            [
                "-f", "concat", "-safe", "0",
                "-i", str(concat_list),
                "-c", "copy",
                str(final_path),
            ]
        )

    info = ffmpeg_wrap.probe(final_path)
    print(f"\nRendered: {final_path}")
    print(f"  duration: {info.duration_sec:.2f}s, {info.width}x{info.height}@{info.fps:.0f}fps")
    return 0


def _render_clip(
    proj: Path,
    item: dict,
    clips_by_id: dict[str, dict],
    voice_by_id: dict[str, dict],
    rp: RenderParams,
    out_path: Path,
    progress: ProgressCb | None = None,
) -> None:
    cid = item.get("clip")
    if not cid or cid not in clips_by_id:
        raise SystemExit(
            f"timeline clip refers to unknown id {cid!r}. Run `cut` first or check cut-plan.json."
        )
    clip = clips_by_id[cid]
    clip_path = proj / clip["path"]
    clip_dur = float(clip["duration_sec"])

    vo_id = item.get("voiceover")
    pad_to_vo = bool(item.get("pad_to_voiceover", True))
    mute_src = bool(item.get("mute_source", False))
    duck_db = item.get("duck_source_db", -15 if vo_id else 0)

    if vo_id and vo_id not in voice_by_id:
        raise SystemExit(
            f"timeline clip '{cid}' references voiceover '{vo_id}' which is not in "
            f"voice/manifest.json. Run `tts` first."
        )

    args: list[str] = []
    filter_complex_parts: list[str] = []

    args += ["-i", str(clip_path)]
    if vo_id:
        vo = voice_by_id[vo_id]
        args += ["-i", str(proj / vo["path"])]
        vo_dur = float(vo["duration_sec"])
        target_dur = max(clip_dur, vo_dur) if pad_to_vo else clip_dur
        extra_pad = max(0.0, target_dur - clip_dur)

        if extra_pad > 0.01:
            filter_complex_parts.append(
                f"[0:v]tpad=stop_mode=clone:stop_duration={extra_pad:.3f},{_scale_pad(rp)}[vout]"
            )
        else:
            filter_complex_parts.append(f"[0:v]{_scale_pad(rp)}[vout]")

        # Duck (or mute) the source audio; if source had no audio, anullsrc fallback.
        src_vol_expr = "volume=0" if mute_src else f"volume={duck_db}dB"
        filter_complex_parts.append(
            f"[0:a]aresample={rp.sr},aformat=channel_layouts=stereo,"
            f"{src_vol_expr},apad=whole_dur={target_dur:.3f}[a0]"
        )
        filter_complex_parts.append(
            f"[1:a]aresample={rp.sr},aformat=channel_layouts=stereo,"
            f"apad=whole_dur={target_dur:.3f}[a1]"
        )
        filter_complex_parts.append(
            f"[a0][a1]amix=inputs=2:duration=longest:normalize=0,"
            f"atrim=duration={target_dur:.3f}[aout]"
        )
        args += ["-filter_complex", ";".join(filter_complex_parts)]
        args += ["-map", "[vout]", "-map", "[aout]"]
        args += ["-t", f"{target_dur:.3f}"]
        render_dur = target_dur
    else:
        filter_complex_parts.append(f"[0:v]{_scale_pad(rp)}[vout]")
        src_vol_expr = "volume=0" if mute_src else None
        if src_vol_expr:
            filter_complex_parts.append(
                f"[0:a]aresample={rp.sr},aformat=channel_layouts=stereo,{src_vol_expr}[aout]"
            )
        else:
            filter_complex_parts.append(
                f"[0:a]aresample={rp.sr},aformat=channel_layouts=stereo[aout]"
            )
        args += ["-filter_complex", ";".join(filter_complex_parts)]
        args += ["-map", "[vout]", "-map", "[aout]"]
        render_dur = clip_dur

    args += rp.video_encode_args() + rp.audio_encode_args()
    args += [str(out_path)]
    ffmpeg_wrap.run_ffmpeg(args, progress=progress, target_duration_sec=render_dur)


def _render_slide(
    proj: Path,
    item: dict,
    voice_by_id: dict[str, dict],
    rp: RenderParams,
    tmp_dir: Path,
    idx: int,
    font: str,
    out_path: Path,
    progress: ProgressCb | None = None,
) -> None:
    vo_id = item.get("voiceover")
    duration = item.get("duration_sec")
    bg_image = item.get("background_image")
    bg_color = item.get("background_color", "#000000")

    if vo_id:
        if vo_id not in voice_by_id:
            raise SystemExit(
                f"slide references voiceover '{vo_id}' not in voice/manifest.json. Run `tts` first."
            )
        vo_dur = float(voice_by_id[vo_id]["duration_sec"])
        pad_after = float(item.get("pad_after_sec", 0.3))
        total = vo_dur + pad_after
    elif duration is not None:
        total = float(duration)
    else:
        raise SystemExit(
            f"slide must have either `voiceover` or `duration_sec`. Item: {item}"
        )

    args: list[str] = []
    vf_chain: list[str] = []

    if bg_image:
        bg_path = (proj / bg_image).resolve()
        if not bg_path.exists():
            raise SystemExit(f"slide background_image not found: {bg_path}")
        args += ["-loop", "1", "-i", str(bg_path)]
        vf_chain.append(_scale_pad(rp))
    else:
        color_arg = _color_to_ffmpeg(bg_color)
        args += [
            "-f", "lavfi",
            "-i", f"color=c={color_arg}:s={rp.width}x{rp.height}:r={rp.fps}",
        ]
        # color source is already correct size/fps; still ensure pixel format.
        vf_chain.append(f"format=yuv420p,setsar=1,fps={rp.fps}")

    motion = item.get("motion")
    if motion is not None:
        if not bg_image:
            raise SystemExit(
                "slide motion requires `background_image`; motion on a solid "
                "`background_color` is a visual no-op. "
                f"Item: {json.dumps(item, ensure_ascii=False)}"
            )
        vf_chain.append(_build_motion_filter(motion, total, rp))

    text_filters = _build_drawtext_filters(item, rp, tmp_dir, idx, font)
    if text_filters:
        vf_chain.extend(text_filters)

    if vo_id:
        args += ["-i", str(proj / voice_by_id[vo_id]["path"])]
    else:
        args += ["-f", "lavfi", "-i", f"anullsrc=r={rp.sr}:cl=stereo"]

    filter_complex = (
        f"[0:v]{','.join(vf_chain)},trim=duration={total:.3f},setpts=PTS-STARTPTS[vout];"
        f"[1:a]aresample={rp.sr},aformat=channel_layouts=stereo,"
        f"apad=whole_dur={total:.3f},atrim=duration={total:.3f},asetpts=PTS-STARTPTS[aout]"
    )
    args += ["-filter_complex", filter_complex]
    args += ["-map", "[vout]", "-map", "[aout]"]
    args += ["-t", f"{total:.3f}"]
    args += rp.video_encode_args() + rp.audio_encode_args()
    args += [str(out_path)]
    ffmpeg_wrap.run_ffmpeg(args, progress=progress, target_duration_sec=total)


def _render_gap(item: dict, rp: RenderParams, out_path: Path) -> None:
    duration = float(item.get("duration_sec", 0))
    if duration <= 0:
        raise SystemExit("gap requires positive duration_sec")
    args = [
        "-f", "lavfi", "-i", f"color=c=0x000000:s={rp.width}x{rp.height}:r={rp.fps}",
        "-f", "lavfi", "-i", f"anullsrc=r={rp.sr}:cl=stereo",
        "-t", f"{duration:.3f}",
        "-pix_fmt", "yuv420p",
    ]
    args += rp.video_encode_args() + rp.audio_encode_args() + [str(out_path)]
    ffmpeg_wrap.run_ffmpeg(args)


def _mix_background_music(
    concat_video: Path, proj: Path, bg: dict, rp: RenderParams, final_path: Path
) -> None:
    music_rel = bg.get("path")
    if not music_rel:
        raise SystemExit("background_music.path is required")
    music_path = (proj / music_rel).resolve()
    if not music_path.exists():
        raise SystemExit(f"background_music.path not found: {music_path}")

    volume_db = float(bg.get("volume_db", -22))
    fade_in = float(bg.get("fade_in_sec", 1.0))
    fade_out = float(bg.get("fade_out_sec", 2.0))

    info = ffmpeg_wrap.probe(concat_video)
    total = info.duration_sec
    fade_out_start = max(0.0, total - fade_out)

    filter_complex = (
        f"[1:a]aresample={rp.sr},aformat=channel_layouts=stereo,"
        f"volume={volume_db}dB,"
        f"afade=t=in:st=0:d={fade_in:.3f},"
        f"afade=t=out:st={fade_out_start:.3f}:d={fade_out:.3f}[bg];"
        f"[0:a][bg]amix=inputs=2:duration=first:normalize=0[aout]"
    )
    args = [
        "-i", str(concat_video),
        "-stream_loop", "-1", "-i", str(music_path),
        "-filter_complex", filter_complex,
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy",
    ]
    args += rp.audio_encode_args() + [str(final_path)]
    ffmpeg_wrap.run_ffmpeg(args)
