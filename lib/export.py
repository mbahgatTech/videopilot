"""`export` — emit EDL / FCPXML / replayable ffmpeg script for a composed timeline."""

from __future__ import annotations

import json
import shlex
from pathlib import Path

from . import ffmpeg_wrap


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def run(
    root: Path,
    slug: str,
    *,
    edl: bool = False,
    fcpxml: bool = False,
    script: bool = False,
) -> int:
    if not any([edl, fcpxml, script]):
        raise SystemExit("Pass at least one of --edl --fcpxml --script.")

    proj = root / slug
    plan = _load_json(proj / "compose-plan.json")
    fps = int((plan.get("output") or {}).get("fps", 30))
    out_name = (plan.get("output") or {}).get("filename", "final.mp4")
    base_stem = Path(out_name).stem

    clips_manifest_path = proj / "clips" / "manifest.json"
    voice_manifest_path = proj / "voice" / "manifest.json"
    clips_by_id: dict[str, dict] = {}
    voice_by_id: dict[str, dict] = {}
    if clips_manifest_path.exists():
        clips_by_id = {c["id"]: c for c in _load_json(clips_manifest_path).get("clips", [])}
    if voice_manifest_path.exists():
        voice_by_id = {v["id"]: v for v in _load_json(voice_manifest_path).get("segments", [])}

    project = _load_json(proj / "project.json")
    sources_by_id = {s["id"]: s for s in project.get("sources", [])}

    out_dir = proj / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    if edl:
        target = out_dir / f"{base_stem}.edl"
        _write_edl(plan, clips_by_id, voice_by_id, sources_by_id, fps, base_stem, target)
        print(f"Wrote {target}")
    if fcpxml:
        target = out_dir / f"{base_stem}.fcpxml"
        _write_fcpxml(plan, clips_by_id, voice_by_id, sources_by_id, fps, base_stem, target, proj)
        print(f"Wrote {target}")
    if script:
        target = out_dir / "render.ps1"
        _write_render_script(plan, clips_by_id, voice_by_id, target)
        print(f"Wrote {target}")
    return 0


# ----- EDL (CMX 3600) ----------------------------------------------------------

def _seconds_to_tc(seconds: float, fps: int) -> str:
    total_frames = round(seconds * fps)
    f = total_frames % fps
    s = (total_frames // fps) % 60
    m = (total_frames // (fps * 60)) % 60
    h = total_frames // (fps * 60 * 60)
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


def _write_edl(
    plan: dict,
    clips_by_id: dict,
    voice_by_id: dict,
    sources_by_id: dict,
    fps: int,
    title: str,
    target: Path,
) -> None:
    lines: list[str] = []
    lines.append(f"TITLE: {title.upper()}")
    lines.append("FCM: NON-DROP FRAME")
    lines.append("")

    record_cursor = 0.0
    evt = 0
    for item in plan.get("timeline", []) or []:
        kind = item.get("type", "clip")
        if kind == "clip":
            clip = clips_by_id.get(item.get("clip", ""))
            if clip is None:
                continue
            src = sources_by_id.get(clip.get("source", ""))
            reel = (src.get("id") if src else "AX").upper()[:8]
            src_in = float(clip["source_start"])
            src_out = float(clip["source_end"])
            duration = src_out - src_in
            evt += 1
            rec_in = record_cursor
            rec_out = record_cursor + duration
            record_cursor = rec_out
            lines.append(
                f"{evt:03d}  {reel:<8} V     C        "
                f"{_seconds_to_tc(src_in, fps)} {_seconds_to_tc(src_out, fps)} "
                f"{_seconds_to_tc(rec_in, fps)} {_seconds_to_tc(rec_out, fps)}"
            )
            lines.append(f"* FROM CLIP NAME: {clip.get('label') or clip['id']}")
            lines.append(f"* CLIP ID: {clip['id']}")
            if item.get("voiceover"):
                lines.append(f"* VOICEOVER: {item['voiceover']}")
            lines.append("")
        elif kind == "slide":
            dur = _slide_duration(item, voice_by_id)
            evt += 1
            rec_in = record_cursor
            rec_out = record_cursor + dur
            record_cursor = rec_out
            lines.append(
                f"{evt:03d}  SLIDE    V     C        "
                f"00:00:00:00 {_seconds_to_tc(dur, fps)} "
                f"{_seconds_to_tc(rec_in, fps)} {_seconds_to_tc(rec_out, fps)}"
            )
            label = item.get("title") or item.get("subtitle") or "Slide"
            lines.append(f"* FROM CLIP NAME: {label}")
            lines.append("")
        elif kind == "gap":
            dur = float(item.get("duration_sec", 0))
            evt += 1
            rec_in = record_cursor
            rec_out = record_cursor + dur
            record_cursor = rec_out
            lines.append(
                f"{evt:03d}  GAP      V     C        "
                f"00:00:00:00 {_seconds_to_tc(dur, fps)} "
                f"{_seconds_to_tc(rec_in, fps)} {_seconds_to_tc(rec_out, fps)}"
            )
            lines.append("* FROM CLIP NAME: Gap")
            lines.append("")

    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ----- FCPXML -----------------------------------------------------------------

def _slide_duration(item: dict, voice_by_id: dict) -> float:
    if item.get("voiceover") and item["voiceover"] in voice_by_id:
        return float(voice_by_id[item["voiceover"]]["duration_sec"]) + float(
            item.get("pad_after_sec", 0.3)
        )
    return float(item.get("duration_sec", 0.0))


def _seconds_to_rational(seconds: float, fps: int) -> str:
    frames = round(seconds * fps)
    return f"{frames * 1000}/{fps * 1000}s"


def _xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _write_fcpxml(
    plan: dict,
    clips_by_id: dict,
    voice_by_id: dict,
    sources_by_id: dict,
    fps: int,
    title: str,
    target: Path,
    proj: Path,
) -> None:
    res = (plan.get("output") or {}).get("resolution", "1920x1080")
    try:
        w, h = (int(x) for x in res.lower().split("x"))
    except Exception:
        w, h = 1920, 1080
    frame_dur = f"1000/{fps * 1000}s"

    asset_lines: list[str] = []
    resource_id_map: dict[str, str] = {}
    next_id = 1

    # Build assets from sources (clips reference into sources, not into cut MP4s,
    # so the NLE can re-trim if it wants to).
    for src_id, src in sources_by_id.items():
        rid = f"r{next_id}"
        next_id += 1
        src_abs = (proj / src["path"]).resolve()
        url = src_abs.as_uri()
        dur_sec = float(src.get("duration_sec", 0))
        dur_rational = _seconds_to_rational(dur_sec, fps)
        asset_lines.append(
            f'    <asset id="{rid}" name="{_xml_escape(src_id)}" '
            f'src="{_xml_escape(url)}" hasVideo="1" hasAudio="1" '
            f'format="r0" duration="{dur_rational}" start="0s"/>'
        )
        resource_id_map[src_id] = rid

    # Voiceover assets.
    voice_resource_id_map: dict[str, str] = {}
    for vo_id, vo in voice_by_id.items():
        rid = f"r{next_id}"
        next_id += 1
        vo_abs = (proj / vo["path"]).resolve()
        url = vo_abs.as_uri()
        dur_rational = _seconds_to_rational(float(vo["duration_sec"]), fps)
        asset_lines.append(
            f'    <asset id="{rid}" name="{_xml_escape(vo_id)}" '
            f'src="{_xml_escape(url)}" hasVideo="0" hasAudio="1" '
            f'duration="{dur_rational}" start="0s"/>'
        )
        voice_resource_id_map[vo_id] = rid

    spine_elements: list[str] = []
    offset_sec = 0.0
    for item in plan.get("timeline", []) or []:
        kind = item.get("type", "clip")
        offset_str = _seconds_to_rational(offset_sec, fps)
        if kind == "clip":
            clip = clips_by_id.get(item.get("clip", ""))
            if not clip:
                continue
            src_id = clip["source"]
            rid = resource_id_map.get(src_id)
            if not rid:
                continue
            in_sec = float(clip["source_start"])
            dur_sec = float(clip["source_end"]) - in_sec
            spine_elements.append(
                f'        <asset-clip name="{_xml_escape(clip.get("label") or clip["id"])}" '
                f'offset="{offset_str}" '
                f'ref="{rid}" '
                f'start="{_seconds_to_rational(in_sec, fps)}" '
                f'duration="{_seconds_to_rational(dur_sec, fps)}" '
                f'tcFormat="NDF"/>'
            )
            if item.get("voiceover") and item["voiceover"] in voice_resource_id_map:
                vrid = voice_resource_id_map[item["voiceover"]]
                vdur = float(voice_by_id[item["voiceover"]]["duration_sec"])
                spine_elements.append(
                    f'        <audio name="{_xml_escape(item["voiceover"])}" '
                    f'lane="-1" offset="{offset_str}" '
                    f'ref="{vrid}" start="0s" '
                    f'duration="{_seconds_to_rational(vdur, fps)}"/>'
                )
            offset_sec += dur_sec
        elif kind == "slide":
            dur_sec = _slide_duration(item, voice_by_id)
            spine_elements.append(
                f'        <gap name="{_xml_escape(item.get("title") or "Slide")}" '
                f'offset="{offset_str}" '
                f'start="0s" duration="{_seconds_to_rational(dur_sec, fps)}"/>'
            )
            if item.get("voiceover") and item["voiceover"] in voice_resource_id_map:
                vrid = voice_resource_id_map[item["voiceover"]]
                vdur = float(voice_by_id[item["voiceover"]]["duration_sec"])
                spine_elements.append(
                    f'        <audio name="{_xml_escape(item["voiceover"])}" '
                    f'lane="-1" offset="{offset_str}" '
                    f'ref="{vrid}" start="0s" '
                    f'duration="{_seconds_to_rational(vdur, fps)}"/>'
                )
            offset_sec += dur_sec
        elif kind == "gap":
            dur_sec = float(item.get("duration_sec", 0))
            spine_elements.append(
                f'        <gap name="Gap" offset="{offset_str}" '
                f'start="0s" duration="{_seconds_to_rational(dur_sec, fps)}"/>'
            )
            offset_sec += dur_sec

    total_dur = _seconds_to_rational(offset_sec, fps)

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.10">
  <resources>
    <format id="r0" name="FFVideoFormat{h}p{fps}" frameDuration="{frame_dur}" width="{w}" height="{h}"/>
{chr(10).join(asset_lines)}
  </resources>
  <library>
    <event name="{_xml_escape(title)}">
      <project name="{_xml_escape(title)}">
        <sequence format="r0" duration="{total_dur}" tcStart="0s" tcFormat="NDF" audioLayout="stereo" audioRate="48k">
          <spine>
{chr(10).join(spine_elements)}
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>
"""
    target.write_text(xml, encoding="utf-8")


# ----- Replayable ffmpeg script -----------------------------------------------

def _write_render_script(
    plan: dict, clips_by_id: dict, voice_by_id: dict, target: Path
) -> None:
    lines: list[str] = []
    lines.append("# Replayable render script generated by videopilot.")
    lines.append("# Edit ffmpeg invocations freely. Run from the project directory:")
    lines.append("#   cd projects\\<slug>")
    lines.append("#   .\\out\\render.ps1")
    lines.append("")
    lines.append("$ErrorActionPreference = 'Stop'")
    lines.append("$tmp = 'tmp'")
    lines.append("$out = 'out'")
    lines.append("New-Item -ItemType Directory -Force -Path $tmp, $out | Out-Null")
    lines.append("")

    out_cfg = plan.get("output", {}) or {}
    res = out_cfg.get("resolution", "1920x1080")
    fps = out_cfg.get("fps", 30)
    out_name = out_cfg.get("filename", "final.mp4")

    intermediates: list[str] = []
    for idx, item in enumerate(plan.get("timeline", []) or [], start=1):
        seg = f"$tmp/seg_{idx:03d}.mp4"
        intermediates.append(seg)
        kind = item.get("type", "clip")
        if kind == "clip":
            clip = clips_by_id.get(item.get("clip", ""))
            if not clip:
                continue
            vo_id = item.get("voiceover")
            cmd = f"# Segment {idx}: clip '{clip['id']}'"
            if vo_id:
                cmd += f" with VO '{vo_id}'"
            lines.append(cmd)
            args = [
                "ffmpeg -y -hide_banner -loglevel error",
                f"-i \"{clip['path']}\"",
            ]
            if vo_id and vo_id in voice_by_id:
                args.append(f"-i \"{voice_by_id[vo_id]['path']}\"")
            args.append(f"-vf \"scale={res.replace('x',':')}:force_original_aspect_ratio=decrease,"
                        f"pad={res.replace('x',':')}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={fps}\"")
            args.append(f"-r {fps} -pix_fmt yuv420p -c:v libx264 -crf 20")
            args.append("-c:a aac -ar 48000 -ac 2 -b:a 192k")
            args.append(f"\"{seg}\"")
            lines.append(" `\n  ".join(args))
            lines.append("")
        elif kind == "slide":
            color = item.get("background_color", "#000000")
            lines.append(f"# Segment {idx}: slide")
            args = [
                "ffmpeg -y -hide_banner -loglevel error",
                f"-f lavfi -i \"color=c=0x{color.lstrip('#')}:s={res}:r={fps}\"",
            ]
            vo_id = item.get("voiceover")
            if vo_id and vo_id in voice_by_id:
                args.append(f"-i \"{voice_by_id[vo_id]['path']}\"")
                args.append(f"-shortest")
            else:
                args.append(f"-f lavfi -i \"anullsrc=r=48000:cl=stereo\"")
                args.append(f"-t {item.get('duration_sec', 3)}")
            args.append(f"-r {fps} -pix_fmt yuv420p -c:v libx264 -crf 20")
            args.append("-c:a aac -ar 48000 -ac 2 -b:a 192k")
            args.append(f"\"{seg}\"")
            lines.append(" `\n  ".join(args))
            lines.append("")
        elif kind == "gap":
            dur = item.get("duration_sec", 1)
            lines.append(f"# Segment {idx}: gap")
            args = [
                "ffmpeg -y -hide_banner -loglevel error",
                f"-f lavfi -i \"color=c=0x000000:s={res}:r={fps}\"",
                f"-f lavfi -i \"anullsrc=r=48000:cl=stereo\"",
                f"-t {dur}",
                f"-r {fps} -pix_fmt yuv420p -c:v libx264 -crf 20",
                "-c:a aac -ar 48000 -ac 2 -b:a 192k",
                f"\"{seg}\"",
            ]
            lines.append(" `\n  ".join(args))
            lines.append("")

    # Concat list.
    lines.append("# Build concat list and combine.")
    lines.append("$concatPath = \"$tmp/concat.txt\"")
    lines.append(
        "@("
        + ", ".join(f"'file ''{p}'''" for p in intermediates)
        + ") | Out-File -Encoding ascii $concatPath"
    )
    lines.append(
        "ffmpeg -y -hide_banner -loglevel error -f concat -safe 0 "
        f"-i $concatPath -c copy \"$out/{out_name}\""
    )
    lines.append("")
    lines.append("Write-Host \"Rendered: $out/" + out_name + "\"")

    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
