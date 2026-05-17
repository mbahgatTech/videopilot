"use client";

import { motion, useReducedMotion } from "motion/react";
import { TOOLS } from "@/lib/tools";

export default function ToolsMarquee() {
  const reduced = useReducedMotion();
  const doubled = [...TOOLS, ...TOOLS];

  return (
    <section
      id="tools"
      className="relative mx-auto w-full max-w-6xl px-4 py-20 sm:px-6 sm:py-28"
    >
      <motion.div
        initial={reduced ? false : { opacity: 0, y: 16 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, margin: "-80px" }}
        transition={{ duration: 0.55 }}
        className="mb-10 max-w-3xl"
      >
        <span className="font-mono text-xs uppercase tracking-widest text-coral">
          MCP tools
        </span>
        <h2
          className="text-balance mt-3 font-semibold tracking-tight"
          style={{ fontSize: "clamp(2rem, 4.5vw, 3.25rem)", lineHeight: 1.05 }}
        >
          20 tools for the calling LLM.
        </h2>
      </motion.div>

      <div className="marquee-pause relative overflow-hidden mask-fade-x">
        <div
          className="flex w-max gap-3 animate-marquee"
          aria-label={`${TOOLS.length} VideoPilot MCP tools`}
        >
          {doubled.map((t, i) => (
            <span
              key={`${t}-${i}`}
              className="inline-flex shrink-0 items-center gap-2 rounded-full border border-border bg-surface/70 px-3 py-1.5 font-mono text-xs text-foreground sm:px-4 sm:py-2 sm:text-sm"
            >
              <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-violet" />
              {t}
            </span>
          ))}
        </div>
      </div>

      <motion.p
        initial={reduced ? false : { opacity: 0, y: 12 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, margin: "-60px" }}
        transition={{ duration: 0.5 }}
        className="mx-auto mt-10 max-w-2xl text-center text-sm leading-relaxed text-muted"
      >
        The{" "}
        <a
          href="https://modelcontextprotocol.io"
          target="_blank"
          rel="noopener noreferrer"
          className="text-foreground underline decoration-violet/60 underline-offset-4 transition hover:decoration-violet"
        >
          Model Context Protocol
        </a>{" "}
        is the open standard for connecting LLM clients to external tools. Wire
        VideoPilot in once and every MCP-aware agent gets the same 20 tools.
      </motion.p>
    </section>
  );
}
