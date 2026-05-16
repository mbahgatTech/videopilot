# videopilot — Agent Runbook

> **You are an LLM connected to the `videopilot` MCP server.** This document
> tells you how to call its 20 tools to turn a user's natural-language request
> into a finished video. Read it in full before issuing your first tool call.

## Mental model

`videopilot` is a **pure executor**. Its MCP tools do mechanical things —
run ffmpeg, run faster-whisper, run Edge TTS — and read/write JSON state
files. **You** (the LLM) do the creative + planning work:

- You write the voiceover script (`script.json`) — typically by calling
  `add_vo_segment` once per beat of narration.
- You pick which sections to keep from a long video (`cut-plan.json`) — by
  reading a transcript or by translating the user's explicit trim
  instructions.
- You assemble the final timeline (`compose-plan.json`) — typically by
  calling `add_slide` once per slide and `set_compose_output` once for the
  final encode settings.
- Then you call the pipeline tools (`tts`, `cut`, `compose`, `export`) to
  make it happen.

The JSON state files in `projects/<slug>/` are the **contract** between you
and the server. The server never invents content — it does exactly what
the JSON says.

A standalone `videopilot` CLI also exists for humans to run a stage by
hand. You don't need it; every CLI subcommand has a matching MCP tool.

## First-time setup

In a fresh project / environment, your first call should be `doctor()`:

```
doctor()
```

It returns the status of ffmpeg, ffprobe, Python deps, and optional Azure
keys. If anything's missing, surface the exact message to the user — it
tells them what to install (typically `winget install --id Gyan.FFmpeg -e`
on Windows, or `brew install ffmpeg` on macOS).

> **`faster-whisper` (used by `transcribe`) is heavy.** On first call it
> downloads a ~150MB–1.5GB model depending on size. Default is `base`
> (~150MB). Skip `transcribe` if the user only wants explicit-timestamp
> trims or pure voiceover output — you don't need it for those flows.

## Tool reference

All 20 tools, grouped by purpose. Argument names and return shapes are
authoritative in `schema()` and in the server's own MCP tool metadata —
this table is a quick index.

### Diagnostics & introspection

| Tool | Purpose |
|---|---|
| `doctor()` | Verify ffmpeg, ffprobe, Python deps, optional Azure keys. Call once per session. |
| `voices(engine?, locale?)` | List available TTS voices. `engine` is `"edge-tts"` (default) or `"azure"`. |
| `schema()` | Returns the authoritative JSON Schemas for every state file (`project`, `script`, `cut-plan`, `compose-plan`, `voice-manifest`, `clips-manifest`). **The source of truth** when this doc and the schema disagree. |
| `list_projects(project_root?)` | List all projects under `projects/`. |
| `project_status(slug)` | Pipeline status for one project: which JSON state files exist, which stages have run. Call when resuming an in-progress session. |

### State authoring

| Tool | Purpose |
|---|---|
| `init(slug, name?, source?, ...)` | Create a new project, optionally with a first source video. |
| `import_source(slug, path, id?)` | Add another source to an existing project. |
| `read_state(slug, kind)` | Read a JSON state file. `kind` is `"project"` / `"script"` / `"cut-plan"` / `"compose-plan"`. |
| `write_state(slug, kind, payload)` | Replace a whole state file. Validates against schema. Reach for this only when you need to replace a whole file — prefer the incremental helpers below. |
| `add_vo_segment(slug, id, text, ...)` | Append or insert one voice segment into `script.json`. Creates the file with sane `voice_defaults` if missing. Rejects duplicate ids. |
| `add_slide(slug, voiceover?, body?, duration_sec?, ...)` | Append or insert one slide into `compose-plan.json`. Creates the file with default 1920x1080@30fps libx264/aac output if missing. Requires `voiceover` OR `duration_sec`. |
| `set_compose_output(slug, ...)` | Patch only the `output` keys you pass (filename, resolution, fps, bitrates, codecs). Unspecified keys are left intact. |

### Pipeline

These tools can take minutes. They run on a worker thread and emit
`notifications/progress` while running — hosts that support MCP progress
(GitHub Copilot CLI, etc.) display live updates instead of staring at a
frozen tool call.

| Tool | Output |
|---|---|
| `tts(slug, only?, force?)` | `voice/<id>.mp3` per segment + `voice/manifest.json` with durations. Re-runs only changed segments unless `force=true`. |
| `transcribe(slug, source_id, model?, language?)` | `transcripts/<source_id>.json` (word-level segments) + `.srt`. Returns segments to you so you can pick spans without re-reading the file. |
| `silence(slug, source_id, threshold_db?, min_silence_sec?)` | Candidate `cut-plan.json` of NON-silent spans. Use when the user just wants silence trimming. |
| `cut(slug, only?, force?)` | `clips/<id>.mp4` per clip + `clips/manifest.json`. Idempotent. |
| `compose(slug)` | `out/final.mp4`. The big one. |
| `export(slug, edl?, fcpxml?, script?)` | `out/final.edl`, `out/final.fcpxml`, `out/render.ps1` — any subset you ask for. |
| `preview_slide(slug, index)` | Render ONE timeline item to `out/preview-NNN.mp4` so you can iterate on a slide without paying the full-timeline cost. |
| `is_up_to_date(slug, scope?)` | mtime-based staleness check. `scope` is `"tts"` / `"cut"` / `"compose"` / `"transcribe"`, or omit for all. Returns `{up_to_date, reasons}` per scope. Call this before re-running an expensive pipeline tool — skip if `up_to_date: true`. |

## State files — the contracts

Every project lives at `projects/<slug>/`. These JSON files are what you
author (directly via `write_state`, or incrementally via `add_vo_segment`
/ `add_slide` / `set_compose_output`). **Always pretty-print with 2-space
indent** so they remain human-editable; the helpers do this for you, but if
you call `write_state` directly, format the payload that way too.

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

`sources[].id` is what other state files reference. Source files are copied
(or symlinked on systems that support it) into `sources/` by `init` and
`import_source`.

### `script.json` — voiceover script (you author this)

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
- `voice`: any Microsoft Neural voice short name. List them with `voices()`.
- `rate`: SSML rate like `-10%`, `+0%`, `+25%`.
- `pitch`: SSML pitch like `-5Hz`, `+0Hz`, `+10Hz`.
- `text` may contain SSML if you wrap it in `<speak>...</speak>` — the
  server passes raw SSML through when it detects a top-level `<speak>` tag.

`tts` writes `voice/<id>.mp3` for each segment + a `voice/manifest.json`
with durations (seconds, float) — read it (via `read_state` or directly)
when you author `compose-plan.json`.

### `cut-plan.json` — which sections of which sources to keep (you author this)

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

If the user gives explicit timestamps, translate directly. If they say
"pick the highlights," call `transcribe` first, read the transcript, and
choose spans yourself. **You** decide what's important — the server has
no opinion.

### `compose-plan.json` — timeline assembly (you author this)

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
- `pad_to_voiceover` (optional, default true): if VO is longer than the
  clip, freeze-frame the last frame to match; if VO is shorter than the
  clip, the clip plays out and the VO ends early (use a longer clip or
  split the VO if you don't want that)

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
- `voiceover` (optional): id from `script.json`
- `motion` (optional, object): Ken Burns motion applied to `background_image`.
  No-op on solid `background_color` (raises). Shape:
  - `{ "type": "zoom_in",  "from": 1.0,  "to": 1.18, "anchor": "center" }`
  - `{ "type": "zoom_out", "from": 1.18, "to": 1.0,  "anchor": "center" }`
  - `{ "type": "pan", "direction": "left"|"right"|"up"|"down", "zoom": 1.18 }`

  `from`/`to`/`zoom` are between 1.0 and 10.0 (zoompan's documented range).
  Anchors: `center` (default), `top_left`, `top_right`, `bottom_left`,
  `bottom_right`. Pan `direction` follows cinematography convention:
  `"left"` = camera moves left, so content appears to move right. The
  engine internally upscales the source 8× with Lanczos before zoompan so
  the motion is subpixel-smooth — you don't need to provide a pre-sized
  image, any resolution works.

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

`background_music` is mixed under the entire final video at the given
volume, with optional fades.

### Output files

After `compose`, `out/` contains:

- `final.mp4` — the rendered video
- `final.fcpxml` (if `export(slug, fcpxml=true)`) — Final Cut XML, imports
  into Final Cut Pro, Premiere Pro, DaVinci Resolve
- `final.edl` (if `export(slug, edl=true)`) — CMX 3600 EDL, broadly
  supported
- `render.ps1` (if `export(slug, script=true)`) — a replayable PowerShell
  script that reproduces the render with raw ffmpeg commands; the user
  can hand-tweak it

## Workflow recipes

Each recipe is a sequence of MCP tool calls. Replace `<slug>` with a short
url-safe identifier (e.g. `q4-demo`).

### Recipe 1 — "Make a 60-second voiceover video from this script"

User has a brief, no source video. Output: MP4 of slides + voiceover.

1. `init(slug="<slug>")`
2. For each beat of narration: `add_vo_segment(slug="<slug>", id="vo-<n>", text="...")`
3. `tts(slug="<slug>")` — synth voice MP3s, populates `voice/manifest.json`
4. `read_state(slug="<slug>", kind="voice-manifest")` to learn segment durations
5. For each slide: `add_slide(slug="<slug>", voiceover="vo-<n>", title="...", body=[...])`
6. `compose(slug="<slug>")` — renders `out/final.mp4`

### Recipe 2 — "Cut this long video down to highlights, no narration"

User has one source video, wants a tight cut. No voiceover.

1. `init(slug="<slug>", source="<path>")`
2. `transcribe(slug="<slug>", source_id="raw1")` — returns word-level
   segments + writes SRT
3. **You read** the returned segments and decide which spans to keep
4. `write_state(slug="<slug>", kind="cut-plan", payload={...})` with your
   chosen spans
5. Author a minimal `compose-plan.json` (one timeline entry per clip, no
   voiceover) via `add_slide` / `set_compose_output` or `write_state`
6. `cut(slug="<slug>")` — emits `clips/<id>.mp4`
7. `compose(slug="<slug>")` — renders `out/final.mp4`

### Recipe 3 — "Cut these specific timestamps from this video"

User gives explicit "keep 0:30–1:15, 3:00–4:20" instructions. No need to
transcribe.

1. `init(slug="<slug>", source="<path>")`
2. `write_state(slug="<slug>", kind="cut-plan", payload={...})` translating
   the user's timestamps directly
3. Author a trivial `compose-plan.json` (each clip back-to-back)
4. `cut(slug="<slug>")`
5. `compose(slug="<slug>")`

### Recipe 4 — "Take this raw recording, cut the highlights, narrate over them"

The full pipeline. Combines recipes 1 + 2.

1. `init(slug="<slug>", source="<path>")`
2. `transcribe(slug="<slug>", source_id="raw1")`
3. **You** pick highlights → write `cut-plan.json` (via `write_state`);
   **you** write narration that complements the clips → add segments via
   `add_vo_segment`
4. `cut(slug="<slug>")` and `tts(slug="<slug>")` (order independent)
5. Read `voice/manifest.json` and `clips/manifest.json` for durations
6. Author `compose-plan.json` lining up VOs against clips with appropriate
   ducking (via `add_slide` + clip entries via `write_state` of the full
   plan, or by patching with `set_compose_output` + repeated `add_slide`
   then a `write_state` for clip entries)
7. `compose(slug="<slug>")`
8. `export(slug="<slug>", edl=true, fcpxml=true, script=true)` if the user
   wants to keep editing in another NLE

### Recipe 5 — "Just trim the boring parts" (no AI)

User wants the long video minus dead air, no smart selection.

1. `init(slug="<slug>", source="<path>")`
2. `silence(slug="<slug>", source_id="raw1", threshold_db=-35, min_silence_sec=1.5)`
   — emits a candidate `cut-plan.json` of NON-silent spans
3. Optionally tweak the cut-plan via `read_state` + `write_state`
4. `cut(slug="<slug>")`, `compose(slug="<slug>")` as usual

### Incremental authoring example

```
add_vo_segment(slug="demo", id="vo-intro", text="Welcome.")
add_slide(slug="demo", voiceover="vo-intro", title="Hello",
          body=["Point one", "Point two"])
preview_slide(slug="demo", index=0)        # eyeball the slide
is_up_to_date(slug="demo", scope="tts")    # gate before re-running tts
tts(slug="demo")
```

## Conventions you must follow

1. **Always call `doctor()` first** in a new session if you don't know
   whether prerequisites are installed. Don't guess.
2. **Always preserve user-provided ids**. Never rename `clip` / `voiceover`
   / `source` ids without asking.
3. **Validate timing before you compose**: read `voice/manifest.json` and
   `clips/manifest.json` to confirm durations match what you wrote in
   `compose-plan.json`. If a VO is 12s and the clip is only 5s with
   `pad_to_voiceover: false`, warn the user.
4. **Don't re-run `tts` for unchanged segments** — it's slow and the audio
   is deterministic. `tts` skips existing files by default unless
   `force=true`. Use `is_up_to_date(scope="tts")` to confirm before re-running.
5. **Don't re-run `cut` for unchanged clips** — same reason. `cut` is
   idempotent. Use `is_up_to_date(scope="cut")`.
6. **Stop and ask** if the user's request is ambiguous about what to keep,
   what voice to use, what tone the script should take, etc. Don't fabricate.
7. **Show the user the script** before you call `tts` — VO audio is not
   free and the user often wants edits. Same for `cut-plan.json` before
   `cut`.
8. **Final render preview**: after `compose`, tell the user where
   `out/final.mp4` is and offer to open it
   (`Start-Process .\projects\<slug>\out\final.mp4`).
9. **Prefer `add_vo_segment` / `add_slide` / `set_compose_output` over
   manually-authored `write_state` payloads when building incrementally** —
   the helpers validate inputs, refuse id collisions, and create missing
   files with sane defaults. Reach for `write_state` only when you genuinely
   need to replace a whole file (e.g. you're writing all clip entries at
   once for a fresh project).
10. **`schema()` is the source of truth.** If a state file's contract
    evolves, the schema reflects it before this doc does. Call it when in
    doubt.
11. **`preview_slide` is the cheap iteration loop.** Use it while tweaking
    `title` / `subtitle` / `body` / colors instead of re-running `compose`.

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
| `doctor()`: `ffmpeg not found` | Not on PATH | `winget install --id Gyan.FFmpeg -e` (Windows) / `brew install ffmpeg` (macOS); restart shell |
| `doctor()`: `edge_tts not installed` | Python deps missing | `pip install --user videopilot` (re-installs deps) |
| `tts`: HTTP errors / "no audio received" | Edge TTS service hiccup or network | Retry; check `https://speech.platform.bing.com` reachable; switch to `engine: "azure"` in `voice_defaults` if persistent |
| `transcribe`: model download stalls | Slow network on first run | Pre-pull manually: `python -c "from faster_whisper import WhisperModel; WhisperModel('base')"` |
| `cut`: "stream copy failed" | Source has unusual codec / variable framerate | Pass `force=true` and consider re-encoding the source first |
| `compose`: timeline durations don't match expectation | `pad_to_voiceover` interaction with short clips | Re-check `clips/manifest.json` vs `voice/manifest.json`; adjust `cut-plan.json` |
| `compose`: audio glitch at clip boundaries | Concat demuxer with mismatched audio params | Already mitigated — `compose` re-encodes per-segment intermediates; if it persists, file a bug with the intermediates |
| Pipeline tool appears to "hang" with no output | Client host doesn't render `notifications/progress` | Not a crash — the server runs the op on a worker thread and will return when done. Wait, or switch to a host that displays MCP progress (Copilot CLI). |

When in doubt, the intermediates in `tmp/` are kept after every `compose`
run (not auto-cleaned) so you can inspect what happened at each step.

## Manual CLI (humans only)

Every pipeline stage is also exposed as a `videopilot` console-script
subcommand for users who want to invoke a stage by hand or in CI. See the
[README](README.md#cli-reference-manual-mode) for the table. You — the LLM
— don't need it; always prefer the MCP tools above.
