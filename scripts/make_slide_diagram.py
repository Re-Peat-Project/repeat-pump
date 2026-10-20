"""Generate docs/diagrams/workflow_slide.svg (1920x1080). For a PNG, open the SVG in a browser and screenshot it at 1920x1080,
or insert the SVG straight into PowerPoint."""
from html import escape
import xml.etree.ElementTree as ET
from pathlib import Path

W, H = 1920, 1080
INK, MUTED, LINE = "#1f2a24", "#5b6862", "#cfd8d2"
GREEN, GREEN_D, GREEN_L = "#1d6b4f", "#14513b", "#e3f1ea"
RED, AMBER, AMBER_L = "#a33a3a", "#b36b00", "#fff3dc"
FONT = "Segoe UI, Calibri, Arial, sans-serif"


def t(x, y, s, size=24, weight=400, fill=INK, anchor="start", italic=False):
    st = ' font-style="italic"' if italic else ""
    return f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}"{st}>{escape(s)}</text>'


def rect(x, y, w, h, fill, stroke=None, sw=2, rx=14, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    s = f' stroke="{stroke}" stroke-width="{sw}"' if stroke else ""
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}"{s}{d}/>'


def arrow(x1, y1, x2, y2, color=GREEN, w=5, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{w}"{d} marker-end="url(#a{color[1:]})"/>'


def dot(cx, cy, n, r=22):
    return f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{RED}"/>' + t(cx, cy + 9, str(n), 26, 700, "#ffffff", "middle")


g = ["<defs>" + "".join(
    f'<marker id="a{c[1:]}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0 0L10 5L0 10z" fill="{c}"/></marker>'
    for c in (GREEN, AMBER)) + "</defs>", rect(0, 0, W, H, "#ffffff", rx=0)]

g.append(t(60, 95, "From data to pump plan", 60, 700, INK))
g.append(t(60, 142, "How RE-PEAT Pompanisasi turns canal, peat and elevation data into sekat and pump locations", 28, 400, MUTED))

TOP, BOT = 205, 790
# ---- inputs
DX, DW = 60, 290
g.append(t(DX, TOP - 12, "YOUR DATA", 22, 700, MUTED))
cards = ["Elevation (DTM)", "Canals + manual fixes", "Peat depth, burn scars", "Moisture index", "Sub-KHGs + priority", "Rivers, existing sekat"]
ch, cgap = 84, 16
for i, c in enumerate(cards):
    y = TOP + i * (ch + cgap)
    g.append(rect(DX, y, DW, ch, "#f6f8f6", LINE, 2))
    g.append(t(DX + 20, y + ch / 2 + 8, c, 23, 600))

# ---- phases
PW, PG = 345, 34
P0 = DX + DW + 36
phases = [
    ("PREPARE", "Stages 1-5", 2,
     ["Check and clip the data", "Clean and connect canals", "Work out water flow", "Cut canals into segments", "Measure the land slope"],
     "Is the network connected\nand the terrain known?"),
    ("DECIDE", "Stages 6-7", 6,
     ["Score each segment", "(burn, peat, dryness, flow)", "Rank and pick top canals", "Count sekat needed", "Place sekat per 0.4 m rise"],
     "Which canals need water,\nand where do blocks go?"),
    ("ROUTE + PUMP", "Stages 8-10", 9,
     ["Find river water sources", "Route to the highest point", "(least uphill pumping)", "Size pumps, place stations", "List gates to add"],
     "How does water get there,\nand what pumps are needed?"),
]
centers = []
for i, (name, stages, stop, bullets, q) in enumerate(phases):
    x = P0 + i * (PW + PG)
    centers.append(x + PW / 2)
    g.append(rect(x, TOP, PW, BOT - TOP, "#ffffff", GREEN, 3))
    g.append(f'<path d="M{x} {TOP + 14}a14 14 0 0 1 14 -14h{PW - 28}a14 14 0 0 1 14 14v96h-{PW}z" fill="{GREEN}"/>')
    g.append(t(x + 24, TOP + 50, name, 31, 700, "#ffffff"))
    g.append(t(x + 24, TOP + 88, stages, 22, 400, "#d6efe3"))
    g.append(dot(x + PW - 38, TOP + 38, stop))
    y = TOP + 168
    for b in bullets:
        sub = b.startswith("(")
        if not sub:
            g.append(f'<circle cx="{x + 30}" cy="{y - 7}" r="5" fill="{GREEN}"/>')
        g.append(t(x + 46, y, b, 21 if sub else 22.5, 400, MUTED if sub else INK))
        y += 52
    g.append(f'<line x1="{x + 24}" y1="{BOT - 112}" x2="{x + PW - 24}" y2="{BOT - 112}" stroke="{LINE}" stroke-width="2"/>')
    for k, ln in enumerate(q.split("\n")):
        g.append(t(x + 24, BOT - 72 + k * 31, ln, 22, 600, GREEN_D, italic=True))

# ---- results
RX = P0 + 3 * PW + 2 * PG + PG
RW = W - 60 - RX
g.append(rect(RX, TOP, RW, BOT - TOP, GREEN_L, GREEN, 3))
g.append(t(RX + 24, TOP + 50, "RESULTS", 31, 700, GREEN_D))
g.append(t(RX + 24, TOP + 88, "one GeoPackage + report", 22, 400, MUTED))
res = ["Canal priority map", "Sekat: place, height, type", "Water sources and routes", "Pump stations + power", "Gates to add", "Layers to double-check", "Run report"]
y = TOP + 168
for r in res:
    g.append(f'<circle cx="{RX + 30}" cy="{y - 7}" r="5" fill="{GREEN}"/>')
    g.append(t(RX + 46, y, r, 22.5, 400))
    y += 55

# ---- arrows between columns
mid = (TOP + BOT) / 2
g.append(arrow(DX + DW + 2, mid, P0 - 2, mid))
for i in range(2):
    xe = P0 + i * (PW + PG) + PW
    g.append(arrow(xe + 2, mid, xe + PG - 2, mid))
xe = P0 + 2 * (PW + PG) + PW
g.append(arrow(xe + 2, mid, RX - 2, mid))

# ---- decisions strip
sy = 840
x0, x1 = P0, P0 + 3 * PW + 2 * PG
g.append(rect(x0, sy, x1 - x0, 150, AMBER_L, AMBER, 3, dash="10 8"))
g.append(t(x0 + 30, sy + 50, "YOUR DECISIONS  (config file)", 26, 700, AMBER))
g.append(t(x0 + 30, sy + 92, "weights  ·  snap tolerance  ·  sekat spacing  ·  pump settings", 26, 400, INK))
g.append(t(x0 + 30, sy + 130, "Nothing is guessed: if a decision is missing, the run stops and lists it.", 22, 400, MUTED))
for cx in centers:
    g.append(arrow(cx, sy - 2, cx, BOT + 6, AMBER, 4, "8 6"))

# review legend
g.append(dot(RX + 24, sy + 36, "!", 20))
g.append(t(RX + 58, sy + 45, "Review stop", 27, 700, RED))
g.append(t(RX, sy + 90, "The run pauses so you can check", 22, 400, INK))
g.append(t(RX, sy + 120, "the result, then approve it.", 22, 400, INK))

g.append(t(60, 1050, "RE-PEAT  ·  KLH  ·  Departemen Teknik Geodesi UGM", 20, 400, MUTED))

svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="{FONT}" '
       f'role="img" aria-label="Workflow: data, prepare, decide, route and pump, results">' + "".join(g) + "</svg>")
ET.fromstring(svg)
out = Path(__file__).resolve().parents[1] / "docs" / "diagrams"
out.mkdir(exist_ok=True)
(out / "workflow_slide.svg").write_text(svg, encoding="utf8")
print("wrote", out / "workflow_slide.svg")
