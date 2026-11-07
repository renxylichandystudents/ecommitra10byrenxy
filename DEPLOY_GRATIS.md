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

### Database permanen (Neon, gratis) — agar login tidak hilang saat redeploy

1. Daftar di [neon.tech](https://neon.tech) (bisa login dengan GitHub) → **Create project**. Region: **AWS Asia Pacific (Singapore)**, versi Postgres bawaan.
2. Di dashboard project klik **Connect** → pilih **Pooled connection** → salin *connection string*, bentuknya:
   `postgresql://neondb_owner:xxxx@ep-xxxx-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require`
3. Streamlit Cloud → app → **Settings** → **Secrets**, tambahkan satu baris (dalam tanda kutip):

   ```toml
   DATABASE_URL = "postgresql://neondb_owner:xxxx@ep-xxxx-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
   ```

4. **Save** → app restart sendiri. Tabel dibuat otomatis saat app pertama dibuka; super user dibuat dari `INITIAL_SUPERUSER_*`.
5. Login sebagai super user, buka **Kelola user**: peringatan "SQLite di disk server sementara" harus sudah hilang. Buat ulang user lain (user di SQLite lama tidak bisa dipindahkan karena disk server sudah terhapus).

Catatan: bila password mengandung karakter `@ : / ? # %`, tulis dalam bentuk URL-encoded (mis. `@` → `%40`). Pakai Supabase? Gunakan URI **Session pooler** (port 5432), bukan *direct connection* (hanya IPv6). Neon gratis menidurkan database setelah ±5 menit tanpa akses; klik pertama sesudahnya ±1 detik lebih lambat, data tetap aman.

### Login dan role

- Semua halaman berada di balik login. Password di-hash bcrypt, minimal 8 karakter. 5× salah password → akun dikunci 15 menit.
- User baru dan user yang di-reset wajib ganti password saat login berikutnya.
- Hak akses ada di satu tempat: matriks `src/core/access.py` (Super user, E-commerce specialist, Team DC, Team IC/MD); `auth/permissions.py` hanya membacanya.
- Sesi login bertahan 12 jam sejak aktivitas terakhir (atur lewat secret `SESSION_TTL_HOURS`): refresh, tab baru, dan tombol back browser tidak meminta login lagi. Cookie `mitra10_session` hanya berisi token acak; di database hanya disimpan hash token-nya (tabel `sessions`). Logout, nonaktifkan user, atau reset password menghapus sesi tersebut.
- Alamat halaman ada di URL (`?page=beranda`, `?page=data-latih`, `?page=analisa&tab=prediksi`, `?page=kelola-user`), jadi back/forward browser berpindah antarhalaman aplikasi.

### Perilaku data di server

- Semua user yang login memakai satu folder data tim yang sama (unggahan, Pengaturan bisnis, riwayat analisa).
- Default database: SQLite `data/app.db`. **Di Streamlit Community Cloud file ini hilang saat reboot/redeploy**, jadi user (selain super user dari Secrets) dan daftar riwayat ikut hilang. Isi `DATABASE_URL` Postgres gratis (Neon/Supabase) di Secrets agar user dan daftar riwayat tetap ada.
- Data latih yang diunggah (folder bulan dan 9 menu) serta file hasil analisa (`data/runs/<id>/`) disalin otomatis ke tabel `file_vault` di Postgres. Saat server baru menyala (setelah tidur, reboot, atau redeploy), file dipulihkan ke disk sebelum halaman tampil, jadi data kemarin tetap terbaca tanpa unggah ulang. Status tampil di halaman Data latih. Tanpa `DATABASE_URL`, file tetap hanya di disk sementara.
- Cek connection string dari laptop: `.venv/bin/python scripts/cek_database.py` (pesan error tidak disensor seperti di Streamlit Cloud).
- Riwayat analisa lebih dari 90 hari dihapus otomatis.

### Setelah deploy

- Setiap `git push origin main` otomatis menarik kode baru ke server, **tetapi** karena `.streamlit/config.toml` memakai `fileWatcherType = "none"`, aplikasi yang sedang berjalan baru memakai kode baru setelah **Reboot** (share.streamlit.io → ⋮ di samping app → Reboot). Reboot memutus user yang sedang aktif; sesi login tetap tersimpan, cukup refresh.
- Bila build gagal, buka **Manage app** → log di kanan bawah untuk melihat paket yang gagal.
- `requirements.txt` memasang XGBoost, LightGBM, Prophet, dan SHAP. Bila salah satunya gagal dimuat di server, aplikasi otomatis memakai cadangan (HistGradientBoosting scikit-learn, permutation importance) dan menulis model yang dilewati di menu **Evaluasi model**. LSTM dan Sentence-BERT tidak dipasang karena butuh torch yang melebihi batas Streamlit Community Cloud.
