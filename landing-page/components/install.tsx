"use client";

import { useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import { Terminal, Package, Zap } from "lucide-react";
import { cn } from "@/lib/cn";
import CopyButton from "./copy-button";
import TerminalBlock from "./terminal-block";

type TabKey = "pypi" | "uvx";

const PYPI_CMD = "pip install --user videopilot";

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
  { key: "pypi", label: "PyPI", icon: Package, hint: "pip install --user" },
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
                      "relative inline-flex items-center gap-2 px-4 py-3 text-sm font-medium transition-colors",
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
              className="p-5"
            >
              <div className="flex items-center justify-between gap-3 rounded-xl border border-border bg-background/70 px-4 py-3">
                <div className="flex min-w-0 items-center gap-3 font-mono text-sm">
                  <span className="select-none text-violet">$</span>
                  <span className="truncate text-foreground">{PYPI_CMD}</span>
                </div>
                <CopyButton value={PYPI_CMD} />
              </div>
              <p className="mt-4 text-xs text-muted">
                Installs the <code className="font-mono">videopilot</code> CLI
                and the <code className="font-mono">videopilot-mcp</code> server
                entry point. You&apos;ll also need <code className="font-mono">ffmpeg</code>{" "}
                on <code className="font-mono">PATH</code>.
              </p>
            </div>

            <div
              id="panel-uvx"
              role="tabpanel"
              aria-labelledby="tab-uvx"
              hidden={tab !== "uvx"}
              className="p-5"
            >
              <div className="rounded-xl border border-border bg-background/70">
                <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
                  <span className="font-mono text-[11px] text-muted-2">
                    ~/.copilot/mcp-config.json
                  </span>
                  <CopyButton value={UVX_CONFIG} />
                </div>
                <pre className="overflow-x-auto px-4 py-3 font-mono text-[12.5px] leading-relaxed text-foreground">
                  <code>{UVX_CONFIG}</code>
                </pre>
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
            <Terminal className="h-3.5 w-3.5" aria-hidden="true" />
            Verify
          </div>
          <TerminalBlock
            title="videopilot doctor"
            lines={[
              { kind: "in", text: "videopilot doctor" },
              { kind: "out", text: "Checking environment..." },
              { kind: "ok", text: "[OK]    ffmpeg     7.1" },
              { kind: "ok", text: "[OK]    ffprobe    7.1" },
              { kind: "ok", text: "[OK]    edge-tts   ready" },
              { kind: "ok", text: "[OK]    whisper    base" },
              { kind: "warn", text: "[skip]  azure      no key (optional)" },
              { kind: "out", text: "" },
              { kind: "ok", text: "All required checks passed." },
            ]}
          />
          <p className="mt-4 text-xs text-muted">
            <code className="font-mono">videopilot doctor</code>{" "}exits 0 when
            every required dep is in place, and prints exactly what&apos;s
            missing otherwise.
          </p>
        </div>
      </div>
    </section>
  );
}
