"use client";

import { useEffect, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import { cn } from "@/lib/cn";
import { GitHubIcon, PlayMarkIcon } from "./brand-icons";

const LINKS = [
  { href: "#features", label: "Features" },
  { href: "#pipeline", label: "Pipeline" },
  { href: "#tools", label: "Tools" },
  { href: "#install", label: "Install" },
];

export default function Nav() {
  const [scrolled, setScrolled] = useState(false);
  const reduced = useReducedMotion();

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <motion.header
      initial={reduced ? false : { opacity: 0, y: -12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: "easeOut" }}
      className={cn(
        "fixed top-0 left-0 right-0 z-50 transition-all duration-300",
        scrolled
          ? "border-b border-border/80 bg-background/80 backdrop-blur-xl"
          : "border-b border-transparent bg-background/30 backdrop-blur-md",
      )}
    >
      <nav
        className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4 sm:px-6"
        aria-label="Primary"
      >
        <a
          href="#top"
          className="group inline-flex items-center gap-2 text-foreground"
          aria-label="VideoPilot home"
        >
          <PlayMarkIcon className="h-5 w-5 transition-transform group-hover:scale-110" />
          <span className="text-sm font-semibold tracking-tight">VideoPilot</span>
        </a>

        <ul className="hidden items-center gap-1 md:flex">
          {LINKS.map((l) => (
            <li key={l.href}>
              <a
                href={l.href}
                className="rounded-full px-3 py-1.5 text-sm text-muted transition hover:bg-surface hover:text-foreground"
              >
                {l.label}
              </a>
            </li>
          ))}
        </ul>

        <div className="flex items-center gap-2">
          <a
            href="https://github.com/mbahgatTech/videopilot"
            target="_blank"
            rel="noopener noreferrer"
            aria-label="VideoPilot on GitHub"
            className="inline-flex h-9 w-9 items-center justify-center rounded-full border border-border bg-surface/60 text-muted transition hover:border-border-strong hover:text-foreground"
          >
            <GitHubIcon className="h-4 w-4" />
          </a>
          <a
            href="#install"
            className="hidden rounded-full bg-foreground px-4 py-2 text-sm font-medium text-background transition hover:bg-white sm:inline-flex"
          >
            Install
          </a>
        </div>
      </nav>
    </motion.header>
  );
}
