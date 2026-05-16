import { GitHubIcon, PlayMarkIcon } from "./brand-icons";
import { Package } from "lucide-react";

export default function Footer() {
  const year = new Date().getFullYear();
  return (
    <footer className="relative mt-12 border-t border-border bg-surface/40">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-10 sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <div className="flex items-center gap-2 text-sm">
          <PlayMarkIcon className="h-5 w-5" />
          <span className="font-semibold tracking-tight text-foreground">
            VideoPilot
          </span>
          <span className="ml-2 rounded-full border border-border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-muted">
            MIT
          </span>
        </div>

        <nav
          aria-label="Footer"
          className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-muted"
        >
          <a
            href="https://github.com/mbahgatTech/videopilot"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 transition hover:text-foreground"
          >
            <GitHubIcon className="h-4 w-4" />
            GitHub
          </a>
          <a
            href="https://pypi.org/project/videopilot/"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 transition hover:text-foreground"
          >
            <Package className="h-4 w-4" />
            PyPI
          </a>
          <a
            href="https://modelcontextprotocol.io"
            target="_blank"
            rel="noopener noreferrer"
            className="transition hover:text-foreground"
          >
            MCP spec
          </a>
        </nav>

        <p className="text-xs text-muted-2">
          © {year} VideoPilot contributors. Open source, MIT licensed.
        </p>
      </div>
    </footer>
  );
}
