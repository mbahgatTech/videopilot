# video-creator — Agent Runbook

> **You are the calling LLM (GitHub Copilot CLI, Claude, etc.).** This document tells
> you how to drive `videopilot.py` from a user's natural-language request to produce
> a finished video. Read it in full before invoking the CLI.

## Mental model

`videopilot.py` is a **pure executor**. It does mechanical things (run ffmpeg, run
Whisper, run Edge TTS) and reads/writes JSON state files. **You** (the LLM) do the
creative + planning work:

- You write the voiceover script (`script.json`).
- You pick which sections to keep from a long video (`cut-plan.json`) — either by
  reading a transcript or by translating the user's explicit trim instructions.
- You assemble the final timeline (`compose-plan.json`) — which clip plays when,
  which voiceover overlays it, where slides go, where background music drops.
- Then you call `videopilot.py` subcommands to make it happen.

The JSON state files in `projects/<slug>/` are the **contract** between you and the
CLI. The CLI never invents content — it does exactly what the JSON says.

## Invocation

`videopilot` is installed as a console script — it works from **any** directory:

```powershell
videopilot <subcommand> <args>
```

If the command isn't found in a fresh shell, refresh PATH first:

```powershell
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
```

The CLI auto-detects ffmpeg in the WinGet `Gyan.FFmpeg` install location, so no manual ffmpeg PATH dance is needed.

> **Legacy invocation** (still works): `python C:\Work\tools\video-creator\videopilot.py <subcommand>`. The console-script form is preferred — every example below assumes it.

## First-time setup

Before doing any real work in a fresh environment, run:

```powershell
videopilot doctor
```

This reports missing prerequisites. If ffmpeg is missing, install with:

```powershell
winget install --id Gyan.FFmpeg -e
```

If Python packages are missing or the `videopilot` command itself is missing:

```powershell
cd C:\Work\tools\video-creator
pip install -e .
```

Re-run `doctor` until it shows all green.

> **`faster-whisper` (used by `transcribe`) is heavy.** On first run it downloads a
> ~150MB–1.5GB model depending on size. Default is `base` (~150MB). Skip
> `transcribe` if the user only wants explicit-timestamp trims or pure voiceover
> output — you don't need it for those flows.

## State files — the contracts

Every project lives at `projects/<slug>/`. These JSON files are what you author.
**Always pretty-print with 2-space indent** so they remain human-editable.

### `project.json` — overall state (created by `init`, you may extend)

```json
{
  "name": "Q4 Demo",
  "slug": "q4-demo",
  "created_at": "2026-05-15T14:30:00Z",
  "sources": [
    { "id": "raw1", "path": "sources/raw-screencast.mp4", "duration_sec": 1834.5 }
  ]
}
```

`sources[].id` is what other state files reference. Source files are copied (or
symlinked on systems that support it) into `sources/` by `init` and `import`.

### `script.json` — voiceover script (you write this)

```json
{
  "voice_defaults": {
    "voice": "en-US-AndrewMultilingualNeural",
    "rate": "+0%",
    "pitch": "+0Hz",
    "engine": "edge-tts"
  },
  "segments": [
    {
      "id": "vo-intro",
      "text": "Welcome to our quarterly review of the product launch.",
      "voice": "en-US-AvaMultilingualNeural",
      "rate": "+5%",
      "pause_after_ms": 500
    },
    {
      "id": "vo-closer",
      "text": "Thanks for watching."
    }
  ]
}
```

- `engine`: `edge-tts` (default, free, no key) or `azure` (requires
  `AZURE_SPEECH_KEY` + `AZURE_SPEECH_REGION` env vars).
- `voice`: any Microsoft Neural voice short name. List them with
  `videopilot voices`.
- `rate`: SSML rate like `-10%`, `+0%`, `+25%`.
- `pitch`: SSML pitch like `-5Hz`, `+0Hz`, `+10Hz`.
- `text` may contain SSML if you wrap it in `<speak>...</speak>` — the CLI
  passes raw SSML through when it detects a top-level `<speak>` tag.

`tts` writes `voice/<id>.mp3` for each segment + a `voice/manifest.json` with
durations (seconds, float) — read it when you author `compose-plan.json`.

### `cut-plan.json` — which sections of which sources to keep (you write this)

```json
{
  "clips": [
    {
      "id": "c-hook",
      "source": "raw1",
      "start": 12.3,
      "end": 28.5,
      "label": "the moment they show the wireframe"
    },
    {
      "id": "c-key",
      "source": "raw1",
      "start": 145.2,
      "end": 167.0,
      "label": "Sarah's key insight about onboarding"
    }
  ]
}
```

Times are in seconds (float). `cut` writes `clips/<id>.mp4` and a
`clips/manifest.json` with verified durations.

If the user gives explicit timestamps, translate directly. If they say "pick
the highlights," run `transcribe` first, read the transcript, and choose
spans yourself. **You** decide what's important — the CLI has no opinion.

### `compose-plan.json` — timeline assembly (you write this)

```json
{
  "output": {
    "filename": "final.mp4",
    "resolution": "1920x1080",
    "fps": 30,
    "video_bitrate": "8M",
    "audio_bitrate": "192k",
    "video_codec": "libx264",
    "audio_codec": "aac"
  },
  "timeline": [
    {
      "type": "slide",
      "duration_sec": 4.0,
      "background_color": "#0b132b",
      "title": "Q4 Product Review",
      "subtitle": "May 2026",
      "voiceover": "vo-intro"
    },
    {
      "type": "clip",
      "clip": "c-hook",
      "voiceover": null
    },
    {
      "type": "clip",
      "clip": "c-key",
      "voiceover": "vo-key-insight",
      "duck_source_db": -18,
      "pad_to_voiceover": true
    },
    {
      "type": "slide",
      "duration_sec": 3.0,
      "background_image": "sources/logo.png",
      "voiceover": "vo-closer"
    }
  ],
  "background_music": {
    "path": "sources/music.mp3",
    "volume_db": -22,
    "fade_in_sec": 1.0,
    "fade_out_sec": 2.0
  }
}
```

Timeline item types:

**`clip`** — plays a cut clip. Fields:
- `clip` (required): id from `cut-plan.json`
- `voiceover` (optional): id from `script.json`; mixed on top of clip audio
- `duck_source_db` (optional, default −15 when VO present, 0 otherwise): how
  much to attenuate the clip's original audio under the voiceover
- `pad_to_voiceover` (optional, default true): if VO is longer than the clip,
  freeze-frame the last frame to match; if VO is shorter than the clip, the
  clip plays out and the VO ends early (use a longer clip or split the VO if
  you don't want that)

**`slide`** — a static title card. Fields:
- `duration_sec` (required UNLESS `voiceover` is set; then VO duration +
  optional `pad_after_sec` determines it)
- `background_color` (optional, hex; default `#000000`)
- `background_image` (optional, path relative to project dir; if both color
  and image are set, image wins)
- `title` (optional): large heading text overlay
- `subtitle` (optional): smaller text below title
- `body` (optional, `list[str]`): body lines rendered left-aligned below the
  subtitle (fontsize 36, `x=200`, starting at `y=h/2+110`, 56px line height).
  Each list entry is one line. Lines starting with `\d+. ` (numbered),
  `"• "`, or `"-  "` are passed through verbatim; any other line is
  auto-prefixed with `"•  "` so plain strings render as bullets.
- `voiceover` (optional): id from script.json

Example slide with body bullets:

```json
{
  "type": "slide",
  "voiceover": "vo-agenda",
  "background_color": "#0b132b",
  "title": "Today's Agenda",
  "subtitle": "Three things to cover",
  "body": [
    "Why the onboarding flow is broken",
    "What the metrics actually show",
    "1. Ship the fix this sprint",
    "- Already-dashed lines pass through"
  ]
}
```

**`gap`** — a fixed silent black pause (useful for breathing room):
- `duration_sec` (required)

`background_music` is mixed under the entire final video at the given volume,
with optional fades.

### Output files

After `compose`, `out/` contains:

- `final.mp4` — the rendered video
- `final.fcpxml` (if `--fcpxml` passed) — Final Cut XML, imports into Final Cut
  Pro, Premiere Pro, DaVinci Resolve
- `final.edl` (if `--edl` passed) — CMX 3600 EDL, broadly supported
- `render.ps1` (if `--script` passed) — a replayable PowerShell script that
  reproduces the render with raw ffmpeg commands; the user can hand-tweak it

## Workflow recipes

### Recipe 1 — "Make a 60-second voiceover video from this script"

User has a brief, no source video. Output: MP4 of slides + voiceover.

1. `videopilot init <slug>` — creates `projects/<slug>/`
2. **You write** `projects/<slug>/script.json` — one segment per beat
3. `videopilot tts <slug>` — synth voice MP3s, populates `voice/manifest.json`
4. Read `voice/manifest.json` to learn segment durations
5. **You write** `projects/<slug>/compose-plan.json` — slides keyed to VO ids
6. `videopilot compose <slug>` — renders `out/final.mp4`

### Recipe 2 — "Cut this long video down to highlights, no narration"

User has one source video, wants a tight cut. No voiceover.

1. `videopilot init <slug> --source <path>` — copies source into project
2. `videopilot transcribe <slug> raw1` — emits `transcripts/raw1.json`
   with word-level timestamps and `transcripts/raw1.srt`
3. **You read** the transcript and decide which spans to keep
4. **You write** `cut-plan.json` with chosen spans
5. **You write** a minimal `compose-plan.json` — one timeline entry per clip,
   no voiceover
6. `videopilot cut <slug>` — emits `clips/<id>.mp4`
7. `videopilot compose <slug>` — renders `out/final.mp4`

### Recipe 3 — "Cut these specific timestamps from this video"

User gives explicit "keep 0:30–1:15, 3:00–4:20" instructions. No need to transcribe.

1. `init` with source
2. **You write** `cut-plan.json` translating the user's timestamps directly
3. **You write** trivial `compose-plan.json` (each clip back-to-back)
4. `cut`
5. `compose`

### Recipe 4 — "Take this raw recording, cut the highlights, narrate over them"

The full pipeline. Combines recipes 1 + 2.

1. `init` with source
2. `transcribe` the source
3. **You** pick highlights → write `cut-plan.json`; **you** write a narration
   that complements the clips → write `script.json`
4. `cut` and `tts` (order independent — can run in parallel via separate
   PowerShell sessions, but sequential is fine)
5. Read `voice/manifest.json` for VO durations; read `clips/manifest.json`
   for clip durations
6. **You write** `compose-plan.json` lining up VOs against clips with
   appropriate ducking
7. `compose`
8. `export --edl --fcpxml --script` if the user wants to keep editing in
   another NLE

### Recipe 5 — "Just trim the boring parts" (no AI)

User wants the long video minus dead air, no smart selection.

1. `init` with source
2. `videopilot silence <slug> raw1 --threshold-db -35 --min-silence-sec 1.5`
   — emits a candidate `cut-plan.json` of NON-silent spans
3. Optionally tweak the cut-plan
4. `cut`, `compose` as usual

## Subcommand reference

| Command | Purpose |
|---|---|
| `doctor` | Check prerequisites (ffmpeg, ffprobe, Python pkgs, optional Azure keys) |
| `voices [--locale en-US] [--engine edge-tts\|azure]` | List available TTS voices |
| `init <slug> [--source <path>...] [--name "Display Name"]` | Create a project |
| `import <slug> <path> [--id raw2]` | Add another source to an existing project |
| `tts <slug> [--only <id>...] [--force]` | Synthesize voiceover MP3s from `script.json` |
| `transcribe <slug> <source-id> [--model base\|small\|medium\|large-v3] [--language en]` | Transcribe a source with faster-whisper |
| `silence <slug> <source-id> [--threshold-db -35] [--min-silence-sec 1.0]` | Emit a cut-plan candidate of non-silent spans |
| `cut <slug> [--only <clip-id>...] [--force]` | Cut clips per `cut-plan.json` |
| `compose <slug>` | Render `out/final.mp4` per `compose-plan.json` |
| `export <slug> [--edl] [--fcpxml] [--script]` | Emit NLE/replay exports |

All commands accept `--quiet` and `--verbose`.

## MCP tools — extras

When you are driving `videopilot` through the MCP server (instead of shelling
out to the CLI), six helper tools sit alongside the subcommand mirrors. They
exist so you can author state incrementally and probe staleness without
re-reading every JSON file.

| Tool | One-liner |
|---|---|
| `schema()` | Returns the authoritative JSON Schemas for every state file (`project`, `script`, `cut-plan`, `compose-plan`, `voice-manifest`, `clips-manifest`). |
| `add_vo_segment(slug, id, text, ...)` | Append or insert one voice segment into `script.json`. Creates the file with sane `voice_defaults` if missing; rejects duplicate ids. |
| `add_slide(slug, voiceover?, body?, duration_sec?, ...)` | Append or insert one slide into `compose-plan.json`. Creates the file with default 1920x1080@30fps libx264/aac output if missing. Requires `voiceover` OR `duration_sec`. |
| `set_compose_output(slug, ...)` | Patch only the `output` keys you pass (filename, resolution, fps, bitrates, codecs). Unspecified keys are left intact. |
| `preview_slide(slug, index)` | Render ONE timeline item to `out/preview-NNN.mp4` so you can iterate on a slide without paying the full-timeline cost. |
| `is_up_to_date(slug, scope?)` | mtime-based staleness check. `scope` is `"tts"`, `"cut"`, `"compose"`, `"transcribe"`, or omit for all. Returns `{up_to_date, reasons}` per scope. |

Tiny example — incrementally build a project:

```
add_vo_segment(slug="demo", id="vo-intro", text="Welcome.")
add_slide(slug="demo", voiceover="vo-intro", title="Hello", body=["Point one", "Point two"])
preview_slide(slug="demo", index=0)        # eyeball the slide
is_up_to_date(slug="demo", scope="tts")     # before re-running tts
```

Notes:

- **`schema` is the source of truth.** If a state file's contract evolves,
  the schema reflects it before this doc does. Call it when in doubt.
- **Prefer `add_vo_segment` / `add_slide` over raw `write_state`** for
  incremental builds — the helpers validate inputs, refuse id collisions,
  and create missing files with sane defaults.
- **`preview_slide` is the cheap iteration loop.** Use it while tweaking
  `title` / `subtitle` / `body` / colors instead of re-running `compose`.
- **`is_up_to_date` is the right call before re-running expensive ops**
  (`tts`, `cut`, `transcribe`, `compose`). Skip the op if every scope you
  care about reports `up_to_date: true`.

### Progress notifications

The MCP server now emits `notifications/progress` while `tts`, `transcribe`,
`compose`, `cut`, and `silence` run. Hosts that support MCP progress
(GitHub Copilot CLI, Claude, etc.) display live updates instead of staring at
a frozen tool call. The work runs on a worker thread, so the call no longer
trips MCP's request timeout on long renders.

The previous workaround of polling `tmp/` for fresh intermediate files is no
longer needed — watch the progress stream instead.

## Conventions you must follow

1. **Always run `doctor` first** in a new session if you don't know whether
   prerequisites are installed. Don't guess.
2. **Always pretty-print JSON state files with 2-space indent** and a trailing
   newline. The user reads these.
3. **Always preserve user-provided ids**. Never rename `clip` / `voiceover` /
   `source` ids without asking.
4. **Validate timing before you compose**: read `voice/manifest.json` and
   `clips/manifest.json` to confirm durations match what you wrote in
   `compose-plan.json`. If a VO is 12s and the clip is only 5s with
   `pad_to_voiceover: false`, warn the user.
5. **Don't re-run `tts` for unchanged segments** — it's slow and the audio is
   deterministic. The CLI skips existing files by default unless `--force`.
6. **Don't re-run `cut` for unchanged clips** — same reason. `cut` is idempotent.
7. **Stop and ask** if the user's request is ambiguous about what to keep,
   what voice to use, what tone the script should take, etc. Don't fabricate.
8. **Show the user the script** before you run `tts` — VO audio is not free
   and the user often wants edits. Same for `cut-plan.json` before `cut`.
9. **Final render preview**: after `compose`, tell the user where `out/final.mp4`
   is and offer to open it (`Start-Process .\projects\<slug>\out\final.mp4`).
10. **Prefer `add_vo_segment` / `add_slide` over manually-authored `write_state`
    payloads when building incrementally** — the helpers validate inputs,
    refuse id collisions, and create missing files with sane defaults. Reach
    for `write_state` only when you genuinely need to replace a whole file.

## Why no Clipchamp export

Clipchamp's project format is proprietary and undocumented. Attempting to
generate one is unreliable and breaks across Clipchamp updates. Instead we
ship:

- **FCPXML** — imports into Premiere Pro, Final Cut Pro, DaVinci Resolve
- **EDL (CMX 3600)** — broadly supported, simple format
- **`render.ps1`** — a replayable ffmpeg script the user can hand-tweak and
  re-run

If the user really wants to edit in Clipchamp, the recommended workflow is:
import `final.mp4` plus the original `sources/*.mp4` and the `voice/*.mp3`
files into Clipchamp as separate tracks. The cut clips in `clips/` can also
be imported as pre-cut pieces.

## Failure modes and recovery

| Symptom | Cause | Fix |
|---|---|---|
| `doctor`: `ffmpeg not found` | Not on PATH | `winget install --id Gyan.FFmpeg -e`; restart shell |
| `doctor`: `edge_tts not installed` | Python deps missing | `pip install -r requirements.txt` |
| `tts`: HTTP errors / "no audio received" | Edge TTS service hiccup or network | Retry; check `https://speech.platform.bing.com` reachable; switch to `engine: azure` if persistent |
| `transcribe`: model download stalls | Slow network on first run | Pre-pull manually: `python -c "from faster_whisper import WhisperModel; WhisperModel('base')"` |
| `cut`: "stream copy failed" | Source has unusual codec / variable framerate | Pass `--reencode` to `cut` to force decode/encode |
| `compose`: timeline durations don't match expectation | `pad_to_voiceover` interaction with short clips | Re-check `clips/manifest.json` vs `voice/manifest.json`; adjust `cut-plan.json` |
| `compose`: audio glitch at clip boundaries | Concat demuxer with mismatched audio params | Already mitigated — `compose` re-encodes per-segment intermediates; if it persists, file a bug with the intermediates |
| MCP `tts` / `transcribe` / `compose` / `cut` / `silence` appears to "hang" with no output | Client host doesn't render `notifications/progress` | Not a crash — the server runs the op on a worker thread and will return when done. Wait, or switch to a host that displays MCP progress (Copilot CLI, Claude). |

When in doubt, the intermediates in `tmp/` are kept after every `compose` run
(not auto-cleaned) so you can inspect what happened at each step.
