"""videopilot CLI entrypoint.

Routes subcommands to the implementations in lib/. Run from this folder:

    videopilot <subcommand> [args]

See AGENT.md for the full agent-facing runbook and README.md for human setup.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make `lib` importable regardless of cwd.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from lib import (
    compose as compose_mod,
    cut as cut_mod,
    doctor as doctor_mod,
    export as export_mod,
    init_cmd,
    silence as silence_mod,
    transcribe as transcribe_mod,
    tts as tts_mod,
    voices as voices_mod,
)


def _projects_root(args: argparse.Namespace) -> Path:
    if getattr(args, "project_root", None):
        return Path(args.project_root).resolve()
    return HERE / "projects"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="videopilot",
        description="Compose videos from a brief: TTS + smart cuts + slides + render.",
    )
    p.add_argument(
        "--project-root",
        help="Override projects directory (default: <video-creator>/projects).",
    )
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--verbose", action="store_true")

    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="Check prerequisites.")

    pv = sub.add_parser("voices", help="List available TTS voices.")
    pv.add_argument("--locale", default=None, help="Filter by locale, e.g. en-US.")
    pv.add_argument("--engine", choices=["edge-tts", "azure"], default="edge-tts")

    pi = sub.add_parser("init", help="Create a new project.")
    pi.add_argument("slug")
    pi.add_argument("--name", default=None, help="Display name.")
    pi.add_argument(
        "--source",
        action="append",
        default=[],
        help="Path to a source video (repeatable).",
    )

    pim = sub.add_parser("import", help="Add a source to an existing project.")
    pim.add_argument("slug")
    pim.add_argument("path")
    pim.add_argument("--id", default=None, dest="source_id")

    pt = sub.add_parser("tts", help="Synthesize voiceover MP3s from script.json.")
    pt.add_argument("slug")
    pt.add_argument("--only", action="append", default=[], help="Only this segment id (repeatable).")
    pt.add_argument("--force", action="store_true", help="Regenerate even if output exists.")

    ptr = sub.add_parser("transcribe", help="Transcribe a source with faster-whisper.")
    ptr.add_argument("slug")
    ptr.add_argument("source_id")
    ptr.add_argument(
        "--model",
        default="base",
        choices=["tiny", "base", "small", "medium", "large-v3"],
    )
    ptr.add_argument("--language", default=None, help="ISO code, e.g. en. Auto-detect if omitted.")

    ps = sub.add_parser("silence", help="Emit a non-silent-spans cut-plan candidate.")
    ps.add_argument("slug")
    ps.add_argument("source_id")
    ps.add_argument("--threshold-db", type=float, default=-35.0)
    ps.add_argument("--min-silence-sec", type=float, default=1.0)
    ps.add_argument(
        "--output",
        default=None,
        help="Where to write the candidate (default: cut-plan.candidate.json).",
    )

    pc = sub.add_parser("cut", help="Cut clips per cut-plan.json.")
    pc.add_argument("slug")
    pc.add_argument("--only", action="append", default=[], help="Only this clip id (repeatable).")
    pc.add_argument("--force", action="store_true")
    pc.add_argument("--copy", action="store_true", help="Stream copy (fast but keyframe-snapped).")

    pcm = sub.add_parser("compose", help="Render final video per compose-plan.json.")
    pcm.add_argument("slug")
    pcm.add_argument("--keep-tmp", action="store_true", help="Don't print warning about tmp/.")

    pe = sub.add_parser("export", help="Emit NLE / replay exports for a composed timeline.")
    pe.add_argument("slug")
    pe.add_argument("--edl", action="store_true")
    pe.add_argument("--fcpxml", action="store_true")
    pe.add_argument("--script", action="store_true")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = _projects_root(args)

    try:
        if args.cmd == "doctor":
            return doctor_mod.run()
        if args.cmd == "voices":
            return voices_mod.run(engine=args.engine, locale=args.locale)
        if args.cmd == "init":
            return init_cmd.run(root, args.slug, name=args.name, sources=args.source)
        if args.cmd == "import":
            return init_cmd.import_source(root, args.slug, args.path, source_id=args.source_id)
        if args.cmd == "tts":
            return tts_mod.run(root, args.slug, only=args.only, force=args.force)
        if args.cmd == "transcribe":
            return transcribe_mod.run(
                root, args.slug, args.source_id, model=args.model, language=args.language
            )
        if args.cmd == "silence":
            return silence_mod.run(
                root,
                args.slug,
                args.source_id,
                threshold_db=args.threshold_db,
                min_silence_sec=args.min_silence_sec,
                output=args.output,
            )
        if args.cmd == "cut":
            return cut_mod.run(
                root, args.slug, only=args.only, force=args.force, stream_copy=args.copy
            )
        if args.cmd == "compose":
            return compose_mod.run(root, args.slug)
        if args.cmd == "export":
            return export_mod.run(
                root, args.slug, edl=args.edl, fcpxml=args.fcpxml, script=args.script
            )
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130

    print(f"Unknown command: {args.cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
