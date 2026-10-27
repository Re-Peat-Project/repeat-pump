/* RE-PEAT run report. Reads the JSON block #data written by repeat_pump.core.html_report; computes nothing new. */
(function () {
"use strict";
const D = JSON.parse(document.getElementById("data").textContent);

// ------------------------------------------------------------------ language
const ID = {
  "Rewetting plan": "Rencana pembasahan", "Map": "Peta", "Interventions": "Intervensi", "Dry-season water balance": "Neraca air musim kemarau",
  "Water held by the sekat, in order of benefit": "Air yang ditahan sekat, menurut urutan manfaat",
  "Cumulative share of the canal water-level rise of all head-rule sekat": "Bagian kumulatif kenaikan muka air kanal dari semua sekat aturan beda tinggi",
  "Interventions per sub-KHG": "Intervensi per sub-KHG", "Number of sub-KHG per treatment class": "Jumlah sub-KHG per kelas penanganan",
  "Monthly water balance": "Neraca air bulanan", "Water table at the SiTMAT stations": "Muka air tanah di stasiun SiTMAT", "Sub-KHG": "Sub-KHG",
  "Search": "Cari", "Sekat proposed": "Sekat diusulkan", "of": "dari", "head-rule sekat": "sekat aturan beda tinggi",
  "Water held": "Air yang ditahan", "of the deficit of the selected sub-KHG": "dari defisit sub-KHG terpilih",
  "Existing sekat": "Sekat yang ada", "on an analysed canal": "pada kanal yang dianalisis", "Sub-KHG analysed for sekat": "Sub-KHG dianalisis untuk sekat",
  "Neraca KHG deficit": "Defisit neraca KHG", "dry season": "musim kemarau",
  "Close or backfill canals (protected peat)": "Tutup atau timbun kanal (gambut lindung)", "Revegetation and fire readiness": "Revegetasi dan kesiagaan kebakaran",
  "Sekat and water supply": "Sekat dan pasokan air", "Sekat and deep wells": "Sekat dan sumur bor", "Sekat": "Sekat", "Maintain and monitor": "Pertahankan dan pantau",
  "Sub-KHG units": "Unit sub-KHG", "Selected sub-KHG": "Sub-KHG terpilih", "Canals": "Kanal", "primary": "primer", "secondary": "sekunder", "tertiary": "tersier",
  "flow direction unknown": "arah aliran tidak diketahui", "Sekat, kept": "Sekat, dipertahankan", "Sekat, low benefit": "Sekat, manfaat rendah",
  "Existing sekat, on an analysed canal": "Sekat yang ada, pada kanal yang dianalisis", "Existing sekat, elsewhere": "Sekat yang ada, di tempat lain",
  "SiTMAT stations": "Stasiun SiTMAT", "Flooded (above 0 m)": "Tergenang (di atas 0 m)", "Normal (0 to -0.4 m)": "Normal (0 sampai -0,4 m)",
  "At risk (-0.4 to -0.8 m)": "Rawan (-0,4 sampai -0,8 m)", "Very much at risk (below -0.8 m)": "Sangat rawan (di bawah -0,8 m)",
  "surplus": "surplus", "deficit": "defisit", "Blocks, in order of benefit": "Sekat, menurut urutan manfaat", "Share of the water held": "Bagian air yang ditahan",
  "kept": "dipertahankan", "target": "target", "blocks": "sekat", "months": "bulan", "Water balance": "Neraca air",
  "Range over all sub-KHG": "Rentang seluruh sub-KHG", "KHG mean": "Rata-rata KHG",
  "The order between sub-KHG is not stable for this KHG, so only the KHG mean is shown.": "Urutan antar sub-KHG tidak stabil untuk KHG ini, sehingga hanya rata-rata KHG yang ditampilkan.",
  "Depth below the surface at the start and the end of the dry-season window": "Kedalaman di bawah permukaan pada awal dan akhir jendela musim kemarau",
  "start": "awal", "end": "akhir", "Depth below the surface": "Kedalaman di bawah permukaan", "stations": "stasiun",
  "No neraca map for this run.": "Tidak ada peta neraca untuk run ini.", "No SiTMAT stations for this run.": "Tidak ada stasiun SiTMAT untuk run ini.",
  "Treatment": "Penanganan", "Otherwise": "Selain itu", "Reasons": "Alasan", "New sekat": "Sekat baru", "Held": "Ditahan", "Deficit": "Defisit", "Held share": "Bagian ditahan",
  "Canal reach": "Jangkauan kanal", "Burnt": "Terbakar", "Water distance": "Jarak air", "Protected": "Lindung", "WB dry season": "NA kemarau",
  "Generated": "Dibuat", "Values marked as proposed defaults are not team decisions.": "Nilai bertanda usulan bukan keputusan tim.",
  "Generated from the run files; do not edit, rerun repeat-pump report-html.": "Dibuat dari berkas run; jangan diedit, jalankan ulang repeat-pump report-html.",
  "Sub-KHG polygons are simplified for display; the analysis uses the full shapes.": "Poligon sub-KHG disederhanakan untuk tampilan; analisis memakai bentuk penuh.",
  "Basemap: OpenFreeMap, data © OpenStreetMap contributors (needs internet; the run layers draw without it).": "Peta dasar: OpenFreeMap, data © kontributor OpenStreetMap (perlu internet; layer run tetap tampil tanpanya).",
  "Pumps": "Pompa", "off (sekat only)": "mati (sekat saja)", "on": "aktif", "Canal classes": "Kelas kanal", "warnings in the run report": "peringatan di laporan run",
  "Hover a sub-KHG, sekat or station for its details.": "Arahkan kursor ke sub-KHG, sekat atau stasiun untuk rinciannya.", "kept for": "dipertahankan untuk", "of the water they hold": "dari air yang ditahan", "rise": "kenaikan", "spacing": "jarak", "rank": "urutan", "share": "bagian",
  "selected": "terpilih", "not analysed": "tidak dianalisis", "mm/month": "mm/bulan",
  "Budget estimate": "Perkiraan anggaran", "Blocks": "Sekat", "Rupiah": "Rupiah", "Spent on sekat, in order of benefit": "Belanja sekat, menurut urutan manfaat",
  "billion rupiah": "miliar rupiah", "not priced": "belum ada harga", "low": "rendah", "central": "tengah", "high": "tinggi",
  "Prices are proposed estimates from published sources, not team decisions; they are not adjusted for inflation.":
    "Harga adalah perkiraan usulan dari sumber terbitan, bukan keputusan tim; belum disesuaikan dengan inflasi.",
  "rupiah per m³ of water held by the sekat": "rupiah per m³ air yang ditahan sekat", "prices of": "harga tahun",
  "Sekat, wooden (kept)": "Sekat kayu (dipertahankan)", "Sekat, concrete (kept)": "Sekat beton (dipertahankan)",
  "Sekat, KLH IPG estimate (sub-KHG not analysed)": "Sekat, perkiraan IPG KLH (sub-KHG tidak dianalisis)", "Canal closure or backfill": "Penutupan atau penimbunan kanal",
  "Revegetation": "Revegetasi", "Deep wells (sumur bor)": "Sumur bor", "Pump units": "Unit pompa", "Pump fuel": "Bahan bakar pompa",
};
let lang = (localStorage.getItem("rp_lang") || (navigator.language || "en").slice(0, 2)) === "id" ? "id" : "en";
const t = s => (lang === "id" && ID[s]) || s;
const nf = (v, d = 0) => v == null || !isFinite(v) ? "–" : new Intl.NumberFormat(lang === "id" ? "id-ID" : "en-GB", {maximumFractionDigits: d, minimumFractionDigits: d}).format(v);
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

// ------------------------------------------------------------------ classes and colours (fixed order, never cycled)
const IV = ["close_canals", "revegetate_fire", "block_water", "block_wells", "block", "maintain"];
const IV_LABEL = {close_canals: "Close or backfill canals (protected peat)", revegetate_fire: "Revegetation and fire readiness",
  block_water: "Sekat and water supply", block_wells: "Sekat and deep wells", block: "Sekat", maintain: "Maintain and monitor"};
const IV_SHORT = {close_canals: "C", revegetate_fire: "R", block_water: "W", block_wells: "B", block: "S", maintain: "M"};
const ivColor = c => css("--s" + (IV.indexOf(c) + 1)) || css("--muted");
const TMAT = ["flooded", "normal", "at_risk", "high_risk"];
const TMAT_LABEL = {flooded: "Flooded (above 0 m)", normal: "Normal (0 to -0.4 m)", at_risk: "At risk (-0.4 to -0.8 m)", high_risk: "Very much at risk (below -0.8 m)"};
const tmatColor = c => ({flooded: css("--s1"), normal: css("--good"), at_risk: css("--warning"), high_risk: css("--critical")})[c] || css("--muted");

const ITEM_LABEL = {sekat_standard: "Sekat, wooden (kept)", sekat_reinforced: "Sekat, concrete (kept)", sekat_ipg_estimate: "Sekat, KLH IPG estimate (sub-KHG not analysed)",
  canal_closure_km: "Canal closure or backfill", revegetation_ha: "Revegetation", deep_wells: "Deep wells (sumur bor)", pump_units: "Pump units", pump_fuel_l: "Pump fuel"};
const ITEM_UNIT = {sekat_standard: "", sekat_reinforced: "", sekat_ipg_estimate: "", canal_closure_km: "km", revegetation_ha: "ha", deep_wells: "", pump_units: "", pump_fuel_l: "L"};
const bn = v => v == null ? "–" : nf(v / 1e9, 1);

// ------------------------------------------------------------------ tooltip
const tip = document.getElementById("tip");
function showTip(html, x, y) { tip.innerHTML = html; tip.hidden = false; const r = tip.getBoundingClientRect();
  tip.style.left = Math.min(x + 14, innerWidth - r.width - 8) + "px"; tip.style.top = Math.min(y + 14, innerHeight - r.height - 8) + "px"; }
const hideTip = () => { tip.hidden = true; };
const row = (k, v) => `<div><span class="k">${k}</span> ${v}</div>`;

// ------------------------------------------------------------------ header, tiles, footer
const T = D.tiles, units = D.geo.units.features.map(f => f.properties);
function header() {
  document.getElementById("title").textContent = D.meta.run;
  document.getElementById("meta").textContent = `${t("Generated")} ${D.meta.generated} · ${t("Pumps")}: ${D.meta.pumping ? t("on") : t("off (sekat only)")} · ` +
    `${t("Canal classes")}: ${(D.meta.canal_classes || []).map(c => t({primer: "primary", sekunder: "secondary", tersier: "tertiary"}[c] || c)).join(", ")}`;
  document.querySelectorAll("[data-i18n]").forEach(el => { el.dataset.en = el.dataset.en || el.textContent; el.textContent = t(el.dataset.en); });
  document.getElementById("q").placeholder = t("Search");
  document.querySelectorAll("[data-lang]").forEach(b => b.classList.toggle("on", b.dataset.lang === lang));
}
function tiles() {
  const share = T.held_m3 != null && T.deficit_m3_selected ? 100 * T.held_m3 / T.deficit_m3_selected : null;
  const items = [
    {l: "Sekat proposed", v: nf(T.kept), s: T.head_rule != null ? `${t("of")} ${nf(T.head_rule)}` : "",
     f: T.target_share ? `${t("head-rule sekat")}; ${t("kept for")} ${nf(100 * T.target_share)} % ${t("of the water they hold")}` : t("head-rule sekat"),
     h: "Stage 7: sekat placed by the head rule (a block where the land rises 0.4 m), then the fewest that hold the target share of the canal water-level rise (canal-rise objective, Urzainki et al. 2020)."},
    {l: "Water held", v: share == null ? "–" : nf(share, 1), s: share == null ? "" : "%", f: t("of the deficit of the selected sub-KHG"),
     h: "Canal water-level rise of the kept sekat x specific yield x lateral reach, against the neraca KHG deficit x area of the selected sub-KHG (stage 11)."},
    {l: "Neraca KHG deficit", v: D.neraca.khg_deficit_mm == null ? "–" : nf(D.neraca.khg_deficit_mm), s: D.neraca.khg_deficit_mm == null ? "" : "mm",
     f: D.neraca.window || "", h: "repeat-neraca: max(0, -sum(P - E) - Sy x observed water-table change) over the dry-season window, from SiTMAT and ERA5."},
    {l: "Budget estimate", v: D.budget && D.budget.total_idr != null ? bn(D.budget.total_idr) : "–", s: D.budget && D.budget.total_idr != null ? t("billion rupiah") : "",
     f: D.budget && D.budget.total_idr != null ? `${bn(D.budget.total_low_idr)} – ${bn(D.budget.total_high_idr)}${(D.budget.unpriced || []).length ? " · " + t("not priced") + ": " + D.budget.unpriced.map(i => t(ITEM_LABEL[i] || i)).join(", ") : ""}` : "",
     h: "Quantities of the run (kept sekat, km of canal to close, ha to revegetate, wells, pumps) x proposed unit prices from published sources (budget.* in the config; docs/proposed_defaults.md). Low and high from the range of the sources."},
    {l: "Existing sekat", v: nf(T.existing != null && T.unsnapped != null ? T.existing - T.unsnapped : T.existing), s: T.existing != null ? `${t("of")} ${nf(T.existing)}` : "",
     f: t("on an analysed canal"), h: "Existing sekat within the snap tolerance of an analysed canal class (stage 7)."},
    {l: "Sub-KHG analysed for sekat", v: nf((T.selected || []).length), s: `${t("of")} ${nf(T.units)}`, f: (T.selected || []).join(", "),
     h: "The sub-KHG chosen in stage 1 (highest priority from the sub-KHG ranking). Every sub-KHG gets an intervention class."},
  ];
  document.getElementById("tiles").innerHTML = items.map(i => `<div class="tile"><div class="lab"><span class="help" title="${i.h}">${t(i.l)}</span></div>` +
    `<div class="val">${i.v}<small>${i.s}</small></div><div class="foot">${i.f}</div></div>`).join("");
}
function footer() {
  document.getElementById("foot").innerHTML = [t("Generated from the run files; do not edit, rerun repeat-pump report-html."),
    `${nf(D.meta.preset_values)} ${t("Values marked as proposed defaults are not team decisions.")} ${nf(D.meta.warnings)} ${t("warnings in the run report")} (${D.files.report}).`,
    t("Sub-KHG polygons are simplified for display; the analysis uses the full shapes."),
    t("Basemap: OpenFreeMap, data © OpenStreetMap contributors (needs internet; the run layers draw without it).")].map(p => `<p>${p}</p>`).join("");
}

// ------------------------------------------------------------------ map
let map, unitMode = "intervention", mapReady = false;
const LAYERS = [
  {id: "units", name: "Sub-KHG units", on: true},
  {id: "selected", name: "Selected sub-KHG", on: true},
  {id: "canals", name: "Canals", on: true},
  {id: "existing", name: "Existing sekat", on: false},
  {id: "low", name: "Sekat, low benefit", on: true},
  {id: "kept", name: "Sekat, kept", on: true},
  {id: "stations", name: "SiTMAT stations", on: true},
];
const SUBLAYERS = {units: ["units-fill", "units-line"], selected: ["selected-line"], canals: ["canals-line"], existing: ["existing-pt"],
  low: ["low-pt"], kept: ["kept-pt"], stations: ["stations-pt"]};
function bbox(fc) { let b = [180, 90, -180, -90]; const walk = c => typeof c[0] === "number" ? (b = [Math.min(b[0], c[0]), Math.min(b[1], c[1]), Math.max(b[2], c[0]), Math.max(b[3], c[1])]) : c.forEach(walk);
  fc.features.forEach(f => walk(f.geometry.coordinates)); return b; }
function wbExpr() {
  const ok = D.neraca.order_ok !== 0;
  if (!ok) return css("--mid");
  const v = units.map(u => u.wb_dry).filter(x => x != null); const m = Math.max(1, ...v.map(Math.abs));
  return ["case", ["==", ["get", "wb_dry"], null], css("--mid"),
    ["interpolate", ["linear"], ["get", "wb_dry"], -m, css("--neg"), 0, css("--mid"), m, css("--pos")]];
}
function unitFill() { return unitMode === "wb" ? wbExpr() : ["match", ["get", "intervention"], ...IV.flatMap(c => [c, ivColor(c)]), css("--mid")]; }
function initMap() {
  map = new maplibregl.Map({container: "map", style: D.style, bounds: bbox(D.geo.units.features.length ? D.geo.units : D.geo.canals),
    fitBoundsOptions: {padding: 24}, attributionControl: {compact: true}});
  map.addControl(new maplibregl.NavigationControl({showCompass: false}), "top-left");
  map.addControl(new maplibregl.ScaleControl({unit: "metric"}), "bottom-left");
  window.__repeatMap = map;                            // for checks in a browser console
  let added = false;
  const addRunLayers = () => { if (added || !map.isStyleLoaded()) return; added = true;
    for (const k of ["units", "canals", "kept", "low", "existing", "stations"]) map.addSource(k, {type: "geojson", data: D.geo[k]});
    map.addLayer({id: "units-fill", type: "fill", source: "units", paint: {"fill-color": unitFill(), "fill-opacity": 0.55}});
    map.addLayer({id: "units-line", type: "line", source: "units", paint: {"line-color": css("--surface"), "line-width": 1}});
    map.addLayer({id: "selected-line", type: "line", source: "units", filter: ["==", ["get", "selected"], true], paint: {"line-color": css("--ink"), "line-width": 2.2}});
    map.addLayer({id: "canals-line", type: "line", source: "canals", paint: {
      "line-color": ["case", ["==", ["get", "direction_method"], "unresolved"], css("--s4"), css("--ink2")],
      "line-width": ["match", ["downcase", ["to-string", ["get", "canal_class"]]], ["primer", "kanal primer"], 1.8, ["sekunder", "kanal sekunder"], 1.1, 0.6],
      "line-dasharray": ["case", ["==", ["get", "direction_method"], "unresolved"], ["literal", [2, 1.5]], ["literal", [1, 0]]]}});
    map.addLayer({id: "existing-pt", type: "circle", source: "existing", paint: {"circle-radius": 2.5, "circle-color": ["case", ["get", "snapped"], css("--s3"), css("--muted")],
      "circle-stroke-color": css("--surface"), "circle-stroke-width": 0.5}});
    map.addLayer({id: "low-pt", type: "circle", source: "low", paint: {"circle-radius": 3, "circle-color": css("--muted"), "circle-stroke-color": css("--surface"), "circle-stroke-width": 1}});
    const gmax = Math.max(1, ...D.geo.kept.features.map(f => f.properties.gain_m2 || 0));
    map.addLayer({id: "kept-pt", type: "circle", source: "kept", paint: {"circle-radius": ["interpolate", ["linear"], ["sqrt", ["coalesce", ["get", "gain_m2"], 0]], 0, 4, Math.sqrt(gmax), 11],
      "circle-color": css("--ink"), "circle-stroke-color": css("--surface"), "circle-stroke-width": 2}});
    map.addLayer({id: "stations-pt", type: "circle", source: "stations", paint: {"circle-radius": 5,
      "circle-color": ["match", ["get", "tmat_class"], ...TMAT.flatMap(c => [c, tmatColor(c)]), css("--muted")], "circle-stroke-color": css("--surface"), "circle-stroke-width": 1.5}});
    mapReady = true; applyVisibility(); bindHover();
  };
  // the run layers must not wait for basemap tiles or fonts (offline, or a slow tile server): add them once the style is parsed
  map.on("style.load", addRunLayers); map.on("load", addRunLayers); map.on("idle", addRunLayers);
}
function applyVisibility() {
  if (!mapReady) return;
  for (const L of LAYERS) for (const id of SUBLAYERS[L.id]) if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", L.on ? "visible" : "none");
}
function restyleMap() {
  if (!mapReady) return;
  map.setPaintProperty("units-fill", "fill-color", unitFill());
  map.setPaintProperty("units-line", "line-color", css("--surface"));
  map.setPaintProperty("selected-line", "line-color", css("--ink"));
  map.setPaintProperty("kept-pt", "circle-color", css("--ink"));
  map.setPaintProperty("stations-pt", "circle-color", ["match", ["get", "tmat_class"], ...TMAT.flatMap(c => [c, tmatColor(c)]), css("--muted")]);
}
function unitTip(p) {
  return `<b>${p.subkhg_id}</b>${p.selected ? ` · ${t("selected")}` : ""}` + row(t("Treatment"), t(IV_LABEL[p.intervention] || "–")) +
    (p.intervention_otherwise ? row(t("Otherwise"), t(IV_LABEL[p.intervention_otherwise])) : "") + row(t("Reasons"), p.reasons || "–") +
    (p.held_share != null ? row(t("Held share"), nf(100 * p.held_share, 1) + " %") : row(t("Held share"), t("not analysed"))) +
    row(t("WB dry season"), p.wb_dry == null ? "–" : nf(p.wb_dry) + " " + t("mm/month"));
}
function bindHover() {
  const tips = {
    "units-fill": unitTip,
    "kept-pt": p => `<b>${p.sekat_pro_id}</b>` + row(t("rank"), nf(p.benefit_rank)) + row(t("rise"), nf(p.gain_m2) + " m²") + row(t("share"), nf(100 * p.cum_share, 1) + " %") +
      row(t("spacing"), nf(p.js_m) + " m"),
    "low-pt": p => `<b>${p.sekat_pro_id}</b> · ${t("Sekat, low benefit")}` + row(t("rank"), nf(p.benefit_rank)) + row(t("rise"), nf(p.gain_m2) + " m²"),
    "stations-pt": p => `<b>${p.station_id}</b>` + row(t(TMAT_LABEL[p.tmat_class] || ""), "") + row(t("start"), nf(p.depth_start_cm) + " cm") +
      row(t("end"), nf(p.depth_end_cm) + " cm") + row(">40 cm", nf(100 * p.share_deeper_40cm) + " %"),
    "canals-line": p => `<b>${p.canal_id}</b> · ${p.canal_class}` + row("IPG", p.ipg == null ? "–" : nf(p.ipg, 2)) + (p.direction_method === "unresolved" ? row(t("flow direction unknown"), "") : ""),
  };
  map.on("mousemove", e => {
    const ids = Object.keys(tips).filter(id => map.getLayer(id) && map.getLayoutProperty(id, "visibility") !== "none");
    const f = map.queryRenderedFeatures(e.point, {layers: ids})[0];
    map.getCanvas().style.cursor = f ? "pointer" : "";
    if (f) showTip(tips[f.layer.id](f.properties), e.originalEvent.clientX, e.originalEvent.clientY); else hideTip();
  });
  map.on("mouseout", hideTip);
}
function layerPanel() {
  const el = document.getElementById("layers");
  const legend = {
    units: unitMode === "wb" ? (D.neraca.order_ok === 0 ? [[css("--mid"), t("The order between sub-KHG is not stable for this KHG, so only the KHG mean is shown.")]] :
      [[css("--neg"), t("deficit")], [css("--mid"), "0"], [css("--pos"), t("surplus")]]) : IV.filter(c => (D.interventions.counts || {})[c]).map(c => [ivColor(c), `${t(IV_LABEL[c])} (${IV_SHORT[c]})`]),
    canals: [[css("--ink2"), t("primary") + " / " + t("secondary"), "line"], [css("--s4"), t("flow direction unknown"), "line"]],
    existing: [[css("--s3"), t("Existing sekat, on an analysed canal"), "dot"], [css("--muted"), t("Existing sekat, elsewhere"), "dot"]],
    stations: TMAT.map(c => [tmatColor(c), t(TMAT_LABEL[c]), "dot"]),
    kept: [[css("--ink"), t("Sekat, kept"), "dot"]], low: [[css("--muted"), t("Sekat, low benefit"), "dot"]],
  };
  el.innerHTML = LAYERS.filter(L => L.id !== "stations" || D.geo.stations.features.length).map(L => `<label><input type="checkbox" data-l="${L.id}" ${L.on ? "checked" : ""}>${t(L.name)}</label>` +
    (legend[L.id] ? `<div class="legend">${legend[L.id].map(([c, s, k]) => `<div><span class="sw ${k || ""}" style="background:${c}"></span> ${s}</div>`).join("")}</div>` : "")).join("");
  el.querySelectorAll("input").forEach(i => i.onchange = () => { LAYERS.find(L => L.id === i.dataset.l).on = i.checked; applyVisibility(); });
  document.getElementById("mapnote").textContent = t("Hover a sub-KHG, sekat or station for its details.");
  document.querySelectorAll("#unitmode button").forEach(b => b.classList.toggle("on", b.dataset.mode === unitMode));
}

// ------------------------------------------------------------------ charts
function frame(id, h = 260, m = {t: 12, r: 16, b: 34, l: 48}) {
  const el = document.getElementById(id); el.innerHTML = "";
  const w = Math.max(280, el.clientWidth); const svg = d3.select(el).append("svg").attr("width", w).attr("height", h);
  return {svg, w, h, m, iw: w - m.l - m.r, ih: h - m.t - m.b, g: svg.append("g").attr("transform", `translate(${m.l},${m.t})`)};
}
function empty(id, msg) { document.getElementById(id).innerHTML = `<div class="note" style="padding:24px 0">${msg}</div>`; }
let curveX = "n";
function curveChart() {
  const sc = (D.budget && D.budget.spend_curve) || [];
  const byCost = curveX === "cost" && sc.length === D.curve.length;
  const c = byCost ? D.curve.map((p, i) => ({...p, n: sc[i].cost_idr})) : D.curve; if (!c.length) return empty("curve", "–");
  document.querySelectorAll("#curvex button").forEach(b => { b.classList.toggle("on", b.dataset.x === (byCost ? "cost" : "n")); b.hidden = !sc.length; });
  const F = frame("curve"); const x = d3.scaleLinear().domain([0, byCost ? c[c.length - 1].n : c.length]).range([0, F.iw]); const y = d3.scaleLinear().domain([0, 1]).range([F.ih, 0]);
  F.g.append("g").attr("class", "gridl").call(d3.axisLeft(y).ticks(5).tickSize(-F.iw).tickFormat(""));
  F.g.append("g").attr("class", "axis").attr("transform", `translate(0,${F.ih})`).call(d3.axisBottom(x).ticks(6).tickFormat(v => byCost ? bn(v) : nf(v)));
  F.g.append("g").attr("class", "axis").call(d3.axisLeft(y).ticks(5).tickFormat(d => nf(100 * d) + " %"));
  const pts = [{n: 0, cum: 0}, ...c];
  const kept = c.filter(p => p.kept).length;
  const keptX = byCost ? (c[kept - 1] || {n: 0}).n : kept;
  F.g.append("rect").attr("x", 0).attr("y", 0).attr("width", x(keptX)).attr("height", F.ih).attr("fill", css("--ink")).attr("opacity", 0.05);
  F.g.append("path").datum(pts).attr("fill", "none").attr("stroke", css("--ink")).attr("stroke-width", 2).attr("d", d3.line().x(d => x(d.n)).y(d => y(d.cum)));
  if (T.target_share) F.g.append("line").attr("x1", 0).attr("x2", F.iw).attr("y1", y(T.target_share)).attr("y2", y(T.target_share)).attr("stroke", css("--muted")).attr("stroke-dasharray", "3 3");
  F.g.append("text").attr("x", x(keptX) + 6).attr("y", 14).text(`${nf(kept)} ${t("kept")}` + (byCost ? ` · ${bn(keptX)} ${t("billion rupiah")}` : ""));
  F.g.append("text").attr("x", F.iw).attr("y", F.ih + 30).attr("text-anchor", "end").text(byCost ? `${t("Spent on sekat, in order of benefit")} (${t("billion rupiah")})` : t("Blocks, in order of benefit"));
  const dot = F.g.append("circle").attr("r", 4).attr("fill", css("--ink")).attr("stroke", css("--surface")).attr("stroke-width", 2).style("display", "none");
  F.svg.append("rect").attr("x", F.m.l).attr("y", F.m.t).attr("width", F.iw).attr("height", F.ih).attr("fill", "transparent")
    .on("mousemove", ev => { const xv = x.invert(d3.pointer(ev)[0] - F.m.l); const i = byCost ? Math.max(0, d3.bisectLeft(c.map(p => p.n), xv)) : Math.round(xv) - 1;
      const p = c[Math.max(0, Math.min(c.length - 1, i))]; const n = c.indexOf(p) + 1;
      dot.style("display", null).attr("cx", x(p.n)).attr("cy", y(p.cum));
      showTip(`<b>${nf(n)} ${t("blocks")}</b>` + (byCost ? row(t("Rupiah"), bn(p.n) + " " + t("billion rupiah")) : "") + row(t("Share of the water held"), nf(100 * p.cum, 1) + " %") +
        row(t("rise"), "+" + nf(p.gain) + " m²"), ev.clientX, ev.clientY); })
    .on("mouseleave", () => { dot.style("display", "none"); hideTip(); });
}
function ivChart() {
  const cnt = D.interventions.counts || {}; const cls = IV.filter(c => cnt[c] != null);
  if (!cls.length) return empty("ivbars", "–");
  const probe = d3.select("body").append("svg").attr("width", 0).attr("height", 0);   // the left margin follows the longest label
  const lw = d3.max(cls, c => probe.append("text").style("font-size", "11.5px").text(`${t(IV_LABEL[c])} (${IV_SHORT[c]})`).node().getComputedTextLength());
  probe.remove();
  const F = frame("ivbars", 260, {t: 8, r: 40, b: 20, l: Math.ceil(lw) + 14});
  const y = d3.scaleBand().domain(cls).range([0, F.ih]).padding(0.28); const x = d3.scaleLinear().domain([0, Math.max(1, ...cls.map(c => cnt[c]))]).range([0, F.iw]);
  F.g.selectAll("rect").data(cls).join("rect").attr("x", 0).attr("y", c => y(c)).attr("height", y.bandwidth()).attr("width", c => Math.max(0, x(cnt[c]))).attr("rx", 4)
    .attr("fill", c => ivColor(c)).on("mousemove", (ev, c) => showTip(`<b>${t(IV_LABEL[c])}</b>` + row(t("Sub-KHG"), nf(cnt[c])) +
      ((D.interventions.closed_otherwise || {})[c] && c !== "close_canals" ? "" : ""), ev.clientX, ev.clientY)).on("mouseleave", hideTip);
  F.g.selectAll("text.lab").data(cls).join("text").attr("class", "lab").attr("x", -8).attr("y", c => y(c) + y.bandwidth() / 2).attr("dy", "0.35em").attr("text-anchor", "end")
    .text(c => `${t(IV_LABEL[c])} (${IV_SHORT[c]})`);
  F.g.selectAll("text.v").data(cls).join("text").attr("class", "v").attr("x", c => x(cnt[c]) + 6).attr("y", c => y(c) + y.bandwidth() / 2).attr("dy", "0.35em").text(c => nf(cnt[c]));
}
function budgetChart() {
  const B = D.budget, sub = document.getElementById("budgetsub");
  if (!B) { document.getElementById("budgetcard").hidden = true; return; }
  sub.textContent = `${t("billion rupiah")}, ${t("prices of")} ${B.price_year || "–"}. ` + t("Prices are proposed estimates from published sources, not team decisions; they are not adjusted for inflation.") +
    (B.idr_per_m3_held ? ` ${nf(B.idr_per_m3_held)} ${t("rupiah per m³ of water held by the sekat")}.` : "");
  const items = Object.entries(B.by_item || {}).filter(([k, v]) => v.quantity > 0).sort((a, b) => (b[1].cost_idr || 0) - (a[1].cost_idr || 0));
  if (!items.length) return empty("budget", "–");
  const probe = d3.select("body").append("svg");
  const lw = d3.max(items, ([k, v]) => probe.append("text").style("font-size", "11.5px").text(`${t(ITEM_LABEL[k] || k)} · ${nf(v.quantity)} ${ITEM_UNIT[k] || ""}`).node().getComputedTextLength());
  probe.remove();
  const F = frame("budget", Math.max(160, items.length * 34 + 30), {t: 8, r: 70, b: 22, l: Math.ceil(lw) + 14});
  const y = d3.scaleBand().domain(items.map(d => d[0])).range([0, F.ih]).padding(0.3);
  const x = d3.scaleLinear().domain([0, d3.max(items, ([k, v]) => v.cost_high_idr || v.cost_idr || 0) || 1]).nice().range([0, F.iw]);
  F.g.append("g").attr("class", "gridl").attr("transform", `translate(0,${F.ih})`).call(d3.axisBottom(x).ticks(5).tickSize(-F.ih).tickFormat(""));
  F.g.append("g").attr("class", "axis").attr("transform", `translate(0,${F.ih})`).call(d3.axisBottom(x).ticks(5).tickFormat(v => bn(v)));
  const g = F.g.selectAll("g.it").data(items).join("g").attr("class", "it").attr("transform", d => `translate(0,${y(d[0])})`);
  g.append("rect").attr("height", y.bandwidth()).attr("width", d => d[1].cost_idr == null ? 0 : x(d[1].cost_idr)).attr("rx", 4).attr("fill", css("--s1"));
  g.append("line").attr("x1", d => d[1].cost_low_idr == null ? 0 : x(d[1].cost_low_idr)).attr("x2", d => d[1].cost_high_idr == null ? 0 : x(d[1].cost_high_idr))
    .attr("y1", y.bandwidth() / 2).attr("y2", y.bandwidth() / 2).attr("stroke", css("--ink")).attr("stroke-width", 1.5);
  g.append("text").attr("x", -8).attr("y", y.bandwidth() / 2).attr("dy", "0.35em").attr("text-anchor", "end").text(([k, v]) => `${t(ITEM_LABEL[k] || k)} · ${nf(v.quantity)} ${ITEM_UNIT[k] || ""}`);
  g.append("text").attr("x", d => (d[1].cost_high_idr ? x(d[1].cost_high_idr) : x(d[1].cost_idr || 0)) + 6).attr("y", y.bandwidth() / 2).attr("dy", "0.35em")
    .text(([k, v]) => v.cost_idr == null ? t("not priced") : bn(v.cost_idr));
  g.on("mousemove", (ev, [k, v]) => showTip(`<b>${t(ITEM_LABEL[k] || k)}</b>` + row(t("low"), bn(v.cost_low_idr)) + row(t("central"), bn(v.cost_idr)) + row(t("high"), bn(v.cost_high_idr)) +
      row("", t("billion rupiah")), ev.clientX, ev.clientY)).on("mouseleave", hideTip);
}
function neracaChart() {
  const U = D.neraca.units || {}; const ids = Object.keys(U);
  const sub = document.getElementById("nerasub");
  if (!ids.length) { sub.textContent = ""; return empty("neraca", t("No neraca map for this run.")); }
  const ok = D.neraca.order_ok !== 0; const months = d3.range(12);
  const mean = months.map(m => d3.mean(ids, id => U[id].clim[m]));
  const lo = months.map(m => d3.min(ids, id => U[id].clim[m])), hi = months.map(m => d3.max(ids, id => U[id].clim[m]));
  sub.textContent = `${t("Water balance")} (${t("mm/month")}), ${D.neraca.et_source || ""}` + (ok ? "" : ". " + t("The order between sub-KHG is not stable for this KHG, so only the KHG mean is shown."));
  const F = frame("neraca"); const x = d3.scalePoint().domain(months).range([0, F.iw]);
  const sel = ok ? (T.selected || []).filter(id => U[id]) : [];
  const all = [...lo, ...hi, ...sel.flatMap(id => U[id].clim)].filter(v => v != null);
  const y = d3.scaleLinear().domain(d3.extent([0, ...all])).nice().range([F.ih, 0]);
  F.g.append("g").attr("class", "gridl").call(d3.axisLeft(y).ticks(5).tickSize(-F.iw).tickFormat(""));
  const mn = lang === "id" ? ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"] : ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  F.g.append("g").attr("class", "axis").attr("transform", `translate(0,${F.ih})`).call(d3.axisBottom(x).tickFormat(m => mn[m]));
  F.g.append("g").attr("class", "axis").call(d3.axisLeft(y).ticks(5));
  F.g.append("line").attr("x1", 0).attr("x2", F.iw).attr("y1", y(0)).attr("y2", y(0)).attr("stroke", css("--axis"));
  F.g.append("path").datum(months).attr("fill", css("--muted")).attr("opacity", 0.16).attr("d", d3.area().x(m => x(m)).y0(m => y(lo[m])).y1(m => y(hi[m])));
  const series = [{id: t("KHG mean"), v: mean, c: css("--ink2"), w: 2, dash: "4 3"}, ...sel.map((id, i) => ({id, v: U[id].clim, c: css("--s" + (i + 1)), w: 2}))];
  for (const s of series) F.g.append("path").datum(months).attr("fill", "none").attr("stroke", s.c).attr("stroke-width", s.w).attr("stroke-dasharray", s.dash || null)
    .attr("d", d3.line().defined(m => s.v[m] != null).x(m => x(m)).y(m => y(s.v[m])));
  const lg = F.svg.append("g").attr("transform", `translate(${F.m.l},${F.h - 4})`);
  let ox = 0; [{id: t("Range over all sub-KHG"), c: css("--muted"), band: 1}, ...series].forEach(s => { const g = lg.append("g").attr("transform", `translate(${ox},0)`);
    g.append(s.band ? "rect" : "line").attr("x", 0).attr("y", s.band ? -8 : -4).attr("width", 14).attr("height", s.band ? 8 : null).attr("x1", 0).attr("x2", 14).attr("y1", -4).attr("y2", -4)
      .attr("fill", s.band ? s.c : null).attr("opacity", s.band ? 0.3 : 1).attr("stroke", s.band ? null : s.c).attr("stroke-width", 2).attr("stroke-dasharray", s.dash || null);
    const tx = g.append("text").attr("x", 18).attr("y", 0).text(s.id); ox += 26 + tx.node().getComputedTextLength(); });
  F.svg.attr("height", F.h + 12);
  const guide = F.g.append("line").attr("y1", 0).attr("y2", F.ih).attr("stroke", css("--axis")).style("display", "none");
  F.svg.append("rect").attr("x", F.m.l).attr("y", F.m.t).attr("width", F.iw).attr("height", F.ih).attr("fill", "transparent")
    .on("mousemove", ev => { const px = d3.pointer(ev)[0] - F.m.l; const m = months.reduce((a, b) => Math.abs(x(b) - px) < Math.abs(x(a) - px) ? b : a, 0);
      guide.style("display", null).attr("x1", x(m)).attr("x2", x(m));
      showTip(`<b>${mn[m]}</b>` + series.map(s => row(s.id, nf(s.v[m], 1) + " mm")).join("") + row(t("Range over all sub-KHG"), `${nf(lo[m], 1)} – ${nf(hi[m], 1)} mm`), ev.clientX, ev.clientY); })
    .on("mouseleave", () => { guide.style("display", "none"); hideTip(); });
}
function stationsChart() {
  const S = D.geo.stations.features.map(f => f.properties).filter(p => p.depth_end_cm != null).sort((a, b) => a.depth_end_cm - b.depth_end_cm);
  const sub = document.getElementById("stsub");
  if (!S.length) { sub.textContent = ""; return empty("stations", t("No SiTMAT stations for this run.")); }
  sub.textContent = `${t("Depth below the surface at the start and the end of the dry-season window")} (cm), ${nf(S.length)} ${t("stations")}`;
  const F = frame("stations", 260, {t: 12, r: 16, b: 34, l: 48});
  const x = d3.scaleBand().domain(S.map(s => s.station_id)).range([0, F.iw]).padding(0.3);
  const ext = d3.extent([0, 80, ...S.flatMap(s => [s.depth_start_cm, s.depth_end_cm])]);
  const y = d3.scaleLinear().domain(ext).nice().range([0, F.ih]);      // depth grows downward, as in the ground
  F.g.append("g").attr("class", "gridl").call(d3.axisLeft(y).ticks(6).tickSize(-F.iw).tickFormat(""));
  F.g.append("g").attr("class", "axis").call(d3.axisLeft(y).ticks(6));
  for (const [v, k] of [[0, "--s1"], [40, "--warning"], [80, "--critical"]]) F.g.append("line").attr("x1", 0).attr("x2", F.iw).attr("y1", y(v)).attr("y2", y(v)).attr("stroke", css(k)).attr("stroke-dasharray", "4 3");
  F.g.selectAll("line.c").data(S).join("line").attr("class", "c").attr("x1", s => x(s.station_id) + x.bandwidth() / 2).attr("x2", s => x(s.station_id) + x.bandwidth() / 2)
    .attr("y1", s => y(s.depth_start_cm)).attr("y2", s => y(s.depth_end_cm)).attr("stroke", css("--axis")).attr("stroke-width", 2);
  F.g.selectAll("circle.s").data(S).join("circle").attr("class", "s").attr("cx", s => x(s.station_id) + x.bandwidth() / 2).attr("cy", s => y(s.depth_start_cm)).attr("r", 3)
    .attr("fill", css("--surface")).attr("stroke", css("--ink2")).attr("stroke-width", 1.5);
  F.g.selectAll("circle.e").data(S).join("circle").attr("class", "e").attr("cx", s => x(s.station_id) + x.bandwidth() / 2).attr("cy", s => y(s.depth_end_cm)).attr("r", 4.5)
    .attr("fill", s => tmatColor(s.tmat_class)).attr("stroke", css("--surface")).attr("stroke-width", 1.5)
    .on("mousemove", (ev, s) => showTip(`<b>${s.station_id}</b>` + row(t(TMAT_LABEL[s.tmat_class] || ""), "") + row(t("start"), `${nf(s.depth_start_cm)} cm (${s.first_date})`) +
      row(t("end"), `${nf(s.depth_end_cm)} cm (${s.last_date})`) + row(">40 cm", nf(100 * s.share_deeper_40cm) + " %"), ev.clientX, ev.clientY)).on("mouseleave", hideTip);
  F.g.append("text").attr("x", 0).attr("y", F.ih + 24).text(`○ ${t("start")}   ● ${t("end")}`);
  F.g.append("text").attr("x", F.iw).attr("y", F.ih + 24).attr("text-anchor", "end").text(t("Depth below the surface") + " (cm)");
}

// ------------------------------------------------------------------ table
const COLS = [
  {k: "subkhg_id", l: "Sub-KHG"}, {k: "intervention", l: "Treatment", f: v => v ? `${t(IV_LABEL[v])}` : "–"},
  {k: "intervention_otherwise", l: "Otherwise", f: v => v ? t(IV_LABEL[v]) : ""}, {k: "sekat_new", l: "New sekat", n: 1, f: v => nf(v)},
  {k: "held_m3", l: "Held", u: "1000 m³", n: 1, f: v => nf(v == null ? null : v / 1000)}, {k: "deficit_m3", l: "Deficit", u: "1000 m³", n: 1, f: v => nf(v == null ? null : v / 1000)},
  {k: "held_share", l: "Held share", u: "%", n: 1, f: v => nf(v == null ? null : 100 * v, 1)}, {k: "f_reach", l: "Canal reach", u: "%", n: 1, f: v => nf(v == null ? null : 100 * v)},
  {k: "u_ndmi", l: "NDMI", n: 1, f: v => nf(v, 2)}, {k: "burned_ever_frac", l: "Burnt", u: "%", n: 1, f: v => nf(v == null ? null : 100 * v)},
  {k: "f_water_dist", l: "Water distance", u: "km", n: 1, f: v => nf(v == null ? null : v / 1000, 1)}, {k: "i_protected", l: "Protected", u: "%", n: 1, f: v => nf(v == null ? null : 100 * v)},
  {k: "wb_dry", l: "WB dry season", u: "mm/month", n: 1, f: v => nf(v)}, {k: "reasons", l: "Reasons"},
];
let sortK = "subkhg_id", sortDir = 1;
function table() {
  const q = document.getElementById("q").value.toLowerCase();
  const rows = units.filter(u => !q || JSON.stringify(u).toLowerCase().includes(q))
    .sort((a, b) => { const x = a[sortK], y = b[sortK]; return (x == null) - (y == null) || (x > y ? 1 : x < y ? -1 : 0) * sortDir; });
  const el = document.getElementById("tbl");
  el.innerHTML = `<thead><tr>${COLS.map(c => `<th data-k="${c.k}" class="${c.n ? "num" : ""}">${t(c.l)}${c.u ? ` <small>${t(c.u)}</small>` : ""}${sortK === c.k ? (sortDir > 0 ? " ▲" : " ▼") : ""}</th>`).join("")}</tr></thead>` +
    `<tbody>${rows.map(r => `<tr class="${r.selected ? "sel" : ""}">${COLS.map(c => `<td class="${c.n ? "num" : ""}">${c.k === "intervention" && r[c.k] ? `<span class="sw" style="background:${ivColor(r[c.k])}"></span> ` : ""}${c.f ? c.f(r[c.k]) : (r[c.k] ?? "–")}</td>`).join("")}</tr>`).join("")}</tbody>`;
  el.querySelectorAll("th").forEach(th => th.onclick = () => { sortDir = sortK === th.dataset.k ? -sortDir : 1; sortK = th.dataset.k; table(); });
}

// ------------------------------------------------------------------ wiring
function themeButton() { const dark = document.documentElement.dataset.theme === "dark" || (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
  document.getElementById("theme").textContent = dark ? "☀" : "☾"; }
function renderAll() { header(); tiles(); layerPanel(); curveChart(); ivChart(); budgetChart(); neracaChart(); stationsChart(); table(); footer(); themeButton(); restyleMap(); }
document.querySelectorAll("#curvex button").forEach(b => b.onclick = () => { curveX = b.dataset.x; curveChart(); });
document.querySelectorAll("[data-lang]").forEach(b => b.onclick = () => { lang = b.dataset.lang; try { localStorage.setItem("rp_lang", lang); } catch (e) {} renderAll(); });
document.getElementById("theme").onclick = () => { const r = document.documentElement; const dark = r.dataset.theme === "dark" || (!r.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
  r.dataset.theme = dark ? "light" : "dark"; try { localStorage.setItem("rp_theme", r.dataset.theme); } catch (e) {} renderAll(); };
document.querySelectorAll("#unitmode button").forEach(b => b.onclick = () => { unitMode = b.dataset.mode; layerPanel(); restyleMap(); });
document.getElementById("q").oninput = table;
try { const th = localStorage.getItem("rp_theme"); if (th) document.documentElement.dataset.theme = th; } catch (e) {}
let rt; addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => { curveChart(); ivChart(); budgetChart(); neracaChart(); stationsChart(); }, 150); });
renderAll(); initMap();
document.body.dataset.parity = `kept:${D.geo.kept.features.length}=${T.kept}`;
})();
