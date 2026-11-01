# Rencana Revisi Aplikasi Prediksi Item Terlaris

Dokumen ini dibuat sebelum Fase 1 sesuai instruksi review. Status awal repository sudah dipelajari: aplikasi Streamlit saat ini berpusat di `app.py`, modul perhitungan berada di `src/`, penyimpanan lama berada di `uploads/library`, dan test otomatis berada di `tests/`.

## Ringkasan Kondisi Saat Ini

- Entry point Streamlit: `app.py` (monolitik, mencakup upload, input parameter, navigasi tab, tabel, grafik, laporan, dan evaluasi model).
- Modul data saat ini: `src/ingest.py`, `src/library.py`, `src/activity.py`.
- Modul prediksi dan stok saat ini: `src/aggregate.py`, `src/forecast.py`, `src/ranking.py`, `src/stock.py`, `src/movement.py`.
- Modul evaluasi/intelligence saat ini: `src/intelligence/preprocess.py`, `src/intelligence/benchmark.py`, `src/intelligence/dashboard.py`.
- Test saat ini: `tests/test_movement.py`, `tests/test_intelligence.py`.
- Dependency saat ini: pandas, numpy, scikit-learn, statsmodels, xgboost, plotly, streamlit, openpyxl, python-dateutil.

## Peta File Existing ke Spesifikasi

| File saat ini | Bagian spesifikasi yang menyentuh | Rencana perubahan |
|---|---|---|
| `app.py` | 2, 3.1, 5.1-5.9, 7 | Dipecah bertahap: tetap menjadi entry point, tetapi logika upload/input, komponen bersama, tab Ringkasan, Prediksi, Data, Rekomendasi, Laporan, Evaluasi dipindahkan ke modul UI/services agar tidak terus membesar. Wording wajib Bagian 7 diterapkan di fase UI. |
| `src/ingest.py` | 3.1, 3.3, 3.4, 4.1 | Diperluas dari parser transaksi menjadi parser multi-sumber dengan validasi header per menu. Fungsi lama transaksi dipertahankan untuk kompatibilitas sampai data layer baru stabil. |
| `src/library.py` | 3.2 | Diganti/ditambah storage lokal Parquet/DuckDB. Penyimpanan lama per bulan `.pkl` menjadi jalur migrasi/fallback agar data lama masih bisa dibaca saat fase transisi. |
| `src/activity.py` | 5.5 | Dipakai ulang untuk Data tab: status pesanan, batal, retur, kontribusi invoice batal, pembeli belum bayar. Perlu disesuaikan dengan filter bersama dan format tabel baru. |
| `src/aggregate.py` | 2.1-2.4, 3.4 | Diperluas menjadi basis analisis `SKU x tanggal`, horizon bergulir, bulan berjalan kalender, dan agregasi lintas sumber. |
| `src/forecast.py` | 2.4, 4.4, 4.8 | Dirapikan menjadi forecasting service. Model lama "Level terkini" menjadi baseline/pembanding. Tambah fitur lag, kalender promo/libur, harga/diskon, iklan, performance, stok tersedia, walk-forward CV, WAPE, bias. |
| `src/stock.py` | 2.4, 4.4 | Rumus safety stock diganti dari `z x sigma x sqrt(hari)` ke rumus lead time yang diminta. Tambah ROP, hari cukup, status stok, lama kosong dari snapshot, multi-source siap config. |
| `src/ranking.py` | 2.3, 2.5, 5.3, 5.4 | Ranking mengikuti parameter Quantity/Sales. Tambah label produk Terlaris/Populer/Paling diminati/Perlu perhatian dan kontribusi Top 50. |
| `src/movement.py` | 5.3 R3-R4 | Snapshot prediksi harian sudah ada, perlu diperluas agar bisa difilter rentang Dari/Sampai dan menyimpan stok/SS/Butuh per horizon. |
| `src/intelligence/preprocess.py` | 4.1 | Saat ini hanya salinan uji. Perlu dipromosikan menjadi preprocessing produksi: KNN/MICE/median/mode, outlier flag promo vs winsorize non-promo, scaling, NLP dasar. |
| `src/intelligence/benchmark.py` | 4.8, 5.9 | Perlu diganti/ditambah evaluasi model tesis: walk-forward CV per horizon, MAPE/RMSE/WAPE/bias, Top 50 accuracy, perbandingan model lama vs model baru. |
| `src/intelligence/dashboard.py` | 5.9 | Diubah menjadi tab Evaluasi model sesuai 5 sub-bagian, bukan penjelasan cara memakai aplikasi. |
| `requirements.txt` | 1.7, 4 | Tambah dependency ringan yang wajib; library berat/opsional diberi try/except dan fallback. |
| `README.md` | Definition of Done pendukung | Perlu diperbarui setelah fase selesai agar dokumentasi sesuai aplikasi baru. |
| `tests/` | 4.9, DoD | Tambah fixture dan unit test rumus wajib, storage, dedup, snapshot stok, bulan berjalan, safety stock, ROP, lama kosong. |

## File Baru yang Akan Dibuat

| File/folder baru | Tujuan |
|---|---|
| `config/business_params.yaml` | Default lead time, kapasitas gudang, MOQ, biaya simpan, HPP/margin, target sales, ambang label produk, batas judul/deskripsi Shopee, template flash sale, parameter sumber stok. Bisa diubah dari UI expander "Pengaturan bisnis". |
| `config/rules.yaml` | Aturan sistem pakar If-Then untuk stok, iklan, batal belum bayar, bundling, pricing, dan rekomendasi kerja. |
| `src/core/config.py` | Load/save config YAML, penanda nilai default, validasi parameter bisnis. |
| `src/core/storage.py` | Storage lokal/server-aware, dataset registry, dedup per sumber, metadata file, snapshot stok, snapshot prediksi harian. Target awal Parquet; DuckDB ditambahkan bila perlu untuk query besar. |
| `src/core/schemas.py` | Definisi 9 menu upload, sinonim kolom, kolom wajib, kunci dedup, status validasi "Siap/Cek kolom/Kosong". |
| `src/core/preprocessing.py` | Prapemrosesan produksi: resampling harian lengkap, missing value, outlier, flag promo, scaling, NLP dasar. |
| `src/core/consolidation.py` | Integrasi semua sumber menjadi basis `SKU x tanggal`, mapping Kode produk ke SKU, alokasi metrik iklan ke variasi. |
| `src/core/segmentation.py` | ABC/XYZ, K-Means/DBSCAN, classifier produktivitas, association rules, sequential pattern insight fallback. |
| `src/core/nlp_competitor.py` | NLP kompetitor, TF-IDF fallback, optional gensim/Sentence-BERT, keyword extraction, scoring nama, template synthesis judul/deskripsi. |
| `src/core/forecasting.py` | Forecasting global, ensemble, Prophet optional, LSTM/TFT optional, model cache joblib, evaluation hooks. |
| `src/core/inventory.py` | Safety stock baru, ROP, kebutuhan, selisih stok, status stok, hari cukup, lama stok kosong, Monte Carlo. |
| `src/core/optimization.py` | MILP optional PuLP/OR-Tools dengan fallback EOQ/ROP, dynamic pricing/markdown. |
| `src/core/expert_system.py` | Production rules, root cause analysis, rekomendasi langkah kerja terukur. |
| `src/core/evaluation.py` | Walk-forward CV, MAPE/RMSE/WAPE/bias, Top 50 accuracy, status algoritma aktif/dilewati. |
| `src/ui/shared.py` | Komponen bersama: filter periode penjualan, toggle Exclude return & batal, format angka, tabel sticky/scroll, download Excel, header config. |
| `src/ui/input_page.py` | Halaman input baru: upload 9 menu, periode analisis data latih, parameter, AnalysisConfig. |
| `src/ui/ringkasan.py` | Tab Ringkasan sesuai R1-R9. |
| `src/ui/prediksi.py` | Tab Prediksi dengan tabel semua produk dan grafik reusable. |
| `src/ui/data_tab.py` | Tab Data yang hanya membaca transaksi/performance sesuai periode user. |
| `src/ui/rekomendasi.py` | Tab baru Rekomendasi dengan 4 sub-tab. |
| `src/ui/laporan.py` | Laporan dengan daftar isi kiri, slide direktur/CEO, SWOT, fishbone, panduan kerja. |
| `src/ui/evaluasi.py` | Evaluasi model baru sesuai 5 sub-bagian. |
| `tests/fixtures/` | Data dummy transaksi, stok, iklan, performance, deskripsi, kompetitor untuk test. Tidak dipakai UI. |

## Urutan Fase

### Fase 1 - Data layer

Target:
- Membuat definisi 9 menu upload dan validasi header.
- Menyimpan data lokal secara persistent, submit baru menambah/memperbarui data lama.
- Dedup sesuai kunci tiap sumber.
- Snapshot stok tidak ditimpa.
- Ringkasan konsolidasi per sumber.

File utama:
- `src/core/schemas.py`
- `src/core/storage.py`
- `src/core/consolidation.py`
- perubahan terbatas di `src/ingest.py`, `src/library.py`, `app.py`
- `tests/test_storage.py`, `tests/fixtures/`

Verifikasi:
- `pytest tests/test_storage.py`
- `streamlit run app.py` harus tetap start tanpa error.

### Fase 2 - Prapemrosesan & segmentasi

Target:
- Resampling harian lengkap per SKU.
- Penjualan 0 dipertahankan sebagai 0, bukan diimpute.
- Missing value, outlier, promo flag, scaling, NLP dasar.
- ABC/XYZ, clustering, classifier produktivitas, association rules/sequential insight dengan fallback jika library tidak tersedia.

File utama:
- `src/core/preprocessing.py`
- `src/core/segmentation.py`
- perluasan `src/intelligence/preprocess.py` atau migrasi bertahap.

Verifikasi:
- Unit test preprocessing: nol tidak berubah, promo spike tidak dibuang, non-promo winsorize.
- Unit test ABC/XYZ dan label segmentasi minimal berjalan di fixture.

### Fase 3 - Forecasting, safety stock, optimisasi, Monte Carlo

Target:
- `AnalysisConfig` menjadi sumber kebenaran per analisis.
- Horizon bergulir dari hari ini.
- Prediksi bulan berjalan = realisasi tanggal 1 s.d. kemarin + prediksi sisa bulan, dan tidak boleh lebih kecil dari realisasi.
- Prediksi sales = QTY x harga jual bersih rata-rata 4 minggu terakhir.
- Safety stock baru: umum, lokal, impor, z dari input user, residual backtest sebagai sigma bila tersedia.
- Kebutuhan = prediksi + SS; ROP; selisih stok; status stok; hari cukup; lama stok kosong.
- Snapshot prediksi harian diperluas.
- Optimisasi MILP optional dengan fallback EOQ/ROP; Monte Carlo.

File utama:
- `src/core/forecasting.py`
- `src/core/inventory.py`
- `src/core/optimization.py`
- `src/core/evaluation.py`
- adaptasi `src/forecast.py`, `src/stock.py`, `src/movement.py`.

Verifikasi:
- Unit test rumus 2.4.
- Unit test safety stock dan ROP.
- Unit test lama stok kosong dari snapshot.
- Smoke test Streamlit.

### Fase 4 - Halaman input

Target:
- Judul dan wording input sesuai checklist.
- Upload 9 menu dengan status per menu.
- `PERIODE ANALISIS DATA LATIH`, checkbox tahun/bulan tanpa dropdown "Semua tahun".
- Parameter periode prediksi segmented control, safety stock rekomendasi+dampak warna, Parameter card Quantity/Sales.
- Ringkasan konfigurasi dan `AnalysisConfig` di `st.session_state`.
- Expander "Pengaturan bisnis".

File utama:
- `src/ui/input_page.py`
- `src/ui/shared.py`
- `app.py`

Verifikasi:
- Manual smoke test UI.
- Test config load/save.

### Fase 5 - Komponen bersama dan Tab Ringkasan

Target:
- Filter periode penjualan reusable.
- Toggle "Exclude return & batal" reusable.
- Format angka Indonesia.
- Tabel/grafik reusable.
- R1-R9 diterapkan, termasuk matriks Top 50, kolom SS/Butuh/Stok, Analisa safety stock, grafik per SKU 2 panel.

File utama:
- `src/ui/shared.py`
- `src/ui/ringkasan.py`
- helper core untuk label produk dan analisa per SKU.

Verifikasi:
- Snapshot/tabel Top 50 pada fixture.
- Smoke test interaksi checkbox grafik.

### Fase 6 - Tab Prediksi dan Data

Target:
- Rename tab "Prediksi & stok" menjadi "Prediksi".
- Tab Prediksi memuat seluruh produk dengan tabel sama seperti R8.
- Hapus blok pergerakan dari tab Prediksi.
- Tab Data hanya aktual, sesuai periode user, tanpa tabel gabungan semua file.
- Rapikan kontribusi invoice batal, belum bayar, retur/batal SKU.

File utama:
- `src/ui/prediksi.py`
- `src/ui/data_tab.py`
- `src/activity.py`

Verifikasi:
- Unit test `unpaid_buyer_table`.
- Manual smoke test filter dan download Excel.

### Fase 7 - NLP kompetitor & sistem pakar dan Tab Rekomendasi

Target:
- NLP kompetitor dan SEO dengan fallback TF-IDF.
- Sistem pakar dari `config/rules.yaml`.
- Sub-tab Nama & deskripsi, Iklan, Flash sale toko, Exposure media sosial.
- Rekomendasi konsisten dengan stok: item stok kurang tidak disarankan untuk iklan/flash sale.

File utama:
- `src/core/nlp_competitor.py`
- `src/core/expert_system.py`
- `src/ui/rekomendasi.py`

Verifikasi:
- Unit test skor nama, deskripsi plain text, aturan stok/iklan.
- Excel export smoke test.

### Fase 8 - Laporan dan Evaluasi model

Target:
- Laporan dengan daftar isi kiri, chip parameter, 11 bagian direktur/CEO.
- SWOT dan fishbone berbasis angka nyata.
- Evaluasi model fokus algoritma: strategi sistem, pemodelan, hasil testing, perbandingan model, kesimpulan + SHAP jika tersedia/fallback feature importance.

File utama:
- `src/ui/laporan.py`
- `src/ui/evaluasi.py`
- `src/core/evaluation.py`

Verifikasi:
- Test evaluasi metrik MAPE/RMSE/WAPE/bias.
- Manual smoke test laporan.

### Fase 9 - Kinerja, ketahanan, dan testing

Target:
- Cache data/model dengan hash data+config.
- Joblib model cache.
- Graceful degradation untuk optional dependencies.
- Downsampling LTTB untuk grafik besar.
- Paginasi/lazy table.
- Test otomatis lengkap sesuai 4.9.

File utama:
- `src/core/cache.py` bila diperlukan.
- `requirements.txt`
- `tests/`

Verifikasi:
- `pytest`
- `streamlit run app.py`
- Catat target 4.9 tercapai/tidak dan alasannya di Evaluasi model serta update dokumen ini.

## Dependency dan Fallback

Wajib/ringan yang kemungkinan ditambahkan:
- `pyyaml` untuk config.
- `pyarrow` atau `duckdb` untuk storage lokal.
- `joblib` untuk model cache.
- `scipy` untuk z-score service level jika belum tercakup.
- `mlxtend` untuk association rules, dengan fallback rules sederhana bila tidak tersedia.
- `Sastrawi` untuk stemming Bahasa Indonesia, dengan fallback regex/lowercase/token sederhana bila tidak tersedia.
- `xlsxwriter` opsional untuk Excel styling; `openpyxl` sudah ada.

Opsional/berat:
- Prophet/NeuralProphet, LightGBM/CatBoost, sentence-transformers, gensim, PuLP/OR-Tools, SHAP, Redis, Celery.
- Semua import optional dilakukan di dalam fungsi `try/except`. Jika tidak tersedia, Evaluasi model mencatat "dilewati" beserta alasan dan sistem memakai fallback.

## Pertanyaan Terbuka

1. File review menyebut dokumen `.docx` di Downloads. Isi instruksi sudah dipaste lengkap di chat; untuk saat ini saya memakai teks chat sebagai sumber utama. Jika ada lampiran `.docx` yang berbeda dari teks chat, perlu dibandingkan sebelum implementasi fase lanjut.
2. Template resmi Shopee untuk flash sale toko belum ada di repo. Opsi aman: siapkan template konfigurasi default di `config/business_params.yaml` dan Excel generik sampai template resmi diberikan.
3. Data lead time pemasok, HPP/margin, MOQ, kapasitas gudang, target sales, dan sumber stok selain "Stok: DC Cikupa" belum ada. Opsi aman: pakai default config dan selalu tampilkan "memakai asumsi default" pada hasil yang bergantung pada nilai itu.
4. Data iklan memakai Kode produk level item, sedangkan transaksi memakai Nomor Referensi SKU. Opsi aman: mapping utama dari file produk; jika mapping hilang, produk iklan ditandai tidak terpetakan dan tidak dipaksakan ke SKU.
5. Data produk kompetitor kemungkinan punya format bebas. Opsi aman: parser fleksibel minimal nama toko, nama produk, harga, terjual, rating/ulasan bila ada; rekomendasi nama/deskripsi diberi status terbatas bila kolom tidak cukup.
6. Aplikasi saat ini menyimpan data lama di `uploads/library/*.pkl` di dalam repo. Spesifikasi meminta storage lokal `~/.prediksi_shopee/` atau server per browser ID. Opsi aman: buat storage baru dan sediakan pembaca data lama sebagai migrasi satu arah, tanpa menghapus data lama.
7. Target MAPE <= 15% mungkin tidak selalu tercapai pada SKU sporadis/bulky bahan bangunan. Opsi aman: laporkan tercapai/tidak per horizon dan tampilkan WAPE/bias sebagai pendamping, sesuai spesifikasi.

## Catatan Batas Implementasi

- Fitur yang tidak disebut dihapus tidak akan dihapus; hanya dipindahkan atau disesuaikan.
- Rumus prediksi, safety stock, dan data yang sudah dikunci tidak diubah di luar permintaan review ini.
- Angka contoh di dokumen review tidak akan di-hardcode.
- Fase berikutnya baru dimulai setelah rencana ini disetujui.

## Log Implementasi

### Fase 1 - Data layer

Status: selesai untuk fondasi data layer dan integrasi awal halaman input.

Perubahan:
- Menambahkan `src/core/schemas.py` untuk definisi 9 menu upload, sinonim kolom, validasi header, status Siap/Cek kolom/Kosong, dan canonical column mapping.
- Menambahkan `src/core/storage.py` untuk storage lokal di `~/.prediksi_shopee`, submit bertambah/memperbarui, dedup per sumber, metadata registry, dan snapshot stok yang tidak menimpa submit lama.
- Menambahkan `src/core/consolidation.py` untuk ringkasan per sumber, persentase SKU transaksi yang cocok stok, persentase produk iklan yang terpetakan ke SKU, jumlah snapshot stok, dan dasar lama kosong dari snapshot stok.
- Mengintegrasikan upload 9 menu ke `app.py`. Data transaksi tetap disalin juga ke storage lama `uploads/library` agar alur analisis yang sudah ada tetap berjalan selama fase transisi.
- Menambahkan fixture dan test `tests/test_data_layer.py`.

Verifikasi:
- `python -m unittest tests.test_data_layer tests.test_movement tests.test_intelligence` lulus 16 test di `.venv`.
- `py_compile` untuk `app.py` dan modul core baru lulus dengan `PYTHONPYCACHEPREFIX=.pycache`.
- Startup `streamlit run app.py` lulus smoke test singkat via subprocess bertimeout.

Catatan:
- Saat test, PyArrow menulis peringatan `sysctlbyname failed` dari sandbox macOS, tetapi test tetap lulus.
- Konsolidasi penuh `SKU x tanggal` baru fondasi awal; pemakaian sebagai basis model akan dilanjutkan di Fase 2-3 sesuai rencana.

### Fase 2 - Prapemrosesan & segmentasi

Status: selesai untuk modul produksi awal dan panel evaluasi.

Perubahan:
- Menambahkan `src/core/preprocessing.py` untuk kalender harian lengkap per SKU, promo flag, imputasi fitur non-penjualan, winsorization outlier non-promo, scaling, dan NLP dasar Bahasa Indonesia dengan fallback bila Sastrawi belum tersedia.
- Menambahkan `src/core/segmentation.py` untuk ABC/XYZ, fitur produk, K-Means/DBSCAN dengan fallback, label produktivitas, classifier produktivitas, association rules, dan insight pola berurutan sederhana.
- Menambahkan `tests/test_phase2_preprocessing_segmentation.py`.
- Menghubungkan hasil Fase 2 ke tab Evaluasi model melalui `src/intelligence/dashboard.py` sebagai panel "Prapemrosesan dan segmentasi produk"; panel ini tidak mengganti rumus prediksi utama.

Verifikasi:
- `python -m unittest tests.test_data_layer tests.test_phase2_preprocessing_segmentation tests.test_movement tests.test_intelligence` lulus 23 test di `.venv`.
- `py_compile` untuk `app.py`, modul Fase 2, dan dashboard evaluasi lulus.
- Startup `streamlit run app.py` lulus smoke test singkat via subprocess bertimeout.

Catatan:
- Warning PyArrow `sysctlbyname failed` masih muncul dari sandbox macOS saat test storage Parquet, tetapi tidak menggagalkan test.
- Association rules saat ini memakai fallback co-occurrence lokal; integrasi `mlxtend` bisa ditambahkan nanti bila dibutuhkan untuk FP-Growth/Apriori penuh.

### Fase 3–9 - Forecast ensemble, halaman input, tab hasil, laporan, evaluasi, deploy

Status: selesai.

Perubahan utama:
- Forecast: ensemble Level terkini + MA28 + Gradient Boosting global (+ Prophet bila terpasang), bobot invers WAPE walk-forward. Exponential Smoothing dipakai sebagai pembanding dan garis tren (spesifikasi 4.8), bukan anggota ensemble. Bobot disimpan per analisis agar "prediksi kemarin" di Pergerakan dihitung dengan bobot yang sama.
- Safety stock: saran service level per periode dari critical ratio newsvendor (margin, biaya kehabisan, biaya simpan) disesuaikan porsi kelas A/C (`src/core/service_level.py`), kotak dampak unit/rupiah/modal di halaman input, lead time dari `config/business_params.yaml`.
- Halaman input: "Pengaturan bisnis" (simpan/kembalikan default, label "memakai asumsi default"), pilihan Periode prediksi, Parameter, Safety stock dengan saran.
- Menu: Ringkasan · Prediksi · Data · Folder data · Rekomendasi · Laporan · Evaluasi model.
- Ringkasan (R1–R9): filter periode data aktual, kartu performa, pergerakan dari analisis sebelumnya + Pergerakan Top 50 dengan kolom stok, ringkasan total Top 50, papan prediksi QTY/sales dengan chip stok, tabel Top 50 + legenda label + definisi safety stock, dialog analisa per SKU (`src/ui/analysis_dialog.py`).
- Prediksi: "Prediksi semua produk" dengan pencarian, filter label/status, Tampilkan 10/50/100/200, pagination.
- Data: filter periode bersama, ringkasan performa toko & iklan, tabel kontribusi/pembeli belum bayar/SKU retur-batal dirapikan (baris total tebal, tooltip, multiselect alasan). "Tabel gabungan dari semua file" dihapus sesuai review.
- Rekomendasi (`src/ui/rekomendasi.py`): Nama & deskripsi, Iklan (produk/grup/tidak perlu), Flash sale toko (kalender + simpan CSV + template), Exposure media sosial.
- Laporan (`src/ui/laporan.py`): 11 bagian dengan daftar isi kiri, chip konteks, target sales, Monte Carlo + ROP, SWOT, fishbone, panduan kerja.
- Evaluasi model (`src/ui/evaluasi.py`): Strategi sistem, Pemodelan, Hasil testing (tabel 4.9), Perbandingan model, Kesimpulan + feature importance (SHAP bila ada, selain itu permutation importance).
- Deploy: mode server otomatis di Streamlit Cloud, folder data per browser (`?uid=`), `requirements.txt` diperbarui, langkah di `DEPLOY_GRATIS.md`.

Hasil kerangka pengujian 4.9 (data lokal Jan–Okt 2026, periode Bulan, 440 SKU):

| No | Komponen | Target | Hasil |
|---|---|---|---|
| 1 | Demand forecasting (walk-forward, MAPE agregat 7 hari) | ≤ 15% | 10,3% — tercapai |
| 2 | Safety stock, stress test keterlambatan impor | 0% stockout | 0,0% — tercapai |
| 3 | MILP restock Top 50 | 0% infeasible | Optimal — tercapai |
| 4 | Sistem pakar, NLP & SEO | 100% berjalan | 50/50, 0 saran tidak valid — tercapai |
| 5 | Tabel keputusan | < 3 detik (cache) | < 0,01 detik — tercapai |

Catatan: MAPE per SKU tetap tinggi (±85–120%) karena penjualan bahan bangunan banyak yang sporadis; WAPE dan bias ditampilkan sebagai pendamping. MAPE agregat horizon 28–30 hari ±17–21%, di atas target 15%.

Verifikasi:
- `python -m unittest discover -s tests` lulus 51 test.
- Smoke test `streamlit.testing.AppTest`: analisis penuh (Bulan ±55 detik dengan walk-forward, Kuartal ±60 detik) lalu ketujuh tab dan 11 bagian Laporan dibuka tanpa exception. Mode server (`PREDIKSI_DEPLOY_MODE=server`) membuat folder per browser dan halaman input terbuka tanpa error.

### Revisi 01-11-2026 (Prompt_Cursor_011126) - Fase 1–5

Status: selesai.

- Fase 1 (GL-01/02/03, RK-03, UI-01): format angka/rupiah bersama `src/utils/format.py` (`show_table`, `input_rupiah`, Excel angka asli), tinggi tabel dinamis, header sticky, deskripsi tanpa judul KAPITAL + ringkasan 60 karakter + panel detail/salin, input data latih berurutan dengan spinner lokal.
- Fase 2 (TR-01, RG-02, TR-05, RK-04): atribusi iklan per periode dan dibagi ke varian proporsional sales (`src/core/ads.py`), omzet iklan dibatasi sales aktual SKU; kartu pergerakan dengan aktual kemarin + Top 50 / All SKU; SKU retur & batal sebagai fragment + cache; alokasi budget iklan (`allocate_budget`).
- Fase 3 (RK-02, RK-05, RK-06): tag packing dipertahankan, kosakata dibatasi produk + `data/brand_dictionary.csv`, kata asing ditolak ("Perlu cek manual"); flash sale "Stok terbatas"; kalender exposure bulanan.
- Fase 4 (FB-02): login & role (`auth/`), bcrypt, kunci 5 menit setelah 5× gagal, wajib ganti password, Kelola user, super user terakhir dilindungi, repository SQLAlchemy (SQLite ↔ Postgres lewat `DATABASE_URL`).
- Fase 5 (FB-01): riwayat analisa (`src/core/runs.py`, tabel `analysis_runs`, hasil Parquet/pickle di `data/runs/<id>/`), Beranda "1. Analisa prediksi" + "2. Riwayat analisa", Buka tanpa hitung ulang (termasuk cache pergerakan stok), tawaran "Buka hasil tersimpan / Analisa ulang", analisa sukses terakhir dimuat saat app dibuka, hapus oleh super user, auto-hapus > 90 hari.

Pertanyaan terbuka tersisa:
- Template resmi Shopee untuk flash sale toko masih memakai template generik.
- Data stok belum diunggah pada data lokal, sehingga Flash sale toko dan chip stok menampilkan "belum ada data stok".
- Di Streamlit Cloud, xgboost (Linux) akan aktif menggantikan HistGradientBoosting; angka evaluasi bisa sedikit berbeda dari hasil lokal macOS.
