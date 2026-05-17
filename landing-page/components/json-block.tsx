"use client";

import { Fragment } from "react";
import { cn } from "@/lib/cn";

type TokenKind = "key" | "string" | "num" | "atom" | "punct" | "ws";

interface Token {
  kind: TokenKind;
  value: string;
}

const TOKEN_RE = new RegExp(
  [
    "(\"(?:[^\"\\\\]|\\\\.)*\")\\s*(?=:)",
    "(\"(?:[^\"\\\\]|\\\\.)*\")",
    "(\\btrue\\b|\\bfalse\\b|\\bnull\\b)",
    "(-?\\d+(?:\\.\\d+)?(?:[eE][+-]?\\d+)?)",
    "([{}\\[\\]:,])",
    "(\\s+)",
  ].join("|"),
  "g",
);

function tokenize(src: string): Token[] {
  const out: Token[] = [];
  let m: RegExpExecArray | null;
  let lastIdx = 0;
  TOKEN_RE.lastIndex = 0;
  while ((m = TOKEN_RE.exec(src)) !== null) {
    if (m.index > lastIdx) {
      out.push({ kind: "punct", value: src.slice(lastIdx, m.index) });
    }
    if (m[1] !== undefined) out.push({ kind: "key", value: m[1] });
    else if (m[2] !== undefined) out.push({ kind: "string", value: m[2] });
    else if (m[3] !== undefined) out.push({ kind: "atom", value: m[3] });
    else if (m[4] !== undefined) out.push({ kind: "num", value: m[4] });
    else if (m[5] !== undefined) out.push({ kind: "punct", value: m[5] });
    else if (m[6] !== undefined) out.push({ kind: "ws", value: m[6] });
    lastIdx = TOKEN_RE.lastIndex;
  }
  if (lastIdx < src.length) {
    out.push({ kind: "punct", value: src.slice(lastIdx) });
  }
  return out;
}

const COLOR: Record<TokenKind, string> = {
  key: "text-cyan",
  string: "text-coral",
  num: "text-violet",
  atom: "text-violet",
  punct: "text-muted-2",
  ws: "",
};

export default function JsonBlock({
  value,
  className,
}: {
  value: string;
  className?: string;
}) {
  const tokens = tokenize(value);
  return (
    <pre
      className={cn(
        "overflow-x-auto whitespace-pre-wrap break-words font-mono text-[11.5px] leading-relaxed sm:whitespace-pre sm:text-[12.5px]",
        className,
      )}
      aria-label="JSON configuration"
    >
      <code>
        {tokens.map((t, i) => (
          <Fragment key={i}>
            {t.kind === "ws" ? (
              t.value
            ) : (
              <span className={COLOR[t.kind]}>{t.value}</span>
            )}
          </Fragment>
        ))}
      </code>
    </pre>
  );
}
