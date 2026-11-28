# Prediksi Stok Shopee

Aplikasi untuk menganalisis laporan transaksi Shopee dan memprediksi **hingga 50 item terlaris** serta **stok yang harus disiapkan** pada periode berikutnya.

User memilih:

- **Dasar peringkat** — kuantitas (qty) atau omzet (sales) tertinggi. Peringkat dihitung dari seluruh baris laporan dan selalu unik: jika qty atau omzet sama, pemecah seri memakai metrik satunya, jumlah pesanan, lalu pesanan terbaru.
- **Periode** — bulan, kuartal, semester, atau tahun. Prediksi qty, omzet, dan stok disarankan dijumlahkan sepanjang periode itu (1, 3, 6, atau 12 bulan).
- **Tingkat layanan (service level %)** — diubah ke z-score Normal, lalu cadangan = `z × sigma × √hari` (bukan persen buffer langsung dari prediksi).
- **Exclude return/batal** — opsional setelah analisis berjalan.

## Model produksi vs benchmark

**Produksi (hot path):** prediksi qty per SKU memakai **Level terkini** (level 28 hari terakhir + profil hari dalam seminggu). Forecast dibatasi ~100 kandidat histori teratas; UI menampilkan Top 50. Holdout MAPE/MAE/RMSE dihitung nyata per SKU.

**Bukan klaim produksi:** Naive / Moving Average / Holt / SARIMA / XGBoost **tidak** dipilih otomatis “MAPE terendah per SKU”. Model klasik hanya **benchmark opsional** di tab Evaluasi (tombol lazy pada total toko), bukan pemenang produksi.

Prediksi omzet = prediksi qty × harga jual rata-rata (omzet histori ÷ qty).

Rekomendasi stok = prediksi qty + cadangan service level. Bila stok aktual diisi: **reorder = max(0, disarankan − aktual)** dengan prioritas tinggi/sedang/pantau.

## Cara menjalankan

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/generate_sample.py
streamlit run app.py
```

Unggah CSV dari Seller Center Shopee (**Pengiriman → Pesanan saya → Ekspor** / laporan pesanan), atau centang data sampel demo. Pilih dasar peringkat dan periode, lalu klik **Jalankan analisis**. Hasil analisis di-cache di sesi: pindah menu tidak menghitung ulang; mengubah tingkat layanan hanya menghitung ulang cadangan/stok.

## Deploy ke Streamlit Community Cloud

Streamlit Community Cloud hanya membaca **GitHub** (bukan Origin). Kode produksi ada di Origin `renxy-lichandy/thesis` branch `main`, main file `app.py`.

1. Buat repo GitHub baru (contoh: `prediksi-stok-shopee`) di akun Anda.
2. Mirror / push isi `main` ke repo itu (sertakan `app.py`, `src/`, `requirements.txt`, `.streamlit/`, `data/`).
3. Buka https://share.streamlit.io/ → sign in dengan GitHub → **Create app**.
4. Isi: **Repository** = repo GitHub Anda, **Branch** = `main`, **Main file path** = `app.py`, Python ≥ 3.11.
5. Deploy; URL permanen berbentuk `https://….streamlit.app`.

## Kolom CSV yang dikenali

Aplikasi memetakan header Indonesia/Inggris secara otomatis, antara lain:

- Waktu Pesanan Dibuat
- Nama Produk, Nomor Referensi SKU (kolom P, pengenal produk), Nama Variasi (kolom Q)
- Jumlah, Total Harga atau Harga Setelah Diskon, Status Pesanan
- Opsional insight: pembeli, alasan batal/retur, returned quantity

Produk tanpa variasi dikunci oleh Nomor Referensi SKU. Produk dengan varian dibedakan Nama Variasi / referensi SKU.

## Catatan skripsi

Laporkan **Level terkini** sebagai model produksi beserta MAPE/RMSE holdout-nya. Bandingkan Naive/MA/Holt/SARIMA/XGBoost hanya sebagai pembanding total toko di Evaluasi — jangan klaim aplikasi memilih pemenang per SKU dari bake-off klasik.
