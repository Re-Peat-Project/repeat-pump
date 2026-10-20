# -*- coding: utf-8 -*-
"""
Metode KLH (versi 2): sekat = perpotongan kanal x kontur 0,5 m, jarak antar sekat >= JARAK_MIN
SEPANJANG JARINGAN KANAL, slope >= SLOPE_MIN_PCT menentukan tipe (atau menyaring).

Syarat: jalankan dulu rute_kanal_multisource.py di Python Console YANG SAMA
(skrip ini memakai G, paths, start_pts, dst. dari console).

Langkah:
  1. Cari perpotongan kanal x kontur pada ruas yang dipakai rute.
  2. Per rute (dari muara ke hulu):
       a. batalkan osilasi: dua perpotongan berurutan dari kontur level SAMA dalam OSC_DIST
          meter dianggap kontur yang menyusuri kanal (penurunan bersih ~0);
       b. pilih perpotongan pertama, lalu berikutnya hanya yang >= JARAK_MIN dari sekat terakhir
          (jarak sepanjang kanal); opsional hanya yang slope-nya >= SLOPE_MIN_PCT.
  3. Saring GLOBAL: urutkan dari yang terdekat muara; terima titik hanya bila jarak jaringannya ke
     semua titik yang sudah diterima >= JARAK_MIN (menutup konflik antar muara / antar rute).
"""
import math
from statistics import median

import networkx as nx
from qgis.core import (QgsGeometry, QgsPointXY, QgsFeature, QgsField, QgsSpatialIndex,
                       QgsVectorLayer, QgsWkbTypes)
from qgis.PyQt.QtCore import QVariant

# ======================= PARAMETER =======================
LAYER_KONTUR = 'Kontur_KHG_Kahseb_49S'   # garis kontur 0,5 m (CRS sama dengan kanal)
FIELD_ELEV = 'ELEV'             # field elevasi kontur (mis. 'ELEV'); dipakai utk mendeteksi osilasi
JARAK_MIN = 500.0             # m, jarak minimum antar sekat SEPANJANG KANAL
ANGLE_MIN = 30.0              # derajat; perpotongan bersudut lebih kecil (kontur sejajar) diabaikan
OSC_DIST = 300.0              # m; 2 perpotongan berurutan kontur level sama <= jarak ini dibatalkan
                              # (0 = nonaktif)
DEDUP_TOL = 50.0              # m, titik antar rute yang lebih dekat dari ini digabung
LAYER_SLOPE = 'Slope'            # raster slope (dari DTM_Smooth), mis. 'Slope_pct'. None = tanpa slope
SLOPE_UNIT = 'persen'         # 'persen' atau 'derajat'
SLOPE_MIN_PCT = 5.0           # %, ambang slope
SLOPE_MODE = 'tandai'         # 'tandai' = hanya tentukan tipe_sekat | 'filter' = sekat hanya bila >= ambang
SLOPE_OFFSETS = [6.0, 10.0]   # m dari sumbu kanal (kiri & kanan), di luar parit
SLOPE_ALONG = [-40, -20, 0, 20, 40]   # m sepanjang kanal di sekitar titik
# =========================================================

_need = ['G', 'paths', 'dist', 'start_pts', 'start_lbl', 'muara_lbl', 'pt_of', 'node_xy',
         'crs_id', 'save', 'get_layer']
_missing = [n for n in _need if n not in globals()]
if _missing:
    raise Exception('Jalankan rute_kanal_multisource.py dulu di console yang sama. '
                    'Variabel belum ada: %s' % ', '.join(_missing))

route_starts = [n for _, _, n in start_pts if n in dist and n in paths and len(paths[n]) > 1]
print('Rute yang diproses:', len(route_starts))


def tangent(g, a, L, h=3.0):
    p0 = g.interpolate(max(a - h, 0.0)).asPoint()
    p1 = g.interpolate(min(a + h, L)).asPoint()
    dx, dy = p1.x() - p0.x(), p1.y() - p0.y()
    n = math.hypot(dx, dy)
    return (dx / n, dy / n) if n > 1e-9 else (1.0, 0.0)


def orient(g, cur):
    pts = g.asMultiPolyline()[0] if g.isMultipart() else g.asPolyline()
    d0 = (cur.x() - pts[0].x()) ** 2 + (cur.y() - pts[0].y()) ** 2
    d1 = (cur.x() - pts[-1].x()) ** 2 + (cur.y() - pts[-1].y()) ** 2
    if d0 > d1:
        pts = list(reversed(pts))
        g = QgsGeometry.fromPolylineXY(pts)
    return g, pts[-1]


# ---------- slope (opsional) ----------
sdp = None
if LAYER_SLOPE:
    sl = get_layer(LAYER_SLOPE)
    if sl.crs().authid() != crs_id:
        raise Exception('CRS raster slope (%s) beda dari kanal (%s)' % (sl.crs().authid(), crs_id))
    sdp = sl.dataProvider()
scache = {}


def slope_at(g, a, L):
    """Median slope (%) di kedua sisi kanal di sekitar posisi a (bukan di parit)."""
    if sdp is None:
        return None
    p = g.interpolate(a).asPoint()
    key = (round(p.x(), 1), round(p.y(), 1))
    if key in scache:
        return scache[key]
    vals = []
    for da in SLOPE_ALONG:
        aa = a + da
        if aa < 0 or aa > L:
            continue
        pc = g.interpolate(aa).asPoint()
        tx, ty = tangent(g, aa, L)
        nx_, ny_ = -ty, tx
        for off in SLOPE_OFFSETS:
            for sgn in (-1, 1):
                v, ok = sdp.sample(QgsPointXY(pc.x() + sgn * off * nx_, pc.y() + sgn * off * ny_), 1)
                if ok and v == v:
                    vals.append(math.tan(math.radians(v)) * 100.0 if SLOPE_UNIT == 'derajat' else v)
    z = median(vals) if vals else None
    scache[key] = z
    return z


# ---------- 1. perpotongan kanal x kontur pada ruas yang dipakai ----------
kont = get_layer(LAYER_KONTUR)
kt = QgsWkbTypes.displayString(kont.wkbType())
print('Kontur: layer "%s" | %d fitur | tipe %s | CRS %s | CRS kanal %s'
      % (kont.name(), kont.featureCount(), kt, kont.crs().authid(), crs_id))
if kont.featureCount() == 0:
    raise Exception('Layer kontur kosong.')
if kont.crs().authid() != crs_id:
    raise Exception('CRS kontur (%s) beda dari kanal (%s). Jalankan "Reproject layer" pada kontur ke %s, '
                    'lalu ulangi.' % (kont.crs().authid(), crs_id, crs_id))
if 'Line' not in kt:
    raise Exception('Kontur bertipe %s, harus GARIS (LineString). Kalau poligon, ubah dulu dengan '
                    '"Polygons to lines".' % kt)
kidx = QgsSpatialIndex(kont.getFeatures())
kfeat = {f.id(): f for f in kont.getFeatures()}
edge_cross = {}          # frozenset(u,v) -> [(QgsPointXY, elev, sudut, id_kontur)]
n_raw = n_keep_angle = n_bbox = 0
for s in route_starts:
    pth = paths[s]
    for u, v in zip(pth[:-1], pth[1:]):
        k = frozenset((u, v))
        if k in edge_cross:
            continue
        edge_cross[k] = []
        g = G[u][v]['geom']
        if g is None:
            continue
        L = g.length()
        for kid in kidx.intersects(g.boundingBox()):
            n_bbox += 1
            kf = kfeat.get(kid)
            if kf is None:
                continue
            kg = kf.geometry()
            ig = g.intersection(kg)
            if ig.isNull() or ig.isEmpty():
                continue
            cps = [part.asPoint() for part in ig.asGeometryCollection()
                   if 'Point' in QgsWkbTypes.displayString(part.wkbType())]
            for cp in cps:
                n_raw += 1
                gp = QgsGeometry.fromPointXY(cp)
                t1 = tangent(g, g.lineLocatePoint(gp), L)
                t2 = tangent(kg, kg.lineLocatePoint(gp), kg.length())
                ang = math.degrees(math.acos(min(1.0, abs(t1[0] * t2[0] + t1[1] * t2[1]))))
                if ang >= ANGLE_MIN:
                    n_keep_angle += 1
                    elev = kf[FIELD_ELEV] if FIELD_ELEV else None
                    edge_cross[k].append((cp, elev, ang, kid))
print('Perpotongan kanal x kontur: %d (lolos filter sudut >= %.0f derajat: %d)'
      % (n_raw, ANGLE_MIN, n_keep_angle))
if n_raw == 0:
    print('\nDIAGNOSIS: 0 perpotongan')
    print('  ruas kanal terpakai: %d | pasangan (ruas, kontur) yang kotak pembatasnya beririsan: %d'
          % (len(edge_cross), n_bbox))
    if n_bbox == 0:
        print('  -> Tidak ada kontur di dekat jaringan terpakai. Cek cakupan layer kontur (extent) '
              'dan apakah layer yang dipilih benar.')
    else:
        print('  -> Kontur ada di dekat kanal tapi tidak ada titik potong. Cek apakah kontur berupa garis '
              'tunggal dan geometri kanal valid.')
    raise Exception('Tidak ada perpotongan kanal x kontur. Lihat DIAGNOSIS di atas.')

# ---------- 2. saring per rute dari muara ----------
cand_sekat = []
aidx, apts = QgsSpatialIndex(), {}
n_osc = 0
for s in route_starts:
    path = paths[s]
    root = path[0]
    cur = pt_of.get(root, node_xy.get(root))
    if cur is None:
        continue
    cands, ch0 = [], 0.0
    for u, v in zip(path[:-1], path[1:]):
        g = G[u][v]['geom']
        if g is None:
            continue
        g, endp = orient(g, cur)
        L = g.length()
        for cp, elev, ang, kid in edge_cross.get(frozenset((u, v)), []):
            a = g.lineLocatePoint(QgsGeometry.fromPointXY(cp))
            cands.append(dict(ch=ch0 + a, cp=cp, elev=elev, ang=ang, kid=kid,
                              eu=u, ev=v, ea=a, eL=L, g=g))
        ch0 += L
        cur = endp
    cands.sort(key=lambda c: c['ch'])

    # a. batalkan osilasi (kontur level sama memotong kanal bolak-balik berdekatan)
    if OSC_DIST > 0:
        kept, i = [], 0
        while i < len(cands):
            c = cands[i]
            if i + 1 < len(cands):
                d2 = cands[i + 1]
                same = (c['elev'] == d2['elev']) if c['elev'] is not None else (c['kid'] == d2['kid'])
                if same and d2['ch'] - c['ch'] <= OSC_DIST:
                    n_osc += 2
                    i += 2
                    continue
            kept.append(c)
            i += 1
        cands = kept

    # b. jarak minimum sepanjang kanal (+ filter slope opsional)
    last_ch = None
    for c in cands:
        if last_ch is not None and c['ch'] - last_ch < JARAK_MIN:
            continue
        sp = slope_at(c['g'], c['ea'], c['eL'])
        if SLOPE_MODE == 'filter' and sdp is not None and (sp is None or sp < SLOPE_MIN_PCT):
            continue
        d_prev = c['ch'] if last_ch is None else c['ch'] - last_ch
        last_ch = c['ch']
        cp = c['cp']
        if cand_sekat:
            near = aidx.nearestNeighbor(cp, 1)
            if near:
                q = apts[near[0]]
                if math.hypot(cp.x() - q.x(), cp.y() - q.y()) < DEDUP_TOL:
                    continue
        i_new = len(cand_sekat)
        ft = QgsFeature()
        ft.setId(i_new)
        ft.setGeometry(QgsGeometry.fromPointXY(cp))
        aidx.addFeature(ft)
        apts[i_new] = cp
        cand_sekat.append(dict(pt=cp, ch=c['ch'], d_prev=d_prev, elev=c['elev'], ang=c['ang'],
                               slope=sp, muara=muara_lbl[path[0]], start=start_lbl[s],
                               eu=c['eu'], ev=c['ev'], ea=c['ea'], eL=c['eL']))
print('Setelah penyaringan per rute: %d titik (osilasi dibatalkan: %d perpotongan)' % (len(cand_sekat), n_osc))

# ---------- 3. saring GLOBAL: jarak jaringan antar semua sekat >= JARAK_MIN ----------
dcache = {}


def node_dists(n):
    if n not in dcache:
        dcache[n] = nx.single_source_dijkstra_path_length(G, n, cutoff=JARAK_MIN, weight='length')
    return dcache[n]


def net_dist(A, B):
    if frozenset((A['eu'], A['ev'])) == frozenset((B['eu'], B['ev'])):
        bB = B['ea'] if B['eu'] == A['eu'] else B['eL'] - B['ea']
        return abs(A['ea'] - bB)
    best = float('inf')
    for nA, dA in ((A['eu'], A['ea']), (A['ev'], A['eL'] - A['ea'])):
        dd = node_dists(nA)
        for nB, dB in ((B['eu'], B['ea']), (B['ev'], B['eL'] - B['ea'])):
            if nB in dd:
                best = min(best, dA + dd[nB] + dB)
    return best


order = sorted(range(len(cand_sekat)), key=lambda i: cand_sekat[i]['ch'])
sekat = []
gidx, gpts = QgsSpatialIndex(), {}
n_drop_global = 0
for i in order:
    r = cand_sekat[i]
    ok = True
    for j in gidx.nearestNeighbor(r['pt'], 50, JARAK_MIN):
        if net_dist(r, sekat[j]) < JARAK_MIN:
            ok = False
            break
    if not ok:
        n_drop_global += 1
        continue
    ft = QgsFeature()
    ft.setId(len(sekat))
    ft.setGeometry(QgsGeometry.fromPointXY(r['pt']))
    gidx.addFeature(ft)
    sekat.append(r)
print('Penyaringan global (jarak jaringan >= %.0f m): %d titik dibuang -> %d sekat final'
      % (JARAK_MIN, n_drop_global, len(sekat)))

# ---------- 4. keluaran ----------
lyr = QgsVectorLayer('Point?crs=' + crs_id, 'titik_sekat_klh', 'memory')
lyr.dataProvider().addAttributes([
    QgsField('id_sekat', QVariant.Int), QgsField('id_muara', QVariant.String),
    QgsField('id_start_contoh', QVariant.String), QgsField('jarak_muara_m', QVariant.Double),
    QgsField('elev_kontur', QVariant.Double), QgsField('sudut_deg', QVariant.Double),
    QgsField('slope_pct', QVariant.Double), QgsField('tipe_sekat', QVariant.String),
    QgsField('jarak_lurus_terdekat_m', QVariant.Double)])
lyr.updateFields()
feats, nn_lurus = [], []
for i, r in enumerate(sekat):
    lur = -1.0
    near = gidx.nearestNeighbor(r['pt'], 2)
    for j in near:
        if j != i:
            q = sekat[j]['pt']
            lur = math.hypot(r['pt'].x() - q.x(), r['pt'].y() - q.y())
            break
    if lur >= 0:
        nn_lurus.append(lur)
    if r['slope'] is None:
        tipe = 'tanpa_data_slope'
    else:
        tipe = 'leaky/reinforced' if r['slope'] >= SLOPE_MIN_PCT else 'standar'
    ft = QgsFeature(lyr.fields())
    ft.setGeometry(QgsGeometry.fromPointXY(r['pt']))
    ft.setAttributes([i + 1, str(r['muara']), str(r['start']), float(r['ch']),
                      float(r['elev']) if r['elev'] is not None else -9999.0, float(r['ang']),
                      float(r['slope']) if r['slope'] is not None else -9999.0, tipe, float(lur)])
    feats.append(ft)
lyr.dataProvider().addFeatures(feats)
save(lyr, 'titik_sekat_klh', False)

print('\n===== RINGKASAN (metode KLH: kontur + jarak min %.0f m sepanjang jaringan) =====' % JARAK_MIN)
print('Perpotongan (lolos sudut): %d -> per rute: %d -> final: %d sekat' % (n_keep_angle, len(cand_sekat), len(sekat)))
if nn_lurus:
    nn_lurus.sort()
    print('Jarak LURUS ke sekat terdekat: min %.0f | median %.0f m '
          '(bisa < %.0f m bila kanalnya berkelok/sejajar; jarak sepanjang kanal tetap >= %.0f m)'
          % (nn_lurus[0], nn_lurus[len(nn_lurus) // 2], JARAK_MIN, JARAK_MIN))
if sdp is not None:
    n_leaky = sum(1 for r in sekat if r['slope'] is not None and r['slope'] >= SLOPE_MIN_PCT)
    n_none = sum(1 for r in sekat if r['slope'] is None)
    print('Slope >= %.1f%% (leaky/reinforced): %d | standar: %d | tanpa data slope: %d (mode %s)'
          % (SLOPE_MIN_PCT, n_leaky, len(sekat) - n_leaky - n_none, n_none, SLOPE_MODE))