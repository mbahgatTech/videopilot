"use client";

import { motion, useReducedMotion } from "motion/react";

export default function VideoShowcase() {
  const reduced = useReducedMotion();
  return (
    <section className="relative mx-auto w-full max-w-6xl px-4 py-16 sm:px-6 sm:py-24">
      <motion.div
        initial={reduced ? false : { opacity: 0, y: 24 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, margin: "-80px" }}
        transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
        className="relative"
      >
        <div
          className="relative rounded-3xl p-[1px]"
          style={{
            background:
              "linear-gradient(135deg, rgba(124,92,255,0.55), rgba(0,212,255,0.45) 50%, rgba(124,92,255,0.15) 100%)",
          }}
        >
          <div className="relative overflow-hidden rounded-[calc(theme(borderRadius.3xl)-1px)] bg-surface">
            <div
              aria-hidden="true"
              className="pointer-events-none absolute -top-1/2 left-1/2 h-[80%] w-[120%] -translate-x-1/2 rounded-full opacity-30 blur-3xl"
              style={{
                background:
                  "radial-gradient(circle, rgba(124,92,255,0.6), transparent 60%)",
              }}
            />
            <div className="relative aspect-video w-full">
              <video
                className="absolute inset-0 h-full w-full bg-background object-cover"
                controls
                preload="metadata"
                playsInline
                poster="/videopilot-demo-poster.jpg"
                aria-label="VideoPilot demo video"
              >
                <source src="/videopilot-demo.mp4" type="video/mp4" />
                Your browser does not support embedded video.
              </video>
            </div>
          </div>
        </div>

        <p className="mt-4 text-center text-sm text-muted">
          Generated end-to-end by VideoPilot itself.
        </p>
      </motion.div>
    </section>
  );
}
