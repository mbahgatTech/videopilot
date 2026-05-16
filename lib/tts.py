"""`tts` — synthesize voiceover MP3s from script.json.

Default engine is edge-tts (free, no key). engine: "azure" routes to
azure-cognitiveservices-speech with subscription credentials.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Callable

from . import ffmpeg_wrap

ProgressCb = Callable[[int, int, str], None]


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
    progress: ProgressCb | None = None,
) -> int:
    proj = root / slug
    script_path = proj / "script.json"
    if not script_path.exists():
        raise SystemExit(f"script.json missing in project: {proj}")
    script = _load_json(script_path)

    defaults = script.get("voice_defaults", {}) or {}
    segments = script.get("segments", []) or []
    if not segments:
        print("script.json has no segments; nothing to do.")
        return 0

    voice_dir = proj / "voice"
    voice_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = voice_dir / "manifest.json"
    manifest = _load_json(manifest_path) if manifest_path.exists() else {"segments": []}
    existing = {s["id"]: s for s in manifest.get("segments", [])}

    only_set = set(only or [])
    todo = [s for s in segments if (not only_set or s["id"] in only_set)]
    print(f"Synthesizing {len(todo)} segment(s) (engine default: {defaults.get('engine','edge-tts')})")

    total = len(todo)
    if progress is not None and total > 0:
        progress(0, total, "starting tts")

    new_entries: dict[str, dict] = {}
    for i, seg in enumerate(todo, start=1):
        seg_id = seg["id"]
        if progress is not None:
            progress(i, total, f"synth {seg_id}")
        out_path = voice_dir / f"{seg_id}.mp3"
        if out_path.exists() and not force:
            print(f"  [skip] {seg_id} (exists; pass --force to regenerate)")
            continue

        engine = (seg.get("engine") or defaults.get("engine") or "edge-tts").lower()
        voice = seg.get("voice") or defaults.get("voice")
        rate = seg.get("rate") or defaults.get("rate") or "+0%"
        pitch = seg.get("pitch") or defaults.get("pitch") or "+0Hz"
        if not voice:
            raise SystemExit(f"segment '{seg_id}' has no voice and no voice_defaults.voice")

        text = seg["text"]
        print(f"  [{engine}] {seg_id} -> {out_path.name} ({voice})")

        if engine == "edge-tts":
            asyncio.run(_synth_edge(text, voice, rate, pitch, out_path))
        elif engine == "azure":
            _synth_azure(text, voice, rate, pitch, out_path, style=seg.get("style"))
        else:
            raise SystemExit(f"Unknown engine: {engine}")

        info = ffmpeg_wrap.probe(out_path)
        entry = {
            "id": seg_id,
            "path": f"voice/{out_path.name}",
            "duration_sec": round(info.duration_sec, 3),
            "engine": engine,
            "voice": voice,
            "pause_after_ms": int(seg.get("pause_after_ms", 0) or 0),
        }
        new_entries[seg_id] = entry

    # Merge into manifest, preserving entries for segments not regenerated.
    merged: list[dict] = []
    for seg in segments:
        sid = seg["id"]
        if sid in new_entries:
            merged.append(new_entries[sid])
        elif sid in existing:
            merged.append(existing[sid])
    manifest = {"segments": merged}
    _write_json(manifest_path, manifest)
    print(f"Wrote {manifest_path}")
    return 0


async def _synth_edge(text: str, voice: str, rate: str, pitch: str, out: Path) -> None:
    try:
        import edge_tts
    except ImportError:
        print("edge-tts not installed. `pip install -r requirements.txt`", file=sys.stderr)
        raise SystemExit(1)

    # If text is wrapped in <speak>, treat as SSML pass-through.
    stripped = text.strip()
    if stripped.startswith("<speak"):
        comm = edge_tts.Communicate(stripped, voice)
    else:
        comm = edge_tts.Communicate(stripped, voice, rate=rate, pitch=pitch)
    await comm.save(str(out))
    if not out.exists() or out.stat().st_size == 0:
        raise SystemExit(f"edge-tts produced no audio for output: {out}")


def _synth_azure(text: str, voice: str, rate: str, pitch: str, out: Path, *, style: str | None = None) -> None:
    try:
        import azure.cognitiveservices.speech as speechsdk
    except ImportError:
        print(
            "azure-cognitiveservices-speech not installed. `pip install azure-cognitiveservices-speech`",
            file=sys.stderr,
        )
        raise SystemExit(1)

    key = os.environ.get("AZURE_SPEECH_KEY")
    region = os.environ.get("AZURE_SPEECH_REGION")
    if not key or not region:
        raise SystemExit("AZURE_SPEECH_KEY / AZURE_SPEECH_REGION env vars are required for engine: azure")

    cfg = speechsdk.SpeechConfig(subscription=key, region=region)
    cfg.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Audio48Khz192KBitRateMonoMp3
    )
    audio_cfg = speechsdk.audio.AudioOutputConfig(filename=str(out))
    synth = speechsdk.SpeechSynthesizer(speech_config=cfg, audio_config=audio_cfg)

    stripped = text.strip()
    if stripped.startswith("<speak"):
        ssml = stripped
    else:
        # Wrap as SSML so we can apply rate/pitch/style consistently.
        style_open = f'<mstts:express-as style="{style}">' if style else ""
        style_close = "</mstts:express-as>" if style else ""
        # Extract locale from voice short name like en-US-AvaNeural.
        locale = "-".join(voice.split("-")[:2])
        ssml = (
            f'<speak version="1.0" xml:lang="{locale}" '
            f'xmlns:mstts="https://www.w3.org/2001/mstts">'
            f'<voice name="{voice}">'
            f'{style_open}'
            f'<prosody rate="{rate}" pitch="{pitch}">{_xml_escape(stripped)}</prosody>'
            f'{style_close}'
            f'</voice></speak>'
        )

    result = synth.speak_ssml_async(ssml).get()
    if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
        details = getattr(result, "error_details", "(no details)")
        raise SystemExit(f"Azure TTS failed: {result.reason}: {details}")


def _xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
