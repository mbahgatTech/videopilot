import { cn } from "@/lib/cn";

type Props = {
  prompt?: string;
  lines: Array<{ kind: "in" | "out" | "ok" | "warn"; text: string }>;
  className?: string;
  title?: string;
};

const KIND_CLASS = {
  in: "text-foreground",
  out: "text-muted",
  ok: "text-cyan",
  warn: "text-coral",
} as const;

export default function TerminalBlock({
  prompt = "$",
  lines,
  className,
  title = "videopilot doctor",
}: Props) {
  return (
    <div
      className={cn(
        "overflow-hidden rounded-2xl border border-border bg-surface/80 shadow-2xl shadow-violet/5",
        className,
      )}
    >
      <div className="flex items-center gap-2 border-b border-border bg-surface-2 px-4 py-2.5">
        <span className="h-2.5 w-2.5 rounded-full bg-[#ff5f56]" aria-hidden="true" />
        <span className="h-2.5 w-2.5 rounded-full bg-[#febc2e]" aria-hidden="true" />
        <span className="h-2.5 w-2.5 rounded-full bg-[#28c840]" aria-hidden="true" />
        <span className="ml-2 font-mono text-[11px] text-muted-2">{title}</span>
      </div>
      <pre className="whitespace-pre-wrap break-words px-4 py-4 font-mono text-[11.5px] leading-relaxed sm:px-5 sm:text-[12.5px]">
        <code>
          {lines.map((l, i) => (
            <div key={i} className={cn("whitespace-pre-wrap break-words", KIND_CLASS[l.kind])}>
              {l.kind === "in" ? (
                <>
                  <span className="select-none text-violet">{prompt} </span>
                  {l.text}
                </>
              ) : (
                l.text
              )}
            </div>
          ))}
        </code>
      </pre>
    </div>
  );
}
