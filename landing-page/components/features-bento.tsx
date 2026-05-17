"use client";

import { motion, useReducedMotion } from "motion/react";
import {
  Bot,
  Mic2,
  ScanText,
  Film,
  Move3d,
  FileVideo,
  Layers,
  RefreshCw,
} from "lucide-react";
import FeatureCard, { type FeatureCardProps } from "./feature-card";

const FEATURES: (FeatureCardProps & { area: string })[] = [
  {
    icon: Bot,
    title: "Agent-driven by design",
    description:
      "Wired for MCP. Any agent — GitHub Copilot CLI, Claude Desktop, Cursor — drives the whole pipeline through 20 typed tool calls.",
    code: '{\n  "command": "uvx",\n  "args": ["--from", "videopilot",\n           "videopilot-mcp"]\n}',
    area: "md:col-span-2 md:row-span-2",
  },
  {
    icon: Mic2,
    title: "400+ neural voices",
    description:
      "Free Microsoft Edge TTS by default across 100+ locales. Drop in an Azure key for premium neural voices.",
    area: "md:col-span-2",
  },
  {
    icon: ScanText,
    title: "Word-level transcription",
    description:
      "Local faster-whisper produces precise word timings and SRT, ready for highlight selection or burn-in captions.",
    area: "",
  },
  {
    icon: Film,
    title: "ffmpeg under the hood",
    description:
      "Filter graphs you don't have to author. Slides, picture-in-picture, ducking, and music underlay just compose.",
    area: "",
  },
  {
    icon: Move3d,
    title: "Subpixel Ken Burns",
    description:
      "Zoom and pan over still images, rendered with Lanczos oversampling so the motion stays buttery, not jittery.",
    area: "",
  },
  {
    icon: FileVideo,
    title: "Hand off to any NLE",
    description:
      "Export the same timeline as EDL (CMX 3600) and FCPXML — open it in Premiere, Resolve, or Final Cut.",
    area: "",
  },
  {
    icon: Layers,
    title: "Composable timeline",
    description:
      "Voiceover segments, clips, slides, motion, music, and ducking all live in a single declarative compose-plan.json.",
    area: "",
  },
  {
    icon: RefreshCw,
    title: "Idempotent re-runs",
    description:
      "Probe whether each stage's outputs are stale, then regenerate only what changed. CI-friendly.",
    area: "",
  },
];

export default function FeaturesBento() {
  const reduced = useReducedMotion();

  return (
    <section id="features" className="relative mx-auto w-full max-w-6xl px-4 py-20 sm:px-6 sm:py-28">
      <motion.div
        initial={reduced ? false : { opacity: 0, y: 16 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, margin: "-60px" }}
        transition={{ duration: 0.5 }}
        className="mb-12 max-w-3xl"
      >
        <span className="font-mono text-xs uppercase tracking-widest text-violet">
          Features
        </span>
        <h2
          className="text-balance mt-3 font-semibold tracking-tight"
          style={{ fontSize: "clamp(2rem, 4.5vw, 3.25rem)", lineHeight: 1.05 }}
        >
          The whole pipeline, exposed as <span className="text-gradient-accent">typed tools</span>.
        </h2>
        <p className="mt-4 max-w-2xl text-base leading-relaxed text-muted">
          Each stage in VideoPilot is an MCP tool with a JSON-schema contract.
          That means agents can author voiceovers, draft cut plans, and compose
          timelines deterministically — no prompt-engineering the editor.
        </p>
      </motion.div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-4 md:auto-rows-[minmax(220px,auto)]">
        {FEATURES.map((f, i) => (
          <FeatureCard
            key={f.title}
            icon={f.icon}
            title={f.title}
            description={f.description}
            code={f.code}
            delay={i * 0.04}
            className={f.area}
          />
        ))}
      </div>
    </section>
  );
}
