# VideoPilot — landing page

Marketing site for **VideoPilot**, the open-source MCP server that lets
LLMs author, edit, and render finished videos. Built with **Next.js 15
(App Router)**, **TypeScript** strict, **Tailwind CSS v4**, and
**Framer Motion** (the new `motion` package).

> The VideoPilot project itself lives at
> [`mbahgatTech/videopilot`](https://github.com/mbahgatTech/videopilot)
> and on [PyPI](https://pypi.org/project/videopilot/).

---

## What's inside

- App Router, server components by default. Only the interactive bits
  (`"use client"`) ship JS.
- Tailwind v4 with theme tokens defined in `app/globals.css` via
  `@theme { ... }`. No `tailwind.config.*` file needed.
- `next/font` loading **Geist** and **Geist Mono**.
- Comprehensive `metadata` + `viewport` in `app/layout.tsx` (Open Graph,
  Twitter card, theme color).
- Custom SVG icon at `app/icon.svg` (Next picks this up automatically as
  the site favicon).
- Novel design elements: animated mesh-gradient hero, cursor-tracking
  spotlight, grid backdrop with radial mask, bento feature grid with
  per-card spotlight-on-hover, animated 6-stage pipeline visualizer,
  infinite tools marquee, magnetic CTA buttons, glassmorphic nav.
- Honours `prefers-reduced-motion`: heavy animations gate themselves off.

## File map

```
app/
  layout.tsx          metadata, fonts, root layout
  page.tsx            section composition
  globals.css         Tailwind v4 theme tokens + animations
  icon.svg            site icon (consumed by Next automatically)
components/
  nav.tsx             sticky glassmorphic nav
  hero.tsx            headline + CTAs + PyPI chip
  hero-background.tsx animated gradient + grid + cursor spotlight
  video-showcase.tsx  demo video card (points at /videopilot-demo.mp4)
  features-bento.tsx  6-card bento grid
  feature-card.tsx    spotlight-on-hover card
  pipeline.tsx        6-stage animated pipeline (SVG + scroll-in)
  tools-marquee.tsx   infinite marquee of 20 MCP tools
  install.tsx         tabbed PyPI / uvx install + doctor terminal
  terminal-block.tsx  styled terminal output panel
  copy-button.tsx     clipboard button with copied state
  magnetic-button.tsx CTA button that drifts toward the cursor
  footer.tsx          links + license
  brand-icons.tsx     inline GitHub + VP play-mark SVGs
lib/
  cn.ts               clsx + tailwind-merge helper
  tools.ts            the 20 MCP tool names
public/
  videopilot-demo.mp4 (populated by a sibling agent; graceful if missing)
```

## Develop

```sh
npm install
npm run dev
```

Open <http://localhost:3000>.

## Build

```sh
npm run build
npm start
```

Build output is the standard Next.js production build. With Next 16 the
build uses Turbopack by default.

## Lint

```sh
npm run lint
```

## Deploy

The fastest path is **[Vercel](https://vercel.com)** — first-class
Next.js host.

```sh
npm i -g vercel       # one-time
vercel                # preview deploy
vercel --prod         # production
```

No `vercel.json` is needed: Vercel auto-detects Next.js, runs
`npm run build`, and serves both the static assets and the React Server
Components.

The same `npm run build && npm start` flow works on any Node 20+ host
(Render, Fly.io, a plain VPS) — point traffic at port 3000.

## Demo video

The hero showcase points at `/videopilot-demo.mp4`. If the file is not
yet present in `public/`, the `<video>` element falls back to its
contents (a one-line "your browser doesn't support video" message) and
the page still renders.

A sibling agent in this workspace is responsible for generating and
dropping that file into `public/`.

## License

MIT, same as the VideoPilot project.
