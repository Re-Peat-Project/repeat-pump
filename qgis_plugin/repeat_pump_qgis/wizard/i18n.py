"""English / Bahasa Indonesia for the wizard. Pure Python (no qgis imports), so it is testable in the engine venv.

English strings are the keys. ``tr("text")`` returns the Indonesian text when that language is active, and the key
itself otherwise (or when a string has no translation, such as text that comes from the engine's own log and warnings).
Strings with values use ``{name}`` placeholders: ``tr("Stage {n} of {total}").format(n=2, total=11)``.
"""
from __future__ import annotations

LANGUAGES = {"en": "English", "id": "Bahasa Indonesia"}
_current = "en"


def set_language(code: str) -> None:
    global _current
    _current = code if code in LANGUAGES else "en"


def language() -> str:
    return _current


def default_language(locale_name: str = "") -> str:
    """``id`` for an Indonesian locale such as ``id_ID``, otherwise ``en``."""
    return "id" if locale_name.lower().startswith("id") else "en"


def tr(text: str) -> str:
    return ID.get(text, text) if _current == "id" else text


ID: dict[str, str] = {
    # ---------------------------------------------------------------- stage cards (title, purpose, what, why)
    "Load and validate": "Muat dan validasi",
    "Tell the module where your data is. It checks projections, extents and the DTM type before anything is processed.":
        "Beri tahu modul di mana data Anda berada. Modul memeriksa proyeksi, cakupan, dan jenis DTM sebelum apa pun diproses.",
    "Reads every layer you point to, checks projection, extent and that the elevation is a bare-earth DTM, selects the priority sub-KHGs and clips the data to them.":
        "Membaca setiap layer yang Anda tunjuk, memeriksa proyeksi, cakupan, dan bahwa data ketinggian adalah DTM permukaan tanah, memilih sub-KHG prioritas, lalu memotong data sesuai sub-KHG tersebut.",
    "A silent projection mismatch or a surface model (DSM) would make every later height and slope wrong.":
        "Proyeksi yang tidak cocok tanpa disadari, atau model permukaan (DSM), akan membuat semua tinggi dan kemiringan sesudahnya salah.",
    "Canal topology": "Topologi kanal",
    "Canals are snapped, noded and de-duplicated. Nothing is deleted silently: you check the loose ends.":
        "Kanal disambungkan, dipecah di persimpangan, dan duplikatnya dibuang. Tidak ada yang dihapus diam-diam: Anda memeriksa ujung-ujung yang terlepas.",
    "Joins canal ends that nearly touch, splits lines at crossings and removes duplicates. Loose ends (dangles) are kept and flagged.":
        "Menyambung ujung kanal yang hampir bertemu, memecah garis di persimpangan, dan membuang duplikat. Ujung yang terlepas (dangle) tetap disimpan dan diberi tanda.",
    "A canal that looks connected on screen but is not would stop pumped water in the routing stage.":
        "Kanal yang tampak tersambung di layar tetapi sebenarnya tidak akan menghentikan air pompa pada tahap penentuan rute.",
    "Hydro-conditioning": "Pengondisian hidrologi",
    "Prepares a copy of the elevation model for flow routing only, then computes flow accumulation.":
        "Menyiapkan salinan model ketinggian khusus untuk penelusuran aliran, lalu menghitung akumulasi aliran.",
    "Removes pits by least-cost breaching, burns the canals into a separate raster, and computes flow accumulation (D-infinity by default).":
        "Menghilangkan cekungan dengan penembusan biaya terendah, membakar kanal ke raster terpisah, dan menghitung akumulasi aliran (D-infinity secara bawaan).",
    "Water must be able to flow along canals in the model. The unmodified DTM is still used for heights and slopes.":
        "Air harus bisa mengalir sepanjang kanal di dalam model. DTM asli yang tidak diubah tetap dipakai untuk tinggi dan kemiringan.",
    "Segmentation": "Segmentasi",
    "Splits canals into pieces of at most the configured length, with stable IDs.":
        "Memotong kanal menjadi bagian dengan panjang paling besar sesuai konfigurasi, dengan ID yang stabil.",
    "Cuts each cleaned canal into segments and numbers them in a fixed order, so results are repeatable.":
        "Memotong setiap kanal yang sudah bersih menjadi segmen dan menomorinya dengan urutan tetap, sehingga hasilnya dapat diulang.",
    "Scoring and sekat design work per segment, so segments must be comparable in length.":
        "Penilaian dan rancangan sekat bekerja per segmen, jadi panjang segmen harus sebanding.",
    "Land profiles": "Profil lahan",
    "Measures how the land rises along each canal, beside the canal rather than in it.":
        "Mengukur bagaimana lahan naik sepanjang setiap kanal, di sisi kanal, bukan di dalam kanal.",
    "Samples the DTM on both banks every few metres, takes the median and smooths it, then works out which way each canal drains.":
        "Mengambil sampel DTM di kedua tepi setiap beberapa meter, mengambil mediannya dan menghaluskannya, lalu menentukan arah aliran setiap kanal.",
    "A canal bed is not the land surface. The bank profile gives the slope that sets sekat spacing.":
        "Dasar kanal bukan permukaan lahan. Profil tepi kanal memberi kemiringan yang menentukan jarak antarsekat.",
    "Prioritisation": "Prioritisasi",
    "Scores each canal segment by need. Feasibility is kept separate from need.":
        "Menilai setiap segmen kanal berdasarkan kebutuhan. Kelayakan dipisahkan dari kebutuhan.",
    "Transfers burn and peat attributes by length, extracts dryness from a ring around the canal, combines criteria with your weights, and tests how stable the ranking is.":
        "Memindahkan atribut kebakaran dan gambut berdasarkan panjang, mengambil tingkat kekeringan dari cincin di sekitar kanal, menggabungkan kriteria dengan bobot Anda, dan menguji seberapa stabil peringkatnya.",
    "Pumping water everywhere is not possible. The ranking decides where rewetting is worth the effort.":
        "Memompa air ke mana-mana tidak mungkin. Peringkat menentukan di mana pembasahan ulang layak diupayakan.",
    "Sekat placement": "Penempatan sekat",
    "Compares existing blocks with what the terrain needs and proposes new sekat by hydraulic head.":
        "Membandingkan sekat yang ada dengan kebutuhan medan, lalu mengusulkan sekat baru berdasarkan tinggi tekan hidraulik.",
    "Counts how many sekat each canal needs from the land rise, then places new ones so each step in water level is dA.":
        "Menghitung berapa sekat yang dibutuhkan setiap kanal dari kenaikan lahan, lalu menempatkan sekat baru agar setiap anak tangga muka air setinggi dA.",
    "Each sekat holds water about dA above the next pool downstream, keeping the peat wet without flooding it.":
        "Setiap sekat menahan air sekitar dA di atas kolam berikutnya ke arah hilir, menjaga gambut tetap basah tanpa menggenanginya.",
    "Network graph": "Graf jaringan",
    "Builds the canal network as a directed graph with heights, sekat and river intersections.":
        "Menyusun jaringan kanal sebagai graf berarah lengkap dengan ketinggian, sekat, dan titik temu dengan sungai.",
    "Creates nodes at segment ends, sekat and river crossings, and edges that remember length and height change.":
        "Membuat simpul di ujung segmen, sekat, dan persilangan sungai, serta ruas yang mengingat panjang dan perubahan tinggi.",
    "Routing needs to know which way is uphill and where blocks stop the water.":
        "Penentuan rute perlu tahu arah mana yang menanjak dan di mana sekat menahan air.",
    "Sources and routes": "Sumber dan rute",
    "Finds water sources and routes pumped water to the highest pool of each target reach.":
        "Mencari sumber air dan menentukan rute air pompa ke kolam tertinggi pada setiap ruas sasaran.",
    "Takes river-canal intersections as sources, then finds the cheapest tree of routes where uphill costs extra.":
        "Menjadikan titik temu sungai dan kanal sebagai sumber, lalu mencari pohon rute termurah dengan tanjakan dihitung lebih mahal.",
    "Lift costs energy. One shared tree of routes needs fewer pumps than separate routes per target.":
        "Mengangkat air memakan energi. Satu pohon rute bersama membutuhkan lebih sedikit pompa daripada rute terpisah untuk tiap sasaran.",
    "Pumps and sizing": "Pompa dan kapasitas",
    "Works out water demand, the head along each route, where stations go and how much power they need.":
        "Menghitung kebutuhan air, tinggi tekan sepanjang rute, lokasi stasiun, dan daya yang dibutuhkan.",
    "Converts the water deficit to a flow rate, adds friction loss to the static lift, places stations and sizes them.":
        "Mengubah defisit air menjadi debit, menambahkan kehilangan akibat gesekan pada angkat statis, menempatkan stasiun, dan menentukan kapasitasnya.",
    "Shows what the pumps would have to do, and where the plan falls short.":
        "Menunjukkan apa yang harus dikerjakan pompa, dan di mana rencana belum mencukupi.",
    "Report": "Laporan",
    "Collects everything into one report, including warnings and parameters still unset.":
        "Mengumpulkan semuanya dalam satu laporan, termasuk peringatan dan parameter yang belum diisi.",
    "Writes run_report.md and run_report.json with counts, warnings, tables and the list of open parameters.":
        "Menulis run_report.md dan run_report.json berisi jumlah, peringatan, tabel, dan daftar parameter yang masih kosong.",
    "The report is what you share and what the dashboard reads.":
        "Laporan inilah yang Anda bagikan dan yang dibaca dasbor.",
    # ---------------------------------------------------------------- result tiles
    "Sub-KHGs selected": "Sub-KHG terpilih", "inside the analysis": "dalam analisis",
    "Canals in scope": "Kanal dalam cakupan", "after clipping": "setelah pemotongan",
    "Canal features in": "Fitur kanal masuk", "before cleaning": "sebelum pembersihan",
    "Canal features out": "Fitur kanal keluar", "after snap and node": "setelah penyambungan dan pemecahan",
    "Dangles found": "Dangle ditemukan", "written to the QA layer": "ditulis ke layer QA",
    "Gaps snapped": "Celah disambung", "within tolerance": "dalam toleransi",
    "Overshoots trimmed": "Kelebihan ujung dipangkas", "Disconnected parts": "Bagian terputus", "of the network": "dari jaringan",
    "Issues": "Masalah", "see the QA layers": "lihat layer QA",
    "Manual edits applied": "Suntingan manual diterapkan",
    "Canals burned in": "Kanal dibakar ke raster", "flow-routing raster only": "hanya raster penelusuran aliran",
    "Segments": "Segmen", "Short pieces flagged": "Potongan pendek ditandai", "kept, not scored": "disimpan, tidak dinilai",
    "Profile stations": "Stasiun profil", "Unresolved directions": "Arah belum terselesaikan", "flat canals": "kanal datar",
    "Segments scored": "Segmen dinilai", "Selected as targets": "Terpilih sebagai sasaran", "Not feasible": "Tidak layak",
    "filtered after scoring": "disaring setelah penilaian",
    "Existing sekat": "Sekat yang ada", "Sekat proposed": "Sekat diusulkan", "ready to review": "siap ditinjau",
    "Unsnapped points": "Titik tak tersambung", "listed in the log": "tercantum di log",
    "Network nodes": "Simpul jaringan", "Network edges": "Ruas jaringan",
    "Water sources": "Sumber air", "Targets": "Sasaran", "Routes": "Rute", "Unreachable targets": "Sasaran tak terjangkau",
    "see the QA layer": "lihat layer QA",
    "Pump stations": "Stasiun pompa", "Gates required": "Pintu air dibutuhkan", "Capacity shortfalls": "Kekurangan kapasitas",
    "Warnings": "Peringatan", "Parameters still unset": "Parameter yang masih kosong",
    # ---------------------------------------------------------------- review hints
    "Open the dangles and gaps layers. Snaps above the tolerance need your decision. To fix canals, add a canal-edits layer in the run setup (stage 1) and re-run from stage 1, or change the snap tolerance below and re-run this stage.":
        "Buka layer dangle dan celah. Penyambungan di atas toleransi membutuhkan keputusan Anda. Untuk memperbaiki kanal, tambahkan layer suntingan kanal pada pengaturan proses (tahap 1) lalu jalankan ulang dari tahap 1, atau ubah toleransi di bawah dan jalankan ulang tahap ini.",
    "Look at the ranking on the map and the sensitivity table. If the top segments change a lot when weights move, discuss the weights.":
        "Lihat peringkat di peta dan tabel sensitivitas. Jika segmen teratas banyak berubah saat bobot digeser, bahaslah bobotnya.",
    "Check that each target is connected to a source. Unreachable targets usually mean a block without a gate.":
        "Periksa bahwa setiap sasaran terhubung ke sumber. Sasaran yang tak terjangkau biasanya berarti ada sekat tanpa pintu air.",
    # ---------------------------------------------------------------- statuses and messages from the view-model
    "Ready to run": "Siap dijalankan", "Running": "Sedang berjalan", "Interrupted": "Terhenti", "Failed": "Gagal",
    "Needs your review": "Perlu tinjauan Anda", "Done": "Selesai", "Locked": "Terkunci", "Locked, review stage": "Terkunci, tahap tinjauan",
    "Out of date": "Usang",
    "The last run was interrupted. Run it again.": "Proses terakhir terhenti. Jalankan lagi.",
    "The engine environment is not set up yet.": "Lingkungan mesin belum disiapkan.",
    "1 required value is empty": "1 nilai wajib masih kosong", "{n} required values are empty": "{n} nilai wajib masih kosong",
    "Re-run stage {n} first.": "Jalankan ulang tahap {n} dahulu.",
    "Stage {n} changed, so this stage is out of date.": "Tahap {n} berubah, sehingga tahap ini usang.",
    "A setting changed after this stage ran. Re-run it to apply the change.":
        "Ada pengaturan yang berubah setelah tahap ini dijalankan. Jalankan ulang untuk menerapkan perubahan.",
    # ---------------------------------------------------------------- parameter fields: label, help, unit
    "Clip margin around sub-KHGs": "Margin pemotongan di sekitar sub-KHG",
    "Extra distance kept around the selected sub-KHGs.": "Jarak tambahan yang dipertahankan di sekitar sub-KHG terpilih.",
    "DTM vertical accuracy (RMSE)": "Akurasi vertikal DTM (RMSE)",
    "From the LiDAR provider. Needed to judge if a dA step is larger than the DTM noise.":
        "Dari penyedia data LiDAR. Diperlukan untuk menilai apakah satu langkah dA lebih besar daripada derau DTM.",
    "Moisture index: higher means wetter": "Indeks kelembapan: nilai lebih tinggi berarti lebih basah",
    "Depends on the index used (check its definition).": "Tergantung indeks yang dipakai (periksa definisinya).",
    "Vertical datum of the DTM": "Datum vertikal DTM",
    "Must be the same as the river water levels. Needed if river levels are used.":
        "Harus sama dengan datum tinggi muka air sungai. Diperlukan jika tinggi muka air sungai dipakai.",
    "Vertical datum of river water levels": "Datum vertikal tinggi muka air sungai",
    "Needed if the rivers layer has dry-season water levels.": "Diperlukan jika layer sungai memuat tinggi muka air musim kemarau.",
    "Snap tolerance": "Toleransi penyambungan",
    "Canal ends closer than this are joined. Larger snaps are listed for your review.":
        "Ujung kanal yang lebih dekat dari nilai ini disambung. Penyambungan yang lebih jauh dicantumkan untuk Anda tinjau.",
    "Maximum breach distance": "Jarak penembusan maksimum",
    "How far a pit may be breached before it is filled instead.": "Seberapa jauh cekungan boleh ditembus sebelum diisi.",
    "Upstream buffer": "Penyangga hulu",
    "Narrow buffer used to read flow accumulation along a segment.": "Penyangga sempit untuk membaca akumulasi aliran sepanjang segmen.",
    "Concession handling": "Penanganan konsesi",
    "Applied after scoring, never inside the need score.": "Diterapkan setelah penilaian, tidak pernah di dalam skor kebutuhan.",
    "Maximum sekat spacing": "Jarak antarsekat maksimum", "Upper bound on spacing between sekat.": "Batas atas jarak antarsekat.",
    "Snap tolerance for existing sekat": "Toleransi penyambungan sekat yang ada",
    "How far an existing sekat may be from a canal and still be attached to it.":
        "Seberapa jauh sekat yang ada boleh dari kanal dan tetap dikaitkan dengannya.",
    "Minimum sekat spacing": "Jarak antarsekat minimum",
    "No new sekat closer than this to an existing one.": "Tidak ada sekat baru yang lebih dekat dari nilai ini ke sekat yang ada.",
    "Uphill penalty (lambda)": "Penalti tanjakan (lambda)", "m per m of lift": "m per m angkatan",
    "Extra route cost per metre of lift: a proxy for pumping energy.": "Biaya rute tambahan per meter angkatan: pendekatan untuk energi pemompaan.",
    "Conveyance": "Penyaluran", "Pump into the canals (open channel) or through pipes.": "Memompa ke dalam kanal (saluran terbuka) atau melalui pipa.",
    "Manning roughness n": "Kekasaran Manning n", "Open-channel friction loss.": "Kehilangan akibat gesekan pada saluran terbuka.",
    "Hazen-Williams C": "Hazen-Williams C", "Pipe friction loss.": "Kehilangan akibat gesekan pada pipa.",
    "Pipe diameter": "Diameter pipa", "Pump efficiency": "Efisiensi pompa",
    "Maximum head per station": "Tinggi tekan maksimum per stasiun", "A new station is placed when this would be exceeded.":
        "Stasiun baru ditempatkan saat nilai ini akan terlampaui.",
    "Capacity per pump unit": "Kapasitas per unit pompa",
    "Canal influence distance": "Jarak pengaruh kanal",
    "How far from a canal the peat is rewetted. Calibrate with water-table observations.":
        "Seberapa jauh dari kanal gambut terbasahi kembali. Kalibrasi dengan pengamatan muka air tanah.",
    "Specific yield": "Hasil jenis (specific yield)", "Needed in specific-yield demand mode, and when there is no water deficit (neraca air).":
        "Diperlukan pada mode kebutuhan hasil jenis, dan saat tidak ada defisit air (neraca air).",
    "Design period": "Periode rancangan", "days": "hari",
    "The days over which the water must be delivered. Needed when the priority table does not give it.":
        "Jumlah hari untuk menyalurkan air tersebut. Diperlukan jika tabel prioritas tidak memberikannya.",
    "Sub-KHG priority table (CSV, optional)": "Tabel prioritas sub-KHG (CSV, opsional)",
    "Required water-table rise": "Kenaikan muka air tanah yang dibutuhkan",
    "AHP pairwise matrix": "Matriks perbandingan berpasangan AHP",
    "Edit this in the YAML file (a matrix cannot be typed here).": "Ubah ini di berkas YAML (matriks tidak dapat diketik di sini).",
    "Weight: {name}": "Bobot: {name}",
    "Relative importance of this criterion. Decided with the team; weights are normalised.":
        "Kepentingan relatif kriteria ini. Diputuskan bersama tim; bobot dinormalisasi.",
    "burn frequency": "frekuensi kebakaran", "peat depth": "kedalaman gambut", "dryness": "kekeringan", "upstream contribution": "kontribusi hulu",
    "cells": "sel", "0-1": "0-1",
    # ---------------------------------------------------------------- wizard chrome
    "Learn mode": "Mode belajar", "Show log": "Tampilkan log", "Hide log": "Sembunyikan log",
    "Run setup": "Pengaturan proses", "Edit setup": "Ubah pengaturan", "Hide setup": "Sembunyikan pengaturan",
    "Output GeoPackage (the run folder is its folder)": "GeoPackage keluaran (folder proses adalah foldernya)",
    "Starting config (policy parameters; yours are saved in the run folder)":
        "Konfigurasi awal (parameter kebijakan; milik Anda disimpan di folder proses)",
    "Sub-KHG priority table (CSV)": "Tabel prioritas sub-KHG (CSV)",
    "Bare-earth DTM (metres)": "DTM permukaan tanah (meter)", "Moisture index raster": "Raster indeks kelembapan",
    "Sub-KHG polygons": "Poligon sub-KHG", "Canal lines": "Garis kanal", "Canal edits (optional)": "Suntingan kanal (opsional)",
    "Existing sekat (optional)": "Sekat yang ada (opsional)",
    "River polygons or lines, the water sources (optional)": "Poligon atau garis sungai, sumber air (opsional)",
    "Burn-scar polygons": "Poligon bekas kebakaran", "Peat-depth polygons": "Poligon kedalaman gambut",
    "Create run": "Buat proses", "Open an existing run...": "Buka proses yang ada...", "Open a run config": "Buka konfigurasi proses",
    "Choose where the output GeoPackage should go.": "Pilih lokasi GeoPackage keluaran.",
    "Choose a starting config (YAML).": "Pilih konfigurasi awal (YAML).",
    "Use the proposed defaults (for trial runs, not team decisions)":
        "Gunakan nilai usulan (untuk uji coba, bukan keputusan tim)",
    "Fills the empty decision fields with researched starting values. Each one stays marked as proposed until you enter a value. Values you type always win.":
        "Mengisi kolom keputusan yang kosong dengan nilai awal hasil kajian. Setiap nilai tetap ditandai sebagai usulan sampai Anda mengisi nilainya sendiri. Nilai yang Anda ketik selalu didahulukan.",
    "Proposed default, not a team decision. Enter a value to make it yours; the run report lists it until then.":
        "Nilai usulan, bukan keputusan tim. Isi nilai untuk menjadikannya milik Anda; laporan proses mencantumkannya sampai saat itu.",
    "Could not turn on the proposed defaults: {err}": "Tidak dapat mengaktifkan nilai usulan: {err}",
    "Choose the sub-KHG priority table (CSV).": "Pilih tabel prioritas sub-KHG (CSV).",
    "Choose a layer for: {text}.": "Pilih layer untuk: {text}.",
    "{text}: the layer must be saved to a file (temporary layers cannot be passed to the engine).":
        "{text}: layer harus tersimpan sebagai berkas (layer sementara tidak dapat diteruskan ke mesin).",
    "Run folder: {path}": "Folder proses: {path}",
    "Re-run stage": "Jalankan ulang tahap",
    "Re-running stage {sid} clears the results of stages {first} to {last}, because they depend on it. Continue?":
        "Menjalankan ulang tahap {sid} menghapus hasil tahap {first} sampai {last}, karena bergantung padanya. Lanjutkan?",
    "Stage {n} of {total}": "Tahap {n} dari {total}", "No run yet": "Belum ada proses",
    "Rewetting with pompanisasi": "Pembasahan ulang dengan pompanisasi",
    "{done} of {total} stages done": "{done} dari {total} tahap selesai",
    "Start with the setup on stage 1": "Mulai dari pengaturan di tahap 1",
    "Set up": "Siapkan", "Set up engine": "Siapkan mesin", "Engine ready": "Mesin siap",
    "The engine is not set up": "Mesin belum disiapkan",
    "Use the Set up engine button on the left. It needs internet once and Python 3.11 or newer.":
        "Gunakan tombol Siapkan mesin di sebelah kiri. Perlu internet satu kali dan Python 3.11 atau lebih baru.",
    "This stage stopped": "Tahap ini berhenti", "These results are out of date": "Hasil ini sudah usang",
    "Your review is needed": "Tinjauan Anda diperlukan", "Worth a look": "Perlu diperiksa",
    "...and {n} more in the run report.": "...dan {n} lagi di laporan proses.", "Open run report": "Buka laporan proses",
    "STAGE {n}": "TAHAP {n}", " · REVIEW NEEDED": " · PERLU TINJAUAN", " · FAILED": " · GAGAL", " · RUNNING": " · BERJALAN",
    " · DONE": " · SELESAI", " · OUT OF DATE": " · USANG", " · REVIEW STAGE": " · TAHAP TINJAUAN",
    "What this does": "Apa yang dilakukan", "Why it matters": "Mengapa penting", "Reference:": "Referensi:",
    "Decisions for this stage": "Keputusan untuk tahap ini", "Decisions needed ({n})": "Keputusan yang diperlukan ({n})",
    "These values are policy choices for your team. The wizard never fills them in for you. They are saved in the run config.":
        "Nilai-nilai ini adalah pilihan kebijakan tim Anda. Wizard tidak pernah mengisinya untuk Anda. Nilai disimpan di konfigurasi proses.",
    "(needed if river water levels are used)": "(diperlukan jika tinggi muka air sungai dipakai)",
    "Edit this in the run YAML file (a matrix cannot be typed here).": "Ubah ini di berkas YAML proses (matriks tidak dapat diketik di sini).",
    "Not decided": "Belum diputuskan", "Not decided yet": "Belum diputuskan", "Yes": "Ya", "No": "Tidak",
    "Back": "Kembali", "Cancel run": "Batalkan proses",
    "Stage {n} is running. QGIS stays usable meanwhile.": "Tahap {n} sedang berjalan. QGIS tetap bisa dipakai.",
    "Set up your run on stage 1 first.": "Siapkan proses Anda di tahap 1 terlebih dahulu.",
    "Run stage": "Jalankan tahap", "Run stage {n}": "Jalankan tahap {n}",
    "Finish stage {n} first. You can already prepare its decisions.": "Selesaikan tahap {n} dahulu. Keputusannya sudah bisa Anda siapkan.",
    "Re-run this stage": "Jalankan ulang tahap ini", "Accept and continue": "Terima dan lanjutkan",
    "Accept and continue: {title}": "Terima dan lanjutkan: {title}", "Next: {title}": "Berikutnya: {title}",
    "Re-run to apply your change": "Jalankan ulang untuk menerapkan perubahan", "Run again": "Jalankan lagi",
    # ---------------------------------------------------------------- controller messages
    "The engine is older than the plugin. Click Set up engine to update it.":
        "Mesin lebih lama daripada plugin. Klik Siapkan mesin untuk memperbaruinya.",
    "Checking the engine...": "Memeriksa mesin...", "Could not check the engine.": "Mesin tidak dapat diperiksa.",
    "Setting up the engine environment (a few minutes, needs internet)...": "Menyiapkan lingkungan mesin (beberapa menit, perlu internet)...",
    "Engine setup failed: {err}": "Penyiapan mesin gagal: {err}", "Engine environment is ready.": "Lingkungan mesin sudah siap.",
    "The run config is not valid: {err}": "Konfigurasi proses tidak valid: {err}",
    "Stage {n} could not run: {err}": "Tahap {n} tidak dapat dijalankan: {err}",
    "Stage {n} was cancelled. Run it again when you are ready.": "Tahap {n} dibatalkan. Jalankan lagi saat Anda siap.",
    "Stage {n} failed. See the message on the card.": "Tahap {n} gagal. Lihat pesan pada kartu.",
    "Stage {n} is ready for your review.": "Tahap {n} siap Anda tinjau.", "Stage {n} finished.": "Tahap {n} selesai.",
    # ---------------------------------------------------------------- stage 12: optional block optimisation
    "Block optimisation": "Optimasi penempatan sekat",
    "Optional. Compares which of the proposed sekat to build first when you can only build some of them.":
        "Opsional. Membandingkan sekat usulan mana yang sebaiknya dibangun lebih dulu jika hanya sebagian yang dapat dibangun.",
    "Scores layouts of new sekat with a canal-level model (or a 2D groundwater model) and searches for the best layout with a genetic algorithm and simulated annealing, next to greedy, random and rule-based comparators.":
        "Menilai tata letak sekat baru dengan model tinggi muka air kanal (atau model air tanah 2D) dan mencari tata letak terbaik dengan algoritma genetika dan simulated annealing, dibandingkan dengan pilihan greedy, acak, dan berbasis aturan.",
    "Money and access limit how many sekat you can build. This shows which layout of the proposed sekat gives the most benefit. It is an alternative plan: the pump stages still assume every proposed sekat is built.":
        "Dana dan akses membatasi jumlah sekat yang dapat dibangun. Tahap ini menunjukkan tata letak sekat usulan yang memberi manfaat terbesar. Ini adalah rencana alternatif: tahap pompa tetap mengasumsikan semua sekat usulan dibangun.",
    "Candidate sites": "Lokasi kandidat", "proposed sekat": "sekat usulan", "Blocks to build": "Sekat yang dibangun",
    "Layouts scored": "Tata letak dinilai", "all algorithms": "semua algoritma", "Best method": "Metode terbaik",
    "Gain over random": "Keunggulan atas acak", "times the random mean": "kali rata-rata acak",
    "Optional, switched off": "Opsional, nonaktif",
    "Run the canal blocking optimisation": "Jalankan optimasi penempatan sekat kanal",
    "Optional. Chooses which proposed sekat to build first when you cannot build them all. It is an alternative plan and does not change the pump stages.":
        "Opsional. Memilih sekat usulan mana yang dibangun lebih dulu bila tidak semuanya dapat dibangun. Ini rencana alternatif dan tidak mengubah tahap pompa.",
    "How layouts are scored": "Cara menilai tata letak",
    "canal_rise is quick and needs few inputs. pde uses a groundwater model and needs the physical inputs below. screen_then_pde searches with canal rise and re-scores the winners with the groundwater model.":
        "canal_rise cepat dan butuh sedikit masukan. pde memakai model air tanah dan butuh masukan fisik di bawah. screen_then_pde mencari dengan kenaikan muka air kanal lalu menilai ulang pemenangnya dengan model air tanah.",
    "Number of new blocks": "Jumlah sekat baru", "blocks": "sekat", "How many of the proposed sekat you can build.": "Berapa banyak sekat usulan yang dapat Anda bangun.",
    "Search budget per algorithm": "Anggaran pencarian per algoritma", "layouts": "tata letak",
    "How many different layouts each algorithm may score. More is better but slower.": "Berapa tata letak berbeda yang boleh dinilai tiap algoritma. Lebih banyak lebih baik tetapi lebih lambat.",
    "Canal water level below the land": "Muka air kanal di bawah lahan", "Dry-season level of the canal water below the surrounding land.": "Tinggi muka air kanal di musim kemarau di bawah lahan sekitarnya.",
    "Groundwater grid cell size": "Ukuran sel grid air tanah", "Cell size of the groundwater model. Smaller is more detailed and slower.": "Ukuran sel model air tanah. Lebih kecil lebih rinci tetapi lebih lambat.",
    "Length of the dry spell": "Lama masa kering", "Days of drying simulated from a saturated start.": "Jumlah hari pengeringan yang disimulasikan dari kondisi jenuh.",
    "Net water loss without rain": "Kehilangan air bersih tanpa hujan", "mm/day": "mm/hari", "Evapotranspiration the peat loses each dry day.": "Evapotranspirasi yang hilang dari gambut setiap hari kering.",
    "Peat transmissivity multiplier": "Pengali transmisivitas gambut",
    "Scales the transmissivity of the built-in peat tables. Results depend strongly on it, so set it for your site.":
        "Mengalikan transmisivitas pada tabel gambut bawaan. Hasil sangat bergantung padanya, jadi tetapkan sesuai lokasi Anda.",
    " · OPTIONAL": " · OPSIONAL",
    "This optional stage is switched off. Choose Yes under Decisions to use it.": "Tahap opsional ini nonaktif. Pilih Ya di bawah Keputusan untuk memakainya.",
}
