# videopilot

> Agent-driven video creation toolkit. Neural TTS voiceover, AI highlight cutting,
> timeline composition with slides and audio ducking, and NLE export — all driven
> by a calling LLM through a JSON state contract.

[![PyPI](https://img.shields.io/badge/PyPI-videopilot-blue.svg)](https://pypi.org/project/videopilot/)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![ffmpeg](https://img.shields.io/badge/depends-ffmpeg-orange.svg)](https://ffmpeg.org)

`videopilot` is a Python CLI that turns raw screen recordings into narrated,
edited MP4s. The CLI does the **mechanical work** — ffmpeg, neural TTS,
faster-whisper transcription, timeline rendering. A calling **agent** (GitHub
Copilot CLI, Claude Code, Continue.dev, or any code-aware LLM) does the
**creative work** — writes the voiceover script, picks the highlight spans,
lays out the timeline — by reading the contract in [`AGENT.md`](AGENT.md) and
authoring small JSON state files.

You can also drive `videopilot` by hand. Each subcommand is independently usable.

```
source.mp4  ->  script.json  ->  tts  ->  cut-plan.json  ->  cut  ->  compose-plan.json  ->  compose  ->  final.mp4
                                                                                                         + EDL / FCPXML / replay script
```

## Highlights

| Capability | Engine |
|---|---|
| Neural voiceover, 400+ voices, 100+ locales | [Microsoft Edge TTS](https://github.com/rany2/edge-tts) (free, no key) |
| Premium neural voices | Azure Speech (optional, with key) |
| Word-level transcription | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (local) |
| Silence trimming, scene cuts | ffmpeg |
| Title slides, picture-in-picture, audio ducking, music underlay | ffmpeg filter graph composer |
| MP4 render at any resolution / fps | ffmpeg |
| Hand-off to Premiere / Resolve / Final Cut | EDL (CMX 3600) + FCPXML export |
| Replayable render scripts | PowerShell / bash export |
| Agent-first design | JSON state-file contract documented in `AGENT.md` |

## Install

### From PyPI (recommended)

```
pip install --user videopilot
```

`videopilot` is a console script — after install it's on your `PATH`. Verify:

```
videopilot doctor
```

You also need **ffmpeg** on `PATH`:

| OS | Command |
|---|---|
| Windows | `winget install --id Gyan.FFmpeg -e` |
| macOS | `brew install ffmpeg` |
| Debian / Ubuntu | `sudo apt install ffmpeg` |
| Fedora | `sudo dnf install ffmpeg` |
| Arch | `sudo pacman -S ffmpeg` |

`videopilot doctor` exits 0 when ffmpeg, ffprobe, Python deps, and optional
Azure keys are all in order; otherwise it prints exactly what's missing.

### From source (development)

```
git clone https://github.com/mbahgatTech/videopilot.git
cd videopilot
pip install --user -e .
```

### Via the Agency plugin

If you use Copilot or Claude inside Microsoft and have access to the
[Agency Playground](https://github.com/agency-microsoft/playground)
marketplace, install the `videopilot` plugin and ask:

> set up videopilot

The plugin's `init` skill runs the same installer logic for you.

## Quick start

```
# 1. Create a project with a source video
videopilot init demo --source "/path/to/raw-recording.mp4"

# 2. Hand-author projects/demo/script.json (one segment per beat of narration),
#    OR have your agent draft it from AGENT.md.

# 3. Synthesize the voiceover
videopilot tts demo

# 4. (Optional) transcribe to help pick highlights
videopilot transcribe demo raw1

# 5. Hand-author projects/demo/cut-plan.json (which spans to keep)

# 6. Cut clips from sources
videopilot cut demo

# 7. Hand-author projects/demo/compose-plan.json (timeline + slides + ducking)

# 8. Render the final video
videopilot compose demo

# 9. Optional: emit NLE projects + replay script
videopilot export demo --edl --fcpxml --script
```

Final output: `projects/demo/out/final.mp4` plus optional `final.edl`,
`final.fcpxml`, and `render.ps1`.

## CLI reference

| Command | Purpose |
|---|---|
| `videopilot doctor` | Verify ffmpeg, ffprobe, Python deps, optional Azure keys. |
| `videopilot voices [--locale en-US]` | List available TTS voices. |
| `videopilot init <slug> [--source PATH]` | Create a new project with optional first source. |
| `videopilot import <slug> <path>` | Add another source to an existing project. |
| `videopilot tts <slug> [--force]` | Synthesize voiceover MP3s from `script.json`. |
| `videopilot transcribe <slug> <source-id>` | Run faster-whisper; emits word-level JSON + SRT. |
| `videopilot silence <slug> <source-id>` | Emit a cut-plan candidate that strips silence. |
| `videopilot cut <slug> [--force] [--reencode]` | Cut clips per `cut-plan.json`. |
| `videopilot compose <slug>` | Render final MP4 per `compose-plan.json`. |
| `videopilot export <slug> [--edl] [--fcpxml] [--script]` | Emit NLE projects + replayable ffmpeg script. |

Run `videopilot <command> --help` for per-command flags.

## Project layout

```
videopilot/
- AGENT.md           <- contract for calling LLMs (start here if you're driving the tool)
- README.md          <- this file
- LICENSE            <- MIT
- pyproject.toml
- videopilot.py      <- argparse router
- videopilot_cli.py  <- console-script shim
- lib/               <- implementation modules
  - tts.py
  - transcribe.py
  - silence.py
  - cut.py
  - compose.py
  - export.py
  - ffmpeg_wrap.py
  - voices.py
  - init_cmd.py
  - doctor.py
- examples/          <- copyable starter JSON state files
- projects/<slug>/   <- per-project workspace (one folder per video)
  - project.json
  - script.json
  - cut-plan.json
  - compose-plan.json
  - sources/
  - voice/
  - transcripts/
  - clips/
  - tmp/
  - out/
```

## Configuration

| Environment variable | Purpose |
|---|---|
| `AZURE_SPEECH_KEY` | Optional. Enables Azure Speech voices (premium neural TTS). |
| `AZURE_SPEECH_REGION` | Required when `AZURE_SPEECH_KEY` is set (e.g. `eastus`). |

Edge TTS is the default and requires no configuration.

## Driving videopilot from an LLM

Read [`AGENT.md`](AGENT.md). It is the contract the calling LLM uses:

- the JSON schema for each state file (`project.json`, `script.json`,
  `cut-plan.json`, `compose-plan.json`);
- when to call which subcommand;
- conventions (2-space JSON, preserved ids, idempotent re-runs);
- common failure modes and recoveries.

The `videopilot` plugin in the Agency Playground packages this contract as a
Copilot/Claude skill so you can just say `set up videopilot` and `make a video
from <source>` instead of orchestrating by hand.

## Development

```
git clone https://github.com/mbahgatTech/videopilot.git
cd videopilot
pip install --user -e ".[dev]"

# Build the package
python -m build

# Validate the dist
python -m twine check dist/*

# Local smoke test
videopilot doctor
```

## Releasing

Releases are published to PyPI automatically when a `v*` tag is pushed.
The workflow uses [PyPI **Trusted Publishing** (OIDC)](https://docs.pypi.org/trusted-publishers/),
so **no API tokens are stored in the repo or in GitHub Secrets** — PyPI verifies
the GitHub OIDC token at publish time.

One-time setup (PyPI side, do this once before the first release):

1. Sign in to <https://pypi.org/>.
2. Account settings → Publishing → **Add a new pending publisher**:
   - PyPI project name: `videopilot`
   - Owner: `mbahgatTech`
   - Repository: `videopilot`
   - Workflow filename: `release.yml`
   - Environment name: `pypi`
3. On GitHub, repo Settings → Environments → **New environment** → `pypi`.
   Optionally add a required reviewer for an extra approval gate.

Cutting a release:

```
# bump pyproject.toml [project] version, e.g. 0.1.0 -> 0.2.0
git commit -am "release: 0.2.0"
git tag v0.2.0
git push origin main --tags
```

The `release` workflow then:

1. Builds sdist + wheel
2. Verifies tag matches `pyproject.toml` version
3. Runs `twine check`
4. Publishes to PyPI via OIDC
5. Creates a GitHub Release with the sdist + wheel attached

## License

MIT. See [`LICENSE`](LICENSE).
