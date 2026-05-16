"use client";

import { motion, useReducedMotion } from "motion/react";
import { ArrowRight, ChevronDown, Sparkles } from "lucide-react";
import HeroBackground from "./hero-background";
import MagneticButton from "./magnetic-button";
import CopyButton from "./copy-button";
import { GitHubIcon } from "./brand-icons";

// Headline options considered:
//   - "Tell an agent. Get a finished video."            <-- picked: clearest agent framing
//   - "Direct the edit. Skip the timeline."
//   - "An MCP server that ships finished videos."

export default function Hero() {
  const reduced = useReducedMotion();
  const fade = (delay = 0) =>
    reduced
      ? { initial: false }
      : {
          initial: { opacity: 0, y: 16 },
          animate: { opacity: 1, y: 0 },
          transition: { duration: 0.6, delay, ease: [0.16, 1, 0.3, 1] as const },
        };

  return (
    <section
      id="top"
      className="relative isolate flex min-h-[100svh] items-center overflow-hidden pt-24 pb-24"
    >
      <HeroBackground />

      <div className="relative z-10 mx-auto w-full max-w-6xl px-4 sm:px-6">
        <motion.div
          {...fade(0)}
          className="mx-auto mb-6 inline-flex w-full justify-center"
        >
          <span className="inline-flex items-center gap-2 rounded-full border border-border bg-surface/60 px-3 py-1 text-xs text-muted backdrop-blur">
            <Sparkles className="h-3.5 w-3.5 text-violet" aria-hidden="true" />
            <span className="font-mono uppercase tracking-wider">
              MCP server · 20 tools · MIT licensed
            </span>
          </span>
        </motion.div>

        <motion.h1
          {...fade(0.05)}
          className="text-balance mx-auto max-w-4xl text-center font-semibold tracking-tight"
          style={{ fontSize: "clamp(2.75rem, 7vw, 5.75rem)", lineHeight: 1.02 }}
        >
          <span className="text-gradient">Tell an agent.</span>{" "}
          <br className="hidden sm:block" />
          <span className="text-foreground">Get a finished video.</span>
        </motion.h1>

        <motion.p
          {...fade(0.12)}
          className="text-balance mx-auto mt-6 max-w-2xl text-center text-base leading-relaxed text-muted sm:text-lg"
        >
          VideoPilot is an open-source MCP server that gives any LLM 20 tools to
          author voiceover, cut highlights, compose timelines, and render
          finished MP4s — straight from your screen recordings.
        </motion.p>

        <motion.div
          {...fade(0.2)}
          className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row"
        >
          <MagneticButton
            href="https://github.com/mbahgatTech/videopilot"
            external
            variant="primary"
            ariaLabel="View VideoPilot on GitHub"
          >
            <GitHubIcon className="h-4 w-4" />
            View on GitHub
            <ArrowRight className="h-4 w-4" />
          </MagneticButton>

          <MagneticButton
            href="#pipeline"
            variant="secondary"
            ariaLabel="See the pipeline"
          >
            See the pipeline
            <ChevronDown className="h-4 w-4" />
          </MagneticButton>
        </motion.div>

        <motion.div
          {...fade(0.28)}
          className="mt-10 flex items-center justify-center px-2"
        >
          <div className="inline-flex max-w-full flex-wrap items-center justify-center gap-x-2 gap-y-1.5 rounded-2xl border border-border bg-surface/70 px-3 py-2 backdrop-blur sm:rounded-full sm:py-1.5">
            <span className="rounded-full bg-violet/15 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-violet">
              PyPI
            </span>
            <code className="font-mono text-xs text-foreground sm:text-sm">
              pip install --user videopilot
            </code>
            <CopyButton
              value="pip install --user videopilot"
              label="Copy"
              className="ml-1"
            />
          </div>
        </motion.div>
      </div>
    </section>
  );
}
