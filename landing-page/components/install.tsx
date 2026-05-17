"use client";

import { useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import { Sparkles, Package, Zap } from "lucide-react";
import { cn } from "@/lib/cn";
import CopyButton from "./copy-button";
import TerminalBlock from "./terminal-block";
import JsonBlock from "./json-block";

type TabKey = "pypi" | "uvx";

const PYPI_CMD = "pip install videopilot";

const PYPI_MCP_CONFIG = `{
  "mcpServers": {
    "videopilot": {
      "type": "stdio",
      "command": "videopilot-mcp",
      "args": [],
      "tools": ["*"]
    }
  }
}`;

const UVX_CONFIG = `{
  "mcpServers": {
    "videopilot": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "videopilot", "videopilot-mcp"],
      "tools": ["*"]
    }
  }
}`;

const TABS: { key: TabKey; label: string; icon: typeof Package; hint: string }[] = [
  { key: "pypi", label: "pip", icon: Package, hint: "pip install" },
  { key: "uvx", label: "uvx (MCP config)", icon: Zap, hint: "~/.copilot/mcp-config.json" },
];

export default function Install() {
  const [tab, setTab] = useState<TabKey>("pypi");
  const reduced = useReducedMotion();

  return (
    <section
      id="install"
      className="relative mx-auto w-full max-w-6xl px-4 py-20 sm:px-6 sm:py-28"
    >
      <motion.div
        initial={reduced ? false : { opacity: 0, y: 16 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, margin: "-60px" }}
        transition={{ duration: 0.55 }}
        className="mb-10 max-w-3xl"
      >
        <span className="font-mono text-xs uppercase tracking-widest text-violet">
          Install
        </span>
        <h2
          className="text-balance mt-3 font-semibold tracking-tight"
          style={{ fontSize: "clamp(2rem, 4.5vw, 3.25rem)", lineHeight: 1.05 }}
        >
          Two minutes to your first MCP call.
        </h2>
        <p className="mt-4 max-w-2xl text-base leading-relaxed text-muted">
          Install once from PyPI, or wire VideoPilot straight into your MCP
          client with <code className="font-mono text-foreground">uvx</code> —
          no global install needed.
        </p>
      </motion.div>

      <div className="grid gap-8 lg:grid-cols-5">
        <div className="lg:col-span-3">
          <div className="overflow-hidden rounded-2xl border border-border bg-surface/70">
            <div
              role="tablist"
              aria-label="Install method"
              className="flex border-b border-border bg-surface-2/60"
            >
              {TABS.map((t) => {
                const Icon = t.icon;
                const active = tab === t.key;
                return (
                  <button
                    key={t.key}
                    type="button"
                    role="tab"
                    aria-selected={active}
                    aria-controls={`panel-${t.key}`}
                    id={`tab-${t.key}`}
                    onClick={() => setTab(t.key)}
                    className={cn(
                      "relative inline-flex items-center gap-2 px-3 py-2.5 text-xs font-medium transition-colors sm:px-4 sm:py-3 sm:text-sm",
                      active
                        ? "text-foreground"
                        : "text-muted hover:text-foreground",
                    )}
                  >
                    <Icon className="h-4 w-4" />
                    {t.label}
                    {active && (
                      <motion.span
                        layoutId="install-underline"
                        className="absolute inset-x-3 bottom-0 h-px bg-gradient-to-r from-violet to-cyan"
                      />
                    )}
                  </button>
                );
              })}
            </div>

            <div
              id="panel-pypi"
              role="tabpanel"
              aria-labelledby="tab-pypi"
              hidden={tab !== "pypi"}
              className="p-4 sm:p-5"
            >
              <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-widest text-muted-2">
                <span className="grid h-4 w-4 place-items-center rounded-full bg-violet/15 text-[9px] text-violet">1</span>
                Install
              </div>
              <div className="mt-2 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-background/70 px-3 py-3 sm:px-4">
                <div className="flex min-w-0 flex-1 items-center gap-2 font-mono text-[12px] sm:gap-3 sm:text-sm">
                  <span className="select-none text-violet">$</span>
                  <span className="min-w-0 break-words text-foreground">{PYPI_CMD}</span>
                </div>
                <CopyButton value={PYPI_CMD} className="shrink-0" />
              </div>
              <p className="mt-3 text-xs text-muted">
                Installs the <code className="font-mono text-foreground">videopilot</code> CLI
                and the <code className="font-mono text-foreground">videopilot-mcp</code> server
                on your <code className="font-mono">PATH</code>. You&apos;ll also need{" "}
                <code className="font-mono text-foreground">ffmpeg</code> available.
              </p>

              <div className="mt-5 flex items-center gap-2 font-mono text-[10px] uppercase tracking-widest text-muted-2">
                <span className="grid h-4 w-4 place-items-center rounded-full bg-violet/15 text-[9px] text-violet">2</span>
                Wire up MCP
              </div>
              <div className="mt-2 rounded-xl border border-border bg-background/70">
                <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2.5 sm:px-4">
                  <span className="min-w-0 truncate font-mono text-[10.5px] text-muted-2 sm:text-[11px]">
                    ~/.copilot/mcp-config.json
                  </span>
                  <CopyButton value={PYPI_MCP_CONFIG} className="shrink-0" />
                </div>
                <JsonBlock value={PYPI_MCP_CONFIG} className="px-3 py-3 sm:px-4" />
              </div>
              <p className="mt-3 text-xs text-muted">
                Restart your MCP client. All 20 VideoPilot tools register over stdio
                via the <code className="font-mono text-foreground">videopilot-mcp</code> entry point.
              </p>
            </div>

            <div
              id="panel-uvx"
              role="tabpanel"
              aria-labelledby="tab-uvx"
              hidden={tab !== "uvx"}
              className="p-4 sm:p-5"
            >
              <div className="rounded-xl border border-border bg-background/70">
                <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2.5 sm:px-4">
                  <span className="min-w-0 truncate font-mono text-[10.5px] text-muted-2 sm:text-[11px]">
                    ~/.copilot/mcp-config.json
                  </span>
                  <CopyButton value={UVX_CONFIG} className="shrink-0" />
                </div>
                <JsonBlock value={UVX_CONFIG} className="px-3 py-3 sm:px-4" />
              </div>
              <p className="mt-4 text-xs text-muted">
                <code className="font-mono">uvx</code> fetches{" "}
                <code className="font-mono">videopilot</code> from PyPI into an
                ephemeral env and runs the MCP server over stdio. Restart your
                MCP client and the 20 tools appear.
              </p>
            </div>
          </div>
        </div>

        <div className="lg:col-span-2">
          <div className="mb-3 inline-flex items-center gap-2 font-mono text-xs uppercase tracking-widest text-muted">
            <Sparkles className="h-3.5 w-3.5 text-violet" aria-hidden="true" />
            Talk to an agent
          </div>
          <TerminalBlock
            title="agent · videopilot"
            prompt="you →"
            lines={[
              {
                kind: "in",
                text:
                  "Turn ~/Recordings/raw.mp4 into a cinematic 60s reel — pick the best moments, write a voiceover, add slides between sections.",
              },
              { kind: "out", text: "" },
              { kind: "warn", text: "[⋯] planning tool sequence…" },
              { kind: "ok", text: "[✓] doctor()              env ok" },
              { kind: "ok", text: "[✓] init('cinema-reel')   project ready" },
              { kind: "ok", text: "[✓] transcribe()          12.4k words" },
              { kind: "ok", text: "[✓] add_vo_segment × 5    narration drafted" },
              { kind: "ok", text: "[✓] add_slide × 3         title cards" },
              { kind: "ok", text: "[✓] tts()                 5 mp3s" },
              { kind: "ok", text: "[✓] cut() · compose()     timeline rendered" },
              { kind: "out", text: "" },
              { kind: "ok", text: "out/final.mp4 — 62s · 1920×1080 ✨" },
            ]}
          />
          <p className="mt-4 text-xs text-muted">
            Once your MCP client picks up the new server, just describe the
            video you want in plain English. The agent picks the tools and
            the order — you watch it happen.
          </p>
        </div>
      </div>
    </section>
  );
}
