# -*- coding: utf-8 -*-
"""
Routing otomatis: SEMUA titik prioritas -> muara/pintu air TERDEKAT,
menelusuri jaringan kanal (bukan garis lurus), dalam SATU kali hitung.

Cara kerja:
  - Jaringan kanal dijadikan graf (node = ujung segmen, edge = segmen).
  - Titik start dan muara disisipkan ke graf pada posisi sebenarnya di segmen
    (segmen dipecah di titik tsb), jadi rute berakhir tepat di titik.
  - networkx.multi_source_dijkstra dijalankan SEKALI dari seluruh muara.
    Hasilnya: untuk tiap titik start -> muara terdekat (menurut jarak di jaringan)
    + jalurnya. Tidak perlu N x M rute dan tidak perlu mode Batch.

Persiapan (sekali saja), di OSGeo4W Shell:
    python -m pip install networkx

Cara pakai: QGIS > Plugins > Python Console > Show Editor > buka file ini,
ubah bagian PARAMETER, lalu Run.

Prasyarat data:
  - Kanal: garis singlepart, sudah di-split di persimpangan, CRS meter (UTM),
    tanpa nilai Z (drop Z/M).
  - Titik start, muara, dan kanal memakai CRS yang sama.
"""
from collections import defaultdict

import networkx as nx
from qgis.core import (QgsProject, QgsGeometry, QgsPointXY, QgsFeature, QgsField,
                       QgsSpatialIndex, QgsVectorLayer, QgsVectorFileWriter)
from qgis.PyQt.QtCore import QVariant

# ======================= PARAMETER =======================
LAYER_KANAL = 'Kanal_split_49S'   # garis kanal (singlepart, ter-split di simpang)
LAYER_START = 'Titik_start'       # titik prioritas (mis. centroid kanal prioritas)
LAYER_MUARA = 'Centroid_kanal_urgent'       # titik pertemuan sungai-kanal / pintu air
FIELD_START = None                # nama field ID titik start (None = pakai id fitur)
FIELD_MUARA = None                # nama field ID muara (None = pakai id fitur)
PAIR_FIELD = None                 # field di layer START yang berisi ID muara tujuannya
                                  # (mis. 'HubName' hasil "Distance to nearest hub").
                                  # None = otomatis ke muara terdekat di jaringan kanal
SNAP_START = 150.0                # m, jarak maks titik start ke kanal
SNAP_MUARA = 50.0                 # m, jarak maks titik muara ke kanal
NODE_TOL = 1.0                    # m, toleransi penyamaan ujung segmen
OUT_GPKG = r'E:\GAMBUT\hasil_rute.gpkg'


def edge_cost(length, fid):
    """Biaya per segmen. Default = panjang (m).
    Contoh variasi: return length * (1 + penalti) bila ingin menghindari
    segmen tertentu (butuh lookup atribut kanal via fid)."""
    return length
# =========================================================


def get_layer(name):
    found = QgsProject.instance().mapLayersByName(name)
    if not found:
        raise Exception('Layer "%s" tidak ditemukan di project' % name)
    return found[0]


kanal, starts, muaras = get_layer(LAYER_KANAL), get_layer(LAYER_START), get_layer(LAYER_MUARA)
if not (kanal.crs() == starts.crs() == muaras.crs()):
    raise Exception('CRS kanal, start, dan muara harus sama')
crs_id = kanal.crs().authid()


def nkey(p):
    return (round(p.x() / NODE_TOL), round(p.y() / NODE_TOL))


# ---------- 1. Baca segmen kanal ----------
edges = {}  # fid -> (node_a, node_b, geometri)
n_multi = n_loop = 0
for f in kanal.getFeatures():
    g = f.geometry()
    if g.isNull():
        continue
    if g.isMultipart():
        parts = g.asMultiPolyline()
        if len(parts) != 1:
            n_multi += 1
            continue
        pl = parts[0]
    else:
        pl = g.asPolyline()
    if len(pl) < 2:
        continue
    a, b = nkey(pl[0]), nkey(pl[-1])
    if a == b:
        n_loop += 1
        continue
    edges[f.id()] = (a, b, QgsGeometry.fromPolylineXY(pl))
if n_multi:
    print('PERINGATAN: %d fitur multipart dilewati. Jalankan "Multipart to singleparts" dulu.' % n_multi)
if n_loop:
    print('Catatan: %d segmen tertutup (ujung = pangkal) dilewati.' % n_loop)
print('Segmen kanal terbaca:', len(edges))

idx = QgsSpatialIndex(kanal.getFeatures())


# ---------- 2. Tempelkan titik ke segmen terdekat ----------
def snap(layer, prefix, field, max_d, pair_field=None):
    out, labels, skipped = [], {}, 0
    pairs = {}
    for f in layer.getFeatures():
        g = f.geometry()
        if g.isNull():
            continue
        pt = g.asMultiPoint()[0] if g.isMultipart() else g.asPoint()
        gp = QgsGeometry.fromPointXY(pt)
        best = None
        for fid in idx.nearestNeighbor(pt, 3):
            if fid in edges:
                d = edges[fid][2].distance(gp)
                if best is None or d < best[1]:
                    best = (fid, d)
        if best is None or best[1] > max_d:
            skipped += 1
            continue
        along = edges[best[0]][2].lineLocatePoint(gp)
        node = (prefix, f.id())
        labels[node] = f[field] if field else f.id()
        if pair_field:
            pairs[node] = str(f[pair_field])
        out.append((best[0], along, node))
    return out, labels, skipped, pairs


start_pts, start_lbl, sk_s, start_pair = snap(starts, 's', FIELD_START, SNAP_START, PAIR_FIELD)
muara_pts, muara_lbl, sk_m, _ = snap(muaras, 'm', FIELD_MUARA, SNAP_MUARA)
print('Titik start tertempel: %d (di luar jangkauan: %d)' % (len(start_pts), sk_s))
print('Muara tertempel: %d (di luar jangkauan: %d)' % (len(muara_pts), sk_m))
if not muara_pts:
    raise Exception('Tidak ada muara yang tertempel ke kanal. Naikkan SNAP_MUARA.')

# ---------- 3. Bangun graf ----------
G = nx.Graph()


def add_seg(u, v, d0, d1, geom, fid):
    length = max(d1 - d0, 0.0)
    cost = edge_cost(length, fid)
    if G.has_edge(u, v) and G[u][v]['w'] <= cost:
        return
    sub = geom.curveSubstring(d0, d1) if length > 1e-6 else None
    G.add_edge(u, v, w=cost, length=length, geom=sub)


by_edge = defaultdict(list)
for fid, along, node in start_pts + muara_pts:
    by_edge[fid].append((along, node))

for fid, (a, b, geom) in edges.items():
    L = geom.length()
    prev, prev_d = a, 0.0
    for along, node in sorted(by_edge.get(fid, [])):
        along = min(max(along, 0.0), L)
        add_seg(prev, node, prev_d, along, geom, fid)
        prev, prev_d = node, along
    add_seg(prev, b, prev_d, L, geom, fid)

n_comp = nx.number_connected_components(G)
print('Graf: %d node, %d edge, %d komponen terhubung' % (G.number_of_nodes(), G.number_of_edges(), n_comp))
if n_comp > 50:
    print('PERINGATAN: komponen banyak -> kemungkinan jaringan belum ter-snap. '
          'Coba naikkan NODE_TOL atau jalankan v.clean (snap).')

# ---------- 4. Dijkstra ----------
if PAIR_FIELD:
    # Mode berpasangan: tiap start dirutekan ke muara yang tertulis di PAIR_FIELD
    # (satu Dijkstra per muara yang punya start).
    lbl2node = {str(l): n for n, l in muara_lbl.items()}
    groups = defaultdict(list)
    for _, _, s in start_pts:
        groups[start_pair[s]].append(s)
    dist, paths = {}, {}
    for lbl, ss in groups.items():
        mn = lbl2node.get(lbl)
        if mn is None or mn not in G:
            continue
        d, p = nx.single_source_dijkstra(G, mn, weight='w')
        for s in ss:
            if s in d:
                dist[s], paths[s] = d[s], p[s]
else:
    # Mode otomatis: SEKALI hitung dari seluruh muara, tiap start -> muara terdekat
    sources = [n for _, _, n in muara_pts if n in G]
    dist, paths = nx.multi_source_dijkstra(G, sources, weight='w')

# ---------- 5. Susun keluaran ----------
def new_layer(name, fields):
    lyr = QgsVectorLayer('MultiLineString?crs=' + crs_id, name, 'memory')
    lyr.dataProvider().addAttributes(fields)
    lyr.updateFields()
    return lyr


def as_multi(geom):
    if geom is not None and not geom.isNull() and not geom.isMultipart():
        geom.convertToMultiType()
    return geom


def merge_path(path):
    geoms = [G[u][v]['geom'] for u, v in zip(path[:-1], path[1:]) if G[u][v]['geom'] is not None]
    if not geoms:
        return None
    return as_multi(QgsGeometry.collectGeometry(geoms).mergeLines())


routes = new_layer('rute_start_ke_muara', [
    QgsField('id_start', QVariant.String), QgsField('id_muara', QVariant.String),
    QgsField('cost', QVariant.Double), QgsField('panjang_m', QVariant.Double)])
usage = defaultdict(int)
usage_muara = {}
per_muara = defaultdict(lambda: [0, 0.0])
unreachable = []
feats = []

for _, _, s in start_pts:
    if s not in dist:
        unreachable.append(start_lbl[s])
        continue
    path = paths[s]            # path[0] = muara sumber, path[-1] = titik start
    m_lbl = muara_lbl[path[0]]
    plen = sum(G[u][v]['length'] for u, v in zip(path[:-1], path[1:]))
    for u, v in zip(path[:-1], path[1:]):
        k = frozenset((u, v))
        usage[k] += 1
        usage_muara[k] = m_lbl
    per_muara[m_lbl][0] += 1
    per_muara[m_lbl][1] += plen
    geom = merge_path(path)
    if geom is None:
        continue
    ft = QgsFeature(routes.fields())
    ft.setGeometry(geom)
    ft.setAttributes([str(start_lbl[s]), str(m_lbl), float(dist[s]), float(plen)])
    feats.append(ft)
routes.dataProvider().addFeatures(feats)

# Jaringan terpakai + jumlah rute yang melewati tiap segmen (utk ketebalan garis di peta/PPT)
net = new_layer('jaringan_terpakai', [
    QgsField('n_rute', QVariant.Int), QgsField('id_muara', QVariant.String),
    QgsField('panjang_m', QVariant.Double)])
nfeats = []
for k, n in usage.items():
    u, v = tuple(k)
    g = G[u][v]['geom']
    if g is None:
        continue
    ft = QgsFeature(net.fields())
    ft.setGeometry(as_multi(QgsGeometry(g)))
    ft.setAttributes([n, str(usage_muara[k]), float(G[u][v]['length'])])
    nfeats.append(ft)
net.dataProvider().addFeatures(nfeats)

# ---------- 6. Simpan & tampilkan ----------
def save(layer, name, first):
    opt = QgsVectorFileWriter.SaveVectorOptions()
    opt.driverName = 'GPKG'
    opt.layerName = name
    opt.actionOnExistingFile = (QgsVectorFileWriter.CreateOrOverwriteFile if first
                                else QgsVectorFileWriter.CreateOrOverwriteLayer)
    res = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer, OUT_GPKG, QgsProject.instance().transformContext(), opt)
    if res[0] != QgsVectorFileWriter.NoError:
        print('Gagal simpan %s: %s' % (name, res[1]))
        return
    QgsProject.instance().addMapLayer(
        QgsVectorLayer('%s|layername=%s' % (OUT_GPKG, name), name, 'ogr'))


save(routes, 'rute_start_ke_muara', True)
save(net, 'jaringan_terpakai', False)

print('\n===== RINGKASAN =====')
print('Rute dibuat: %d | tidak terjangkau (beda komponen jaringan): %d' % (len(feats), len(unreachable)))
if unreachable:
    print('ID start tidak terjangkau (maks 20):', unreachable[:20])
print('Muara dipakai: %d dari %d' % (len(per_muara), len(muara_pts)))
print('10 muara dengan titik terbanyak:')
for m, (n, tot) in sorted(per_muara.items(), key=lambda x: -x[1][0])[:10]:
    print('  muara %s: %d titik, total rute %.0f m' % (m, n, tot))
print('Hasil tersimpan di', OUT_GPKG)