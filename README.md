# Prediksi Stok Shopee

Aplikasi untuk menganalisis laporan transaksi Shopee dan memprediksi **hingga 50 item terlaris** serta **stok yang harus disiapkan** pada periode berikutnya.

User memilih:

- **Dasar peringkat** — kuantitas (qty) atau omzet (sales) tertinggi. Peringkat dihitung dari seluruh baris laporan dan selalu unik: jika qty atau omzet sama, pemecah seri memakai metrik satunya, jumlah pesanan, lalu pesanan terbaru.
- **Periode** — bulan, kuartal, semester, atau tahun. Prediksi qty, omzet, dan stok disarankan dijumlahkan sepanjang periode itu (1, 3, 6, atau 12 bulan). Laporan yang lebih pendek dari 3 bulan diproyeksikan dari pola harian.
- **Status pesanan** — daftar diambil dari laporan. Default-nya semua status kecuali batal, cancel, atau unpaid.

Tidak ada satu algoritma yang selalu terbaik untuk semua SKU. Aplikasi menguji beberapa model pada data hold-out, lalu memilih model dengan **MAPE terendah per item untuk kuantitas**. Prediksi omzet = prediksi qty × harga jual rata-rata (omzet histori ÷ qty), karena di Shopee omzet mengikuti harga setelah diskon. Omzet baru berlawanan arah dengan qty bila harga jualnya berubah.

## Model yang dibandingkan

| Model | Kapan biasanya unggul |
| --- | --- |
| Naive / Seasonal Naive | Baseline, pola musiman sederhana |
| Moving Average | Histori pendek atau data berisik |
| Holt-Winters / Holt Linear | Tren + musim (Ramadan, 12.12) |
| ARIMA / SARIMA | Otokorelasi dan musim kalender |
| XGBoost (fitur lag) | Banyak titik data, pola non-linear |

Rekomendasi stok = prediksi qty pada periode yang dipilih + safety stock (`z × standar deviasi × akar langkah horizon`), dalam satuan unit.

## Cara menjalankan

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/generate_sample.py
streamlit run app.py
```

Unggah CSV dari Seller Center Shopee (**Pengiriman → Pesanan saya → Ekspor** / laporan pesanan), atau centang data sampel demo. Pilih dasar peringkat, periode, dan status pesanan, lalu klik **Jalankan analisis**. Tab **Prediksi & stok** menampilkan hingga 50 item terlaris beserta prediksi qty, prediksi omzet, dan stok disarankan. Hasil yang sama bisa diunduh sebagai CSV.

## Kolom CSV yang dikenali

Aplikasi memetakan header Indonesia/Inggris secara otomatis, antara lain:

- Waktu Pesanan Dibuat
- Nama Produk, Nomor Referensi SKU (kolom P, pengenal produk), Nama Variasi (kolom Q)

Produk tanpa variasi dikunci oleh Nomor Referensi SKU. Produk dengan varian memiliki nama yang sama; tiap pilihan (warna, ukuran, dan sejenisnya) punya referensi SKU sendiri dan dibedakan oleh Nama Variasi, jadi tidak digabung menjadi satu item. SKU Induk tidak dipakai sebagai kunci karena satu induk bisa mencakup beberapa varian.
- Jumlah
- Total Harga atau Harga Setelah Diskon
- Status Pesanan (bisa dipilih setelah file terbaca; batal tidak ikut secara default)

Laporan Excel Seller Center (`Order.all....xlsx`) dikenali dari isi filenya, bukan hanya dari ekstensi. Harga berformat Indonesia seperti `1.226.842` atau `49.000` dibaca sebagai omzet satuan. Status “Pesanan diterima … hingga tanggal” digabung menjadi **Pesanan Diterima** supaya bisa dipilih sebagai satu status.

## Catatan skripsi

Hasil “algoritma terbaik” bersifat empiris: lihat tab **Evaluasi model** setelah file dianalisis. Laporkan MAPE/RMSE rata-rata per model, lalu jelaskan model mana yang paling sering menang pada dataset toko Anda.
