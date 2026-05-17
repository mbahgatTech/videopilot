"use client";

import type { LucideIcon } from "lucide-react";
import { useRef, type MouseEvent } from "react";
import { motion, useReducedMotion } from "motion/react";
import { cn } from "@/lib/cn";

export type FeatureCardProps = {
  icon: LucideIcon;
  title: string;
  description: string;
  code?: string;
  className?: string;
  delay?: number;
};

export default function FeatureCard({
  icon: Icon,
  title,
  description,
  code,
  className,
  delay = 0,
}: FeatureCardProps) {
  const ref = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();

  function handleMove(e: MouseEvent<HTMLDivElement>) {
    const el = ref.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    el.style.setProperty("--x", `${e.clientX - rect.left}px`);
    el.style.setProperty("--y", `${e.clientY - rect.top}px`);
  }

  return (
    <motion.div
      ref={ref}
      onMouseMove={handleMove}
      initial={reduced ? false : { opacity: 0, y: 20 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-60px" }}
      transition={{ duration: 0.55, delay, ease: [0.16, 1, 0.3, 1] }}
      className={cn(
        "group relative overflow-hidden rounded-2xl border border-border bg-surface/70 p-6 transition-colors hover:border-border-strong",
        className,
      )}
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 opacity-0 transition-opacity duration-300 group-hover:opacity-100"
        style={{
          background:
            "radial-gradient(420px circle at var(--x, 50%) var(--y, 50%), rgba(124,92,255,0.18), rgba(0,212,255,0.06) 35%, transparent 60%)",
        }}
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-px rounded-[calc(theme(borderRadius.2xl)-1px)] opacity-0 transition-opacity duration-300 group-hover:opacity-100"
        style={{
          background:
            "radial-gradient(220px circle at var(--x, 50%) var(--y, 50%), rgba(124,92,255,0.32), transparent 70%)",
          mixBlendMode: "plus-lighter",
        }}
      />

      <div className="relative z-10 flex h-full flex-col">
        <div className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-border bg-surface-2 text-violet">
          <Icon className="h-5 w-5" aria-hidden="true" />
        </div>
        <h3 className="mt-5 text-lg font-semibold tracking-tight text-foreground">
          {title}
        </h3>
        <p className="mt-2 text-sm leading-relaxed text-muted">{description}</p>
        {code && (
          <pre className="mt-5 overflow-x-auto whitespace-pre-wrap break-words rounded-lg border border-border bg-background/70 p-3 font-mono text-[11px] leading-relaxed text-muted sm:whitespace-pre sm:text-[12px]">
            <code>{code}</code>
          </pre>
        )}
      </div>
    </motion.div>
  );
}
