# videopilot

> Agent-driven video creation toolkit. An **MCP server** giving LLMs 20 tools
> to author voiceover, cut highlights, compose timelines, and render finished
> MP4s — plus a CLI for manual / scripted runs when you don't want an agent
> in the loop.

[![PyPI](https://img.shields.io/badge/PyPI-videopilot-blue.svg)](https://pypi.org/project/videopilot/)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![ffmpeg](https://img.shields.io/badge/depends-ffmpeg-orange.svg)](https://ffmpeg.org)

`videopilot` is an **MCP (Model Context Protocol) server** that lets a calling
LLM — driven by GitHub Copilot CLI or any other MCP-aware client — turn raw
screen recordings into narrated, edited MP4s. The server exposes 20 tools
covering the full pipeline: neural TTS voiceover, faster-whisper
transcription, silence detection, clip cutting, timeline composition with
slides and audio ducking, and NLE export to EDL / FCPXML.

The MCP server is the **primary interface**. A standalone `videopilot` CLI
ships alongside it for manual or scripted runs — useful for one-off stages,
CI, or workflows without an agent in the loop.

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
| Ken Burns motion on still images (zoom in/out, pan) | ffmpeg `zoompan` over a Lanczos-oversampled source (subpixel-smooth) |
| MP4 render at any resolution / fps | ffmpeg |
| Hand-off to Premiere / Resolve / Final Cut | EDL (CMX 3600) + FCPXML export |
| Replayable render scripts | PowerShell / bash export |
| Agent integration | MCP server with 20 tools — see [MCP tools](#mcp-tools) |
| Authoring contract | JSON state files documented in [`AGENT.md`](AGENT.md) (incremental authoring, schema introspection, idempotency probes) |

## Install

### From PyPI (recommended)

```
pip install --user videopilot
```

Two console scripts are installed:

| Script | Purpose |
|---|---|
| `videopilot-mcp` | The MCP server (stdio transport). Wire this into your MCP client. |
| `videopilot` | The manual CLI. Useful for one-off stages and CI. |

Verify the install:

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
The same check is also exposed as the `doctor` MCP tool.

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

## Connect to an MCP client

`videopilot-mcp` runs the MCP server over stdio. The verified config for the
GitHub Copilot CLI (`~/.copilot/mcp-config.json`) is:

```json
{
  "mcpServers": {
    "videopilot": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "videopilot", "videopilot-mcp"],
      "tools": ["*"]
    }
  }
}
```

`uvx` pulls the latest `videopilot` from PyPI into an ephemeral environment
and runs the `videopilot-mcp` entry point — no global install required. If
you already have `videopilot` installed globally (`pip install --user
videopilot`) you can instead use `"command": "videopilot-mcp"` with no
`args`.

Any MCP-aware client that supports stdio servers can run `videopilot-mcp`
the same way — consult your client's docs for the exact config-file
location and schema.

After your client restarts, the agent can call any of the 20 `videopilot.*`
tools below.

## MCP tools

| Tool | Purpose |
|---|---|
| `doctor` | Verify ffmpeg, ffprobe, Python deps, optional Azure keys. |
| `voices` | List available neural TTS voices (Edge TTS or Azure). |
| `list_projects` | List all projects under `projects/`. |
| `project_status` | Pipeline status for one project: which JSON state files exist, which stages have run. |
| `init` | Create a new project, optionally with a first source video. |
| `import_source` | Add another source to an existing project. |
| `read_state` | Read a JSON state file (`project` / `script` / `cut-plan` / `compose-plan`). |
| `write_state` | Write a JSON state file with schema validation. |
| `tts` | Synthesize voiceover MP3s from `script.json` (async, emits progress notifications). |
| `transcribe` | Run faster-whisper; returns word-level segments and writes SRT. |
| `silence` | Emit a cut-plan candidate that strips silence. |
| `cut` | Cut clips per `cut-plan.json`. |
| `compose` | Render final MP4 per `compose-plan.json`. |
| `export` | Emit NLE projects (EDL, FCPXML) and replayable ffmpeg script. |
| `schema` | Return JSON schemas (agent-facing) for every state file. |
| `add_vo_segment` | Append or upsert a voiceover segment in `script.json`. |
| `add_slide` | Append a slide entry (with optional body text) to `compose-plan.json`. |
| `set_compose_output` | Set compose output resolution / fps / codec. |
| `preview_slide` | Render a single slide as a PNG for fast preview without running `compose`. |
| `is_up_to_date` | Probe whether a stage's outputs are current for its inputs (idempotency check). |

The contract — what each tool reads and writes, the JSON state-file schemas,
and the recommended call order — is documented in [`AGENT.md`](AGENT.md).
Calling agents should read `AGENT.md` before issuing tool calls.

## CLI reference (manual mode)

Each pipeline stage is also exposed as a `videopilot` CLI subcommand. Use it
when you want to run a step by hand, drop the agent, or invoke from CI.

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

### Manual quick start

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

## Project layout

```
videopilot/
- AGENT.md           <- contract for calling LLMs (start here if you're driving the tool)
- README.md          <- this file
- LICENSE            <- MIT
- pyproject.toml
- videopilot_mcp.py  <- MCP server (primary entry point; console-script: videopilot-mcp)
- videopilot.py      <- argparse router (CLI implementation)
- videopilot_cli.py  <- console-script shim for the CLI
- lib/               <- shared implementation modules
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
- tests/             <- standalone test scripts (mcp_e2e.py, progress_smoke.py)
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

# MCP server stdio + progress-notification smoke test
python tests/progress_smoke.py

# End-to-end MCP test (real ffmpeg + Edge TTS + full pipeline)
python tests/mcp_e2e.py
```

## Releasing

Releases publish to PyPI automatically when a `v*` tag is pushed. The
version is derived from the tag itself via
[setuptools_scm](https://setuptools-scm.readthedocs.io/) — there is no
`version =` line in `pyproject.toml` and no version-bump commit is required.

The workflow uses [PyPI **Trusted Publishing** (OIDC)](https://docs.pypi.org/trusted-publishers/),
so **no API tokens are stored in the repo or in GitHub Secrets** — PyPI
verifies the GitHub OIDC token at publish time.

One-time setup (PyPI side, done once before the first release):

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
git tag v0.2.0
git push origin v0.2.0
```

That's it. The `release` workflow then:

1. Builds sdist + wheel (version derived from the tag)
2. Verifies the tag matches the `setuptools_scm`-derived version
3. Runs `twine check`
4. Publishes to PyPI via OIDC
5. Creates a GitHub Release with the sdist + wheel attached

## License

MIT. See [`LICENSE`](LICENSE).
