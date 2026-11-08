# Status terbaru aplikasi

Diperbarui: 7 November 2026.

## Titik awal

- **`main` adalah satu-satunya versi acuan.** Semua pekerjaan baru (di Cursor atau di Claude) dimulai dari `main` terbaru: jalankan `git pull origin main` dulu sebelum mengubah apa pun.
- PR #1 (`perbaikan-audit-nov2026`, 2 Nov 2026) sudah **ditutup tanpa merge**. Isinya sudah tertinggal dari `main`. Jangan dipakai lagi.
- Setiap push ke `main` menarik kode baru ke Streamlit Community Cloud, lalu aplikasi perlu **di-Reboot** agar kode baru dipakai (`fileWatcherType = "none"`; lihat `DEPLOY_GRATIS.md`).

## Isi versi ini

Dasar: commit `bf17477` (5 Nov 2026), "Audit lanjutan": pembulatan QTY ke bawah, status stok seragam (Kurang = stok < prediksi + SS), Top 50 dari semua SKU, aktual hari penuh, prediksi vs bulan penuh terakhir, analisa prediksi (porsi iklan, tren, batas restock), kolom tabel bisa digeser, font dan tampilan tabel konsisten, tombol Analisa lebih cepat.

Perapian 7 Nov 2026 (tidak mengubah rumus prediksi, safety stock, atau data):

- Kartu analisa per SKU kini menyebut model yang benar-benar dipakai (**Ensemble**, atau **Level terkini** bila ensemble tidak tersedia). Sebelumnya selalu tertulis "Level terkini" walau tabel memakai Ensemble.
- Import dan variabel yang tidak terpakai dibuang (`app.py`, `src/core/preprocessing.py`, dua file tes).
- `README.md` ditulis ulang sesuai metode saat ini (ensemble walk-forward 6 lipatan, rumus stok, 4 role).
- `DEPLOY_GRATIS.md`: lokasi matriks hak akses dan daftar library yang dipasang disesuaikan.

Perbaikan tampilan 7 Nov 2026:

- Pindah halaman (mis. Buka riwayat → Ringkasan, atau ganti menu): sisa elemen halaman lama tidak lagi tampil acak di kolom halaman baru selama halaman baru dihitung.
- Tombol Buka di Riwayat analisa menampilkan indikator "Membuka hasil analisa …".
- Riwayat analisa di HP: baris tetap mendatar dan bisa digeser ke samping.
- `DEPLOY_GRATIS.md`: kunci akun 15 menit setelah 5× salah password (sesuai kode).

## Perbaikan hasil audit 7 Nov 2026 (98 temuan)

Dokumen audit: "Audit Tampilan & Fitur — Aplikasi Prediksi Item Terlaris Mitra10" (kode temuan B, D, R, P, DA, DF, RK, L, E, S, X).

Prioritas Tinggi (17, semua disetujui):
- S1 menu akun: isi pop-up tidak lagi ikut "dipaku" skrip header; pop-up di atas header (z-index).
- S2 usulan SKU dikecualikan mengabaikan label "[INCLUDE PACKING KAYU]"; S3 role bawaan Tambah user = Team DC.
- RK1/RK2 alokasi iklan berhenti di titik impas (ROAS marginal × margin ≥ 1), maks. 5× budget saat ini per SKU, strategi bawaan Efisien, keputusan "Jangan tambah".
- DA1 tabel SKU retur & batal satu baris per SKU; P1 prediksi vs aktual memakai hari penuh terakhir.
- L1/L2 grafik Tren laporan: dua dasar (sales produk = dasar prediksi, sales bersih = kartu), bulan berjalan ditandai dan tidak masuk moving average.
- E1–E3 Evaluasi: layanan SS 54,6% di Kelemahan + penjelasan, jumlah lipatan aktual, keterbatasan in-sample.
- R5 pergerakan "dibanding kemarin" kini membandingkan SKU Top 50 yang sama (sebelumnya semua SKU → −38% s.d. −55% semu).
- X1/R1/R2/R3 indikator memuat otomatis, kartu per SKU 10 dulu (rerun fragment), tabel restock selebar penuh; pengukur waktu `?debug=waktu` (super user).

Sedang & Rendah: format tanggal dd/mm/yyyy, angka/persen gaya Indonesia, teks Inggris diterjemahkan (unggah file, skor nama, Keluar, Varian, Semua), alasan batal ringkas, Laporan "Semua bagian" + cetak PDF, judul rekomendasi mempertahankan kode tipe & garansi, kalkulator biaya tanpa HPP, dll. Rincian per kode ada di dokumen audit.

Tidak diubah (perlu keputusan/data): label "Prediksi Nov 2026" (ketentuan review 2B, rentang tanggal ditambahkan di keterangan), istilah "Sales value", kuota flash sale (RK9), angka porsi iklan 95,9% (L6).

Uji: 184 tes lolos di Python 3.12; semua menu dan sub-menu diuji dengan Streamlit AppTest memakai data sintetis 2026 tanpa error.

## Revisi 7 Nov malam

- Periode Kuartal/Semester/Tahun mengikuti kalender (Kuartal I–IV = Jan–Mar … Okt–Des, Semester 1 = Jan–Jun, Semester 2 = Jul–Des); jendela prediksi = hari ini s.d. akhir periode kalender; pembanding = periode kalender sebelumnya. Bulan tetap 30 hari ke depan. `src/core/periods.py`.
- **Akar prediksi berubah-ubah (terbukti di data live 6 Nov):** saklar "Kecualikan batal & retur" ikut berpindah saat membuka analisa lama, lalu Jalankan analisa berikutnya mewarisinya (11:32 OFF = 427 unit/hari, 11:50 ON = 341 unit/hari, sidik data sama). Sekarang setelan data latih disimpan di Pengaturan bisnis (`analisa.kecualikan_batal_retur`), dipakai semua analisa baru, dan ditampilkan di Beranda; membuka analisa lama hanya mengubah tampilan.
- Konsistensi prediksi: diuji 4 kali (2× jalankan, 2× buka) dan di 2 proses dengan PYTHONHASHSEED berbeda → identik (830 SKU). Ditambah seed tetap + LightGBM deterministic, TZ selalu WIB, dan kolom Sidik data + Prediksi/hari di Riwayat analisa (⚠️ bila analisa dengan data/parameter/tanggal sama berbeda).
- Deskripsi selebar halaman (max-width seragam), tinggi baris tabel hanya naik bila teks > 90 huruf.
- Menu upload dikelompokkan (Penjualan, Iklan, Stok, Produk); "✓ Siap" hanya untuk menu yang diunggah & disimpan di sesi ini, lainnya "tersimpan dd/mm/yyyy".
- Rincian kecocokan: tabel bernomor, Muat 20 lagi, Unduh Excel, periode data; iklan belum terpetakan memuat SKU (varian) dari Data transaksi, biaya/omzet lewat mesin atribusi (tanpa dobel).

## Perhitungan iklan: acuan Semua Laporan Iklan (7 Nov 2026)

- Total biaya, omzet, ROAS = file **all iklan** (Semua Laporan Iklan); diuji dengan ekspor 01–07/11/2026: Rp 63.179.759 / Rp 961.507.139 / ROAS 15,22, sama persis.
- Rincian per produk = iklan produk otomatis + grup iklan + iklan satu produk di all iklan (cocok dengan total, selisih hanya jam unduh); dibagi ke varian menurut sales varian.
- Omzet tidak lagi dipotong sales SKU (sama dengan Seller Centre).
- Laporan diprorata per hari ke periode yang diminta; laporan menu sama yang rentangnya tumpang tindih → unggahan terakhir dipakai.
- Biaya harian = biaya ÷ hari yang tercakup laporan (sebelumnya laporan 7 hari dianggap sebulan → budget saat ini 4× terlalu kecil).
- ROAS perencanaan = 60% ROAS 30 hari + 40% ROAS 90 hari (riwayat iklan). Logika: `src/core/ads.py`.
- Cakupan tanggal iklan di Ringkasan data terkonsolidasi tidak lagi tertukar (01/05 – 01/11, bukan 05/01 – 11/01).

## Stok DC Site 10062 & 10036 (7 Nov 2026)

- Menu upload bertambah dari 9 menjadi 11: **Data stok Site 10062 (DC Cikupa)** dan **Data stok Site 10036 (DC Cipeucang)**, dari laporan ERP "Stock Qty and Value" (kolom Item No, Quantity, Blocked, Store Code). Item No tanpa nol di depan = SKU Shopee.
- Menu lama "Data stok" (kolom "Stok: DC Cikupa" di ekspor Shopee) sekarang bernama **Data stok Site 10037**; semua label "Stok DC Cikupa"/"Stok DC" diganti "Stok Site 10037".
- Bila stok Site 10037 < prediksi + SS, kekurangan diambil dulu dari Site 10062, lalu Site 10036; sisanya PO supplier (kolom "Ambil dari DC" di tabel restock Ringkasan, tabel Prediksi, rekomendasi Laporan, dan kartu analisa SKU). Stok Blocked = Yes tidak dihitung.
- Upload ditolak bila Store Code di file tidak sama dengan site menu yang dipilih. Snapshot DC disimpan 4 terakhir.
- Logika: `src/core/dc_stock.py`; tes: `tests/test_dc_stock.py`.

## Kalkulator margin: aktual dan prediksi bulan berjalan (8 Nov 2026)

- Kartu Ringkasan untuk bulan berjalan: **Penjualan aktual** (tgl 1 s.d. data terakhir), **Margin bersih aktual** (dihitung dari penjualan aktual bulan itu), **Prediksi penjualan** (aktual + prediksi sisa hari), dan **Prediksi margin bersih** (prediksi penjualan × margin aktual).
- SKU rugi, SKU margin rendah, dan daftar prioritas tetap mengikuti Periode analisa; margin periode itu tampil di kartu terpisah.
- Bulan yang sudah lewat: penjualan dan margin aktual bulan penuh, tanpa kartu prediksi.
- Kode: `src/ui/kalkulator.py` (`_summary`, `show_calculator`).

## Target sales bulanan & pencapaian (8 Nov 2026)

- Ubah data latih › Menu upload › **Target › Target sales bulanan** (dulu di Pengaturan bisnis): unduh template (Bulan, Target (Rp)), isi, unggah, simpan. Disimpan per bulan di tabel `sales_target` (bulan yang sama diganti; margin minimum & strategi iklan bulan itu tetap).
- Kolom lama "Target sales bulanan (Rp)" (satu angka untuk semua bulan) dihapus; `business_targets` tidak lagi memakai angka itu. Bulan tanpa target = "belum diunggah".
- Pencapaian = sales aktual ÷ target bulan yang sama. Rentang sebagian bulan memakai target prorata per hari kalender (contoh 1–8 Nov = target Nov × 8/30); persen ≥ 100% biru, di bawahnya merah.
- Tampil di: Ringkasan (kartu Sales bersih), Data (kartu Sales bersih), Laporan (kartu Sales bersih + garis target di grafik tren + tabel pencapaian per bulan), Prediksi vs aktual (omzet seluruh toko hari itu vs target harian), Folder data (kolom Target & Pencapaian target, baris Total), Kalkulator biaya (penjualan aktual & prediksi pencapaian).
- Kode: `src/core/targets.py` (parsing & prorata), `src/ui/targets_view.py` (unggah & baris pencapaian); tes: `tests/test_business.py`.
- Lokal: jalankan `streamlit run app.py --server.fileWatcherType auto` agar perubahan kode cukup Rerun (config repo mematikan file watcher untuk Cloud). Catatan: setelah file berubah, kadang semua menu tertulis "tidak punya akses" karena objek login lama tidak cocok dengan modul yang dimuat ulang; restart server lalu muat ulang halaman.

## Rekomendasi › Iklan: strategi kejar target (8 Nov 2026)

- Dirombak total. Hanya **iklan produk tunggal** dan **iklan grup** (plus usulan iklan produk tunggal baru); iklan otomatis tidak dihitung.
- Setelan di halaman ini (disimpan per bulan di `sales_target.budget_json`): **Target sales** (bawaan dari target bulanan), **Target ROAS**, **Budget iklan sisa bulan**. "Margin bersih minimum" dihapus; "Budget iklan maksimum" dihapus dari Pengaturan bisnis (Target ROAS di sana hanya nilai awal).
- Target ROAS = ROAS **rata-rata** seluruh iklan di rencana (arti yang sama dengan Target ROAS Shopee). Urutan: pindahkan budget dari iklan kurang efektif ke yang efektif → pangkas bila melebihi budget/ROAS → tambah ke iklan paling efektif sampai gap target tertutup (maks. 3× budget sekarang per iklan; iklan baru maks. Rp 100 rb/hari). Iklan dijeda dihitung dari omzet 0.
- Stok dan margin **tidak** membatasi rencana; tampil sebagai catatan per iklan (⚠️ stok kurang, margin minus) dan kotak catatan.
- Kesimpulan otomatis: bila target belum tercapai, tombol "Pakai budget …", "Pakai ROAS …", atau "Pakai ROAS … + budget" mengisi setelan; bila iklan saja tidak cukup, sisa gap diarahkan ke flash sale/voucher. Expander "Bandingkan target ROAS lain".
- Tabel per iklan: tindakan, budget harian sekarang → usulan, Target ROAS Shopee per iklan (ROAS rata-rata iklan itu pada budget usulan), tambahan omzet/hari, catatan; filter jenis & tindakan; Excel.
- Expander lama "Rencana iklan per periode (perhitungan sebelumnya)" dihapus.
- Kode: `src/core/ads_strategy.py` (`allocate_target`, `plan_effect`, `target_actions`, `budget_needed`, `roas_for_budget`, `ad_sales`), `src/ui/ads_target.py`; proyeksi bulan berjalan `src/ui/targets_view.py::month_outlook` (dipakai juga Kalkulator biaya). Tes: `tests/test_ads_target.py`.

## Pengaturan bisnis dihapus (8 Nov 2026)

- Expander "Pengaturan bisnis" di Ubah data latih dihapus (`src/ui/settings.py` dihapus). Semua angka diambil dari data/menu masing-masing:
  - Target sales bulanan → Menu upload › Target.
  - Target ROAS & budget iklan → Rekomendasi › Iklan per bulan. Bila bulan ini belum disimpan: target ROAS bulan terakhir yang tersimpan, lalu ROAS iklan berjalan. Laporan memakai target ROAS bulan laporan.
  - Margin → File margin; lead time impor → Setting › Kedatangan impor; kapasitas gudang → Setting › Kapasitas gudang.
  - Lead time lokal (7 hari) dan kapasitas unit optimasi restock (100.000) tetap dari `config/business_params.yaml` / nilai tersimpan; rumus safety stock tidak berubah.

## Parameter gudang & batas Shopee untuk iklan (8 Nov 2026)

- Setting › Kapasitas gudang: expander **"Parameter perhitungan stok & restock"** (`gudang_view.show_parameters`) menampilkan nilai yang dipakai algoritma beserta sumbernya: lead time lokal (diisi tim, bisa diubah di sini — file replenishment tidak memuat lead time; ROP di file ≈ 40 hari cakupan), σ lead time, lead time impor (dari Kedatangan impor), kapasitas restock, MOQ, biaya simpan/kehabisan.
- Kapasitas restock kini dari replenishment terbaru: Σ max(Max − stok, 0) per SKU (`gudang.restock_capacity`, disuntikkan di `app.current_params`). Snapshot 23/09/2026: 6.589 unit, 253 dari 756 SKU masih punya ruang. Nilai 100.000 hanya dipakai bila replenishment belum ada.
- Iklan mengikuti batas Shopee: Target ROAS per iklan maks. 30 (`MAX_SHOPEE_ROAS`); perubahan budget harian per minggu dibatasi ½×–2× atau jeda (`MAX_CHANGE = 2`), iklan baru maks. Rp 100 rb/hari. Rencana dibuat **mingguan**, diubah di Shopee setiap Senin dan tidak diubah sampai Minggu.
- Langkah baru **Pemilihan produk iklan** (`ads_strategy.product_selection`): dari hasil iklan 2 bulan, porsi omzet dalam grup, peringkat prediksi omzet, dan stok → Buat iklan tunggal, Jadikan iklan tunggal (maks. 10/minggu), Pertahankan, Pindahkan ke grup, Keluarkan dari grup, Jeda sampai restock. ROAS per iklan boleh bervariasi; yang dijaga ROAS rata-rata rencana ≥ target.

## Hasil pemeriksaan

- Lint (`ruff`, aturan F dan E9): bersih, tidak ada nama tak terdefinisi.
- Semua file Python bisa dikompilasi; sintaks aman untuk Python 3.9 (lokal) dan 3.11/3.12 (Streamlit Cloud).
- File YAML di `config/` dan `.streamlit/config.toml` valid.
- Status stok konsisten di semua modul (`inventory.py`, `decision_table.py`, `restock.py`, tampilan).
- Tes: 103 lolos di lingkungan pemeriksaan. Tes yang butuh `sqlalchemy`, `streamlit`, `statsmodels`, dan `xgboost` belum dijalankan di sana karena paketnya tidak terpasang. Jalankan `python -m pytest -q` di `.venv` lokal untuk hasil lengkap.

## Langkah berikutnya

Audit ulang per menu bersama pengguna, satu per satu:
Beranda → Data latih & Jalankan analisa → Ringkasan & Prediksi → Prediksi vs aktual → Data → Folder data → Rekomendasi → Laporan → Evaluasi model → Setting → Kelola user.
