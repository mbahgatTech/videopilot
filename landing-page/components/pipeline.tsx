"use client";

import { motion, useReducedMotion } from "motion/react";
import {
  FileText,
  AudioLines,
  Scissors,
  Layers3,
  PlayCircle,
  Share2,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

type Stage = {
  id: string;
  label: string;
  state: string;
  icon: LucideIcon;
};

const STAGES: Stage[] = [
  { id: "script", label: "Script", state: "script.json", icon: FileText },
  { id: "tts", label: "TTS", state: "voiceover MP3s", icon: AudioLines },
  { id: "cut", label: "Cut", state: "cut-plan.json", icon: Scissors },
  { id: "compose", label: "Compose", state: "compose-plan.json", icon: Layers3 },
  { id: "final", label: "Final", state: "final.mp4", icon: PlayCircle },
  { id: "export", label: "Export", state: "EDL · FCPXML", icon: Share2 },
];

export default function Pipeline() {
  const reduced = useReducedMotion();

  return (
    <section
      id="pipeline"
      className="relative mx-auto w-full max-w-6xl px-4 py-20 sm:px-6 sm:py-28"
    >
      <div className="mb-12 max-w-3xl">
        <span className="font-mono text-xs uppercase tracking-widest text-cyan">
          Pipeline
        </span>
        <h2
          className="text-balance mt-3 font-semibold tracking-tight"
          style={{ fontSize: "clamp(2rem, 4.5vw, 3.25rem)", lineHeight: 1.05 }}
        >
          Six stages. One pipeline.
        </h2>
        <p className="mt-4 max-w-2xl text-base leading-relaxed text-muted">
          Each stage reads and writes a JSON state file. Agents author the state,
          VideoPilot does the rendering — and any stage can be re-run on its own.
        </p>
      </div>

      <div className="relative">
        <div className="hidden md:block">
          <DesktopFlow reduced={!!reduced} />
        </div>
        <div className="md:hidden">
          <MobileFlow reduced={!!reduced} />
        </div>
      </div>
    </section>
  );
}

function DesktopFlow({ reduced }: { reduced: boolean }) {
  return (
    <div className="relative">
      <svg
        viewBox="0 0 1200 80"
        preserveAspectRatio="none"
        aria-hidden="true"
        className="absolute left-0 top-[44px] hidden h-20 w-full md:block"
      >
        <defs>
          <linearGradient id="pipe-line" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="#7c5cff" />
            <stop offset="100%" stopColor="#00d4ff" />
          </linearGradient>
        </defs>
        <motion.path
          d="M 60 40 L 1140 40"
          fill="none"
          stroke="url(#pipe-line)"
          strokeWidth={2}
          strokeLinecap="round"
          initial={reduced ? false : { pathLength: 0 }}
          whileInView={{ pathLength: 1 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 1.6, ease: "easeOut" }}
        />
      </svg>

      <ol className="relative grid grid-cols-6 gap-2">
        {STAGES.map((s, i) => (
          <StageNode key={s.id} stage={s} index={i} reduced={reduced} />
        ))}
      </ol>
    </div>
  );
}

function MobileFlow({ reduced }: { reduced: boolean }) {
  return (
    <ol className="relative flex flex-col gap-4">
      <div
        aria-hidden="true"
        className="absolute left-[27px] top-2 bottom-2 w-px bg-gradient-to-b from-violet via-cyan to-violet/30"
      />
      {STAGES.map((s, i) => (
        <motion.li
          key={s.id}
          initial={reduced ? false : { opacity: 0, x: -12 }}
          whileInView={{ opacity: 1, x: 0 }}
          viewport={{ once: true, margin: "-40px" }}
          transition={{ duration: 0.5, delay: i * 0.08 }}
          className="relative flex items-center gap-4 rounded-2xl border border-border bg-surface/70 p-4"
        >
          <div className="relative z-10 flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border border-border bg-surface-2 text-violet">
            <s.icon className="h-5 w-5" />
          </div>
          <div>
            <div className="text-sm font-semibold text-foreground">
              {i + 1}. {s.label}
            </div>
            <div className="mt-0.5 font-mono text-xs text-muted">{s.state}</div>
          </div>
        </motion.li>
      ))}
    </ol>
  );
}

function StageNode({
  stage,
  index,
  reduced,
}: {
  stage: Stage;
  index: number;
  reduced: boolean;
}) {
  const Icon = stage.icon;
  return (
    <motion.li
      initial={reduced ? false : { opacity: 0, y: 14, scale: 0.96 }}
      whileInView={{ opacity: 1, y: 0, scale: 1 }}
      viewport={{ once: true, margin: "-80px" }}
      transition={{ duration: 0.5, delay: index * 0.14, ease: [0.16, 1, 0.3, 1] }}
      className="relative flex flex-col items-center text-center"
    >
      <div className="relative">
        <div
          aria-hidden="true"
          className="absolute inset-0 -z-10 rounded-2xl bg-violet/30 blur-xl"
        />
        <div className="relative flex h-20 w-20 items-center justify-center rounded-2xl border border-border bg-surface text-foreground transition-colors hover:border-violet/60">
          <Icon className="h-7 w-7 text-violet" />
        </div>
      </div>
      <div className="mt-4 text-sm font-semibold tracking-tight">{stage.label}</div>
      <div className="mt-1 font-mono text-[11px] leading-tight text-muted">
        {stage.state}
      </div>
    </motion.li>
  );
}
