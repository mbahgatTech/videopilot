"use client";

import { useEffect, useRef } from "react";
import {
  motion,
  useMotionValue,
  useSpring,
  useTransform,
  useReducedMotion,
  type MotionValue,
} from "motion/react";

function useRadialFollow(x: MotionValue<number>, y: MotionValue<number>) {
  return useTransform([x, y] as MotionValue<number>[], (vals) => {
    const [px, py] = vals as [number, number];
    const cx = (px * 100).toFixed(2);
    const cy = (py * 100).toFixed(2);
    return `radial-gradient(420px circle at ${cx}% ${cy}%, rgba(124,92,255,0.18), rgba(0,212,255,0.08) 35%, transparent 60%)`;
  });
}

export default function HeroBackground() {
  const ref = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();

  const x = useMotionValue(0.5);
  const y = useMotionValue(0.5);
  const sx = useSpring(x, { stiffness: 120, damping: 25, mass: 0.6 });
  const sy = useSpring(y, { stiffness: 120, damping: 25, mass: 0.6 });
  const spotlight = useRadialFollow(sx, sy);

  useEffect(() => {
    if (reduced) return;
    const el = ref.current;
    if (!el) return;

    const onMove = (e: PointerEvent) => {
      const rect = el.getBoundingClientRect();
      const px = (e.clientX - rect.left) / rect.width;
      const py = (e.clientY - rect.top) / rect.height;
      x.set(Math.max(0, Math.min(1, px)));
      y.set(Math.max(0, Math.min(1, py)));
    };

    window.addEventListener("pointermove", onMove);
    return () => window.removeEventListener("pointermove", onMove);
  }, [reduced, x, y]);

  return (
    <div
      ref={ref}
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 overflow-hidden"
    >
      <div className="absolute inset-0 bg-background" />

      {!reduced && (
        <motion.div
          className="absolute -top-1/3 left-1/2 h-[120vh] w-[120vh] -translate-x-1/2 rounded-full opacity-70 blur-3xl"
          style={{
            background:
              "conic-gradient(from 180deg at 50% 50%, rgba(124,92,255,0.45), rgba(0,212,255,0.35), rgba(255,122,89,0.18), rgba(124,92,255,0.45))",
          }}
          animate={{ rotate: 360 }}
          transition={{ duration: 60, ease: "linear", repeat: Infinity }}
        />
      )}

      <motion.div
        className="absolute -top-40 -left-40 h-[60vh] w-[60vh] rounded-full opacity-40 blur-3xl"
        style={{ background: "radial-gradient(circle, rgba(124,92,255,0.55), transparent 60%)" }}
        animate={reduced ? undefined : { x: [0, 30, 0], y: [0, 15, 0] }}
        transition={{ duration: 14, ease: "easeInOut", repeat: Infinity }}
      />
      <motion.div
        className="absolute -bottom-40 -right-40 h-[60vh] w-[60vh] rounded-full opacity-40 blur-3xl"
        style={{ background: "radial-gradient(circle, rgba(0,212,255,0.45), transparent 60%)" }}
        animate={reduced ? undefined : { x: [0, -25, 0], y: [0, -20, 0] }}
        transition={{ duration: 18, ease: "easeInOut", repeat: Infinity }}
      />

      <div className="absolute inset-0 bg-grid mask-radial-fade opacity-50" />

      <div className="absolute inset-0 bg-gradient-to-b from-transparent via-transparent to-background" />

      {!reduced && (
        <motion.div
          className="absolute inset-0"
          style={{
            background: spotlight,
            mixBlendMode: "plus-lighter",
          }}
        />
      )}
    </div>
  );
}
