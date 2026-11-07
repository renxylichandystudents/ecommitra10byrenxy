# Mitra10 · Keputusan Stok & Penjualan Shopee

Aplikasi Streamlit untuk toko bahan bangunan Mitra10 di Shopee. Dipakai sehari-hari oleh tim e-commerce untuk keputusan stok, iklan, retur, dan batal, sekaligus sebagai artefak tesis Magister Teknik Informatika.

Aplikasi membaca laporan Seller Center Shopee, memprediksi **Top 50 item terlaris** (diurutkan dari seluruh SKU), lalu menghitung **stok yang harus disiapkan** per SKU.

> **Status terbaru:** lihat [`docs/STATUS.md`](docs/STATUS.md). Branch `main` adalah satu-satunya versi acuan; setiap push ke `main` otomatis men-deploy ulang aplikasi di Streamlit Community Cloud.

## Alur pemakaian

1. Login (tidak ada pendaftaran mandiri; user dibuat dari **Kelola user**).
2. **Ubah data latih & Jalankan analisa**: unggah 9 jenis data per bulan:
   data transaksi, performa toko, iklan produk otomatis, iklan produk grup, keseluruhan iklan, iklan pencarian, stok, deskripsi produk, dan produk kompetitor.
3. Pilih dasar peringkat (QTY atau sales), periode prediksi (bulan, kuartal, semester, tahun), dan service level, lalu klik **Jalankan analisa**.
4. Baca hasil di menu: Ringkasan & Prediksi, Prediksi vs aktual, Data, Folder data, Rekomendasi, Laporan, dan Evaluasi model.

Hak akses per menu diatur di satu tempat, `src/core/access.py`, untuk 4 role: **Super user**, **E-commerce specialist**, **Team DC**, dan **Team IC/MD**. Hanya Super user dan E-commerce specialist yang bisa mengubah data latih.

## Metode prediksi

Permintaan dibaca sebagai matriks harian SKU × tanggal (hari tanpa transaksi = 0; hari stok kosong dianggap permintaan tersensor, bukan permintaan rendah).

| Model | Keterangan |
| --- | --- |
| Level terkini | Metode lama (level 28 hari terakhir); juga menjadi cadangan bila model lain gagal |
| Moving Average 28 | Rata-rata 28 hari terakhir; menjadi ambang masuk ensemble |
| Exponential Smoothing | Simple exponential smoothing, α = 0,1 |
| XGBoost global | Fitur lag 1/7/14/28, rolling, kalender promo, flag stok (cadangan: HistGradientBoosting scikit-learn) |
| LightGBM global | Fitur sama dengan XGBoost |
| Prophet | Total toko + regresor promo, dibagi ke SKU |

**Prediksi akhir = Ensemble.** Setiap model diuji dengan walk-forward 6 lipatan untuk horizon hari, minggu, bulan, dan kuartal. Hanya model yang WAPE-nya lebih kecil dari Moving Average 28 yang masuk ensemble, dengan bobot 1/WAPE, lalu dikoreksi faktor bias. Bila tidak ada model yang mengalahkan MA28, MA28 dipakai sendiri. Semua angka di menu **Evaluasi model** (MAPE, RMSE, WAPE, bias) dibaca dari record walk-forward yang sama.

- Prediksi QTY dibulatkan ke bawah (unit pecahan tidak bisa terjual).
- Prediksi sales = QTY × harga bersih rata-rata 4 minggu terakhir.

## Stok

- **Safety stock (lokal)** = Z × σ harian × √lead time (default lead time 7 hari, `config/business_params.yaml`).
  Bila variasi lead time diisi: Z × √(L × σ_D² + D² × σ_L²). Bila sumber impor: (L maks − L rata-rata) × D.
- **Kebutuhan** = prediksi + safety stock.
- **Status stok** (sama di semua menu): *Kosong* bila stok 0, *Kurang* bila stok < prediksi + SS, *Aman* bila sebaliknya, *Tanpa data stok* bila SKU tidak ada di data stok.
- **Restock** = kebutuhan − stok (dibulatkan ke atas); ROP = permintaan harian × lead time + SS.

## Menjalankan di komputer

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # isi INITIAL_SUPERUSER_*
streamlit run app.py
```

Di Mac cukup double-click `Buka Thesis Localhost.command`. Panduan deploy permanen (Streamlit Community Cloud + database Neon) ada di [`DEPLOY_GRATIS.md`](DEPLOY_GRATIS.md).

## Tes

```bash
python -m pytest -q
```

Tes ada di `tests/` (rumus stok, metrik, walk-forward, ensemble, akses role, login, penyimpanan file, format angka, dan routing halaman).

## Struktur folder

| Folder | Isi |
| --- | --- |
| `app.py` | Entry point Streamlit dan sebagian besar halaman |
| `auth/` | Login, sesi cookie, hash password, kelola user |
| `src/core/` | Logika bisnis: ensemble, evaluasi, stok, iklan, margin, rekomendasi, sistem pakar, database |
| `src/models/` | Walk-forward CV per horizon |
| `src/ui/` | Halaman dan komponen tampilan |
| `config/` | Parameter bisnis, aturan sistem pakar, alasan batal |
| `components/top50_table/` | Tabel Top 50 kustom (HTML) |
| `docs/` | Status terbaru dan rencana revisi |

## Catatan tesis

Konteks penelitian adalah pengambilan keputusan e-commerce Mitra10, supermarket bahan bangunan. Gunakan menu **Evaluasi model** untuk bab metode dan hasil (perbandingan model pada walk-forward); menu lain untuk keputusan harian.
