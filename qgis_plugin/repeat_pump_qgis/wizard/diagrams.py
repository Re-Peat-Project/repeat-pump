"""Three small schematics for the Learn card: the sekat head rule (stage 7), the moisture ring (stage 6) and the head-aware route
cost (stage 9). Built as inline SVG so they follow the language switch and need no image files. Pure Python (no Qt)."""
from __future__ import annotations

from typing import Optional

from .i18n import tr

INK, MUTED, TEAL, AMBER, WATER, GROUND, RED = "#17261F", "#4C5E57", "#1F8A8A", "#E0922F", "#3F9DAA", "#8D7B5E", "#C0392B"
W, H = 380, 170


def _svg(body: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="Segoe UI, Arial, sans-serif">'
            f'<rect width="{W}" height="{H}" rx="10" fill="#FBFAF6"/>{body}</svg>')


def _t(x: float, y: float, text: str, size: float = 10.5, color: str = INK, anchor: str = "start", weight: str = "normal") -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;")
    return f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" text-anchor="{anchor}" font-weight="{weight}">{text}</text>'


def sekat_head_rule() -> str:
    """Ground rises upstream; water steps up at every sekat; the step is dA, the spacing is dA divided by the slope."""
    def ground(x: float) -> float:
        return 118 - (x - 20) * 0.2
    xs = [20, 120, 220, 320]
    body = [f'<polyline points="20,{ground(20)} 340,{ground(340)}" stroke="{GROUND}" stroke-width="3" fill="none"/>']
    for a, b in zip(xs, xs[1:]):
        yw = ground(a) + 3                                       # water level of this reach: the ground level at its downstream sekat
        body.append(f'<line x1="{a}" y1="{yw}" x2="{b}" y2="{yw}" stroke="{WATER}" stroke-width="3"/>')
        body.append(f'<line x1="{a}" y1="{yw - 2}" x2="{a}" y2="{yw + 16}" stroke="{AMBER}" stroke-width="5"/>')
    body.append(f'<line x1="320" y1="{ground(320) + 1}" x2="320" y2="{ground(320) + 16}" stroke="{AMBER}" stroke-width="5"/>')
    # dA: ground above the water at the upstream end of the first reach
    gx = 118
    g, w = ground(gx), ground(20) + 3
    body.append(f'<line x1="{gx}" y1="{g}" x2="{gx}" y2="{w}" stroke="{RED}" stroke-width="1.6" stroke-dasharray="3 2"/>')
    body.append(_t(gx - 6, (g + w) / 2 + 3, "dA", 11, RED, "end", "600"))
    # js between two sekat
    body.append(f'<line x1="20" y1="148" x2="120" y2="148" stroke="{TEAL}" stroke-width="1.6"/>'
                f'<line x1="20" y1="143" x2="20" y2="153" stroke="{TEAL}"/><line x1="120" y1="143" x2="120" y2="153" stroke="{TEAL}"/>')
    body.append(_t(70, 163, tr("spacing = dA / slope"), 10.5, TEAL, "middle", "600"))
    body.append(_t(18, 20, tr("Each reach holds water at most dA below the ground."), 10.5, INK, "start", "600"))
    body.append(_t(18, 35, tr("Steeper land needs sekat closer together."), 10, MUTED))
    body.append(_t(338, 100 - 78, tr("ground"), 10, GROUND, "end"))
    body.append(_t(190, 136 - 19, tr("canal water"), 10, WATER, "middle"))
    body.append(_t(122, ground(20) + 33, tr("sekat"), 10, "#7A4300", "start"))
    return _svg("".join(body))


def moisture_ring() -> str:
    """Plan view: canal water is not read; the ring on both sides is."""
    cy, inner, outer = 98, 12, 54                            # the real distances are set under Advanced settings
    body = [f'<rect x="20" y="{cy - outer}" width="340" height="{2 * outer}" rx="4" fill="#F6DDB0"/>',
            f'<rect x="20" y="{cy - inner}" width="340" height="{2 * inner}" fill="#FBFAF6"/>',
            f'<rect x="20" y="{cy - 7}" width="340" height="14" fill="{WATER}"/>']
    body.append(_t(190, cy + 4, tr("canal water: not read"), 10, "#FFFFFF", "middle", "600"))
    body.append(_t(190, cy - inner - 12, tr("ring: dryness is read here"), 10.5, "#7A4300", "middle", "600"))
    body.append(_t(190, cy + inner + 22, tr("ring: dryness is read here"), 10.5, "#7A4300", "middle", "600"))
    body.append(_t(18, 20, tr("The moisture index is averaged inside the ring,"), 10.5, INK, "start", "600"))
    body.append(_t(18, 35, tr("not over the canal water itself."), 10.5, INK, "start", "600"))
    body.append(_t(18, 166, tr("The inner and outer distance are in the Advanced settings of this stage."), 9.5, MUTED))
    return _svg("".join(body))


def route_cost() -> str:
    """Two ways from the river to a target: short but uphill, or long and almost flat."""
    sx, sy, tx, ty = 36, 132, 340, 52
    body = [f'<polyline points="{sx},{sy} {sx + 20},{sy - 4} {tx - 70},{ty + 16} {tx},{ty}" stroke="{AMBER}" stroke-width="3.5" fill="none" stroke-dasharray="7 4"/>',
            f'<polyline points="{sx},{sy} {tx - 20},{sy} {tx - 20},{ty + 4} {tx},{ty}" stroke="{TEAL}" stroke-width="3.5" fill="none"/>',
            f'<circle cx="{sx}" cy="{sy}" r="7" fill="{WATER}" stroke="{INK}"/><path d="M{tx},{ty - 9} l9,16 h-18 z" fill="#2E9E7B" stroke="{INK}"/>']
    body.append(_t(sx, sy + 20, tr("river"), 10, INK))
    body.append(_t(tx - 4, ty - 14, tr("target"), 10, INK, "end"))
    body.append(_t(150, 82, tr("short, but it climbs"), 10.5, "#7A4300", "middle", "600"))
    body.append(_t(190, sy - 7, tr("longer, but almost flat"), 10.5, TEAL, "middle", "600"))
    body.append(_t(18, 20, tr("cost = length + lambda x lift"), 11.5, INK, "start", "700"))
    body.append(_t(18, 36, tr("A large lambda prefers the flat route: lifting water costs pumping energy."), 10, MUTED))
    return _svg("".join(body))


DIAGRAMS = {6: moisture_ring, 7: sekat_head_rule, 9: route_cost}


def svg_for(stage: int) -> Optional[str]:
    fn = DIAGRAMS.get(stage)
    return fn() if fn else None
