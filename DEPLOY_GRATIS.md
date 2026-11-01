# Deploy gratis aplikasi thesis

## Buka di Mac ini tanpa Cursor

Double-click file:

```bash
Buka Thesis Localhost.command
```

File ini akan membuka aplikasi di:

```text
http://localhost:8501
```

Biarkan jendela Terminal tetap terbuka selama aplikasi dipakai.

## Bagikan ke internet gratis sementara

Double-click file:

```bash
Share Thesis Internet.command
```

Terminal akan menampilkan URL `https://...localhost.run`. Link itu bisa dibuka dari internet selama:

- Mac menyala.
- Internet Mac aktif.
- Jendela Terminal tunnel tetap terbuka.

Ini cocok untuk demo cepat. Link bisa berubah setiap kali dijalankan.

## Deploy gratis permanen

Untuk link permanen yang tidak bergantung pada Mac menyala, pakai Streamlit Community Cloud.
Repository GitHub: `renxylichandystudents/ecommitra10byrenxy`, branch `main`.

1. Commit dan push perubahan ke GitHub:

   ```bash
   git add -A
   git commit -m "Revisi aplikasi prediksi item terlaris sesuai review v4"
   git push origin main
   ```

   File laporan Shopee (`uploads/`, `*.xlsx`) tidak ikut ter-push karena sudah ada di `.gitignore`.
2. Buka [share.streamlit.io](https://share.streamlit.io), login dengan akun GitHub.
3. Klik **Create app** → **Deploy a public app from GitHub**.
4. Isi: Repository `renxylichandystudents/ecommitra10byrenxy`, Branch `main`, Main file path `app.py`.
5. Di **Advanced settings** pilih Python **3.11** atau **3.12**.
6. (Opsional) atur App URL, misalnya `prediksi-mitra10`.
7. Klik **Deploy**. Build pertama ±5–10 menit karena memasang scikit-learn, statsmodels, xgboost, dan PuLP.
8. Supaya bisa dibuka siapa saja: menu app → **Settings** → **Sharing** → pilih **This app is public and searchable** (atau public tanpa login).

### Perilaku data di server

- Aplikasi otomatis masuk mode server di Streamlit Cloud. Setiap browser mendapat folder data sendiri, ditandai parameter `?uid=...` di URL, sehingga pengunjung lain tidak melihat data Anda.
- Simpan link lengkap dengan `?uid=...` bila ingin kembali ke data yang sama. Jangan bagikan link ber-`uid` itu ke orang lain.
- Penyimpanan Streamlit Cloud bersifat sementara: data hilang saat aplikasi tidur (tidak dibuka ±12 jam), di-reboot, atau di-deploy ulang. Unggah ulang laporan Shopee bila itu terjadi.
- Pengaturan bisnis yang disimpan dari menu "Pengaturan bisnis" juga per browser. Nilai default untuk semua pengunjung ada di `config/business_params.yaml`.

### Setelah deploy

- Setiap `git push origin main` otomatis memperbarui aplikasi.
- Bila build gagal, buka **Manage app** → log di kanan bawah untuk melihat paket yang gagal.
- Prophet, SHAP, dan LSTM sengaja tidak dipasang agar build ringan. Aplikasi memakai cadangan otomatis (ensemble MA28 + ES + GBM, permutation importance).
