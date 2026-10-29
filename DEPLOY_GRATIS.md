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

Untuk link permanen yang tidak bergantung pada Mac menyala, pilihan paling mudah adalah Streamlit Community Cloud:

1. Push project ke GitHub.
2. Buka `https://share.streamlit.io`.
3. Pilih repository project thesis.
4. Set main file ke `app.py`.
5. Deploy.

Catatan: Streamlit Community Cloud membutuhkan akun GitHub/Streamlit. Project ini sekarang memakai remote Cursor Origin, jadi perlu dibuatkan mirror/repository GitHub dulu sebelum bisa deploy permanen di Streamlit Cloud.
