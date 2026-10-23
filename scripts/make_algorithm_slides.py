"""Generate three technical slides (Bahasa Indonesia, 1920x1080 SVG) into docs/diagrams/:

  algoritma_1_alur_data.svg      all 11 stages: analyses and data flow
  algoritma_2_sekat_skoring.svg  land profile, sekat placement, need scoring
  algoritma_3_routing_pompa.svg  network routing (Steiner) and pump sizing

Colour scheme: navy + orange titles, blue-gradient card headers, green-blue chips, orange output chips, orange chevrons.
Export PNG by opening an SVG in a browser and screenshotting at 1920x1080, or insert the SVG into PowerPoint.
"""
import xml.etree.ElementTree as ET
from html import escape
from pathlib import Path

W, H = 1920, 1080
NAVY, ORANGE, TXT, MUTED = "#12406b", "#f26522", "#16324f", "#5f7389"
CARD, CARD_LINE, CHEV = "#f3f6fb", "#dce5f1", "#f7941d"
BLUE, GREEN, RED, GREY = "#2979f2", "#08a67a", "#d9363e", "#9aa6a0"
FONT = "Plus Jakarta Sans, Poppins, Segoe UI, Calibri, Arial, sans-serif"
OUT = Path(__file__).resolve().parents[1] / "docs" / "diagrams"


def t(x, y, s, size=18, weight=400, fill=TXT, anchor="start", italic=False, mono=False, opacity=None):
    st = ' font-style="italic"' if italic else ""
    ff = ' font-family="Consolas, Menlo, monospace"' if mono else ""
    op = f' fill-opacity="{opacity}"' if opacity else ""
    return f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}"{st}{ff}{op}>{escape(s)}</text>'


def rect(x, y, w, h, fill, stroke=None, sw=2, rx=12, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    s = f' stroke="{stroke}" stroke-width="{sw}"' if stroke else ""
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}"{s}{d}/>'


def circle(cx, cy, r, fill, stroke=None, sw=2):
    s = f' stroke="{stroke}" stroke-width="{sw}"' if stroke else ""
    return f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{fill}"{s}/>'


def line(x1, y1, x2, y2, color=MUTED, w=2, dash=None, arrow=False):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    m = f' marker-end="url(#m{color[1:]})"' if arrow else ""
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{w}"{d}{m}/>'


def poly(points, color=MUTED, w=2, dash=None, arrow=False, fill="none"):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    m = f' marker-end="url(#m{color[1:]})"' if arrow else ""
    p = " ".join(f"{x},{y}" for x, y in points)
    return f'<polyline points="{p}" fill="{fill}" stroke="{color}" stroke-width="{w}"{d}{m} stroke-linejoin="round"/>'


def chip(x, y, w, h, kind="g", rx=None):
    """Gradient chip: g = green-blue, o = orange, b = blue."""
    return rect(x, y, w, h, {"g": "url(#gChip)", "o": "url(#gOrange)", "b": "url(#gBlue)"}[kind], None, 0, rx if rx is not None else min(h / 2, 18))


def chevron(cx, cy, w=22, h=56):
    x0, y0 = cx - w / 2, cy - h / 2
    pts = [(x0, y0), (x0 + w * 0.5, y0), (x0 + w, cy), (x0 + w * 0.5, y0 + h), (x0, y0 + h), (x0 + w * 0.5, cy)]
    return f'<polygon points="{" ".join(f"{a:.1f},{b:.1f}" for a, b in pts)}" fill="{CHEV}"/>'


def card(x, y, w, h, title, hh=46, rx=22, title_x=None):
    s = rect(x, y, w, h, CARD, CARD_LINE, 2, rx)
    s += (f'<path d="M{x} {y + hh}V{y + rx}a{rx} {rx} 0 0 1 {rx} -{rx}H{x + w - rx}a{rx} {rx} 0 0 1 {rx} {rx}V{y + hh}Z" fill="url(#gBlue)"/>')
    s += t(title_x if title_x is not None else x + 22, y + hh / 2 + 8, title, 22, 700, "#ffffff")
    return s


def defs():
    cols = (NAVY, ORANGE, GREEN, BLUE, RED, MUTED, GREY, CHEV)
    mk = "".join(f'<marker id="m{c[1:]}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10z" fill="{c}"/></marker>' for c in cols)
    gr = ('<linearGradient id="gBlue" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#2979f2"/><stop offset="1" stop-color="#153e6a"/></linearGradient>'
          '<linearGradient id="gChip" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#08a67a"/><stop offset="1" stop-color="#2279ee"/></linearGradient>'
          '<linearGradient id="gOrange" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ffb300"/><stop offset="1" stop-color="#f26522"/></linearGradient>')
    return f"<defs>{mk}{gr}</defs>"


def banner(text):
    return chip(50, 1010, 1820, 50, "b", 25) + t(960, 1042, text, 22, 700, "#ffffff", "middle")


def slide(title_a, title_b, body, msg, footer="RE-PEAT  ·  KLH  ·  Departemen Teknik Geodesi UGM"):
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="{FONT}" role="img" aria-label="{escape(title_a + title_b)}">'
           + defs() + rect(0, 0, W, H, "#ffffff", rx=0)
           + f'<text x="50" y="84" font-size="52" font-weight="800" fill="{NAVY}">{escape(title_a)}<tspan fill="{ORANGE}">{escape(title_b)}</tspan></text>'
           + "".join(body) + banner(msg) + t(1870, 1076, footer, 14, 400, MUTED, "end") + "</svg>")
    ET.fromstring(svg)
    return svg


# =============================================================================== SLIDE 1
def slide1():
    g = []
    bw, bh, gx, gy = 420, 262, 40, 40
    xs = [50 + i * (bw + gx) for i in range(4)]
    ys = [125 + j * (bh + gy) for j in range(3)]
    HH = 54
    stages = [
        None,
        (1, "Muat dan validasi", False, ["Tolak DSM; CRS semua layer harus sama (m)", "Parse \"2x\" → 2 dan \"3,0 - 4,0 meter\" → 3–4", "Pilih sub-KHG (peringkat), clip + margin"],
         ["inputs_clipped_*, DTM dan", "kelembapan terpotong"]),
        (2, "Topologi kanal", True, ["Filter kelas kanal (opsional: primer, sekunder)", "Terapkan sunting kanal (tambah / hapus)", "Snap ujung → noding di persimpangan", "Hapus duplikat; pangkas overshoot (opsional)", "Cek konektivitas tiap kanal ke sungai"],
         ["canals_clean, qa_topology_*"]),
        (3, "Kondisioning hidrologi", False, ["Burning kanal pada SALINAN DTM", "Breach least-cost + fill (WhiteboxTools)", "Akumulasi aliran D-infinity / MFD / D8"],
         ["dtm_conditioned.tif, flow_acc.tif", "(hanya untuk aliran, bukan tinggi)"]),
        (4, "Segmentasi", False, ["Potong kanal ≤ 500 m dari ujung awal", "seg_id stabil: urut canal_id lalu posisi", "Segmen < 25 m → status_mcda = 0"],
         ["canal_segments"]),
        (5, "Profil lahan dan arah aliran", False, ["Sampel DTM ASLI di offset ±6 dan ±10 m", "Median antar offset → median filter 50 m", "Kemiringan = gradien profil memanjang", "Hilir dari tren profil; datar → jarak ke sungai"],
         ["canal_profiles, z_hulu / z_hilir,", "i_lahan, arah per kanal"]),
        (6, "Prioritas kebutuhan", True, ["Kekeringan: rata-rata cincin 15–100 m", "Hulu: log(maks flow acc) dalam buffer", "Min–max → bobot (langsung / AHP) → skor", "Mode KLH: skor 1–3 per kriteria, total ≥ ambang", "Konsesi = filter SETELAH skor"],
         ["need_score, need_rank, selected,", "qa_sensitivity"]),
        (7, "Sekat: celah dan penempatan", False, ["n_perlu = ceil((z_hulu − z_hilir) / dA)", "IPG = n_eksisting / n_perlu", "Sekat baru tiap lahan naik dA (hilir → hulu)", "Duplikat dibuang; sunting tambah / hapus", "ts = dk + js·tanα − dA, dihitung ulang"],
         ["sekat_proposed,", "sekat_existing_assessed"]),
        (8, "Graf jaringan", False, ["Node: ujung segmen, sekat, titik sungai", "Edge dua arah (z_dari, z_ke, Δz)", "Ruas dipecah di titik sekat dan sungai"],
         ["network_nodes, network_edges"]),
        (9, "Sumber, target, rute", True, ["Sumber: sungai–kanal (buffer 30 m) + manual", "Target: node tertinggi tiap klaster terpilih", "Biaya = panjang + λ·max(0, Δz)", "Steiner (Takahashi–Matsuyama), super-source", "Sekat eksisting tanpa pintu = penghalang"],
         ["pump_routes, pump_targets,", "qa_unreachable_targets"]),
        (10, "Kebutuhan air dan pompa", False, ["V = defisit × luas gambut terlayani", "Q = V / (hari × 86400)", "H = H_statik + Σ h_f (Manning / Hazen-Williams)", "Stasiun tiap H > H maks; P = ρ·g·Q·H / η"],
         ["pump_stations, gates_required"]),
        (11, "Laporan", False, ["Peringatan, akurasi DTM, IPG per kanal", "Bobot dan sensitivitas, ringkasan rute", "Tabel pompa; parameter yang masih null"],
         ["run_report.md / run_report.json"]),
    ]
    # slot 0: input data (green-blue chips)
    x, y = xs[0], ys[0]
    g.append(card(x, y, bw, bh, "Data masukan", HH))
    ins = [("DTM bare-earth", "Sub-KHG + prioritas"), ("Kanal", "Sunting kanal (ops.)"), ("Sekat eksisting", "Sungai"), ("Terbakar* + gambut", "Kelembapan*, konsesi")]
    for r, (a, b) in enumerate(ins):
        for c, lab in enumerate((a, b)):
            cx_, cy_ = x + 14 + c * 198, y + HH + 12 + r * 36
            g.append(chip(cx_, cy_, 190, 30, "g"))
            g.append(t(cx_ + 95, cy_ + 20, lab, 15.5, 700, "#fff", "middle"))
    g.append(t(x + 16, y + HH + 12 + 4 * 36 + 10, "* bisa diambil dari cloud (MODIS, Sentinel-2 / GEE)", 13.5, 500, MUTED))
    g.append(rect(x + 14, y + bh - 36, bw - 28, 28, "#ffffff", ORANGE, 2, 14, "7 5"))
    g.append(t(x + bw / 2, y + bh - 17, "+ config.yaml: nilai kebijakan dari tim", 16, 700, ORANGE, "middle"))
    for idx, st in enumerate(stages):
        if st is None:
            continue
        n, title, review, bullets, outs = st
        x, y = xs[idx % 4], ys[idx // 4]
        g.append(card(x, y, bw, bh, title, HH, title_x=x + 56))
        g.append(circle(x + 30, y + HH / 2, 16, "#ffffff") + t(x + 30, y + HH / 2 + 6, str(n), 17, 800, NAVY, "middle"))
        if review:
            g.append(rect(x + bw - 92, y + 13, 78, 28, ORANGE, "#fff", 2, 14))
            g.append(t(x + bw - 53, y + 33, "tinjau", 15, 800, "#fff", "middle"))
        yy = y + HH + 28
        for b in bullets:
            g.append(circle(x + 24, yy - 5, 3.8, ORANGE))
            g.append(t(x + 36, yy, b, 16.5, 500))
            yy += 25
        ch_h = 14 + 19 * len(outs)
        cy_ = y + bh - ch_h - 12
        g.append(chip(x + 14, cy_, bw - 28, ch_h, "o", 14))
        for k, o in enumerate(outs):
            g.append(t(x + 28, cy_ + 20 + k * 19, ("Keluar: " if k == 0 else "          ") + o, 15, 700, "#fff"))
    # chevrons and row wraps
    for j in range(3):
        for i in range(3):
            g.append(chevron(xs[i] + bw + gx / 2, ys[j] + bh / 2))
    for j in range(2):
        cx_end, cx_start = xs[3] + bw / 2, xs[0] + bw / 2
        yb = ys[j] + bh
        g.append(poly([(cx_end, yb + 2), (cx_end, yb + gy / 2), (cx_start, yb + gy / 2), (cx_start, ys[j + 1] - 4)], CHEV, 5, arrow=True))
    return slide("Alur analisis SIG dan data: ", "11 tahap + 1 opsional", g,
                 "Tiap tahap membaca layer tahap sebelumnya dari satu GeoPackage; \"tinjau\" berhenti sampai disetujui. Tahap 12 (optimasi blok) opsional.")


# =============================================================================== SLIDE 2
def slide2():
    g = []
    # ---------- panel A: cross-section
    ax, ay, aw, ah = 50, 125, 640, 340
    g.append(card(ax, ay, aw, ah, "A. Profil lahan: tinggi DI TEPI kanal"))
    gy0 = ay + 205
    pts = [(ax + 40, gy0), (ax + 250, gy0), (ax + 275, gy0 + 70), (ax + 365, gy0 + 70), (ax + 390, gy0), (ax + aw - 40, gy0)]
    g.append(f'<polygon points="{" ".join(f"{x},{y}" for x, y in pts)} {ax + aw - 40},{ay + ah - 20} {ax + 40},{ay + ah - 20}" fill="#dbe9fb" opacity="0.8"/>')
    g.append(poly(pts, NAVY, 3))
    g.append(rect(ax + 276, gy0 + 38, 88, 32, "#ffffff", BLUE, 1.5, 4))
    g.append(t(ax + 320, gy0 + 60, "air / parit", 14, 600, BLUE, "middle"))
    cxm = ax + 320
    for off, lab in ((-10, "−10"), (-6, "−6"), (6, "+6"), (10, "+10")):
        px = cxm + off * 12.5
        g.append(circle(px, gy0, 7, ORANGE, "#fff", 2))
        g.append(line(px, gy0 - 8, px, gy0 - 40, ORANGE, 1.5, "4 3"))
        g.append(t(px, gy0 - 46, lab, 15, 800, ORANGE, "middle"))
    g.append(line(ax + 110, gy0 - 100, ax + 530, gy0 - 100, GREEN, 2, "9 5"))
    g.append(t(ax + aw / 2, gy0 - 108, "z_lahan = median keempat titik (offset dalam m)", 16, 700, NAVY, "middle"))
    g.append(t(ax + 22, ay + ah - 42, "Dasar kanal lebih rendah dari lahan, jadi titik tengah tidak dipakai.", 15.5, 500, MUTED))
    g.append(t(ax + 22, ay + ah - 20, "Lalu median filter 50 m sepanjang kanal; kemiringan = gradien.", 15.5, 500, MUTED))

    # ---------- panel C: scoring
    cx_, cy_, cw, ch = 50, 490, 640, 500
    g.append(card(cx_, cy_, cw, ch, "C. Skor kebutuhan per segmen"))
    crit = [("Frekuensi terbakar", "kelas terpanjang"), ("Kedalaman gambut", "titik tengah kelas"), ("Kekeringan", "rata-rata cincin 15–100 m"), ("Kontribusi hulu", "log(maks flow acc)")]
    y0c = cy_ + 62
    for i, (a, b) in enumerate(crit):
        yy = y0c + i * 52
        g.append(chip(cx_ + 18, yy, 270, 44, "g", 14))
        g.append(t(cx_ + 32, yy + 20, a, 16.5, 800, "#fff"))
        g.append(t(cx_ + 32, yy + 37, b, 13.5, 500, "#fff", opacity=0.9))
    g.append(poly([(cx_ + 290, y0c + 22), (cx_ + 320, y0c + 22), (cx_ + 320, y0c + 3 * 52 + 22), (cx_ + 290, y0c + 3 * 52 + 22)], CHEV, 3))
    g.append(chevron(cx_ + 337, y0c + 1.5 * 52 + 22, 18, 40))
    steps = [("Normalisasi min–max", "0–1, arah \"lebih tinggi = lebih buruk\""), ("Bobot", "langsung / AHP (CR ≤ 0,10) / KLH"), ("Skor = Σ bobot × nilai", "segmen status_mcda = 1 saja"),
             ("Peringkat → pilih top 20%", "mode KLH: skor ≥ ambang (dari 12)")]
    sx = cx_ + 362
    for i, (a, b) in enumerate(steps):
        yy = y0c - 4 + i * 60
        g.append(rect(sx, yy, 258, 50, "#ffffff", BLUE, 2, 14))
        g.append(t(sx + 12, yy + 22, a, 16.5, 800, NAVY))
        g.append(t(sx + 12, yy + 40, b, 13.5, 500, MUTED))
        if i < 3:
            g.append(line(sx + 129, yy + 50, sx + 129, yy + 60, CHEV, 3, arrow=True))
    g.append(rect(cx_ + 18, cy_ + 316, 604, 56, "#ffffff", ORANGE, 2, 14, "6 4"))
    g.append(t(cx_ + 32, cy_ + 340, "Konsesi: filter kelayakan SETELAH skor (exclude / flag / ignore),", 15.5, 500))
    g.append(t(cx_ + 32, cy_ + 360, "tidak pernah masuk ke dalam skor kebutuhan.", 15.5, 500))
    g.append(rect(cx_ + 18, cy_ + 382, 604, 56, "#e6f0fa", BLUE, 2, 14))
    g.append(t(cx_ + 32, cy_ + 406, "Sensitivitas: bobot diubah ±10% dan ±20% satu per satu;", 15.5, 500))
    g.append(t(cx_ + 32, cy_ + 426, "dilaporkan korelasi Spearman dan porsi top yang bertahan.", 15.5, 500))
    g.append(t(cx_ + 22, cy_ + 464, "Hasil: need_score, need_rank, selected, qa_sensitivity", 15.5, 800, NAVY))
    g.append(t(cx_ + 22, cy_ + 484, "Segmen di luar sub-KHG terpilih tidak diberi skor.", 15, 500, MUTED))

    # ---------- panel B
    bx, by, bw_, bh_ = 730, 125, 1140, 865
    g.append(card(bx, by, bw_, bh_, "B. Penempatan sekat: lahan naik sebesar dA dari sekat sebelumnya"))
    g.append(t(bx + 22, by + 72, "Contoh: lereng 1 m/km, dA = 0,40 m (PP 57/2016); dihitung dari hilir (sungai) ke hulu", 16, 500, MUTED))
    x0, y0 = bx + 90, by + 495
    sx_, sz_ = 0.54, 185
    X = lambda d: x0 + d * sx_
    Y = lambda z: y0 - (z - 2.0) * sz_
    g.append(line(x0, y0 + 20, X(1850), y0 + 20, MUTED, 2, arrow=True))
    g.append(line(x0 - 20, y0 + 10, x0 - 20, Y(3.95), MUTED, 2, arrow=True))
    g.append(t(X(1850), y0 + 50, "jarak dari hilir (m)", 15, 500, MUTED, "end"))
    g.append(t(x0 - 30, Y(3.95) - 10, "tinggi lahan z (m)", 15, 500, MUTED))
    for d in (0, 500, 1000, 1500):
        g.append(line(X(d), y0 + 20, X(d), y0 + 28, MUTED, 2) + t(X(d), y0 + 46, str(d), 14, 500, MUTED, "middle"))
    for z in (2.0, 2.4, 2.8, 3.2, 3.6):
        g.append(line(x0 - 26, Y(z), x0 - 20, Y(z), MUTED, 2) + t(x0 - 32, Y(z) + 5, f"{z:.1f}".replace(".", ","), 14, 500, MUTED, "end"))
    prof = [(X(d), Y(2.0 + 0.001 * d + (0.02 if (d // 100) % 2 else -0.02) * 0.4)) for d in range(0, 1801, 100)]
    g.append(poly(prof, NAVY, 3.5))
    g.append(t(x0, y0 + 70, "hilir (sungai)", 16, 800, BLUE))
    g.append(t(X(1800), Y(3.8) - 22, "hulu", 16, 800, MUTED, "end"))
    sek = [(300, 2.3, "eks", "E1 (tanpa pintu)"), (700, 2.7, "new", "P1"), (1000, 3.0, "eks", "E2 (berpintu)"), (1400, 3.4, "new", "P2")]
    base = [(0, 2.0), (300, 2.3), (700, 2.7), (1000, 3.0), (1400, 3.4)]
    for (d, z), nxt in zip(base, sek):
        g.append(line(X(d), Y(z), X(nxt[0]), Y(z), GREEN, 1.8, "6 4"))
        g.append(line(X(nxt[0]), Y(z), X(nxt[0]), Y(nxt[1]), GREEN, 1.8, "6 4"))
    for d, z, kind, lab in sek:
        col = GREY if kind == "eks" else GREEN
        g.append(rect(X(d) - 8, Y(z) - 46, 16, 46, col, NAVY, 1.5, 3))
        g.append(t(X(d), Y(z) - 56, lab, 15, 800, NAVY if kind == "new" else MUTED, "middle"))
    g.append(line(X(700), Y(2.3), X(790), Y(2.3), ORANGE, 1.3, "4 3"))
    g.append(line(X(700), Y(2.7), X(790), Y(2.7), ORANGE, 1.3, "4 3"))
    g.append(line(X(780), Y(2.3), X(780), Y(2.7), ORANGE, 2.5, arrow=True))
    g.append(t(X(780) + 10, Y(2.5) + 5, "dA = 0,40 m", 16, 800, ORANGE))
    g.append(t(X(300) + 6, Y(2.3) + 34, "baseline di-reset", 14, 500, MUTED))
    g.append(t(X(300) + 6, Y(2.3) + 50, "oleh sekat eksisting", 14, 500, MUTED))
    g.append(t(X(1000) + 6, Y(3.0) + 34, "reset lagi", 14, 500, MUTED))
    lx, ly = bx + 380, by + 92
    g.append(rect(lx, ly, 18, 24, GREY, NAVY, 1.5, 3) + t(lx + 28, ly + 19, "sekat eksisting (snap ke kanal)", 15, 500))
    g.append(rect(lx, ly + 32, 18, 24, GREEN, NAVY, 1.5, 3) + t(lx + 28, ly + 51, "sekat usulan", 15, 500))
    g.append(line(lx, ly + 74, lx + 18, ly + 74, GREEN, 1.8, "6 4") + t(lx + 28, ly + 80, "garis penelusuran dA", 15, 500))
    fy = by + 578
    cards = [("Jarak butuh", "js = dA / i_lahan", "dibatasi max_spacing_m"), ("Jumlah butuh", "n = ceil(Δz / dA)", "Δz = z_hulu − z_hilir, per kanal"),
             ("Kecukupan", "IPG = n_eksisting / n_butuh", "> 1 berarti memadai"), ("Tinggi sekat", "ts = dk + js·tanα − dA", "dk = kedalaman kanal")]
    cw_ = (bw_ - 40 - 3 * 14) / 4
    for i, (a, b, c) in enumerate(cards):
        x = bx + 20 + i * (cw_ + 14)
        g.append(chip(x, fy, cw_, 104, "g", 16))
        g.append(t(x + 14, fy + 28, a, 16, 800, "#fff"))
        g.append(t(x + 14, fy + 58, b, 15, 700, "#fff", mono=True))
        g.append(t(x + 14, fy + 86, c, 13.5, 500, "#fff", opacity=0.92))
    rules = ["Sekat usulan tidak dalam min_spacing_m dari sekat eksisting; duplikat dibuang.", "Sunting manual (tambah / hapus), lalu jarak dan tinggi dihitung ulang.",
             "Tipe: leaky / reinforced bila lereng ≥ 5%, selain itu standar.", "Profil memakai DTM asli; DTM hasil burning tidak pernah dipakai di sini."]
    for k, r in enumerate(rules):
        g.append(circle(bx + 30, fy + 134 + k * 26 - 5, 4, ORANGE))
        g.append(t(bx + 44, fy + 134 + k * 26, r, 16.5, 500))
    g.append(chip(bx + 20, fy + 238, bw_ - 40, 34, "o", 17))
    g.append(t(bx + 36, fy + 261, "Keluaran: sekat_proposed (jarak, tinggi, tipe), sekat_existing_assessed, IPG per kanal", 16, 800, "#fff"))
    return slide("Analisis medan, penempatan sekat, ", "dan skoring", g,
                 "Tinggi dan kemiringan selalu dari DTM asli; DTM hasil burning hanya dipakai untuk arah aliran.")


# =============================================================================== SLIDE 3
def slide3():
    g = []
    ax, ay, aw, ah = 50, 125, 1000, 865
    g.append(card(ax, ay, aw, ah, "A. Routing: dari sungai ke titik tertinggi, dengan biaya berbasis tinggi"))
    g.append(t(ax + 22, ay + 76, "Graf berarah; biaya(u→v) = panjang + λ · max(0, z_ke − z_dari)", 16, 700, NAVY, mono=True))
    OY = ay + 20
    N = {"S": (ax + 110, OY + 520, 2.0), "A": (ax + 300, OY + 520, 2.3), "B": (ax + 480, OY + 440, 2.7), "C": (ax + 680, OY + 360, 3.1),
         "T1": (ax + 860, OY + 250, 3.5), "T2": (ax + 860, OY + 450, 3.4), "D": (ax + 480, OY + 250, 3.0), "F": (ax + 300, OY + 632, 2.2), "G": (ax + 640, OY + 632, 2.3)}
    P = lambda k: (N[k][0], N[k][1])
    g.append(rect(ax + 30, OY + 310, 40, 340, "#dbe9fb", BLUE, 2, 14))
    g.append(t(ax + 50, OY + 490, "Sungai", 17, 800, BLUE, "middle").replace("<text", f'<text transform="rotate(-90 {ax + 50} {OY + 490})"'))
    for a, b in (("S", "F"), ("F", "G"), ("G", "C")):
        g.append(line(*P(a), *P(b), GREY, 3))
    g.append(t((P("S")[0] + P("F")[0]) / 2 + 22, (P("S")[1] + P("F")[1]) / 2 - 6, "datar tapi panjang", 14, 500, MUTED))
    g.append(line(*P("B"), *P("D"), GREY, 3, "8 6"))
    g.append(line(*P("D"), *P("T1"), GREY, 3, "8 6"))
    bx_, by_ = (P("B")[0] + P("D")[0]) / 2, (P("B")[1] + P("D")[1]) / 2
    g.append(rect(bx_ - 14, by_ - 14, 28, 28, "#fff", RED, 3, 4))
    g.append(line(bx_ - 9, by_ - 9, bx_ + 9, by_ + 9, RED, 3) + line(bx_ - 9, by_ + 9, bx_ + 9, by_ - 9, RED, 3))
    g.append(t(bx_ - 24, by_ - 4, "sekat eksisting TANPA pintu", 15, 800, RED, "end"))
    g.append(t(bx_ - 24, by_ + 14, "= penghalang, aliran tidak lewat", 14, 500, RED, "end"))
    for a, b in (("S", "A"), ("A", "B"), ("B", "C"), ("C", "T1"), ("C", "T2")):
        g.append(line(*P(a), *P(b), GREEN, 7))
    mx, my = (P("A")[0] + P("B")[0]) / 2, (P("A")[1] + P("B")[1]) / 2
    g.append(rect(mx - 11, my - 11, 22, 22, "#d7f2ea", NAVY, 2.5, 3))
    g.append(t(mx + 16, my + 40, "sekat usulan: tidak menghalang,", 14, 600, NAVY))
    g.append(t(mx + 16, my + 56, "masuk daftar pintu (gates_required)", 14, 600, NAVY))
    for k, (x, y, z) in N.items():
        zl = f"z = {str(z).replace('.', ',')}"
        if k == "S":
            g.append(circle(x, y, 22, BLUE, "#fff", 3) + t(x, y + 6, "S", 17, 800, "#fff", "middle"))
        elif k in ("T1", "T2"):
            g.append(circle(x, y, 24, ORANGE, "#fff", 3) + t(x, y + 6, k, 16, 800, "#fff", "middle"))
        else:
            g.append(circle(x, y, 17, "#fff", NAVY if k in ("A", "B", "C") else GREY, 3) + t(x, y + 5, k, 14, 800, TXT, "middle"))
        if k in ("T1", "T2"):
            g.append(t(x + 32, y + 6, zl, 14, 500, MUTED))
        elif k == "B":
            g.append(t(x + 30, y + 24, zl, 14, 500, MUTED))
        else:
            g.append(t(x, y + (40 if k in ("F", "G") else -28), zl, 14, 500, MUTED, "middle"))
    g.append(circle(ax + 40, ay + 112, 11, BLUE) + t(ax + 60, ay + 118, "Sumber: titik sungai–kanal (buffer 30 m), atau ditambah manual", 16, 500))
    g.append(circle(ax + 40, ay + 144, 11, ORANGE) + t(ax + 60, ay + 150, "Target: node TERTINGGI tiap klaster terpilih (bisa diganti manual)", 16, 500))
    g.append(line(ax + 28, ay + 176, ax + 52, ay + 176, GREEN, 7) + t(ax + 60, ay + 182, "Pohon Steiner: ruas bersama dipakai ulang oleh beberapa target", 16, 500))
    g.append(line(ax + 28, ay + 208, ax + 52, ay + 208, GREY, 3) + t(ax + 60, ay + 214, "Jalur alternatif lebih mahal / terblokir", 16, 500))
    # algorithm box
    g.append(rect(ax + 16, ay + 718, aw - 32, 130, "#ffffff", BLUE, 2, 16))
    g.append(chip(ax + 28, ay + 708, 380, 28, "g", 14))
    g.append(t(ax + 42, ay + 728, "Heuristik jalur terpendek (Takahashi–Matsuyama)", 15, 800, "#fff"))
    steps = ["1. Tambahkan super-source ke semua sumber (biaya 0)", "2. Dijkstra dari pohon saat ini ke semua node", "3. Sambung target terdekat yang belum terhubung", "4. Ulangi sampai semua target terhubung atau tak terjangkau"]
    for k, s in enumerate(steps):
        g.append(t(ax + 32, ay + 764 + k * 25, s, 16.5, 500))
    g.append(t(ax + aw - 30, ay + 806, "Target tak terjangkau → qa_unreachable_targets", 15, 800, RED, "end"))
    g.append(t(ax + aw - 30, ay + 828, "alasan: sekat tanpa pintu / terputus dari sungai / tanpa jalur", 14, 500, MUTED, "end"))

    # ---------- panel B
    bx, by, bw_, bh_ = 1090, 125, 780, 865
    g.append(card(bx, by, bw_, bh_, "B. Kebutuhan air, tinggi tekan, dan stasiun pompa"))
    chain = [("Defisit", "(mm, tabel prioritas)", False), ("× luas gambut", "dalam jarak pengaruh", False), ("= V", "(m³)", True), ("÷ detik periode", "(hari × 86400)", False), ("= Q", "(m³/s)", True)]
    cw = 134
    for i, (a, b, res) in enumerate(chain):
        x = bx + 18 + i * (cw + 14)
        if res:
            g.append(chip(x, by + 62, cw, 70, "g", 16))
            g.append(t(x + cw / 2, by + 94, a, 16, 800, "#fff", "middle") + t(x + cw / 2, by + 116, b, 12.5, 500, "#fff", "middle", opacity=0.92))
        else:
            g.append(rect(x, by + 62, cw, 70, "#ffffff", CARD_LINE, 2, 16))
            g.append(t(x + cw / 2, by + 94, a, 15, 800, NAVY, "middle") + t(x + cw / 2, by + 116, b, 12.5, 500, MUTED, "middle"))
        if i < 4:
            g.append(chevron(x + cw + 7, by + 97, 10, 26))
    g.append(t(bx + 20, by + 156, "Per sub-KHG: luas = gambut ∩ buffer segmen terlayani ∩ sub-KHG; Q dijumlah antar sub-KHG.", 14.5, 500, MUTED))
    g.append(t(bx + 20, by + 184, "Stasiun dipasang di sumber, lalu setiap kali head kumulatif akan melebihi H maks (digeser ke sekat terdekat).", 14.5, 500, MUTED))

    cx0, cy0 = bx + 90, by + 480
    g.append(line(cx0, cy0 + 16, bx + bw_ - 30, cy0 + 16, MUTED, 2, arrow=True))
    g.append(line(cx0 - 14, cy0 + 8, cx0 - 14, by + 232, MUTED, 2, arrow=True))
    g.append(t(bx + bw_ - 30, cy0 + 42, "jarak sepanjang rute dari sumber", 14, 500, MUTED, "end"))
    g.append(t(cx0 - 20, by + 224, "muka air (m)", 14, 500, MUTED))
    Xr = lambda f: cx0 + f * (bw_ - 170)
    Yr = lambda z: cy0 - (z - 2.0) * 160
    levels = [(0.0, 2.0), (0.12, 2.15), (0.3, 2.45), (0.5, 2.8), (0.7, 3.05), (0.85, 3.3), (1.0, 3.55)]
    g.append(poly([(Xr(f), Yr(z)) for f, z in levels], NAVY, 3.5))
    g.append(t(Xr(0.03), Yr(3.35), "muka kolam yang diperlukan = z_lahan − dA", 14.5, 800, NAVY))
    g.append(line(Xr(0), Yr(2.0), Xr(1.0), Yr(2.0), BLUE, 2, "7 4"))
    g.append(t(Xr(0.62), Yr(2.0) - 8, "z_sumber (muka air sungai)", 14.5, 800, BLUE))
    stations = [(0.0, 2.0, 0.42, 2.58), (0.42, 2.58, 0.8, 3.18)]
    for k, (f0, z0, f1, z1) in enumerate(stations):
        g.append(line(Xr(f0), Yr(z0), Xr(f1), Yr(z0), ORANGE, 1.5, "5 4"))
        g.append(line(Xr(f1) - 6, Yr(z0), Xr(f1) - 6, Yr(z1), ORANGE, 2.5, arrow=True))
        g.append(t(Xr(f1) - 16, (Yr(z0) + Yr(z1)) / 2 + 5, f"H{k + 1}", 15, 800, ORANGE, "end"))
    for f, z, nm in ((0.0, 2.0, "PS1 (di sumber)"), (0.42, 2.58, "PS2 (di sekat terdekat)")):
        g.append(rect(Xr(f) - 12, Yr(z) - 12, 24, 24, NAVY, "#fff", 2, 5))
        g.append(t(Xr(f), Yr(z) + 5, "P", 14, 800, "#fff", "middle"))
        g.append(t(Xr(f) + (-4 if f == 0 else 22), Yr(z) + (40 if f == 0 else 34), nm, 14, 800, NAVY, "start"))
    g.append(circle(Xr(1.0), Yr(3.55), 18, ORANGE, "#fff", 3) + t(Xr(1.0), Yr(3.55) + 6, "T", 15, 800, "#fff", "middle"))
    g.append(t(Xr(1.0) - 12, Yr(3.55) - 28, "target", 15, 800, ORANGE, "end"))
    fy = by + 548
    forms = [("H total", "H = H_statik + Σ h_f", "H_statik = muka kolam target − z_sumber"),
             ("Gesekan (kanal)", "h_f = L·(n·Q / (A·R^(2/3)))²", "Manning, penampang persegi dari lebar, kedalaman"),
             ("Gesekan (pipa)", "h_f = 10,67·L·Q^1,852 / (C^1,852·D^4,87)", "Hazen–Williams"),
             ("Daya", "P = ρ·g·Q·H / η", "ρ = 1000 kg/m³, g = 9,81 m/s²")]
    for i, (a, b, c) in enumerate(forms):
        y = fy + i * 62
        g.append(chip(bx + 18, y, bw_ - 36, 54, "g", 16))
        g.append(t(bx + 34, y + 23, a, 15.5, 800, "#fff"))
        g.append(t(bx + 200, y + 23, b, 16, 700, "#fff", mono=True))
        g.append(t(bx + 200, y + 43, c, 13.5, 500, "#fff", opacity=0.92))
    g.append(chip(bx + 18, fy + 256, bw_ - 36, 50, "o", 16))
    g.append(t(bx + 34, fy + 278, "Keluaran: pump_stations (Q, H, kW, jumlah unit), gates_required,", 15.5, 800, "#fff"))
    g.append(t(bx + 34, fy + 298, "demand per rute di pump_routes. Kekurangan kapasitas dilaporkan, tidak dipotong.", 14.5, 500, "#fff", opacity=0.95))
    return slide("Routing air dan ", "pompanisasi", g,
                 "Target yang tidak terjangkau dilaporkan beserta alasannya; kekurangan kapasitas pompa dilaporkan, tidak dipotong diam-diam.")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fn in (("algoritma_1_alur_data", slide1), ("algoritma_2_sekat_skoring", slide2), ("algoritma_3_routing_pompa", slide3)):
        (OUT / f"{name}.svg").write_text(fn(), encoding="utf8")
        print("wrote", OUT / f"{name}.svg")


if __name__ == "__main__":
    main()
