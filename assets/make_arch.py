"""Generate the README architecture diagram for videopilot.

Faithful to the live codebase at https://github.com/mbahgatTech/videopilot:

  Clients          - LLM Agent (MCP) and Operator (CLI)
  Entry points     - videopilot-mcp (stdio server, 20 tools) and videopilot (CLI)
  lib/ pipeline    - init_cmd, tts, voices, transcribe, silence, doctor,
                     cut, compose, export
  External engines - ffmpeg, ffprobe, edge-tts, Azure Speech, faster-whisper
                     (invoked via lib/ffmpeg_wrap.py)
  Per-project      - projects/<slug>/{project,script,cut-plan,compose-plan}.json
                     plus voice/, clips/, transcripts/, out/ artifacts

The output palette is intentionally vivid: per-module neon accents over a
deep-indigo backdrop so the diagram reads well embedded in the README.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1920, 1080
OUT = Path(__file__).resolve().parent / "architecture.png"

# ---------- palette ----------
BG_TOP = (8, 6, 32)
BG_MID = (28, 10, 64)
BG_BOTTOM = (8, 28, 64)
ACCENT = (255, 213, 79)      # gold
TEXT = (255, 255, 255)
MUTED = (210, 220, 245)
DIM = (160, 175, 210)

CLIENT_FILL = (16, 38, 90)
CLIENT_STROKE = (96, 220, 255)

ENTRY_FILL = (70, 18, 110)
ENTRY_STROKE = (220, 130, 255)

# Per-module accents for the 3x3 lib/ grid.
LIB_MODULES = [
    ("init_cmd",   "scaffold project",   (255,  88, 168)),  # hot pink
    ("tts",        "edge-tts / azure",   (124,  92, 255)),  # violet
    ("voices",     "list neural voices", (255, 140,  64)),  # orange
    ("transcribe", "faster-whisper",     ( 80, 220, 160)),  # emerald
    ("silence",    "ffprobe scan",       (255, 213,  79)),  # gold
    ("doctor",     "prereq check",       (120, 240, 110)),  # lime
    ("cut",        "ffmpeg trim",        ( 96, 220, 255)),  # cyan
    ("compose",    "ffmpeg render",      (255,  96, 132)),  # rose
    ("export",     "EDL / FCPXML",       (255, 196,  64)),  # amber
]

ENGINES = [
    ("ffmpeg",         (255, 196, 100)),
    ("ffprobe",        (255, 160,  90)),
    ("edge-tts",       (120, 230, 255)),
    ("Azure Speech",   (210, 150, 255)),
    ("faster-whisper", (130, 240, 180)),
]

STATE_FILL = (18, 50, 60)
STATE_STROKE = (130, 240, 210)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    paths = [
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _gradient_bg() -> Image.Image:
    """Three-stop vertical gradient with three large radial neon glows."""
    img = Image.new("RGB", (W, H), BG_TOP)
    draw = ImageDraw.Draw(img)
    mid = H // 2
    for y in range(H):
        if y < mid:
            t = y / max(mid - 1, 1)
            r = int(BG_TOP[0] * (1 - t) + BG_MID[0] * t)
            g = int(BG_TOP[1] * (1 - t) + BG_MID[1] * t)
            b = int(BG_TOP[2] * (1 - t) + BG_MID[2] * t)
        else:
            t = (y - mid) / max(H - mid - 1, 1)
            r = int(BG_MID[0] * (1 - t) + BG_BOTTOM[0] * t)
            g = int(BG_MID[1] * (1 - t) + BG_BOTTOM[1] * t)
            b = int(BG_MID[2] * (1 - t) + BG_BOTTOM[2] * t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))

    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    g.ellipse((W - 900, -400, W + 300, 700), fill=(255, 80, 200, 70))   # top-right magenta
    g.ellipse((-400, H - 700, 700, H + 300), fill=(80, 200, 255, 65))    # bottom-left cyan
    g.ellipse((W // 2 - 600, H // 2 - 300, W // 2 + 600, H // 2 + 300),
              fill=(160, 110, 255, 35))                                  # center violet wash
    glow = glow.filter(ImageFilter.GaussianBlur(160))
    return Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")


def _glow_box(base: Image.Image, xy, radius, fill, outline, width=3,
              blur=14, glow_alpha=140):
    """Rounded rect with a soft drop shadow AND a neon outline glow."""
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    x0, y0, x1, y1 = xy
    ld.rounded_rectangle((x0 + 6, y0 + 12, x1 + 6, y1 + 12),
                         radius=radius, fill=(0, 0, 0, 150))
    ld.rounded_rectangle((x0 - 4, y0 - 4, x1 + 4, y1 + 4),
                         radius=radius + 4,
                         outline=outline + (glow_alpha,), width=6)
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    base.alpha_composite(layer)
    ImageDraw.Draw(base).rounded_rectangle(
        xy, radius=radius, fill=fill + (255,),
        outline=outline + (255,), width=width,
    )


def _text_centered(draw, xy, text, font, fill):
    x0, y0, x1, y1 = xy
    tw = draw.textlength(text, font=font)
    bbox = font.getbbox(text)
    th = bbox[3] - bbox[1]
    tx = x0 + (x1 - x0 - tw) / 2
    ty = y0 + (y1 - y0 - th) / 2 - bbox[1]
    draw.text((tx, ty), text, font=font, fill=fill)


def _arrow(draw, p0, p1, color, width=3, head=12):
    draw.line([p0, p1], fill=color, width=width)
    angle = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
    a1 = angle + math.radians(150)
    a2 = angle - math.radians(150)
    hx1 = p1[0] + head * math.cos(a1)
    hy1 = p1[1] + head * math.sin(a1)
    hx2 = p1[0] + head * math.cos(a2)
    hy2 = p1[1] + head * math.sin(a2)
    draw.polygon([p1, (hx1, hy1), (hx2, hy2)], fill=color)


def main() -> None:
    img = _gradient_bg().convert("RGBA")
    d = ImageDraw.Draw(img)

    # ----- header -----
    d.rectangle((120, 88, 240, 100), fill=ACCENT)
    d.text((120, 116), "ARCHITECTURE",
           font=_font(32, bold=True), fill=TEXT)
    d.text((120, 168), "How videopilot is wired",
           font=_font(78, bold=True), fill=TEXT,
           stroke_width=2, stroke_fill=(0, 0, 0, 140))
    d.text((124, 268),
           "MCP server + CLI  -  shared lib/ pipeline  -  ffmpeg under the hood",
           font=_font(28), fill=MUTED)

    # brand mark, bottom-right
    d.ellipse((1664, 1020, 1688, 1044), fill=ACCENT)
    d.text((1700, 1019), "VIDEOPILOT",
           font=_font(26, bold=True), fill=ACCENT)

    # ----- layout constants -----
    LX, RX = 80, 1380
    SX0, SX1 = 1400, 1840

    Y_CLIENT = 340
    Y_ENTRY = 490
    Y_LIB = 650
    Y_EXT = 960
    BOX_H = 96

    arrow_color = (255, 255, 255, 230)

    # ----- LAYER 1: CLIENTS -----
    d.text((LX + 20, Y_CLIENT - 36), "CLIENTS",
           font=_font(20, bold=True), fill=DIM)

    client_w = (RX - LX - 80) // 2
    c1 = (LX + 20, Y_CLIENT, LX + 20 + client_w, Y_CLIENT + BOX_H)
    c2 = (LX + 60 + client_w, Y_CLIENT, RX - 20, Y_CLIENT + BOX_H)
    _glow_box(img, c1, 14, CLIENT_FILL, CLIENT_STROKE)
    _glow_box(img, c2, 14, CLIENT_FILL, CLIENT_STROKE)
    d = ImageDraw.Draw(img)
    d.text((c1[0] + 24, c1[1] + 14), "LLM Agent",
           font=_font(28, bold=True), fill=TEXT)
    d.text((c1[0] + 24, c1[1] + 54),
           "Copilot CLI  -  Claude  -  Cursor  -  any MCP client",
           font=_font(19), fill=MUTED)
    d.text((c2[0] + 24, c2[1] + 14), "Operator",
           font=_font(28, bold=True), fill=TEXT)
    d.text((c2[0] + 24, c2[1] + 54),
           "terminal  -  CI  -  scripts",
           font=_font(19), fill=MUTED)

    # ----- LAYER 2: ENTRY POINTS -----
    d.text((LX + 20, Y_ENTRY - 36), "ENTRY POINTS",
           font=_font(20, bold=True), fill=DIM)

    e1 = (LX + 20, Y_ENTRY, LX + 20 + client_w, Y_ENTRY + BOX_H)
    e2 = (LX + 60 + client_w, Y_ENTRY, RX - 20, Y_ENTRY + BOX_H)
    _glow_box(img, e1, 14, ENTRY_FILL, ENTRY_STROKE)
    _glow_box(img, e2, 14, ENTRY_FILL, ENTRY_STROKE)
    d = ImageDraw.Draw(img)
    d.text((e1[0] + 24, e1[1] + 12), "videopilot-mcp",
           font=_font(28, bold=True), fill=TEXT)
    d.text((e1[0] + 24, e1[1] + 52),
           "MCP stdio server  -  20 tools  -  videopilot_mcp.py",
           font=_font(19), fill=MUTED)
    d.text((e2[0] + 24, e2[1] + 12), "videopilot",
           font=_font(28, bold=True), fill=TEXT)
    d.text((e2[0] + 24, e2[1] + 52),
           "argparse CLI  -  videopilot.py",
           font=_font(19), fill=MUTED)

    # arrows: clients -> entry
    _arrow(d, ((c1[0] + c1[2]) // 2, c1[3] + 4),
           ((e1[0] + e1[2]) // 2, e1[1] - 4), arrow_color, width=3, head=12)
    _arrow(d, ((c2[0] + c2[2]) // 2, c2[3] + 4),
           ((e2[0] + e2[2]) // 2, e2[1] - 4), arrow_color, width=3, head=12)
    d.text(((c1[0] + c1[2]) // 2 + 16, c1[3] + 14), "MCP  stdio",
           font=_font(14, bold=True), fill=DIM)
    d.text(((c2[0] + c2[2]) // 2 + 16, c2[3] + 14), "exec",
           font=_font(14, bold=True), fill=DIM)

    # ----- LAYER 3: lib/ PIPELINE (3x3 grid, per-module neon accents) -----
    d.text((LX + 20, Y_LIB - 36), "lib/  -  PIPELINE MODULES",
           font=_font(20, bold=True), fill=DIM)

    # subtle band behind the grid to group both entry points fanning in
    band = Image.new("RGBA", img.size, (0, 0, 0, 0))
    bd = ImageDraw.Draw(band)
    bd.rounded_rectangle((LX, Y_LIB - 12, RX, Y_LIB + 254),
                         radius=18, fill=(255, 255, 255, 16),
                         outline=(255, 255, 255, 50), width=1)
    img.alpha_composite(band)
    d = ImageDraw.Draw(img)

    cols, rows = 3, 3
    margin = 24
    grid_w = (RX - LX) - 2 * margin
    cell_w = (grid_w - (cols - 1) * 18) // cols
    cell_h = 76
    for i, (name, caption, accent) in enumerate(LIB_MODULES):
        row = i // cols
        col = i % cols
        x0 = LX + margin + col * (cell_w + 18)
        y0 = Y_LIB + 6 + row * (cell_h + 12)
        xy = (x0, y0, x0 + cell_w, y0 + cell_h)
        fill = tuple(int(c * 0.18) for c in accent)
        _glow_box(img, xy, 12, fill, accent, width=2, blur=10, glow_alpha=160)
        d = ImageDraw.Draw(img)
        _text_centered(d, (x0, y0 + 6, x0 + cell_w, y0 + cell_h // 2 + 6),
                       name, _font(26, bold=True), TEXT)
        _text_centered(d, (x0, y0 + cell_h // 2 + 6, x0 + cell_w, y0 + cell_h - 4),
                       caption, _font(16), accent)

    # arrows: entry points -> lib band
    _arrow(d, ((e1[0] + e1[2]) // 2, e1[3] + 4),
           ((e1[0] + e1[2]) // 2, Y_LIB - 12), arrow_color, width=3, head=12)
    _arrow(d, ((e2[0] + e2[2]) // 2, e2[3] + 4),
           ((e2[0] + e2[2]) // 2, Y_LIB - 12), arrow_color, width=3, head=12)
    d.text(((e1[0] + e1[2]) // 2 + 16, e1[3] + 22), "imports lib/",
           font=_font(14, bold=True), fill=DIM)
    d.text(((e2[0] + e2[2]) // 2 + 16, e2[3] + 22), "imports lib/",
           font=_font(14, bold=True), fill=DIM)

    # ----- LAYER 4: EXTERNAL ENGINES (neon pills) -----
    d.text((LX + 20, Y_EXT - 32), "EXTERNAL ENGINES",
           font=_font(20, bold=True), fill=DIM)

    pill_h = 58
    pill_w = (RX - LX - 40 - (len(ENGINES) - 1) * 14) // len(ENGINES)
    for i, (name, color) in enumerate(ENGINES):
        x0 = LX + 20 + i * (pill_w + 14)
        y0 = Y_EXT
        xy = (x0, y0, x0 + pill_w, y0 + pill_h)
        # soft outer glow
        glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.rounded_rectangle((x0 - 4, y0 - 4, x0 + pill_w + 4, y0 + pill_h + 4),
                             radius=32, outline=color + (160,), width=5)
        glow = glow.filter(ImageFilter.GaussianBlur(10))
        img.alpha_composite(glow)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle(xy, radius=28,
                            fill=tuple(int(c * 0.18) for c in color) + (255,),
                            outline=color + (255,), width=2)
        _text_centered(d, xy, name, _font(22, bold=True), color)

    # one arrow from lib band down to engines bar
    _arrow(d, ((LX + RX) // 2, Y_LIB + 254 + 4),
           ((LX + RX) // 2, Y_EXT - 38), arrow_color, width=2, head=12)
    d.text(((LX + RX) // 2 + 14, Y_LIB + 258),
           "shells out via lib/ffmpeg_wrap.py",
           font=_font(14, bold=True), fill=DIM)

    # ----- RIGHT SIDEBAR: per-project STATE + OUTPUTS -----
    sidebar_xy = (SX0, Y_CLIENT - 50, SX1, Y_EXT + pill_h + 10)
    sb = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(sb)
    sd.rounded_rectangle(sidebar_xy, radius=20,
                         fill=(255, 255, 255, 16),
                         outline=(255, 255, 255, 60), width=1)
    img.alpha_composite(sb)
    d = ImageDraw.Draw(img)

    d.text((SX0 + 20, Y_CLIENT - 42), "PER-PROJECT WORKSPACE",
           font=_font(18, bold=True), fill=DIM)
    d.text((SX0 + 20, Y_CLIENT - 14),
           "projects/<slug>/", font=_font(22, bold=True), fill=ACCENT)

    state_label_y = Y_CLIENT + 22
    d.text((SX0 + 20, state_label_y), "STATE (JSON)",
           font=_font(17, bold=True), fill=STATE_STROKE)
    state_files = [
        ("project.json", "manifest"),
        ("script.json", "voiceover"),
        ("cut-plan.json", "clips"),
        ("compose-plan.json", "timeline"),
    ]
    sy = state_label_y + 30
    for name, sub in state_files:
        xy = (SX0 + 20, sy, SX1 - 20, sy + 54)
        _glow_box(img, xy, 10, STATE_FILL, STATE_STROKE,
                  width=2, blur=8, glow_alpha=130)
        d = ImageDraw.Draw(img)
        d.text((SX0 + 36, sy + 8), name,
               font=_font(20, bold=True), fill=TEXT)
        d.text((SX0 + 36, sy + 32), sub,
               font=_font(16), fill=MUTED)
        sy += 62

    d.text((SX0 + 20, sy + 8), "OUTPUTS",
           font=_font(17, bold=True), fill=ACCENT)
    outputs = [
        "voice/*.mp3",
        "clips/*.mp4",
        "transcripts/*.srt",
        "out/final.mp4",
        "out/final.edl  -  .fcpxml  -  render.ps1",
    ]
    oy = sy + 40
    for line in outputs:
        d.text((SX0 + 32, oy), "-  " + line,
               font=_font(19), fill=MUTED)
        oy += 28

    # arrow: lib band <-> sidebar (reads / writes JSON state)
    _arrow(d, (RX - 10, Y_LIB + 38),
           (SX0 + 6, Y_LIB + 38), arrow_color, width=3, head=12)
    d.text((RX - 90, Y_LIB + 8), "reads / writes",
           font=_font(15, bold=True), fill=DIM)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(OUT, "PNG", optimize=True)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
