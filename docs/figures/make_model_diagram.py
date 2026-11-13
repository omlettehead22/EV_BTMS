"""Draw docs/figures/model_overview.svg: how the model works, in four panels.

A  the module: cells in a hex array, filler in the gaps, coolant ribbons,
   interior and edge cells
B  one cell's share of the module, solved as a 1D radial problem
C  the design loop
D  the 2D slices used where cooling reaches the cell from one side

Run: python docs/figures/make_model_diagram.py
"""

from __future__ import annotations

import itertools
import math
from pathlib import Path

W, H = 1200, 960
TEXT, TEXT_2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#8a8984", "#e1e0d9", "#fcfcfb"
CELL, CELL_EDGE = "#9ec5f4", "#256abf"
FILL, FILL_EDGE = "#f6d79a", "#c98a1b"
COOL_IN, COOL_OUT = "#8fdcbf", "#0f7a55"
COOL = "#1baf7a"
FONT = "Inter, 'Segoe UI', Helvetica, Arial, sans-serif"

out: list[str] = []


def add(s: str) -> None:
    out.append(s)


def text(x, y, s, size=13, color=TEXT, weight=400, anchor="start", italic=False) -> None:
    style = ' font-style="italic"' if italic else ""
    add(
        f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{color}" font-weight="{weight}" '
        f'text-anchor="{anchor}"{style}>{s}</text>'
    )


def lines(x, y, rows, size=12, color=TEXT_2, anchor="start", lh=None) -> None:
    lh = lh or size * 1.35
    for i, r in enumerate(rows):
        text(x, y + i * lh, r, size, color, anchor=anchor)


def arrow(x1, y1, x2, y2, color=TEXT_2, width=1.5, marker="arrow") -> None:
    add(
        f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{color}" '
        f'stroke-width="{width}" marker-end="url(#{marker})"/>'
    )


add(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="{FONT}">')
add(f"""<defs>
  <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
    <path d="M0,1 L9,5 L0,9 z" fill="{TEXT_2}"/></marker>
  <marker id="arrow-cool" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
    <path d="M0,1 L9,5 L0,9 z" fill="{COOL_OUT}"/></marker>
  <linearGradient id="coolant" x1="0" x2="1" y1="0" y2="0">
    <stop offset="0" stop-color="{COOL_IN}"/><stop offset="1" stop-color="{COOL_OUT}"/></linearGradient>
  <pattern id="roll" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
    <rect width="7" height="7" fill="{CELL}"/><line x1="0" y1="0" x2="0" y2="7" stroke="#b9d6f8" stroke-width="2.5"/></pattern>
</defs>""")
add(f'<rect width="{W}" height="{H}" fill="{SURFACE}"/>')
text(30, 40, "How the model works", 22, TEXT, 700)
text(
    30,
    64,
    "A packed module is reduced to a few representative cells, each solved on its own share, then swept over design choices.",
    13.5,
    TEXT_2,
)

# ---------------------------------------------------------------------------
# A  Module (top view)
# ---------------------------------------------------------------------------
text(30, 104, "A", 15, TEXT, 700)
text(50, 104, "Module, top view", 15, TEXT, 700)
R, p = 24.0, 62.0
dy = p * math.sqrt(3) / 2
x0, y0 = 72.0, 150.0
rows, cols = 4, 5
centres = [(x0 + c * p + (p / 2 if r % 2 else 0), y0 + r * dy, r, c) for r in range(rows) for c in range(cols)]
# Filler between the cans
add(
    f'<rect x="{x0 - R - 12}" y="{y0 - R - 12}" width="{(cols - 1) * p + p / 2 + 2 * R + 24}" '
    f'height="{(rows - 1) * dy + 2 * R + 24}" rx="10" fill="{FILL}" stroke="{TEXT_2}" stroke-width="3"/>'
)
# Coolant ribbons weaving between rows 0-1 and 2-3
for r in (0, 2):
    ya, yb = y0 + r * dy, y0 + (r + 1) * dy
    pts = [(x0 - R - 30, (ya + yb) / 2)]
    for c in range(cols):
        pts.append((x0 + c * p, ya + R + 5.5))  # under a cell of the upper row
        pts.append((x0 + c * p + p / 2, yb - R - 5.5))  # over a cell of the lower row
    pts.append((x0 + (cols - 1) * p + p / 2 + R + 34, (ya + yb) / 2))
    d = f"M{pts[0][0]:.1f},{pts[0][1]:.1f}"
    for (xa, ya_), (xb, yb_) in itertools.pairwise(pts):
        xm = (xa + xb) / 2
        d += f" C{xm:.1f},{ya_:.1f} {xm:.1f},{yb_:.1f} {xb:.1f},{yb_:.1f}"
    add(f'<path d="{d}" fill="none" stroke="url(#coolant)" stroke-width="4" stroke-linecap="round"/>')
# Cells
for cx, cy, r, c in centres:
    add(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{R}" fill="url(#roll)" stroke="{CELL_EDGE}" stroke-width="1.5"/>')
# Unit cell around an interior cell
ux, uy = x0 + 2 * p + p / 2, y0 + dy
hexpts = " ".join(
    f"{ux + (p / math.sqrt(3)) * math.cos(math.radians(30 + 60 * k)):.1f},"
    f"{uy + (p / math.sqrt(3)) * math.sin(math.radians(30 + 60 * k)):.1f}"
    for k in range(6)
)
add(f'<polygon points="{hexpts}" fill="none" stroke="{TEXT}" stroke-width="1.6" stroke-dasharray="5 4"/>')
r_u = p * math.sqrt(math.sqrt(3) / (2 * math.pi))
add(f'<circle cx="{ux:.1f}" cy="{uy:.1f}" r="{r_u:.1f}" fill="none" stroke="{TEXT}" stroke-width="1.2"/>')
# Edge cell: bottom row, against the module wall
ex, ey = x0 + 1 * p + p / 2, y0 + 3 * dy
add(f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="{R + 5}" fill="none" stroke="{TEXT}" stroke-width="2.2"/>')
# Flow labels
ylab = y0 + (rows - 1) * dy + R + 38
text(x0 - R - 12, ylab, "coolant in", 12, COOL_OUT, 600)
text(x0 + (cols - 1) * p + p / 2 + R + 12, ylab, "out", 12, COOL_OUT, 600, anchor="end")
arrow(x0 + 50, ylab - 4, x0 + (cols - 1) * p - 10, ylab - 4, COOL_OUT, 1.5, "arrow-cool")
lines(
    x0 - R - 12,
    ylab + 24,
    [
        "Coolant warms along the channel, so outlet cells",
        "run hottest; cells on the wall see a different",
        "boundary. Each design is judged on four cells:",
        "interior and edge, at the inlet and the outlet.",
    ],
)
# Legend
ly = ylab + 108
for i, (fill, edge, label) in enumerate(
    ((("url(#roll)"), CELL_EDGE, "cell (jelly roll)"), (FILL, FILL_EDGE, "filler: PCM, PCM + graphite or air"))
):
    add(f'<rect x="{x0 - R - 12}" y="{ly + i * 22 - 11}" width="14" height="14" rx="3" fill="{fill}" stroke="{edge}"/>')
    text(x0 - R + 10, ly + i * 22, label, 12, TEXT_2)
add(
    f'<line x1="{x0 - R - 12}" y1="{ly + 44 - 4}" x2="{x0 - R + 2}" y2="{ly + 44 - 4}" stroke="{COOL}" stroke-width="5" stroke-linecap="round"/>'
)
text(x0 - R + 10, ly + 44, "cooling: side ribbon (or bottom plate, or air)", 12, TEXT_2)
add(
    f'<line x1="{x0 - R - 12}" y1="{ly + 66 - 4}" x2="{x0 - R + 2}" y2="{ly + 66 - 4}" stroke="{TEXT}" stroke-width="1.6" stroke-dasharray="5 4"/>'
)
text(x0 - R + 10, ly + 66, "interior cell's share (unit cell) → circle of equal area", 12, TEXT_2)
add(f'<circle cx="{x0 - R - 5}" cy="{ly + 88 - 4}" r="7" fill="none" stroke="{TEXT}" stroke-width="2.2"/>')
text(x0 - R + 10, ly + 88, "edge cell: part of its share lies on the module wall", 12, TEXT_2)

# Leader from the unit cell to panel B
bx0, by0 = 470.0, 290.0  # apex of the sector in panel B
add(
    f'<path d="M{ux + r_u + 4:.1f},{uy:.1f} C{ux + 70:.1f},{uy:.1f} {bx0 - 70:.1f},{by0 - 60:.1f} {bx0 - 12:.1f},{by0 - 22:.1f}" '
    f'fill="none" stroke="{MUTED}" stroke-width="1.2" stroke-dasharray="3 4" marker-end="url(#arrow)"/>'
)

# ---------------------------------------------------------------------------
# B  One cell's share, 1D radial
# ---------------------------------------------------------------------------
text(440, 104, "B", 15, TEXT, 700)
text(460, 104, "One cell's share, solved in 1D (radius)", 15, TEXT, 700)
rc_px, ru_px, half = 180.0, 250.0, 22.0  # cell radius, unit-cell radius (px), half angle (deg)


def sector(r0, r1, fill, edge):
    a = math.radians(half)
    p1 = (bx0 + r0 * math.cos(a), by0 - r0 * math.sin(a))
    p2 = (bx0 + r1 * math.cos(a), by0 - r1 * math.sin(a))
    p3 = (bx0 + r1 * math.cos(a), by0 + r1 * math.sin(a))
    p4 = (bx0 + r0 * math.cos(a), by0 + r0 * math.sin(a))
    d = f"M{p1[0]:.1f},{p1[1]:.1f} L{p2[0]:.1f},{p2[1]:.1f} A{r1},{r1} 0 0 1 {p3[0]:.1f},{p3[1]:.1f} L{p4[0]:.1f},{p4[1]:.1f}"
    d += f" A{r0},{r0} 0 0 0 {p1[0]:.1f},{p1[1]:.1f} Z" if r0 > 0 else " Z"
    add(f'<path d="{d}" fill="{fill}" stroke="{edge}" stroke-width="1.5"/>')


sector(0, rc_px, "url(#roll)", CELL_EDGE)
sector(rc_px, ru_px, FILL, FILL_EDGE)
# Finite-volume nodes along the centre line
for k in range(14):
    r = (k + 0.5) * rc_px / 14
    add(f'<circle cx="{bx0 + r:.1f}" cy="{by0:.1f}" r="2.6" fill="{CELL_EDGE}"/>')
for k in range(5):
    r = rc_px + (k + 0.5) * (ru_px - rc_px) / 5
    add(f'<circle cx="{bx0 + r:.1f}" cy="{by0:.1f}" r="2.6" fill="{FILL_EDGE}"/>')
# Radius axis with boundary conditions under each tick
SUB = "<tspan baseline-shift='sub' font-size='9'>{}</tspan>"
ay = by0 + ru_px * math.sin(math.radians(half)) + 24
add(f'<line x1="{bx0}" y1="{ay}" x2="{bx0 + ru_px}" y2="{ay}" stroke="{TEXT_2}" stroke-width="1"/>')
for r, lab, note, anchor in (
    (0, "0", "symmetry", "middle"),
    (rc_px, "r" + SUB.format("cell"), "can", "middle"),
    (ru_px, "r" + SUB.format("u"), "no heat crosses", "middle"),
):
    add(f'<line x1="{bx0 + r}" y1="{ay - 4}" x2="{bx0 + r}" y2="{ay + 4}" stroke="{TEXT_2}" stroke-width="1"/>')
    text(bx0 + r, ay + 20, lab, 13, TEXT, anchor=anchor)
    text(bx0 + r, ay + 36, note, 11.5, TEXT_2, anchor=anchor)
# Region labels above the sector, with leaders
top = by0 - ru_px * math.sin(math.radians(half))
lines(
    bx0 - 10,
    top - 22,
    ["Jelly roll: heat q‴(t) from the", "electro-thermal model; k, ρc" + SUB.format("p")],
    12,
    TEXT_2,
)
add(f'<line x1="{bx0 + 110}" y1="{top - 2}" x2="{bx0 + 110}" y2="{by0 - 18}" stroke="{MUTED}" stroke-width="1"/>')
lines(bx0 + 200, top - 58, ["Filler: PCM melts and", "re-freezes (enthalpy form)"], 12, TEXT_2)
add(f'<line x1="{bx0 + 222}" y1="{top - 38}" x2="{bx0 + 222}" y2="{by0 - 40}" stroke="{MUTED}" stroke-width="1"/>')
# Cooling sink at the can surface
a = math.radians(half)
sx, sy = bx0 + rc_px * math.cos(a), by0 + rc_px * math.sin(a)
arrow(sx, sy + 4, bx0 + rc_px, ay - 8, COOL_OUT, 2.2, "arrow-cool")
lines(
    bx0 - 20,
    ay + 74,
    [
        "Cooling sink: heat leaves into coolant at T" + SUB.format("c") + "(t), set by",
        "the coolant's own heat balance along the channel.",
        "Air cooling wets the whole can, so 1D fits. A plate",
        "or a ribbon touches one side, so those run in 2D (D).",
    ],
    12,
    COOL_OUT,
)


# ---------------------------------------------------------------------------
# C  Design loop
# ---------------------------------------------------------------------------
text(830, 104, "C", 15, TEXT, 700)
text(850, 104, "Design loop", 15, TEXT, 700)
steps = [
    ("Duty cycle", "WLTC, motorway + rapid charge, constant C-rate"),
    ("Electro-thermal cell", "OCV, resistance, kinetics → heat q‴(t)"),
    ("Module cells (B, D)", "interior and edge × inlet and outlet"),
    ("Sweep the designs", "topology × flow × chiller × filler × gap"),
    ("Trade-off and picks", "mass vs fan / pump / chiller energy,"),
]
bx, bw, bh, gap = 830.0, 340.0, 58.0, 20.0
for i, (head, sub) in enumerate(steps):
    y = 128 + i * (bh + gap)
    last = i == len(steps) - 1
    h = bh + (18 if last else 0)
    add(
        f'<rect x="{bx}" y="{y}" width="{bw}" height="{h}" rx="8" fill="#ffffff" '
        f'stroke="{TEXT if last else GRID}" stroke-width="{1.6 if last else 1.2}"/>'
    )
    text(bx + 16, y + 24, head, 14, TEXT, 600)
    text(bx + 16, y + 44, sub, 12, TEXT_2)
    if last:
        text(bx + 16, y + 62, "re-checked at worst-case resistance", 12, TEXT_2)
    else:
        arrow(bx + bw / 2, y + bh + 2, bx + bw / 2, y + bh + gap - 2)


# ---------------------------------------------------------------------------
# D  2D slices
# ---------------------------------------------------------------------------
dy0 = 650.0
add(f'<line x1="30" y1="{dy0 - 34}" x2="{W - 30}" y2="{dy0 - 34}" stroke="{GRID}" stroke-width="1"/>')
text(30, dy0, "D", 15, TEXT, 700)
text(50, dy0, "Where cooling touches one side: 2D slices of the same share", 15, TEXT, 700)

# D1  bottom plate: radius x height
gx, gy, gw, gh, fw = 90.0, dy0 + 40, 150.0, 170.0, 40.0  # cell width (r), height (z), filler width
add(f'<rect x="{gx}" y="{gy}" width="{gw}" height="{gh}" fill="url(#roll)" stroke="{CELL_EDGE}" stroke-width="1.5"/>')
add(f'<rect x="{gx + gw}" y="{gy}" width="{fw}" height="{gh}" fill="{FILL}" stroke="{FILL_EDGE}" stroke-width="1.5"/>')
add(f'<rect x="{gx - 6}" y="{gy + gh + 4}" width="{gw + fw + 12}" height="14" rx="3" fill="url(#coolant)"/>')
for i in range(7):
    for j in range(8):
        add(
            f'<circle cx="{gx + (i + 0.5) * gw / 7:.1f}" cy="{gy + (j + 0.5) * gh / 8:.1f}" r="2.2" fill="{CELL_EDGE}"/>'
        )
for j in range(8):
    add(f'<circle cx="{gx + gw + fw / 2:.1f}" cy="{gy + (j + 0.5) * gh / 8:.1f}" r="2.2" fill="{FILL_EDGE}"/>')
add(
    f'<line x1="{gx}" y1="{gy - 10}" x2="{gx}" y2="{gy + gh + 26}" stroke="{TEXT_2}" stroke-width="1" stroke-dasharray="4 3"/>'
)
text(gx - 8, gy + gh / 2, "axis", 11.5, TEXT_2, anchor="end")
arrow(gx + gw / 2, gy + 30, gx + gw / 2, gy + gh - 10, COOL_OUT, 2.2, "arrow-cool")
text(gx + gw + fw + 14, gy + gh + 15, "plate + TIM", 12, COOL_OUT, 600)
text(gx + gw + fw + 14, gy + 14, "top: hottest", 12, TEXT_2)
text(gx, gy + gh + 46, "Bottom plate: radius × height", 13, TEXT, 600)
lines(gx, gy + gh + 64, ["Heat runs down the winding to the plate,", "so the top of the cell runs hottest."], 12)

# D2  side ribbon: radius x angle (top view, half domain by symmetry)
cx2, cy2, rc2, ru2 = 570.0, dy0 + 185, 105.0, 135.0


def pol(r, a):
    return cx2 + r * math.cos(math.radians(a)), cy2 - r * math.sin(math.radians(a))


def half_ring(r0, r1, fill, edge):
    p1, p2, p3, p4 = pol(r0, 0), pol(r1, 0), pol(r1, 180), pol(r0, 180)
    d = f"M{p1[0]:.1f},{p1[1]:.1f} L{p2[0]:.1f},{p2[1]:.1f} A{r1},{r1} 0 0 0 {p3[0]:.1f},{p3[1]:.1f}"
    d += f" L{p4[0]:.1f},{p4[1]:.1f} A{r0},{r0} 0 0 1 {p1[0]:.1f},{p1[1]:.1f} Z" if r0 > 0 else " Z"
    add(f'<path d="{d}" fill="{fill}" stroke="{edge}" stroke-width="1.5"/>')


half_ring(0, rc2, "url(#roll)", CELL_EDGE)
half_ring(rc2, ru2, FILL, FILL_EDGE)
for i in range(1, 6):
    for k in range(9):
        x, y = pol(i * rc2 / 5.6, (k + 0.5) * 180 / 9)
        add(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.2" fill="{CELL_EDGE}"/>')
q0, q1 = pol(rc2 + 4, 34), pol(rc2 + 4, 1)
add(
    f'<path d="M{q0[0]:.1f},{q0[1]:.1f} A{rc2 + 4},{rc2 + 4} 0 0 1 {q1[0]:.1f},{q1[1]:.1f}" '
    f'fill="none" stroke="{COOL}" stroke-width="9" stroke-linecap="round"/>'
)
add(
    f'<line x1="{cx2 - ru2 - 14}" y1="{cy2}" x2="{cx2 + ru2 + 14}" y2="{cy2}" '
    f'stroke="{TEXT_2}" stroke-width="1" stroke-dasharray="4 3"/>'
)
text(cx2 + ru2 + 6, cy2 - 52, "ribbon contact", 12, COOL_OUT, 600)
text(cx2 - ru2 - 8, cy2 - 34, "far side:", 12, TEXT_2, anchor="end")
text(cx2 - ru2 - 8, cy2 - 18, "warmer", 12, TEXT_2, anchor="end")
text(cx2, cy2 + 18, "symmetry plane: half the can is solved", 11.5, TEXT_2, anchor="middle")
text(cx2 - ru2, dy0 + 240, "Side ribbon: radius × angle (top view)", 13, TEXT, 600)
lines(cx2 - ru2, dy0 + 258, ["The ribbon touches a strip of the can, so heat", "runs round the can to reach it."], 12)

# Notes
lines(
    850,
    dy0 + 50,
    [
        "Both slices share one solver with the 1D model:",
        "finite volumes in enthalpy form, so the PCM melts",
        "and re-freezes, with the same cell heat, coolant",
        "balance and edge-cell wall.",
        "",
        "The 2D field changes the answer: the plate case",
        "runs about 6 K hotter at the top than at the base",
        "at the 1.5C peak, which a 1D model cannot see.",
        "",
        "Computed fields: docs/figures/fields_2d.png",
    ],
    12.5,
    TEXT_2,
    lh=19,
)
add(
    f'<text x="{W - 30}" y="{H - 16}" font-size="11" fill="{MUTED}" text-anchor="end">'
    "Schematic, not to scale. r<tspan baseline-shift='sub' font-size='8'>u</tspan>: radius of a circle with the same area as one cell's share.</text>"
)
add("</svg>")

path = Path(__file__).with_name("model_overview.svg")
path.write_text("\n".join(out), encoding="utf-8")
print(f"Wrote {path}")
