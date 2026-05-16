"""List available TTS voices for the chosen engine."""

from __future__ import annotations

import asyncio
import os
import sys


def run(*, engine: str = "edge-tts", locale: str | None = None) -> int:
    if engine == "edge-tts":
        return _edge(locale)
    if engine == "azure":
        return _azure(locale)
    print(f"Unknown engine: {engine}", file=sys.stderr)
    return 2


def _edge(locale: str | None) -> int:
    try:
        import edge_tts
    except ImportError:
        print("edge-tts not installed. `pip install -r requirements.txt`", file=sys.stderr)
        return 1

    async def _list() -> list[dict]:
        return await edge_tts.list_voices()

    voices = asyncio.run(_list())
    if locale:
        voices = [v for v in voices if v.get("Locale", "").lower() == locale.lower()]

    voices.sort(key=lambda v: (v.get("Locale", ""), v.get("ShortName", "")))
    print(f"{len(voices)} edge-tts voices" + (f" in locale {locale}" if locale else ""))
    print(f"{'ShortName':<46} {'Gender':<8} {'Locale':<10} Personalities")
    for v in voices:
        personalities = ",".join(v.get("VoiceTag", {}).get("VoicePersonalities", []) or [])
        print(
            f"{v.get('ShortName',''):<46} "
            f"{v.get('Gender',''):<8} "
            f"{v.get('Locale',''):<10} {personalities}"
        )
    return 0


def _azure(locale: str | None) -> int:
    try:
        import azure.cognitiveservices.speech as speechsdk
    except ImportError:
        print(
            "azure-cognitiveservices-speech not installed. "
            "`pip install azure-cognitiveservices-speech`",
            file=sys.stderr,
        )
        return 1

    key = os.environ.get("AZURE_SPEECH_KEY")
    region = os.environ.get("AZURE_SPEECH_REGION")
    if not key or not region:
        print("Set AZURE_SPEECH_KEY and AZURE_SPEECH_REGION env vars first.", file=sys.stderr)
        return 1

    cfg = speechsdk.SpeechConfig(subscription=key, region=region)
    synth = speechsdk.SpeechSynthesizer(speech_config=cfg, audio_config=None)
    result = synth.get_voices_async(locale or "").get()
    if result.reason != speechsdk.ResultReason.VoicesListRetrieved:
        print(f"Azure voice list failed: {result.error_details}", file=sys.stderr)
        return 1

    voices = result.voices
    voices.sort(key=lambda v: (v.locale, v.short_name))
    print(f"{len(voices)} Azure neural voices" + (f" in locale {locale}" if locale else ""))
    print(f"{'ShortName':<46} {'Gender':<8} {'Locale':<10} Styles")
    for v in voices:
        gender = "Female" if v.gender == speechsdk.SynthesisVoiceGender.Female else "Male"
        styles = ",".join(v.style_list or [])
        print(f"{v.short_name:<46} {gender:<8} {v.locale:<10} {styles}")
    return 0
