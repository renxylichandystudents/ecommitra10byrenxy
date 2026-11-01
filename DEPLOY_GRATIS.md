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
9. **Wajib (login):** menu app → **Settings** → **Secrets**, tempel isi seperti `.streamlit/secrets.toml.example`:

   ```toml
   INITIAL_SUPERUSER_USERNAME = "renxy"
   INITIAL_SUPERUSER_PASSWORD = "password-min-8-karakter"
   # DATABASE_URL = "postgresql://user:password@host:5432/db?sslmode=require"
   ```

   Super user pertama dibuat otomatis saat tabel user masih kosong. User lain ditambahkan dari **Kelola user** (tidak ada pendaftaran mandiri). Saat lokal, simpan file yang sama sebagai `.streamlit/secrets.toml` (sudah di `.gitignore`).

### Login dan role

- Semua halaman berada di balik login. Password di-hash bcrypt, minimal 8 karakter. 5× salah password → tunggu 5 menit.
- User baru dan user yang di-reset wajib ganti password saat login berikutnya.
- Hak akses ada di satu tempat: `auth/permissions.py` (Super user, E-commerce specialist, IC, Gudang).
- Sesi login bertahan 8 jam: refresh, tab baru, dan tombol back browser tidak meminta login lagi. Cookie `mitra10_session` hanya berisi token acak; di database hanya disimpan hash token-nya (tabel `sessions`). Logout, nonaktifkan user, atau reset password menghapus sesi tersebut.
- Alamat halaman ada di URL (`?page=beranda`, `?page=data-latih`, `?page=analisa&tab=prediksi`, `?page=kelola-user`), jadi back/forward browser berpindah antarhalaman aplikasi.

### Perilaku data di server

- Semua user yang login memakai satu folder data tim yang sama (unggahan, Pengaturan bisnis, riwayat analisa).
- Default database: SQLite `data/app.db`. **Di Streamlit Community Cloud file ini hilang saat reboot/redeploy**, jadi user (selain super user dari Secrets) dan daftar riwayat ikut hilang. Isi `DATABASE_URL` Postgres gratis (Neon/Supabase) di Secrets agar user dan daftar riwayat tetap ada.
- File hasil analisa (`data/runs/<id>/`) dan laporan yang diunggah tetap di disk server, yang bersifat sementara: hilang saat aplikasi tidur (±12 jam tidak dibuka), reboot, atau redeploy. Riwayat yang filenya hilang tampil "File hasil hilang"; unggah ulang data dan jalankan analisa lagi.
- Riwayat analisa lebih dari 90 hari dihapus otomatis.

### Setelah deploy

- Setiap `git push origin main` otomatis memperbarui aplikasi.
- Bila build gagal, buka **Manage app** → log di kanan bawah untuk melihat paket yang gagal.
- Prophet, SHAP, dan LSTM sengaja tidak dipasang agar build ringan. Aplikasi memakai cadangan otomatis (ensemble MA28 + ES + GBM, permutation importance).
