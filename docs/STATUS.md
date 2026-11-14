# Status terbaru aplikasi

Diperbarui: 13 November 2026.

## Ringkasan: Outstanding Site 10037 untuk SKU kosong/kurang padahal DC ada stok (14 Nov 2026)

- Masukan pengguna: barang keluar Site 10037 hanya barang terjual, jadi PO/TR/TO/TR dari toko lain semuanya barang masuk. Yang dibutuhkan: SKU kosong/kurang di Site 10037 padahal stok Site 10062/10036 ada, dan sudah berapa lama outstanding-nya belum diterima (bahan tanya tim gudang).
- Bagian baru di bawah tabel Kebutuhan restock prioritas: kartu (jumlah SKU, belum ada outstanding, outstanding ≥ 3 hari, outstanding menutup kebutuhan) + tabel semua SKU berprediksi (Rank bila Top 50, stok 10037/10062/10036, kebutuhan restock 30 hari, outstanding per jenis, total, Outstanding sejak, Umur, Keterangan) + Excel. Urut kosong dulu lalu umur terlama.
- Umur (`insight_live.outstanding_age`): per jenis, unggahan replenishment pertama dari rangkaian terakhir bernilai > 0; berhenti di 0. Kolom yang belum tercatat di snapshot lama (TO & TR dari toko lain sebelum 14/11) atau rangkaian sampai snapshot tertua → minimal ("≤ tanggal", "≥ N hari"). Riwayat dari semua snapshot `warehouse_replenishment` (`FeatureData.replenishment_history`). Unggahan tidak harian, jadi umur = sejak unggahan yang pertama mencatat.
- Data 14 Nov (snapshot 23/09, 9/11, 10/11, 12/11, 14/11; analisa 16): 90 SKU kosong/kurang padahal DC ada stok (12 kosong, 31 Top 50); 65 belum ada outstanding; 7 outstanding 4–5 hari belum diterima; 15 hanya TO/TR toko lain (umur belum diketahui).
- Tes `test_outstanding_age_runs_and_minimal`, `test_stuck_outstanding_only_short_with_dc_stock`.

## Insight Ringkasan: bulan berjalan, iklan yang sedang berjalan, outstanding PO/TR/TO (14 Nov 2026)

- **Bulan berjalan**: SKU Top 50 yang perlu restock untuk sisa bulan = prediksi sisa bulan (unit utuh, `run_rest_qty`) + SS − stok Site 10037, dibagi DC (10062 → 10036) lalu PO dengan `transfer_plan` (aturan sama dengan Analisa safety stock).
- **Iklan**: dulu "SKU beriklan" = SKU dengan biaya iklan > 0 di jendela 30 hari (termasuk iklan yang sudah berhenti). Kini hanya iklan berstatus **Berjalan** di unggahan laporan iklan terakhir yang disimpan **sebelum analisa yang dibuka dijalankan** (`run_at`): anggota grup Berjalan (laporan grup), produk tunggal Berjalan (Semua Laporan Iklan), produk berbiaya di iklan otomatis bila iklan otomatis Berjalan. Kode produk → SKU lewat Data stok terbaru. Alasan tahan dirinci (stok, margin, batal). Bila ada laporan iklan lebih baru dari analisa, diberi catatan untuk jalankan analisa.
- **Outstanding** (koreksi pengguna: hanya dari Replenishment Calculation by Date **Site 10037**, per SKU; Stock Qty and Value Site 10062/10036 hanya untuk stok DC): PO, TR, TO, TR dari toko lain, semuanya dihitung barang dalam proses menuju Site 10037. Insight: berapa SKU Top 50 yang perlu restock sudah punya outstanding, yang sudah menutup restock-nya, yang belum ada sama sekali; kebutuhan PO 30 hari (`kurang_setelah_dc`) vs outstanding → PO baru. Tabel Kebutuhan restock prioritas: kolom baru **Outstanding Site 10037** ("PO 10 · TR 5 · TO 2"), ikut Excel.
- Database: `warehouse_replenishment` + kolom `out_to`, `out_tr_lain` (`gudang.REPL_COLUMNS`: Outstanding TO, Outstanding TR from other Store). `FeatureStore` kini menambah kolom nullable baru ke tabel lama (`_add_missing_columns`, ALTER TABLE ADD COLUMN; SQLite & Postgres). Snapshot lama terbaca 0 untuk TO/TR toko lain → **unggah ulang Replenishment Site 10037** di Setting › Kapasitas gudang. Saran gudang (`gudang._item_status`, "di jalan" = PO + TR) belum diubah.
- Kode `src/core/insight_live.py` (`month_restock`, `running_ads`, `outstanding_10037`, `outstanding_for`, `outstanding_text`, `po_coverage`), `dashboard._month_line/_outstanding_lines/_ads_line`, `FeatureData.replenishment`, `app._run_at_of`. Tes `tests/test_insight_live.py`. Rumus prediksi & SS tidak berubah.
- Data lokal (analisa 16, laporan iklan 14 Nov 07:14): 5 grup + 3 produk tunggal + otomatis berjalan = 546 SKU (49 di Top 50); 350 dari 492 SKU berprediksi sebaiknya ditahan (322 batal tinggi, 103 stok).

## Kartu "SKU Top 50 stok kurang": rincian menjumlah + bulan berjalan (14 Nov 2026)

- Masukan pengguna: "4 kosong · 34 di bawah SS" tidak menjumlah ke 44. Kini rincian tanpa tumpang tindih: kurang = kosong + masih berstok tapi di bawah SS + di atas SS tapi belum cukup (mis. 44 = 4 + 30 + 10); total di bawah SS (kosong + berstok di bawah SS) tetap disebut; di luar hitungan: cukup · tanpa data stok.
- Baris baru **Bulan berjalan** (sisa hari ini s.d. akhir bulan): SKU stok < prediksi sisa bulan (unit utuh, `run_rest_qty`) + SS dan total kekurangan unit, aturan sama dengan baris Bulan berjalan di Analisa safety stock.
- `decision_table.stock_shortage` menambah kunci `bawah_ss_berstok`, `di_atas_ss`, `aman` (status & rumus tidak berubah); `dashboard._running_month_shortage`. Tes `tests/test_stock_shortage.py`.

## Rincian kecocokan: SKU aktif belum pernah terjual (14 Nov 2026)

- Upload data › Ringkasan data tersimpan › Rincian kecocokan, di bawah tabel "SKU transaksi yang tidak ada di Data stok": tabel baru **SKU aktif di Data stok yang belum pernah terjual** (SKU di unggahan Data stok Site 10037 terbaru yang tidak pernah muncul di Data transaksi). Kolom: SKU, Produk, Variasi, Stok Site 10037/10036/10062, Tidak terjual sejak, Umur tidak terjual (hari); urut total stok terbesar; bernomor, bertahap, Excel. Kartu: jumlah SKU, stok toko, stok DC, tanpa stok di mana pun.
- Umur = hari sejak awal data transaksi s.d. hari ini (angka minimal; tanggal tayang listing tidak ada di ekspor Shopee); SKU yang baru muncul setelah unggahan Data stok pertama = listing baru, dihitung sejak tanggal itu. Dari data tersimpan, tanpa menjalankan analisa.
- Kode `consolidation._unsold_active` (dipanggil `match_diagnostics`, kunci `stock_unsold`); tes `tests/test_unsold_active.py`. Data lokal: 159 SKU, semuanya ≤ 01/01/2026 (317 hari).

## Localhost + Supabase = salinan baca-saja dari Cloud (14 Nov 2026)

- Insiden: localhost yang disambungkan ke Supabase (DATABASE_URL) memakai folder laptop dan brankas mendorong file laptop ke `file_vault`, menimpa `team/sources/*`, `team/registry.json`, dan file analisa 6–11 milik Cloud (analisa 12–15 utuh), serta menambah kunci `library/` dan `history/` yang tidak dipakai Cloud. Beranda lokal juga menampilkan transaksi s.d. 8 Nov karena file laptop tidak ditimpa versi database.
- Perbaikan: `CLOUD_MIRROR` (lokal + database bukan SQLite) memakai `~/.prediksi_shopee/salinan_cloud/{shared,runs}` dengan susunan sama seperti Cloud; `FileVault(read_only=True)` tidak pernah push; `restore(refresh=True)` menimpa file yang berbeda dari database (diulang tiap 5 menit). Upload data dan Jalankan analisa dikunci di localhost mode ini, dengan keterangan di Beranda.
- Pemulihan Cloud: perubahan `file_vault()` membuat Cloud membuat brankas baru dan mengirim ulang file dari disknya sendiri pada kunjungan berikutnya; kunci `library/` dan `history/` dari laptop dihapus dari brankas.

## Ringkasan: hari belum penuh & sumber data latih (14 Nov 2026)

- Kartu "Kecualikan batal & retur" menghitung periode, pesanan batal/Belum Bayar, dan unit retur dari data transaksi yang tersimpan bersama analisa (bukan file pustaka yang sedang dipilih), sehingga selalu sesuai analisa yang dibuka.
- Baris "Aktual <kemarin>" di kartu batang tidak dibandingkan bila hari itu belum penuh di laporan (data < 23:00); tertulis "laporan baru s.d. <tgl> pukul <jam>; belum penuh" dan sel angka "belum penuh".
- Kartu periode penjualan menandai bila tanggal akhir belum penuh ("angkanya masih bertambah").
- Istilah "setelan … aktif/mati" diganti "centang Kecualikan batal & retur dicentang/tidak dicentang saat analisa dijalankan"; "tanpa batal & retur" menyebut Belum Bayar.
- Kotak safety stock: hari yang sudah lewat tetapi belum penuh disebut dengan hari penuh terakhirnya.

## Centang "Kecualikan batal & retur" = dasar prediksi; cara baca di Ringkasan (14 Nov 2026)

- Centang tetap di Upload data › Setelan analisa (ditentukan sebelum analisa dijalankan). Dicentang = dasar BERSIH (batal, Belum Bayar, unit retur tidak dilatih; `cancelled_status_mask`), tidak dicentang = dasar MASUK (semua status). Keterangan di bawah centang ditulis ulang.
- Kotak baru "Cara baca Ringkasan" (`common.basis_guide`) di paling atas Ringkasan: dasar analisa yang dibuka, arti masuk/bersih, pembanding prediksi, sales produk vs sales bersih toko, hari penuh terakhir.
- Kartu Kecualikan batal & retur: "DICENTANG · dasar prediksi bersih" / "TIDAK DICENTANG · dasar prediksi masuk".
- Istilah asing di Ringkasan diganti: "nett" dihapus, "All SKU" → "semua SKU".

## Audit halaman Ringkasan: masuk vs bersih (QTY & sales), periode, angka lengkap (14 Nov 2026)

- Prioritas hari ini: kartu hari ini bertanggal + sales produk + pembanding "terjual bersih/masuk <tgl>" dengan arah selisih ("prediksi X% lebih rendah dari ..."); bulan berjalan menyebut dasar dan sales produk; Kebutuhan stok = prediksi + SS, stok, kurang (unit); Stok kurang "N dari 50 SKU" dengan periode.
- Insight: restock bertanggal + unit dari DC vs PO; iklan ditahan "X dari Y SKU beriklan (semua SKU)".
- Sales hilang karena kosong: tanggal s.d. hari penuh terakhir; persen kekurangan target 2 desimal bila < 1% dan kalimat kesimpulan mengikuti besarnya (tidak lagi "sebagian kekurangan target..." saat 0%); sisa bulan bertanggal + unit + total s.d. akhir bulan.
- Kartu Periode penjualan: masuk → bersih (%) dan rincian batal / Belum Bayar / retur untuk pesanan, sales (Total Pembayaran) dan QTY (`order_metrics` + `qty_masuk`, `qty_batal`, `qty_menunggu_bayar`); penjelasan masuk, bersih, sales Total Pembayaran vs sales produk. Kartu Kecualikan batal & retur menyebut rentang data latih.
- Pergerakan: pembanding hari ini & bulan berjalan menyebut dasar (terjual bersih / masuk) dan arah selisih.
- Kartu batang: chip stok "Kurang X dari kebutuhan Y unit (Z% belum tertutup stok)"; baris Aktual kemarin menyebut laporan baru s.d. tanggal terakhir bila belum masuk.
- Analisa safety stock: baris Bulan berjalan menjelaskan hari yang sudah lewat tetapi belum ada di data latih.

## Grafik SKU (Grafik QTY/Sales · Bulan ini): bulan berjalan, dasar bersih/masuk, tanggal terbaca (14 Nov 2026)

- Batang Terjual memakai dasar yang sama dengan data latih dan tabel Top 50 (`sku_insight.daily_profile` dari semua status); nama legenda "Terjual bersih" atau "Masuk (semua pesanan)"; hover menampilkan bersih, masuk, batal, Belum Bayar, retur per tanggal.
- Prediksi sisa bulan memakai `run_rest_qty` (laju harian × pola hari, sama dengan tabel); kartu baru "Bulan berjalan" = terjual (dasar) tgl 1 s.d. kemarin + prediksi sisa. Kartu Terjual menyebut dasarnya dan angka dasar lain.
- Tanggal kini tampil juga di bawah panel batang (sebelumnya hanya di bawah panel stok); garis "aktual | prediksi" di hari ini. Prediksi sebelumnya tampil mulai tgl 1 termasuk nilai 0 (dulu batang 0 tidak terlihat), dan catatan "Aktual vs prediksi sebelumnya" dihitung mulai tgl 1.
- Tabel baru "Aktual vs prediksi sebelumnya per tanggal" (masuk, bersih, prediksi, selisih, sales, sumber) agar hari yang meleset terlihat.

## Analisa safety stock: baris Bulan berjalan (14 Nov 2026)

- Baris baru "Bulan berjalan · sisa 13–30 Nov (18 hari)": kebutuhan = prediksi sisa bulan (laju harian × pola hari, unit utuh per SKU, dari `run_rest_qty`) + SS; keterangan aktual 1 s.d. hari penuh terakhir (dasar bersih/masuk) dan proyeksi bulan. Aktual tidak dihitung sebagai kebutuhan stok.
- "Dipenuhi dari" kini dihitung untuk semua baris dengan `dc_stock.transfer_plan` (Site 10062 lalu 10036); baris 30 hari tetap sama dengan `kurang_setelah_dc` (diverifikasi).
- Penjelasan tambahan: Prediksi QTY unit utuh vs total sebelum dibulatkan di Ringkasan, beda "SKU stok di bawah SS" (kartu) vs "SKU stok < kebutuhan" (tabel). Tidak ada rumus SS/prediksi yang diubah.

## Tabel Top 50 / Prediksi semua produk: masuk vs bersih, bulan berjalan, lama kosong (14 Nov 2026)

- Masukan pengguna: kolom Terjual ambigu (bersih atau semua), tambah prediksi bulan berjalan, lama kosong mengikuti data latih seperti Restock.
- `sku_insight.table_extras` (dites): `sold_*` masuk & bersih pada periode penjualan terpilih (semua status dari `orders_all`), `run_*` prediksi bulan berjalan (aktual dasar tgl 1 s.d. hari penuh terakhir + laju × pola hari sisa bulan), `empty_*` hari kosong & sales hilang dari unggahan stok 0 pertama s.d. hari penuh terakhir data latih.
- `app._with_table_extras` (cache per run) menambah kolom ke `enriched`/`shown`; `table_parts(meta=)` menampilkan kelompok "Aktual · tanggal" (Terjual bersih / Masuk, kolom dasar ditandai "(dasar)"), "Prediksi bulan berjalan · 1–30 Nov", dan Lama kosong "N hari · sejak … s.d. … · hilang Rp …". Excel ikut. `decision_table_guide` menjelaskan semua istilah di atas kedua tabel.
- Batas "s.d." disamakan ke hari penuh terakhir data latih (data ≥ 23:00): Restock prioritas (`restock_priority(through=)`), kotak sales hilang, dialog Analisa. Pergerakan Top 50: aktual bulan berjalan kini dari `orders_all` dengan dasar yang sama (bersih/masuk), jadi angkanya sama dengan tabel ini.

## Dialog Analisa prediksi per SKU: menyeluruh & bertanggal (14 Nov 2026)

- Masukan pengguna: tambah analisa bulan berjalan, setiap angka sebut periodenya, jelaskan bersih vs masuk, analisa menyeluruh (transaksi, kompetitor, deskripsi, prediksi/potensi).
- Modul baru `src/core/sku_insight.py` (dites di `tests/test_sku_insight.py`): `transaction_profile` (masuk, batal, Belum Bayar, retur, bersih, pesanan, pembeli, alasan batal per rentang), `running_month` (aktual 1 s.d. hari penuh terakhir + prediksi sisa bulan × pola hari = proyeksi; pembanding periode sama bulan lalu dan bulan lalu penuh), `stock_potential`, `description_review`/`find_description`, `competitor_view` (aturan sama dengan halaman Rekomendasi).
- `app._insight_context` menyusun bahan saat tombol Analisa diklik (di-cache per SKU); `analysis_markup(..., context=)` sekarang 9 blok: Bulan berjalan, Prediksi per periode vs stok, Transaksi SKU, Stok & DC, Kompetitor, Deskripsi, Performa toko (seluruh toko, tanggal), Iklan (tanggal laporan: kolom baru `iklan_mulai`/`iklan_sampai` dari `enrich`), Dua sisi + Langkah kerja. Paragraf "Cara baca angka" menjelaskan masuk/bersih/sales produk dan dasar analisa (ikut setelan Kecualikan batal & retur).
- Kalimat sistem pakar yang belum bertanggal ditempeli periode (tren 28 hari, tingkat batal seluruh laporan). `sku_facts` memakai `tanggal_habis` agar tanggal habis di langkah kerja sama dengan blok stok.
- Kompetitor: file hanya berisi peringkat & judul (tanpa harga/terjual), jadi perbandingan harga ditulis belum bisa dihitung.

## Kartu Prediksi per SKU (batang): sales + bersih vs masuk (13 Nov 2026 malam)

- Masukan pengguna: tambahkan sales; harus jelas kartu menganalisa sales bersih atau aktual masuk.
- Batang kini berbunyi "▲ Prediksi 1.194 unit · Rp … · 8,0% di atas terjual bersih" (QTY + sales produk = prediksi QTY × harga bersih 4 minggu).
- Kolom kanan dua: Terjual bersih (nett) dan Masuk (semua pesanan), masing-masing QTY + sales produk, dibaca dari semua status (`orders_all`) lewat `decision_table.sku_actuals`.
- Dasar analisa mengikuti setelan prediksi: Kecualikan batal & retur aktif → batang dibanding terjual bersih; mati → dibanding masuk. Kolom yang dipakai diberi latar biru muda; kalimat "Dasar analisa" tampil di atas kartu.
- Baris prediksi menulis bulan pembanding ("vs aktual 1 Okt – 31 Okt 2026"). Dialog Analisa memakai angka dasar yang sama.
- `_sales_bars`, `_extra_period_bar`, `_day_sold_map`, `_last_month_sold` diganti `_card_bars`/`_split_bar`/`_board_actuals`/`_last_month_span`.

## Ringkasan total Top 50: aktual masuk vs bersih (13 Nov 2026 malam)

- Masukan pengguna: "Aktual Okt 2026" tidak jelas sales apa dan tanggal berapa; perlu angka bersih (nett) sekaligus semua data real yang masuk.
- `decision_table.period_actuals` kini membaca semua status (`orders_all`) dan mengembalikan: `qty_masuk`/`sales_masuk` (semua pesanan Top 50, termasuk batal, Belum Bayar, retur), `qty`/`sales` bersih (tanpa batal & Belum Bayar, setelah retur; tidak lagi ikut saklar), `store_sales` (sales produk bersih toko), `store_net` (sales bersih toko = Total Pembayaran − batal − Belum Bayar − retur), `start`/`end`.
- Tabel (`decision_view.top50_matrix`): kolom Aktual pembanding (tanggal) menulis rentang lengkap ("Okt 2026 · 1 Oktober 2026 – 31 Oktober 2026 (31 hari)", "12 November 2026 (1 hari, hari penuh terakhir)"); QTY masuk, QTY terjual bersih, Sales produk masuk, Sales produk bersih (+ "x% lebih kecil dari masuk"); Prediksi sales produk; Sales bersih seluruh toko (dasar target). Penjelasan ditulis ulang untuk pembaca awam, termasuk kolom mana yang dibandingkan dengan prediksi menurut setelan Kecualikan batal & retur.
- Tes: `test_period_actuals_gross_and_net_with_dates`.

## Pergerakan Top 50: kolom Prediksi bulan berjalan (13 Nov 2026 malam)

- Grup kolom baru **Prediksi bulan berjalan (Nov 2026)** di antara Prediksi hari ini dan Prediksi 30 hari: Sales produk & QTY per SKU = aktual SKU tgl 1 s.d. hari penuh terakhir + laju prediksi harian × pola hari sisa bulan (aturan sama dengan kartu Prediksi bulan berjalan, `app._running_month_actuals`, `_daily_rate`). Sub-teks sel "aktual 1–12 Nov: …"; angka ▲/▼ = perubahan laju antara tanggal Dari–Sampai × pola sisa bulan. Excel ikut 4 kolom baru.
- Semua kolom Sales di tabel ini diberi label **Sales produk**; penjelasan tabel menyebut beda dengan sales bersih, dan bahwa Prediksi 30 hari bukan bulan kalender. Total tabel hanya SKU yang bergerak, jadi bisa sedikit di bawah kartu (semua Top 50).

## Restock prioritas: sales hilang sejak kosong (13 Nov 2026 malam)

- Masukan pengguna: potensi hilang terus bertambah selama stok tidak diisi; tabel harus menunjukkan berapa yang sudah hilang sejak SKU kosong dan sejak kapan, sebagai bahan menjelaskan kenapa target tidak tercapai.
- `restock.empty_loss`: untuk SKU Kosong, hari `zero_since` s.d. kemarin; permintaan = laju prediksi harian × pola hari (`month_track_view.day_weight_fn`, pola sama dengan Pantauan harian); hilang = permintaan − yang tetap terjual hari-hari itu (min. 0). Sales = sales produk. Bagian bulan berjalan dipisah. Rumus prediksi & SS tidak berubah.
- Tabel kolom baru: **Kosong sejak** ("≤" bila kosong sejak data stok pertama → angka minimal), **Hari kosong**, **Sales hilang sejak kosong**, **Sales hilang bulan ini**, **QTY hilang sejak kosong**. Kolom lama diganti nama **Potensi sales/QTY hilang ke depan** (prediksi periode − stok). Urutan dalam kelompok kini memakai sudah hilang + potensi ke depan.
- Kotak merah **Sales hilang karena Top 50 kosong** di atas tabel: jumlah SKU kosong & total hilang, SKU terlama kosong, hilang bulan ini setara sales bersih (× faktor) sebagai % kekurangan target berjalan s.d. hari penuh terakhir, sisa bulan yang hilang lagi bila tidak direstock, 3 penyumbang terbesar.
- Tes: `test_restock_empty_age.py` (kolom & angka, `empty_loss` pola hari, potong terjual, bagian bulan).

## Istilah sales tidak bermakna ganda (13 Nov 2026 malam)

- Pertanyaan pengguna: "Pencapaian s.d. 12 Nov Rp 1.551.146.267" vs "aktual 1–12 Nov: Rp 1.773.338.194" di kartu bulan berjalan. Keduanya beda pengertian: **sales bersih** = Total Pembayaran − batal − Belum Bayar − retur (sudah dipotong voucher; dasar target) vs **sales produk** = Harga Setelah Diskon × QTY terjual (dasar prediksi). Rasio bulan ini ±0,87. Angka & rumus tidak diubah, hanya label dan penjelasan.
- Pencapaian (`targets_view.achievement_line`, dipakai Ringkasan/Data/Laporan/Kalkulator): "Pencapaian · sales bersih 1 Nov 2026 – 12 Nov 2026 Rp … (hari penuh terakhir; 13 Nov 2026 belum penuh, tidak dihitung) = …% dari target … · target berjalan (pola hari) s.d. 12 Nov 2026 …".
- Pergerakan › Prediksi bulan berjalan: "aktual sales produk 1–12 Nov" / "aktual terjual 1–12 Nov"; kartu All SKU bernama "Prediksi sales produk …" + baris **Dalam sales bersih (dasar target)**: aktual = Pencapaian kartu Sales bersih, proyeksi = Pantauan harian (`app._net_month_hint` → `month_outlook`). Penjelasan Pergerakan menambah "Sales di bagian ini = sales produk".
- Prediksi vs aktual: kartu "Aktual omzet bersih" (padahal sales produk SKU berprediksi) → **Aktual sales produk**; kolom/legend "Prediksi omzet", "Aktual omzet", "Aktual SKU" → "Prediksi sales produk" / "Aktual sales produk".
- Laporan: penjelasan Sales bersih kini menyebut Belum Bayar & target berpola hari (dulu "prorata hari kalender", sudah tidak berlaku); tabel produk terlaris "Sales produk"; kartu prediksi 30 hari menyebut sales produk 30 hari ke depan vs target bulan (sales bersih). "sales produk bersih" → "sales produk".
- Exposure: "Omzet 30 hari" (prediksi × harga × 30) → **Prediksi omzet 30 hari**, karena di Kapasitas gudang "Omzet 30 hari" berarti penjualan 30 hari terakhir.
- Tes: `test_achievement_line_names_net_sales_and_dates`.

## Restock prioritas: umur kosong & tanggal stok habis (13 Nov 2026)

- Status SKU Kosong kini "Kosong · 8 hari (sejak 5 Nov 2026)" (dari `stock_zero_duration`: unggahan pertama dengan stok 0 di rangkaian kosong terakhir Data stok Site 10037). Bila semua unggahan tersimpan sudah 0 (`kosong_sejak_awal`), ditulis "≥ N hari" karena umur sebenarnya tidak diketahui.
- Kolom Stok habis untuk SKU Kosong = tanggal stok mulai 0 ("Habis 5 Nov 2026" / "Habis ≤ 3 Nov 2026"), bukan hari ini. `restock.stock_out_date` dibatasi 10 tahun (overflow sama seperti tanggal habis di tabel keputusan). `status_badges` mempertahankan keterangan setelah " · ". Tes `tests/test_restock_empty_age.py`.

## Ringkasan: kartu Prediksi QTY bulan berjalan (13 Nov 2026)

- Prioritas hari ini kini 5 kartu; kartu baru kedua **Prediksi QTY bulan berjalan (Nov 2026) · Top 50** = QTY aktual Top 50 tgl 1 s.d. hari penuh terakhir + laju prediksi harian Top 50 (nilai harapan, sama dengan kartu hari ini) × jumlah pola hari sisa bulan (`month_track_view.month_remaining_weight`, pola sama dengan Pantauan harian). Keterangan: "aktual 1–12 Nov: … + prediksi 13–30 Nov: …". Rumus prediksi tidak berubah. Kode `dashboard.running_month`; tes `tests/test_running_month.py`.
- Pergerakan dari analisa sebelumnya: baris baru **Prediksi bulan berjalan (Nov 2026)** (`app._running_month_cards`): QTY & sales Top 50 (pembanding = aktual yang sama + laju prediksi kemarin = total hari ini kemarin ÷ pola hari ini) dan sales All SKU (aktual seluruh pesanan + laju semua SKU). Sales = sales produk, belum × faktor sales bersih (beda dengan proyeksi Pantauan harian yang bersih).

## Target bulanan bisa dikoreksi (13 Nov 2026)

- Masalah: unggahan hanya menambah/mengganti bulan di file; bulan kosong/tidak ada dilewati, jadi target 2027 yang salah tetap tersimpan (12 + 10 = 22 bulan) dan tidak bisa dihapus.
- Upload data › Target sales bulanan kini dua tab: **Lihat & koreksi target** (tabel bisa diedit: ubah angka, centang Hapus, tambah baris; ringkasan "Belum disimpan: …" lalu Simpan koreksi) dan **Unggah file target** dengan pilihan **Ganti semua target dengan isi file** (bawaan; bulan yang tidak ada/kosong di file dihapus) atau **Perbarui hanya bulan yang ada di file**, plus pratinjau Baru/Diubah/Tidak berubah/Dihapus.
- Menu upload: Target sales bulanan dan File margin kini ikut tanda "✓ Siap (baru disimpan)" setelah disimpan di sesi ini (`common.mark_upload_done`), selain itu "tersimpan" (+ tanggal unggah untuk margin), sama dengan menu lain.
- Hapus = target 0 (baris `sales_target` tetap ada), sehingga Target ROAS & budget iklan bulan itu tidak hilang. Logika `targets.plan_changes`; tes `TargetChangesTest`.

## Stok tidak terbaca & umpan balik unggah (13 Nov 2026)

- **Penyebab kotak kuning "Sebagian data pendukung … seconds=2372535360000000000"**: `tanggal_habis` = hari ini + stok ÷ prediksi harian. SKU berstok dengan prediksi harian hampir 0 menghasilkan ±27 triliun hari → `OutOfBoundsTimedelta`, sehingga `enrich_catalog` gagal dan Ringkasan memakai tabel dasar tanpa stok/iklan/label ("50 tanpa data stok"). Sekarang cakupan > 3.650 hari tidak diberi tanggal habis (`decision_table.MAX_COVER_DAYS`, juga kartu analisa SKU). Teks peringatan diganti bahasa manajer + detail teknis. Tes `test_tiny_forecast_with_stock_has_no_overflow_date`.
- **Umpan balik unggah seragam** (`common.file_check`, `set_upload_notice`, `show_upload_notice`) untuk File margin, Target bulanan, Denah gudang, Replenishment Site 10037, dan isian data barang: setelah file dipilih tampil kotak hijau "File sesuai, belum disimpan" atau merah "File tidak sesuai" + alasan; setelah Simpan hasilnya tetap tampil (dengan jam diterima) sampai unggahan berikutnya. Dulu pesan sekali pakai (`pop`) bisa terhapus oleh rerun otomatis, pesan replenishment berada di expander yang tertutup setelah simpan, dan denah hanya `st.toast` sebelum `st.rerun()` tanpa penanganan galat.

## Audit konsistensi angka antar halaman (11 Nov 2026)

Rumus prediksi, safety stock, dan data terkunci tidak diubah. Tes baru: `tests/test_consistency.py`.

Diperbaiki:
- **Proyeksi akhir bulan satu sumber**: Kalkulator biaya dan Rekomendasi › Iklan (`targets_view.month_outlook`) kini memakai perhitungan Pantauan harian (`month_track_view.month_state`): aktual s.d. hari penuh terakhir (≥ 23:00) + prediksi per tanggal berpola × faktor. Dulu laju datar, hari berjalan dihitung penuh, dan faktor berbeda. Laju datar hanya cadangan bila snapshot prediksi bulan itu belum ada. Faktor sales bersih ÷ sales produk satu fungsi `net_factor` (dulu disalin 3×).
- **Prediksi vs aktual**: "Aktual omzet bersih" selalu bersih (`metrics.sold_lines`: tanpa batal & Belum Bayar, setelah retur) walau saklar Kecualikan batal & retur mati; dulu kotor dan Belum Bayar terhitung dua kali di batang kuning. Hint "seluruh toko" kini sales bersih toko vs target harian berpola (sama dengan baris tabel breakdown), dulu sales produk vs target rata.
- **Biaya iklan per unit** (margin bersih Kalkulator, Laporan margin, iklan/promo): biaya iklan 30 hari ÷ QTY di jendela laporan iklan yang sama (`qty_sku` dari `attribute_ads`). Dulu dibagi QTY seluruh periode penjualan terpilih → biaya iklan/unit terlalu kecil (periode 12 bulan ±12×), margin tampak lebih tinggi.
- **Evaluasi model**: baris "Demand forecasting" di kerangka pengujian memakai MAPE agregat toko, sama dengan kartu, gauge, dan uji kesesuaian (dulu MAPE per SKU gabungan, bisa memberi status berlawanan).
- **Laporan**: tabel pencapaian per bulan menilai bulan belum penuh terhadap target prorata (kolom baru "Target s.d. data"), sama dengan kartu Sales bersih; caption restock "stok DC" → stok Site 10037 + urutan ambil DC.
- **Ringkasan**: kartu periode kalender (Kuartal/Semester/Tahun) memprorata target s.d. tanggal data terakhir, bukan s.d. hari ini. Baris Total tabel Top 50 kolom Prediksi = jumlah sebelum dibulatkan per SKU, sama dengan kartu "Prediksi QTY hari ini" dan matriks Top 50.
- **Pantauan harian › Top 5 Stok**: jumlah restock = kebutuhan sisa bulan + SS − stok (aturan Kurang di Ringkasan); potensi omzet tetap permintaan yang tidak tertutup stok.
- **Exposure**: "Omzet 30 hari" = laju harian × harga × 30, sama dengan Kapasitas gudang (dulu jendela bulan 28–31 hari dibulatkan ke bawah).
- **File margin**: margin kotor di pratinjau unggah dari harga termasuk pajak (dasar semua hitungan) + angka versi file.

Tahap 2 (atas permintaan pengguna: logika disamakan dengan aturan README). **Jalankan analisa ulang** agar SS, ROP, dan simulasi Evaluasi dihitung ulang:
- **SS dibulatkan ke atas** per SKU (stok pengaman tidak boleh kurang dari rumus): dulu dibulatkan ke terdekat sebelum tabel keputusan, jadi SS 2,4 → 2. Berlaku di tabel keputusan, papan Ringkasan, dan pembagian periode.
- **Lead time satu aturan** (`inventory.lead_time_days`): SS, ROP (= d × L + SS), dan Monte Carlo Laporan memakai lead time impor bila mode impor aktif (σ_L Monte Carlo = (Lmaks − Lrata) ÷ 1,645), selain itu lead time lokal. Dulu ROP & Monte Carlo selalu lokal.
- **Simulasi tingkat layanan Evaluasi** = rumus SS produksi: Z dari tingkat layanan rekomendasi Bulan, √(lead time lokal + review), SS dibulatkan ke atas; target cek "Tingkat layanan simulasi" = tingkat layanan itu (dulu Z 1,645 × √7 tetap, target 90%).
- **ROAS impas Top 5 iklan** = 100 ÷ margin sebelum iklan (margin bersih + iklan per unit ÷ harga), sama dengan Rekomendasi › Iklan. Dulu memakai margin yang sudah dipotong iklan → titik impas terlalu tinggi, usulan iklan hilang.
- **Ruang stok iklan** (Rekomendasi › Iklan): sisa stok = stok − prediksi sisa bulan − SS, sama dengan Top 5.

Tahap 3 (11 Nov malam, "temukan celah galat, salah hitung, salah logika"). **Jalankan analisa ulang** agar record evaluasi baru terbentuk:
- **Prediksi tidak lagi dibulatkan dua kali**: katalog (`top_bestsellers`) menyimpan prediksi model apa adanya; hanya tabel keputusan yang membulatkan ke bawah. Dulu total periode dibulatkan ke terdekat → SKU lambat (< 0,5 unit/periode) jadi 0 lalu ditimpa rata-rata seumur data (min. 1 unit). Rata-rata riwayat kini hanya bila model tidak punya prediksi SKU itu. Periode Kuartal/Semester/Tahun juga dibulatkan ke bawah (dulu terdekat).
- **Laporan margin = Kalkulator**: harga akhir = (penjualan − voucher ditanggung penjual) ÷ QTY; margin kotor, potongan, dan persen dari harga akhir. Kolom baru "Setelah voucher penjual".
- **Batas margin promo** bawaan 0% (asal tidak rugi), sama dengan `business_targets`; dulu Ringkasan memakai 8%.
- **Iklan per bulan** (Ringkasan) tanpa laporan all iklan memakai jumlah per produk (sama dengan kartu iklan), dulu Rp 0; kolom Sumber.
- **Evaluasi model** (`src/models/evaluate.py`):
  - **Uji luar sampel (nested walk-forward)** baru: lipatan k dinilai dengan bobot, faktor bias, dan model per segmen dari lipatan sebelum k saja (`fit_combination`, `_nested_scores`, record `luar_sampel`); tabel di tab Evaluasi › Hasil.
  - Kesimpulan membandingkan **MAPE agregat** dengan target 15% (dulu MAPE per SKU); uji "Tidak bias" memakai bias luar sampel (dulu ≈ 0 karena faktor disetel di lipatan yang sama).
  - Simulasi tingkat layanan = **cycle service level**: jendela L + R hari (SS melindungi lead time + tinjau), pasangan dengan hari stok kosong tidak dinilai.
  - SKU uji dipilih dari 90 hari sebelum titik potong pertama (dulu 90 hari terakhir = melihat data uji). `top_n_hits` hanya menghitung SKU yang laku.
  - Teks metodologi diperbaiki: penyebut MAPE, perlakuan hari stok kosong per model.
- Dicek dengan data lokal: total Sales bersih harian Laporan = `order_metrics` (Rp 2.373.100.635, Okt 1–26).

Tahap 4 (keputusan pengguna: model produksi dipilih luar sampel; SS empiris "Kalibrasi robust (MAD) + target layanan per kelas ABC"). **Jalankan analisa ulang** agar bobot, faktor kalibrasi, dan SS baru dipakai:
- **Model produksi** = WAPE luar sampel terkecil per horizon (`record["model_produksi"]`, `weights_produksi`; `production_weights`). Data lokal: Exponential Smoothing untuk hari/minggu/bulan, Gradient Boosting global untuk kuartal. Tabel kandidat Evaluasi punya baris "Model produksi".
- `apply_ensemble` tidak lagi membulatkan/memaksa minimal 1 per model (pembulatan hanya di tabel keputusan).
- **SS = Z(kelas) × r × σ × √(L + R)**, dibulatkan ke atas. r = faktor kalibrasi dari galat prediksi jendela L+R di walk-forward, diestimasi robust: median|z| ÷ 0,6745, dibatasi 0,5–5 (`ss_calibration`, kunci `_kalibrasi_ss` di bobot). Simulasi menilai lipatan k dengan r dari lipatan sebelum k saja.
- **Target layanan per kelas ABC** (QTY 90 hari, `abc_by_qty`): A = dasar + 2, B = dasar, C = dasar − 7, batas 80–99 (`layanan_kelas` di `business_params.yaml`). Dasar 97% → A 99%, B 97%, C 90%. Kolom `target_layanan_pct` di rekomendasi stok.
- Hasil data lokal (bulan, 4 lipatan luar sampel): Exponential Smoothing WAPE 68,8%, MAPE agregat 12,8%, bias −12,3% (Ensemble per segmen 70,6%; in-sample 68,5% terlalu optimis). r = 1,57. Cycle service level tercapai **80,9%** (tanpa kalibrasi 76,9%) vs target rata-rata 93,5%: kelas A 86,8%/99%, B 83,2%/97%, C 78,0%/90%. Target belum tercapai karena permintaan proyek bergerombol (ekor galat tebal, q97 |z| ≈ 9) dan bias kurang prediksi; dilaporkan apa adanya di tesis.
- Dampak SS (run lokal, horizon hari 30 langkah): 12.028 → 19.963 unit, Rp 2,61 M → Rp 4,20 M (A Rp 2,29 M, B Rp 0,69 M, C Rp 1,22 M). Kalibrasi RMS (ditolak) memberi ±47.500 unit.

Tahap 5 (sampel layar Rekomendasi › Iklan "budget dikunci" dari pengguna). Satu aturan untuk semua halaman:
- **Pencapaian target** (Data, Ringkasan, Prediksi, Kalkulator, Iklan, Laporan, Pantauan) = aktual s.d. hari penuh terakhir (data ≥ 23:00) ÷ target berjalan berpola hari (`range_target(..., weight)`, bobot `seasonal_profile(...).factor` via `month_track_view.target_pattern`). Dulu kartu memakai pembagian datar 8/30 + hari 8 Nov yang belum penuh (Rp 735 jt, 55,4%); kini semua Rp 724.192.017 → 65,4% dari Rp 1.106.882.404.
- **Aktual hari terakhir** (Ringkasan, matriks Top 50, `period_actuals`) melewati hari belum penuh: dulu "8 Nov: 26 (+796%)", kini "7 Nov: 257 (−9,3%)".
- **Iklan**: rencana utama, rekomendasi sistem (`recommend(..., stock_cap=True)`), dan panel budget dikunci sama-sama dibatasi ruang stok. Dulu panel 69,9% vs rencana 72,8% untuk budget sama; kini 69,8% + bonus atur budget per tanggal Rp 1,7 jt = 69,9%. "Omzet iklan sekarang" diberi label susunan baru vs semua iklan berjalan.
- **Target ROAS Laporan = Iklan** (`target_roas_for` mengambil bulan tersimpan terdekat sebelumnya, lalu sesudahnya): dulu 25 dari file lama, kini 15,0.
- Kartu Kebutuhan menampilkan "= unit utuh + SS"; kotak safety stock menampilkan service level per kelas ABC dan r kalibrasi.
- Verifikasi Iklan (data lokal, campaign 11–30 Nov): rekomendasi ROAS 11 / Rp 212 jt bila dipakai sebagai setelan memberi hasil sama (biaya Rp 211,7 jt, +Rp 345,8 jt, 72,17%); ROAS rata-rata tiap minggu ≥ target; tidak ada iklan yang menjual melebihi ruang stok. Teks diperbaiki: "ROAS dibutuhkan" memakai omzet iklan susunan baru (26,9; dulu 27,4 dari semua iklan berjalan), jumlah iklan tanpa prediksi dipisah dari yang tertahan stok (23 + 10, dulu "33 tanpa prediksi"), batas tambahan omzet ditulis sebagai 50% × prediksi.

Tahap 6 (sampel pengguna 11 Nov 23:45, data s.d. 11/11 ≥ 23:00):
- **Hari penuh terakhir satu aturan** (`month_track_view.full_day_cutoff` = `pred_actual.complete_through`): hari ini tidak pernah dihitung penuh, hari data < 23:00 juga tidak. Dulu Pantauan menghitung 11/11 penuh (data ≥ 23:00) sementara breakdown berhenti di 10/11 → aktual s.d. "kemarin" Rp 1.421 jt vs Rp 1.036 jt, target 11/11 Rp 478 jt vs Rp 486 jt, proyeksi 75,0% vs 74,7%.
- Breakdown Prediksi vs aktual mengambil hari penuh dari seluruh pesanan (sama dengan Pantauan) dan baris Total bulan memakai proyeksi Pantauan (`month_state`), jadi angkanya identik.
- **Label "Prediksi Nov 2026" diganti "Prediksi 30 hari (11 Nov – 10 Des 2026)"** (`format_period_label`): jendela prediksi 30 hari mulai hari ini, bukan bulan kalender; dulu mudah dikira sama dengan proyeksi akhir November.
- Kartu Ringkasan "Prediksi sales hari ini · All SKU" = laju harian rata-rata; kini menulis pola hari ini (mis. 11.11 ×2,93 → ±Rp 360 jt sales produk), yang × faktor bersih = kartu Hari ini di Pantauan.
- Teks "Aktual s.d. kemarin" menyebut tanggal hari penuh terakhir bila bukan kemarin.

Tahap 7 (sampel pengguna 12 Nov 00:05: "hari ini" Rp 149 jt / 126 jt / 110 jt):
- Penyebab: Ringkasan memakai laju rata-rata (prediksi 30 hari ÷ 30 = 149 jt), breakdown memakai laju × pola hari ini ×0,84 (126 jt), Pantauan = 126 jt × faktor sales bersih (110 jt).
- **Semua angka "hari ini" kini laju × pola hari ini** (`month_track_view.day_multiplier`, pola yang sama dengan Pantauan & breakdown): kartu Ringkasan Top 50 & All SKU, tabel Periode, Kebutuhan stok hari ini, tabel per SKU, Pergerakan, kartu SKU (`TODAY_FACTOR`, `build_decision_table(day_factor=)`, `slice_forecast(..., day_factor)`). Jendela 30 hari, SS, dan rumus model tidak berubah; tanggal lampau (`_one_day_prediction_map`) tetap rata-rata.
- Cek data lokal: Ringkasan All SKU Rp 107.704.745 = breakdown 12 Nov; Pantauan Rp 96.606.381 = angka itu × faktor bersih 0,897.
- Baris "Aktual terjual kemarin" menyebut pola tanggal pembanding bila beda jauh dengan hari ini (mis. 11/11 ×2,9 vs 12/11 ×0,84).

Ditemukan, belum diubah (perlu keputusan):
- Laju harian prediksi ikut berubah saat Periode Bulan ↔ Kuartal (horizon model & pembulatan total periode) — pilihan desain; menyamakannya butuh dua kali jalan model.
- Level terkini, fitur lag GBM, dan Prophet membaca hari stok kosong sebagai 0 (MA28, ES, target GBM, dan data uji sudah melewatinya).
- Periode bawaan Kalkulator (30 hari) vs Laporan margin (bulan penuh terakhir).
- Tab Data membaca file mentah (`ledger_from_raw`), Ringkasan/Laporan membaca frame analisa — beda bila ada baris duplikat atau tanpa Harga Setelah Diskon; matriks Top 50 sengaja ikut saklar batal & retur.

## Serah terima terakhir (10 Nov 2026, 02:30)

- Semua kode sudah di `main` (commit `86df002`) dan aktif di Streamlit Community Cloud; data Cloud ada di Supabase, jadi analisa & upload data bisa dilakukan dari komputer mana pun lewat app publik tanpa laptop ini.
- Pekerjaan terakhir: fitur khusus Iklan "Kejar target hanya dengan iklan · budget dikunci" (Target ROAS = ROAS rata-rata rencana terbaik, kotak Hitungan target: ROAS dibutuhkan vs realistis). Rincian di bagian akhir file ini.
- Setelah upload data baru di Cloud, cek angka panel Iklan (Target ROAS, ROAS dibutuhkan) dengan data terbaru; masukan pengguna berikutnya dikerjakan dari `main`.
- File lokal `_cadangan_perubahan_lokal_5nov.patch` dan `stash@{0}` hanya cadangan di laptop; tidak dipakai.

## Titik awal

- **`main` adalah satu-satunya versi acuan.** Semua pekerjaan baru (di Cursor atau di Claude) dimulai dari `main` terbaru: jalankan `git pull origin main` dulu sebelum mengubah apa pun.
- PR #1 (`perbaikan-audit-nov2026`, 2 Nov 2026) sudah **ditutup tanpa merge**. Isinya sudah tertinggal dari `main`. Jangan dipakai lagi.
- Setiap push ke `main` menarik kode baru ke Streamlit Community Cloud; `app.py` memuat ulang modul `src` yang berubah, jadi biasanya tanpa Reboot. Bila masih ada galat setelah push, Reboot lewat Manage app (lihat `DEPLOY_GRATIS.md`).

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

## Alur harian dirapikan (8 Nov 2026)

- Satu alur: **Upload data → Jalankan analisa → Lihat hasil**. Analisa yang dipakai selalu analisa sukses terakhir; status dihitung di satu tempat (`app.analysis_status`, logika murni `src/core/journey.py`, tes `tests/test_journey.py`).
- Status: *Belum ada analisa* · *Ada data baru sejak analisa terakhir* (sidik data berubah / bulan baru) · *Hasil analisa sudah terbaru* · *Transaksi hari ini belum diunggah*. Tombol utama mengikuti status.
- Beranda: kartu "Pekerjaan hari ini" (3 langkah + tombol), tabel "Status data" (terakhir diunggah, jadwal: transaksi setiap hari, data lain bila berubah, target awal bulan), Riwayat analisa dilipat.
- Header: "Ubah data latih" → **Upload data**, "Analisa prediksi" → **Hasil analisa**; judul header mengikuti halaman.
- Halaman Upload data: Langkah 1 Upload (menu transaksi diberi ⚠️ bila belum diunggah hari ini; setelah simpan ada ajakan ke Langkah 3), Langkah 2 Setelan analisa (terisi dari analisa terakhir + bulan terbaru; saklar "Kecualikan batal & retur" kini ada di sini), Langkah 3 Jalankan analisa (memberi tahu bila setelan berbeda dari analisa harian). Halaman ini tidak lagi mengubah data analisa yang sedang dibuka sebelum Jalankan analisa ditekan.
- Jalankan analisa harian (Beranda / halaman hasil) memakai setelan analisa terakhir dan rentang bulannya diperpanjang ke bulan tersimpan terbaru (sebelumnya bulan baru bisa tertinggal).
- Halaman hasil: baris status di atas menu (analisa mana, transaksi s.d., terbaru / ada data baru + tombol Jalankan analisa / analisa lama + tombol Buka analisa terakhir).
- Rumus prediksi dan safety stock tidak berubah.
- Perbaikan: analisa terakhir kini dimuat ulang bila pemuatan pertama terputus (sebelumnya sesi bisa tertahan di Upload data tanpa hasil).

## Iklan: pemilihan produk & budget satu alur (8 Nov 2026)

- Masalah: langkah 3 (pemilihan produk) dan langkah 4 (budget per iklan) dihitung terpisah, dan omzet iklan rencana bisa melebihi prediksi omzet produknya. Pada data 8 Nov: rencana mengandaikan omzet iklan Rp 155 jt/hari, di atas prediksi omzet seluruh produk (Rp 122 jt/hari); 21 dari 53 iklan melampaui prediksi produk anggotanya. Penyebab: produk yang sama di banyak grup dihitung berkali-kali, dan kurva iklan yang diaktifkan kembali tidak dibatasi permintaan.
- Sekarang `ads_strategy.build_plan`: pemilihan produk → `restructure` (anggota keluar/dijeda dilepas dan biaya/omzet grup dikurangi porsinya; andalan dipisah jadi iklan tunggal dengan budget dari grup; iklan tunggal baru untuk produk laris belum diiklankan) → `allocate_target`. Usulan iklan tunggal yang tidak kebagian budget dikembalikan ke grup, lalu dihitung ulang. Langkah 3 menampilkan "Iklan di rencana" dan "Budget usulan iklan/hari".
- Satu produk = satu iklan (iklan dengan omzet tertinggi). Duplikat di iklan dijeda/berakhir masuk "Sudah di iklan lain" (tanpa tindakan); duplikat di iklan aktif → Keluarkan/Pindahkan.
- Batas permintaan `DEMAND_LIFT = 0.5`: tambahan omzet sebuah iklan maks. +50% prediksi omzet produk anggotanya. Langkah 4 menampilkan prediksi omzet produk dan omzet iklan usulan; di bawah kartu ada baris "Cek angka" (omzet iklan sekarang → rencana = budget × ROAS → selisih × sisa hari = tambahan pada proyeksi).
- Tes: `UnifiedPlanTest` di `tests/test_ads_target.py`.

## Flash sale toko dirombak (8 Nov 2026)

- Logika di `src/core/flash_sale.py` (tes `tests/test_flash_sale.py`); tampilan `rekomendasi_plus.show_flash_sale`. Rencana lama (`_flash_tab`) dihapus dari tampilan; template Shopee kini dari jadwal baru.
- Flash sale selalu terisi: sumber kuota per SKU = stok toko (di atas SS + kebutuhan 7 hari) → transfer DC 10062/10036 (kirim H-3, SKU DC tidak dijadwalkan 3 hari pertama) → kuota kecil dari stok di atas SS. Stok 0 & DC kosong → tidak dijadwalkan (alasan ditampilkan).
- Dua tujuan: Pendorong omzet (laris, diskon 10/7/5%, kuota 3 × prediksi harian) dan Habiskan stok lebih (stok ≥ 90 hari, diskon 20/15/10/5%, kuota ≤ penjualan 30 hari). Harga flash tidak di bawah impas.
- Batas batal relatif: maks(15%, 1,5 × rata-rata batal toko tertimbang omzet) — data 8 Nov: 44%. Produk andalan bulky (kloset, water heater) batal 28–36%, jadi batas tetap 15% membuang semuanya; SKU batal > 15% diberi batas beli 1/pembeli.
- Jadwal harian (+3 SKU di tanggal kembar/gajian/Harbolnas), SKU sama berjarak ≥ 7 hari (≥ 3 bila kandidat kurang), daftar transfer DC, unduhan template Shopee, simpan rencana (`kv_setting` kunci `flash_plan:<tanggal>`).
- Harga impas flash = File margin tanpa biaya iklan (pesanan flash tidak lewat iklan). Menurut File margin, produk andalan (kloset, lem silicone) impasnya 1,18–1,37 × harga sekarang (program Shopee ±33%), jadi aturan impas ketat membuang semuanya. Pilihan "Aturan harga flash": Prioritas omzet (default; diskon minimal 5%, kolom Margin/unit + total rugi maks. di kartu) atau Tidak di bawah impas. Data 8 Nov: 73 slot, 42 di bawah impas, rugi maks. ±Rp 177 jt bila semua kuota habis. Perlu ditinjau: modal/program di File margin.

## Ranking kategori dirombak (8 Nov 2026)

- Logika di `src/core/category_rank.py` (tes `tests/test_category_rank.py`); tampilan `rekomendasi_plus.show_ranking`. Skor kesiapan & Brand Portal lama dipindah ke expander "Data lain".
- Baris toko "Mitra10" dihitung milik kita walau `own_shop` False. Label kategori = frasa terbanyak di judul daftar itu.
- Status per produk: Sudah Top 10 / Dekat (11–50) / Menengah (51–500) / Jauh. Perkiraan penjualan untuk Top 10 = penjualan produk kita yang sudah Top 10 di daftar itu × peringkatnya ÷ 10 (bila tidak ada, penjualan produk itu sendiri × peringkat ÷ 10) → "Kali lipat".
- Langkah per produk: restock → iklan tunggal → flash sale (peringkat ≤ 500) → kata kunci Top 10 yang belum ada di judul (hanya bila jenis produk sama) → tag promo → konten. Data 8 Nov: 5 produk sudah Top 10 (Kloset Duduk, Water Heater), 16 Dekat.

## Exposure Shopee Video & media sosial dirombak (8 Nov 2026)

- Logika di `src/core/exposure.py` (tes `tests/test_exposure.py`).
- Produk dipilih bila terjual 90 hari dan stok toko + DC ≥ 14 hari. Segmen: Produk andalan (top 30 prediksi omzet), Sedang naik (tren 14 hari ≥ +30%), Stok lebih (≥ 90 hari), Banyak dilihat jarang dibeli (klik ≥ 50, konversi < 1%).
- Jadwal mingguan: hari & jam tayang = waktu pesanan terbanyak per kategori dari riwayat pesanan; maks. 2 konten/hari; produk tidak diulang 14 hari.
- Brief per konten: format per kategori bahan bangunan (mis. before–after kamar mandi, uji rekat), hook masalah, poin jual dari nama (garansi, packing kayu, material, ukuran) + deskripsi, ajakan harga, hashtag, naskah 30 detik. Unduh Excel brief; simpan ke `exposure_schedule`.

## Campaign tersimpan: Iklan, Flash sale, Exposure (8 Nov 2026)

- Logika `src/core/campaigns.py` (tes `tests/test_campaigns.py`), komponen `src/ui/campaign_ui.py`. Disimpan di `kv_setting` kunci `campaign:iklan|flash|exposure` (maks. 30 per jenis).
- Tiap tab punya periode campaign dengan kalender gaya Shopee (`date_range_picker` kini menerima `presets` rencana ke depan: sisa bulan ini, minggu depan, 7/14/30 hari, 4 minggu, bulan depan).
- Campaign yang berjalan/terjadwal terkunci dan tampil sebagai acuan harian (tampilan "Campaign tersimpan"), lalu dicek dengan data terbaru:
  - Iklan: hitung ulang dengan setelan campaign; perlu ditinjau bila target bulan berubah, > 20% iklan beda budget > 20%, atau proyeksi turun > 5 poin.
  - Flash sale & Exposure: slot/konten mendatang yang SKU-nya tidak lolos seleksi hari ini (stok, batal, harga) ditandai.
- "Buat campaign baru": susun ulang; bila periodenya bertabrakan, wajib centang "hentikan campaign #N" — campaign lama dihentikan saat yang baru disimpan. Riwayat: hentikan atau hapus (dengan konfirmasi).
- Iklan: budget = total periode campaign; perhitungan memakai hari campaign di sisa bulan target. Simpan campaign juga menulis `sales_target.budget_json` (target ROAS bulan itu). Exposure juga menulis `exposure_schedule`.
- Unduh SKU tidak dijadwalkan: Flash sale (tidak dijadwalkan + alasan), Exposure (ditunda stok), Iklan (produk tidak diiklankan di rencana).
- Exposure: brief dipilih lewat saringan minggu, segmen, kategori, cari produk/SKU.
- Ranking: satu baris per produk katalog saat ini (8 Nov: 524 produk / 786 SKU; 98 produk di ranking, 426 "Belum masuk ranking" dengan kategori perkiraan). Filter kelompok › kategori terurut; detail kategori terurut kelompok › kategori › daftar. 14 produk ranking yang tidak ada di katalog dipisah ke unduhan.

## Hasil pemeriksaan

- Lint (`ruff`, aturan F dan E9): bersih, tidak ada nama tak terdefinisi.
- Semua file Python bisa dikompilasi; sintaks aman untuk Python 3.9 (lokal) dan 3.11/3.12 (Streamlit Cloud).
- File YAML di `config/` dan `.streamlit/config.toml` valid.
- Status stok konsisten di semua modul (`inventory.py`, `decision_table.py`, `restock.py`, tampilan).
- Tes: 103 lolos di lingkungan pemeriksaan. Tes yang butuh `sqlalchemy`, `streamlit`, `statsmodels`, dan `xgboost` belum dijalankan di sana karena paketnya tidak terpasang. Jalankan `python -m pytest -q` di `.venv` lokal untuk hasil lengkap.

## Iklan: rekomendasi, budget bertahap per minggu, evaluasi harian (8 Nov 2026)

- Masalah: mengubah budget/ROAS seolah tidak berpengaruh. Penyebab: (1) pada target ROAS tinggi budget di atas batas tidak terserap (ROAS rata-rata akan turun), (2) batas 2× Shopee dulu dihitung sekali untuk seluruh bulan, (3) batas tambahan omzet +50% prediksi produk membuat iklan maks. ±96% target.
- `ads_strategy`: `week_blocks`, `ramp` (budget per iklan boleh naik maks. 2× tiap minggu, bertahap), `ramp_effect`, `weekly_table`, `unit_weekly_budget`, `recommend` (ROAS tertinggi dari 30 ke bawah yang menutup target dengan iklan saja), `month_totals`, `evaluate`. `Unit.lift` (daya dorong) dan `Unit.last_days`; `build_plan`/`recommend` menerima `lift`.
- UI Iklan: setelan baru **Daya dorong iklan maks.** (+50% konservatif bawaan / +75% / +100%). Kotak **Rekomendasi sistem** + tombol "Pakai rekomendasi"; bila +50% tidak cukup, ditawarkan asumsi berikutnya yang mencapai target. Kartu budget menampilkan budget tidak terserap; kesimpulan menjelaskan apakah perlu turunkan ROAS atau naikkan budget. Jadwal budget per minggu + unduhan budget per iklan per minggu. Flash sale & exposure tidak dihitung.
- Data nyata Nov 2026: +50% → maks. 96,3% (ROAS 11, Rp 329 jt); +75% → 101,8% target dengan ROAS 13, budget Rp 313 jt.
- Campaign tersimpan menyimpan `rekomendasi` (dipakai/tidak), `jadwal_minggu`, `iklan_minggu`, `baseline` (total laporan iklan bulan berjalan saat disimpan), `daya_dorong`.
- **Evaluasi pelaksanaan** di campaign tersimpan: laporan iklan terbaru − baseline (laporan bulanan kumulatif) → biaya & omzet harian per iklan sejak disimpan; "dijalankan" = biaya 60–140% budget usulan minggu berjalan (dijeda: ≈ 0). Iklan tunggal baru (`pisah:`/`baru:`) dicocokkan ke `produk:<kode>`. Bila laporan belum ada hari baru: minta unggah laporan esok hari.
- Nama campaign ikut setelan terbaru selama belum diketik manual.
- Mengganti **Daya dorong iklan maks.** langsung mengisi target ROAS & budget dengan rekomendasi untuk asumsi itu (lewat flag + rerun, karena nilai widget tidak boleh diubah sesudah dibuat).

## Laporan per rentang & laporan tersimpan (8 Nov 2026)

- Laporan pakai kalender rentang (`date_range_picker`, bawaan bulan penuh terakhir). Semua angka, grafik & tabel dihitung untuk rentang itu dan dibanding periode sebelumnya yang sama panjang; prediksi, stok, Monte Carlo & rekomendasi tetap dari analisa aktif (diberi keterangan).
- 12 bagian: ringkasan, target & tren (harian + rata-rata 7 hari, kumulatif vs laju target, 6 bulan + target), produk terlaris (bar, treemap, perubahan), prediksi & stok, iklan (biaya vs omzet per produk), campaign tersimpan yang beririsan (timeline), performa toko harian, transaksi/batal/retur, SWOT, fishbone, rekomendasi, panduan kerja. Unduh semua tabel (Excel) + cetak PDF.
- **Simpan laporan**: snapshot JSON di kv_setting (`laporan:index`, `laporan:<id>`, maks. 60) lewat `src/core/report_data.py` (`build_snapshot` di UI, `ReportStore`, `to_json`/`from_json`). Mode **Laporan tersimpan** membuka laporan persis seperti saat disimpan tanpa menghitung ulang; bisa dihapus.
- `daily_orders` cocok dengan `order_metrics` (sales bersih, pesanan, batal) — diuji.

## Evaluasi model untuk tesis (8 Nov 2026)

- `src/core/model_history.py`: riwayat semua analisa tersimpan (data/runs/*/state.pkl), uji kesesuaian metode (skill vs MA28 & Level terkini, MAPE agregat ≤ 15%, bias, Top 50, tingkat layanan, jumlah lipatan, stabilitas & konsistensi antar analisa, keterbatasan in-sample segmen), profil permintaan Syntetos–Boylan (ADI/CV²), Pareto, replikasi walk-forward per SKU (disimpan `eval_detail.pkl` di folder run), uji maju (prediction_snapshot vs aktual sesudah tanggal analisa).
- Tab Evaluasi: 9 bagian (Ringkasan & kesesuaian metode, Metodologi, Profil data, Hasil uji walk-forward, Kurva aktual vs prediksi, Uji maju, Riwayat analisa, Fitur & segmen, Lampiran), gambar bernomor, unduhan Excel per bagian & lampiran lengkap.
- Analisa #5 (bulan): Ensemble per segmen, MAPE agregat 18,6% (target 15%), WAPE 68,1% vs MA28 70,4% (skill +3,3%), bias −16,5% → 5 dari 10 uji sesuai. Uji maju terisi setelah transaksi hari sesudah analisa diunggah.

## Data: performa penjualan instan & urutan bagian (8 Nov 2026)

- Urutan tab Data: Status pesanan → Kontribusi invoice batal → **SKU dengan retur dan batal** (dipindah ke sini agar satu kelompok batal/retur) → Asal pesanan per wilayah → **Performa penjualan instan** (baru) → Pembeli batal karena belum bayar.
- `src/core/instant.py` + `src/ui/instant.py`: instan = Opsi Pengiriman Instant, Instant Prioritas, Same Day (SPX/GoSend/GrabExpress), ikut periode data. Kartu invoice/sales bersih/tingkat batal/AOV instan vs lainnya, median waktu proses (bayar → pengiriman diatur), pesanan diproses > 2 jam, median sampai selesai; grafik harian per layanan + porsi instan, jam pesanan + % batal, box plot waktu proses; tabel per layanan × kurir (semua opsi sebagai pembanding), alasan batal instan, kota tujuan, produk instan teratas; Excel.
- Sales bersih per layanan dijumlah = sales bersih tab Data (Okt 2026: Rp 2.849.936.785). Okt 2026: 334 invoice instan (4,9%), batal 12,3% vs 23,1% lainnya, median proses 2,7 jam, 9 batal karena penjual tidak mengatur pengiriman.

## Langkah berikutnya

Audit ulang per menu bersama pengguna, satu per satu:
Beranda → Data latih & Jalankan analisa → Ringkasan & Prediksi → Prediksi vs aktual → Data → Folder data → Rekomendasi → Laporan → Evaluasi model → Setting → Kelola user.

## Audit menyeluruh 8 Nov 2026

Perbaikan logika:
- Iklan bertahap (`ads_strategy.ramp`): kekurangan tiap minggu dikurangi tambahan omzet yang sudah terbawa dari minggu sebelumnya. Dulu rencana 1,7–2× kekurangan, sekarang ±1,2×.
- Flash sale: stok flash per SKU dibagi ke semua slotnya; slot berulang tidak memakai stok/transfer DC yang sama dua kali. Aturan harga bawaan = **Tidak di bawah impas**. SKU tanpa data margin diberi catatan.
- Iklan: peringatan bila periode campaign di luar sisa bulan target; kunci cache rekomendasi ikut omzet iklan, produk & kontribusi; pesan "permintaan sudah penuh" diganti penjelasan batas prediksi (+ jumlah iklan tanpa prediksi).
- File margin: persen "8.5", "0,5%", "1" dan angka "1.250.000" dibaca benar (dulu 85%, 50%, 100%).
- Label ⚠ Perlu perhatian butuh min. 5 baris pesanan.
- Exposure: playbook Bak cuci piring; naskah 12–22 dtk tidak lagi "demo <manfaat>".
- Evaluasi model: SKU-lipatan dengan hari stok kosong di periode uji tidak dinilai (dulu dianggap 0). Bobot ensemble, faktor bias, dan pilihan segmen diungkap sebagai in-sample. Angka baru muncul setelah analisa dijalankan ulang.

Tampilan & wording: actual → aktual, Potensi loss → Potensi … hilang, Dashboard prioritas → Prioritas hari ini, ROAS protection → perlindungan ROAS Shopee, E-commerce Jakarta, footer Beranda, warna naik hijau → biru, font kalkulator/iklan/Top 50 ikut skala `--fs-*`, judul bagian Laporan, data gudang > 1 hari ditandai merah, galat Rekomendasi tanpa teks teknis di depan, nama produk di kalender dipotong per kata.

Data baru dimanfaatkan: tab Data › **Pembayaran, berat & ketepatan kirim** (Metode Pembayaran, Total Berat, Pesanan Harus Dikirimkan Sebelum). Okt 2026: Online Payment batal 33,7% vs ShopeePay 9,9%; paket ≥ 20 kg lebih sering batal; 13,2% pesanan diatur kirim setelah batas Shopee (Instant 56%).

Keputusan pengguna (sudah diterapkan):
- Target & proyeksi pakai **sales bersih** di semua halaman (Kalkulator, target iklan). Prediksi model (harga produk) dikali faktor sales bersih ÷ sales produk bulan berjalan (dibatasi 0,5–1,2); omzet tambahan iklan juga dikali faktor ini.
- **Belum Bayar** yang masih terbuka dipisah: bukan batal, bukan terjual (Okt 2026: 6 pesanan, Rp 2.577.772). Batal = status batal saja. Sales bersih Okt tetap Rp 2.848.905.957.
- **Safety stock** = Z × σ × √(L + R), R = periode tinjau (`lead_time.review_hari`, bawaan 7). Impor: Z × √((L+R)σ² + d²σ_L²), σ_L = (L maks − L rata) ÷ 1,645, jadi tingkat layanan ikut berpengaruh.
- **MA28**: bila 28 hari terakhir semua tersensor (stok kosong), pakai rata-rata 28 hari terakhir yang teramati (dulu 0).
- **Winsorize** dihitung per SKU (dulu batas gabungan semua SKU memotong hari normal SKU laris).
- **XYZ** (segmentasi Dashboard/Rekomendasi) menghitung hari tanpa penjualan sebagai 0; batas **ABC** disamakan 80/95% seperti evaluasi.
- **Monte Carlo**: permintaan lead time ~ N(d·L, σ·√L) dengan L acak; SS tidak ditambahkan lagi; risiko = P(permintaan lead time > stok).
- Replikasi kurva Evaluasi memakai `zero_since` analisa aktif dan melewati SKU-lipatan tersensor (versi detail 2, dihitung ulang otomatis).
- **Perlu dijalankan ulang**: analisa (Jalankan analisa) lalu buka Evaluasi model agar SS, ROP, bobot ensemble, dan kurva memakai rumus baru.

Belum dipakai: kolom voucher Shopee & potongan ongkir karena format angkanya ambigu ("10.138" vs "167.21").

## Pindah database ke Supabase (9 Nov 2026)

- Neon habis masa gratis; app tetap memakai `DATABASE_URL` Postgres, sekarang diarahkan ke Supabase (URI **Session pooler**, port 5432).
- Hemat kuota: isi `file_vault` dikompres zlib (penanda `\x00ZL1`, baris lama tanpa kompresi tetap terbaca); data laptop 136 MB → 54 MB. Pool koneksi 2 + 3. Halaman Data latih menampilkan MB terpakai vs kuota 500 MB.
- `scripts/pindah_ke_supabase.py` (+ `src/core/migrate.py`): buat tabel lewat kode app, salin 24 tabel SQLite lokal, unggah data latih (`team/…`) dan hasil analisa yang tercatat (`runs/<id>/…`) ke brankas dengan kunci yang dipakai server. Folder run yatim (7–11) tidak ikut.
- Evaluasi mencocokkan riwayat run lewat `folder_of`, jadi path laptop di `result_path` tidak mengganggu di server.
- Langkah pengguna: buat project Supabase (Singapore) → `scripts/cek_database.py` → `scripts/pindah_ke_supabase.py` → ganti `DATABASE_URL` di Secrets Streamlit → Reboot. Panduan di `DEPLOY_GRATIS.md`.

## Satu tempat unggah: stok, replenishment, margin, target (9 Nov 2026)

- Stok diunggah di **Upload data › Stok**: Stok Site 10037 (Shopee), Stok DC 10062, Stok DC 10036. Team DC mendapat izin `upload_stok` (level "upload") dan membuka Upload data khusus menu Stok.
- **Replenishment Site 10037** hanya diunggah di **Setting › Kapasitas gudang** (kebutuhan denah gudang), dengan izin baru `upload_replenishment`: Super user, Team DC, dan Team IC/MD (E-commerce specialist hanya melihat). Simpan memberi pesan tetap dan menolak file site lain.
- Stok DC 10062/10036 kini menerima laporan *Replenishment Calculation by Date* (stok = kolom **Stock On Hand**, site = **Site No**). Sebelumnya stok terbaca dari kolom Quantity PO (0) sehingga Ringkasan menganggap DC kosong; unggahan lama dipulihkan otomatis dari kolom Stock On Hand yang ikut tersimpan. File stok yang semua kuantitasnya 0 ditolak. Replenishment Site 10037 menolak file site lain.
- **File margin** dipindah ke Upload data › Target & margin › File margin; Setting › Kalkulator biaya hanya menampilkan status. Simpan kini memberi pesan tetap (berhasil + jumlah baris, atau galat) dan mengosongkan kotak unggah.
- Template target bulanan mulai **Januari tahun berjalan s.d. Desember tahun depan** dan sudah berisi target tersimpan; baris target kosong dilewati (tidak menimpa). Simpan target memberi pesan tetap berisi bulan yang tersimpan.
- Rumus prediksi, safety stock, dan data terkunci tidak diubah.

## Masuk aplikasi lebih ringan (9 Nov 2026)

- Beranda tidak lagi membuka file hasil analisa (±8 MB). File itu dibaca saat halaman hasil dibuka.
- Tanggal pesanan terakhir diingat per file bulan, jadi beranda tidak membaca ulang data transaksi pada setiap klik.
- Huruf tidak lagi menunggu Google Fonts sebelum CSS tampilan dipakai. Font Plus Jakarta tetap dimuat tema, dengan cadangan font sistem.
- Library model (scikit-learn, statsmodels, XGBoost) baru dimuat saat prediksi atau imputasi berjalan, bukan saat halaman login/beranda.
- Pemeriksaan sesi login ke database dilewati selama 45 detik setelah berhasil, dan antrean cookie dipendekkan. Rumus prediksi dan safety stock tidak berubah.
- Pemeriksaan ulang (9 Nov malam): analisa terakhir kembali dimuat otomatis di semua halaman **kecuali Beranda** (Setting, Upload data, hasil). Sebelumnya hanya di halaman hasil, sehingga Setting › Kalkulator biaya/Laporan margin/Kapasitas gudang bisa memakai transaksi tersimpan mentah (tanpa saklar batal & retur) bila dibuka sebelum Hasil analisa. Tombol Hasil analisa di header Beranda tampil lagi bila ada analisa tersimpan. Batas tunggu cookie login dikembalikan ke ±4,8 detik (24 × 0,2 dtk) agar refresh di Cloud tidak minta login ulang.

## Batas kapasitas database (9 Nov 2026)

- Supabase project `mitra10-prediksi` (Singapore, gratis, Data API mati) aktif di Streamlit Cloud; data laptop sudah dipindah (94 MB dari 500 MB).
- Satu analisa ±9 MB (file hasil ±5,8 MB terkompres + snapshot prediksi ±2,9 MB). Tanpa batas, 90 hari analisa harian ±780 MB.
- `src/core/storage_guard.py` + `config/business_params.yaml` › `penyimpanan`: simpan 12 analisa terbaru, snapshot prediksi 30 analisa, log aktivitas 180 hari, hapus file brankas milik analisa yang sudah dihapus; > 400 MB → VACUUM FULL lalu hapus analisa tertua (min. 3 tersisa). Dijalankan saat server mulai dan setiap analisa disimpan. Perkiraan stabil ±200 MB.
- Data latih menampilkan "Database terpakai X dari 500 MB" dan peringatan bila > 400 MB.

## Kapasitas gudang 0% setelah upload replenishment 09/11 (9 Nov 2026)

- Penyebab: **Spesifikasi Barang** (Besar/Kecil) dan **Pick Location** adalah definisi tim, bukan kolom ekspor sistem. File 09/11 adalah ekspor mentah, jadi gondola terisi = 0 dan SKU Besar berstok = 0 → kartu kapasitas 0,0%.
- Sekarang definisi itu disimpan per SKU di tabel `warehouse_item_master` (tidak ikut terhapus saat snapshot replenishment dipangkas ke 60). Isi awal otomatis dari snapshot terbaru yang masih membawa kolom itu (23/09: 756 SKU). Isian master dipakai untuk semua replenishment berikutnya (`gudang.apply_master`); file yang masih membawa kolom itu ikut memperbarui master.
- Setting › Kapasitas gudang: peringatan jumlah SKU belum lengkap (Spesifikasi kosong, atau barang Kecil tanpa Pick Location) + bagian **Lengkapi data barang** dengan dua cara: *Edit per item* (tabel, saring belum lengkap/semua, cari SKU) dan *Unggah Excel* (template SKU belum lengkap / semua SKU). Validasi: Spesifikasi harus Besar/Kecil, Pick Location harus ada di denah. Hak ubah = hak unggah replenishment (Team DC, Team IC/MD, Super user).
- Data 09/11: 41 SKU baru belum lengkap; kapasitas 60,7% (534 dari 880 lokasi · gondola 225/300 · rak ±309/580).
- `FeatureStore.replace` dengan satu kunci kini menghapus massal (IN) agar simpan ratusan SKU ke Supabase cepat.

## Ringkasan: teks "Prediksi" terpotong jadi "diksi" (9 Nov 2026)

- Batang kartu Top 50 ("▼ Prediksi Rp … · x% di bawah terjual") rata kanan, satu baris, di dalam kotak `overflow: hidden`; bila tidak muat, awal kalimat yang terpotong. CSS `.qty-track`/`.qty-fill` di `app.py` kini membungkus ke baris kedua.

## Tinggi baris tabel teks sedang (10 Nov 2026)

- Tabel Kontribusi invoice batal: satu alasan 61 huruf ("Sistem Shopee · Penjual gagal mengirimkan pesanan tepat waktu") melewati batas kolom 400 px, sehingga semua baris dibuat 65 px (tinggi minimum bungkus) padahal teks muat satu baris.
- `wrap_layout` (`src/utils/format.py`): kolom teks s.d. ±90 huruf (660 px) kini dilebarkan sesuai isi dan tetap satu baris (35 px); baris hanya ditinggikan bila teks lebih panjang. Berlaku untuk semua tabel `show_table`.

## Prediksi › Pantauan harian bulan berjalan (10 Nov 2026)

Bagian baru di halaman Prediksi (di bawah prediksi vs aktual): `src/core/month_track.py` (logika) + `src/ui/month_track_view.py` (tampilan); tes `tests/test_month_track.py`. Rumus prediksi dan safety stock tidak diubah.

- **Per tanggal tgl 1 s.d. akhir bulan**: target harian, prediksi, aktual, selisih, % capaian, status, analisa sumber prediksi, kumulatif aktual/target/proyeksi; grafik Harian/Kumulatif (hari gajian & tanggal kembar diwarnai); Excel. Pilihan 3 bulan terakhir.
- **Prediksi H-1**: tiap tanggal memakai snapshot dari analisa terakhir yang dibuat sebelum tanggal itu (prediction_snapshot), jadi akurasi kemarin tetap bisa diaudit walau data latih berubah di analisa berikutnya. Tanggal mendatang memakai analisa terbaru.
- **Basis** sales bersih (sama dengan target); prediksi × faktor (sales bersih ÷ sales produk bulan ini), sama dengan `month_outlook`. `daily_net_sales` = `order_metrics` per hari (diuji).
- **Pola musiman**: indeks hari Senin–Minggu + kenaikan hari gajian (25–3) dan tanggal kembar dari ≤ 365 hari riwayat (median vs garis dasar 15 hari, disusutkan bila contoh sedikit). Laju datar model disebar dengan pola ini dan dinormalkan (total sebulan tetap = prediksi model). Target harian dibagi dengan pola yang sama.
- Hari dianggap penuh bila data sampai ≥ 23:00; hari yang belum penuh tampil "Berjalan". Peringatan bila data pesanan terlambat.
- **Kartu**: hari penuh terakhir (prediksi vs aktual + status), hari ini, besok (prediksi + target hari itu + jenis hari), proyeksi akhir bulan vs target (kurang/lebih).
- **Peringatan target** (kurang Rp, perlu Rp/hari vs prediksi Rp/hari) + **Top 5 tindakan** urut potensi omzet bersih s.d. akhir bulan: Stok (kebutuhan sisa bulan − stok; ambil Site 10062/10036 lalu PO), Iklan (riwayat iklan, stok cukup, tambah budget sampai titik impas 100 ÷ margin, maks. 5×, tambahan ≤ penjualan harian SKU), Harga & listing (7 hari < 60% prediksi dan < 60% laju 28 hari sebelumnya), Kejar bayar (30% nominal Belum Bayar 3 hari). Keterangan bila data stok/iklan belum ada di analisa.
- Data lokal (data s.d. 08/11 08:29, target Nov Rp 4,98 M): proyeksi Rp 3,28 M (66%), kurang Rp 1,70 M; 11.11 pola ×2,93.

## Tabel: baris Total terpotong & baris terlalu tinggi (10 Nov 2026)

- **Baris Total terpotong** (mis. Omzet 30 hari "·528.289.129" di Kapasitas gudang): Streamlit 1.50 menggambar sel ber-`font-weight` dengan huruf `700 0.875rem`, lebih besar dari huruf tabel yang dipakai menghitung lebar kolom, sehingga angka rata kanan terpotong. Baris Total kini ditandai latar biru muda `TOTAL_ROW_CSS` (`src/utils/format.py`), tanpa huruf tebal; berlaku untuk semua `show_table(..., bold_label=...)` dan tabel kejar bayar.
- **Tinggi baris**: Streamlit hanya membungkus teks bila tinggi baris > 4rem, jadi satu sel panjang membuat semua baris ≥ 65 px. `wrap_layout` kini: (1) teks yang 90% barisnya ≤ ±90 huruf dan terpanjang ≤ 1.000 px tetap satu baris (kolom dilebarkan); (2) lebar bernama (`small`/`medium`/`large`) dianggap minimum, dilebarkan bila teksnya muat satu baris; (3) paragraf dibungkus pada lebar 520 px (sebelumnya 400) agar barisnya lebih sedikit.
- **Saran gudang** diringkas (angka & logika sama): "Isi ulang ±18 unit (s.d. Max 20, 3 di jalan)", "Prediksi 30 hr 1 ≪ Max: turunkan Max". Semua tabel Kapasitas gudang kini 35 px per baris (sebelumnya 68 px).

## Deploy tanpa Reboot (10 Nov 2026)

- Setelah push, Cloud menjalankan `app.py` baru tetapi modul `src` lama masih di memori, sehingga impor nama baru gagal (`ImportError: TOTAL_ROW_CSS`) sampai app di-Reboot. `app.py` kini mencatat waktu ubah terbaru file `src/**/*.py`; bila berubah sejak rerun sebelumnya, modul `src.*` dibuang lalu diimpor ulang. Push ke `main` langsung aktif tanpa Reboot.

## Prediksi vs aktual harian: breakdown sebulan & hari belum penuh (10 Nov 2026)

- Grafik 7 hari diganti **breakdown tgl 1 s.d. akhir bulan** (`_month_breakdown`, `_month_chart`, `_month_table` di `src/ui/prediksi_top.py`): batang Prediksi vs Aktual bersih + Belum Bayar (kuning) per tanggal, % capaian di atas batang hari penuh, tabel per tanggal dengan baris Total s.d. hari penuh terakhir. Tanggal mendatang = prediksi analisa terbaru. Basis tetap SKU berprediksi (sama dengan kartu).
- **Hari penuh** (`complete_through`, `src/core/pred_actual.py`): hari data terakhir hanya dinilai bila sudah lewat hari ini atau data sampai ≥ 23:00 (sebelumnya cukup "bukan hari ini", jadi hari yang diekspor sore ikut dinilai dan tampak anjlok).
- **Belum Bayar** (`unpaid_by_day`): omzet pesanan yang masih Belum Bayar ditampilkan terpisah + "% bila Belum Bayar dibayar". Di data lokal hari penuh terakhir (7 Nov) masih 6,2% Belum Bayar saat ekspor; hari lama 0% (sudah dibayar/batal), jadi hari terbaru selalu tampak lebih rendah.
- Catatan pemeriksaan 9 Nov (79,7%): prediksi 9 Nov memakai snapshot analisa terbaru (laju datar Rp 122,9 jt/hari, 786 SKU), sedangkan 1–7 Nov uji mundur (±Rp 92–136 jt, SKU aktif) — lompatan basis prediksi. Laju 122,9 jt wajar (rata-rata 7/14 hari Rp 115/120 jt), jadi selisih 9 Nov = penjualan Senin memang lebih rendah + Belum Bayar belum masuk (+ kemungkinan data belum penuh).
- **Konsisten dengan Pantauan harian** (10 Nov): prediksi tanggal mendatang dan snapshot "analisa H-1" (laju datar) kini disebar dengan pola hari yang sama (`month_track.month_shape`, dipakai juga oleh `month_table`): Senin–Minggu, gajian, tanggal kembar; total sebulan tetap. Sebelumnya breakdown memakai laju datar (11 Nov ±Rp 123 jt) sementara Pantauan harian ±Rp 323 jt. Sekarang 11 Nov Rp 360 jt (basis SKU, sales produk) vs Rp 323 jt (sales bersih toko = × faktor 0,90). Kolom baru: Jenis hari, Pola hari. Hari "uji mundur" tetap memakai pola Senin–Minggu dari model uji mundur.
- **Baris Total sebulan** (10 Nov) di atas breakdown: Prediksi = Σ prediksi semua tanggal bulan itu, Aktual = terkumpul s.d. hari penuh terakhir, % = progres terhadap prediksi sebulan, Status = proyeksi akhir bulan (aktual + prediksi hari tersisa). `style_frame`/`show_table` kini menerima beberapa label Total (`bold_label=(a, b)`). Beda angka dengan kartu Pantauan harian: basis (SKU berprediksi, sales produk vs sales bersih seluruh toko × faktor ±0,90).
- **Target sales di breakdown** (10 Nov): garis merah "Target harian" di grafik + kolom Target harian & % target di tabel. Target bulanan (sales bersih toko, menu Target sales) dibagi per tanggal dengan pola hari yang sama dengan Pantauan harian, lalu dikali rasio aktual grafik ÷ sales bersih toko s.d. kemarin agar setara basis SKU (data lokal: rasio 1,08). Baris Total s.d. = aktual ÷ target berjalan (65%); baris Total bulan = proyeksi ÷ target sebulan (68%, selaras Pantauan harian 66%).
- **Target tampil apa adanya** (10 Nov): sebelumnya target dikali rasio aktual SKU ÷ sales bersih (1,08) sehingga totalnya tampak Rp 5,37 M. Kini kolom Target harian = target bulan dibagi pola hari (total persis = target, mis. Rp 4.979.324.119; 11 Nov Rp 487 jt = kartu Pantauan harian), dan % target dihitung dari kolom baru **Sales bersih toko** (basis sama dengan target). Baris Total bulan: proyeksi bersih = sales bersih s.d. kemarin + prediksi sisa × faktor sales bersih ÷ sales produk (sama dengan Pantauan harian) → data lokal Rp 3.283.460.608 (66%), identik dengan kartu Proyeksi akhir bulan. Kolom "Aktual bersih" diganti nama "Aktual SKU".
- **Pantauan harian**: grafik Harian/Kumulatif dan expander "Rincian per tanggal" dihapus (sudah ada di breakdown Prediksi vs aktual di atasnya); kartu, peringatan target, Top 5, dan Cara membaca tetap.

## Kapasitas gudang 0% di Cloud: tabel master belum dibuat (10 Nov 2026)

- Gejala: 742 SKU "belum punya Spesifikasi", kapasitas 0%, walau snapshot 23/09 (data valid tim gudang: 756 SKU lengkap Spesifikasi, 291 Pick Location) ada di database Cloud.
- Sebab: `FeatureStore` di-cache per proses (`auth/ui.py` `st.cache_resource`) dan dibuat sebelum tabel `warehouse_item_master` ada; proses Cloud belum restart, jadi tabel tidak pernah dibuat dan `load_master` gagal diam-diam → data awal tidak pernah disalin.
- Perbaikan: (1) `FeatureStore._table` membuat tabel yang belum ada saat pertama dipakai; (2) cache store diberi versi kode (`MITRA10_SRC_STAMP`) dan `app.py` ikut memuat ulang `auth.ui` (bukan `auth.repository`, agar sesi login tetap) saat kode berubah; (3) `load_master` menampilkan peringatan bila gagal baca. Saat halaman dibuka, master diisi sekali dari snapshot terbaru yang membawa Spesifikasi (23/09), lalu dipakai untuk snapshot 09/11; SKU baru tetap muncul di "Lengkapi data barang".
- Lanjutan (10 Nov 01:30): di Cloud masih muncul "Tabel fitur tidak dikenal: warehouse_item_master" — store lama tetap terpakai karena pembersihan modul berbasis satu stempel waktu bisa terlewat (file hasil pull ditulis bertahap; rerun di tengah memakai app.py lama lalu mencatat stempel baru). Diganti: pencatat waktu impor (`_ImportClock` di `sys.meta_path`) + modul `src.*`/`auth.ui` dibuang bila filenya lebih baru dari saat diimpor (atau diimpor sebelum pencatat ada). Run pertama sesudah push ini pasti memuat ulang semuanya, termasuk store baru yang membuat tabel master.

## Iklan: strategi budget & ROAS tetap (10 Nov 2026)

- Panel baru bersorot oranye di Rekomendasi › Iklan, tepat di bawah Rekomendasi sistem: **Selamatkan target dengan budget & ROAS yang Anda punya**. Input sendiri: budget maksimal (plafon) dan ROAS minimal; rekomendasi ideal tetap ada sebagai pembanding.
- Rencana (`src/core/ads_fixed.py` + `build_plan(..., stock_cap=True)`): alur iklan sama dengan Kejar target (pemilihan produk → budget per iklan → naik bertahap per minggu), ditambah (1) tambahan omzet tiap iklan dibatasi juga ruang stok produknya (`stock_capped`), (2) **kalender budget harian** (`day_plan`): budget mingguan sama, digeser ×0,7–1,4 ke tanggal ramai menurut pola sales bersih (gajian, tanggal kembar, hari dalam minggu), hanya untuk iklan yang masih bisa tumbuh ("Ikut kalender"). Rumus rekomendasi ideal tidak berubah (stock_cap bawaan mati).
- Kekurangan sisa dirinci per sumber (Jalur penyelamatan target): susun ulang iklan → atur budget per tanggal → kejar Belum Bayar terbuka bulan ini (rencana 50% dibayar setelah chat) → flash sale/voucher produk berstok aman (`push_candidates`: belum didorong iklan, margin tidak minus, tambahan per produk maks. min(ruang stok, daya dorong × prediksi)).
- Strategi detail otomatis: iklan tempat budget dipusatkan, iklan yang dipangkas, iklan dibatasi stok (ajukan PO), tanggal naik/turun budget, selisih janji tanpa batas stok, budget maksimal yang masih berguna pada ROAS yang sama, dan aturan pantau harian. Unduhan Excel berisi perbandingan, jalur, budget per iklan, kalender, produk didorong.
- Tombol **Jadikan setelan campaign**: Setelan ROAS & budget diisi dari panel, langkah 2–4 memakai rencana berbatas stok + kalender, dan saat disimpan campaign ikut mengunci kalender harian (tampil di campaign terkunci).
- Data lokal (ROAS 15, budget Rp 163 jt/21 hari): iklan +Rp 216 jt (tanpa batas stok +Rp 356 jt, Rp 140 jt melebihi stok), kalender +Rp 3 jt, Belum Bayar Rp 7 jt, dorongan 30 produk Rp 44 jt → 68,9% target; budget yang masih berguna pada ROAS 15 maks. Rp 181 jt.
- **Disederhanakan** (10 Nov, masukan: penjelasan membingungkan saat budget Rp 250 jt & ROAS 20): panel kini berisi 3 kartu (Proyeksi akhir bulan, Budget terpakai, Kekurangan), kotak **Kenapa hasilnya begini** (mis. "ROAS minimal 20 lebih tinggi dari ROAS iklan sekarang 15,3 → iklan lemah harus dikurangi, omzet iklan turun Rp 311 jt; hanya Rp 103 jt dari Rp 250 jt bisa dipakai"), tabel **Pilihan ROAS dengan budget yang sama** (setelan Anda vs ROAS sekarang vs rekomendasi ideal, berbatas stok) + tombol pakai ROAS yang lebih baik, dan daftar **Yang dikerjakan** (putuskan ROAS → ubah budget iklan → tanggal ramai → chat Belum Bayar → flash sale/voucher → PO → pantau). Rincian angka, perbandingan ideal, budget per iklan, kalender, dan produk flash sale dipindah ke expander.
- **Hanya iklan, budget dikunci** (10 Nov, masukan: "kunci budget, ROAS diatur sistem, hanya mengandalkan iklan"): flash sale/voucher dan chat Belum Bayar dihapus dari hitungan & langkah. Pilihan **Diatur sistem** (default) mencari ROAS tertinggi yang masih memberi omzet iklan terbesar dengan budget itu (`ads_fixed.best_roas`); **Saya tentukan** tetap ada. Kartu: Proyeksi akhir bulan, Omzet tambahan dari iklan (ROAS rata-rata & minimal per iklan), Budget terpakai. Kotak **Agar target tercapai dengan iklan**: tabel per asumsi daya dorong (+50/+75/+100%) berisi maks. dengan stok sekarang, maks. bila restock, budget terkecil yang menutup target (`ads_fixed.budget_needed`), ROAS-nya, dan nilai restock; daftar produk iklan yang perlu restock + tombol pakai budget itu. Data 9 Nov (budget Rp 250 jt): ROAS dipilih 6,0, proyeksi 70,7% (Rp 228 jt terserap); target hanya tercapai pada daya dorong +100% dengan restock ±Rp 1,41 M nilai jual dan budget Rp 410 jt ROAS ±10,5 — penghambat utama stok.
- **Formula dibenahi** (10 Nov, masukan: "ROAS dipilih 1,0" & tabel daya dorong membingungkan): (1) Target ROAS otomatis kini `ads_fixed.pick_roas` — semua Target ROAS di grid 1–30 dicoba pada budget terkunci, dipilih omzet iklan terbesar (pencarian lama mengandaikan hasil naik saat ROAS turun; nyatanya tidak, mis. Rp 150 jt: ROAS 16–17 memberi +Rp 146 jt vs ROAS 1 +Rp 123 jt, karena pemilihan produk ikut ROAS). (2) Kotak **Hitungan target dengan budget ini** menggantikan tabel daya dorong/budget lain: kekurangan per hari (dan % dari prediksi semua produk), **ROAS dibutuhkan** = (omzet iklan sekarang × hari + kekurangan) ÷ budget (`needed_roas`), ROAS realistis dengan stok sekarang & bila restock, lalu kesimpulan. Data 9 Nov, Rp 250 jt: kekurangan Rp 96 jt/hari (+79% dari prediksi Rp 122 jt/hari) → ROAS dibutuhkan 18,1 vs realistis 12,5 (14,0 bila restock, 82,6% target). Tombol "pakai budget lain" dihapus karena budget dikunci.
- **Target ROAS 1 dibenahi** (10 Nov, masukan: "target ROAS 1 itu salah"): ROAS di pencarian adalah batas ROAS rata-rata, jadi batas 1 membiarkan sisa budget dipakai di iklan yang hampir tidak menjual (Rp 250 jt: ROAS 12 → 1 hanya +Rp 20 jt omzet untuk +Rp 11 jt biaya), dan pemilihan produk ikut berubah dengan ROAS. Sekarang: pemilihan produk memakai ROAS iklan sekarang (`build_plan(select_roas=...)`, `ads_fixed.selection_roas`); semua ROAS dicoba, lalu **Target ROAS = ROAS rata-rata rencana terbaik dibulatkan ke bawah** (`ads_fixed.shopee_roas`) dan rencana dihitung ulang dengan angka itu. Data 9 Nov: Rp 250 jt → Target ROAS 13,0 (rata-rata 13,1, 70,0% target, Rp 212 jt terpakai); Rp 150 jt → 17,0 (terpakai penuh). Hasil `plafon` yang tidak dipakai dihapus dari `_fixed_plan`.

## Kolom Ambil dari DC + outstanding (14 Nov 2026)

- Bila SKU punya outstanding di Replenishment Calculation by Date Site 10037 terbaru, kolom **Ambil dari DC** kini menambahkan keterangannya: mis. "Ambil 5 dari Site 10062 · kurang 3 → PO supplier · Outstanding: PO 10 · TR 5"; SKU tanpa kebutuhan restock tetapi ada outstanding: "Outstanding: TO 4". Berlaku di tabel Restock Ringkasan, tabel keputusan (Prediksi/Top 50), tabel Prediksi Top, rekap prediksi harian, unduhan Excel, dan daftar tindakan restock.
- Sumber: `insight_live.attach_outstanding` (kolom `outstanding_10037` pada katalog setelah data fitur dibaca di `app.py`) + `dc_stock.dc_take_label`. `sumber_restock` tidak diubah, jadi hitungan "cukup dari DC / sebagian / harus PO" tetap membaca rencana saja (`dc_stock.plan_only`).
- Kolom terpisah "Outstanding Site 10037" di tabel Restock Ringkasan dihapus karena isinya sekarang ada di Ambil dari DC.

## Kapasitas gudang: barang di jalan = PO + TR + TO + TR toko lain (14 Nov 2026)

- Saran isi ulang (`gudang._item_action`) dan kolom "Barang dalam perjalanan" kini menghitung outstanding PO + TR + TO + TR dari toko lain (`items["di_jalan"]`, `gudang.INCOMING`); sebelumnya hanya PO + TR. Snapshot lama tanpa kolom TO/TR toko lain dibaca 0.
- Perbaikan teks: "s.d. Max 20. 3 di jalan" → "s.d. Max 20, 3 di jalan" (koma pemisah sebelumnya ikut diganti titik). "Tunggu barang di jalan" kini menyebut jumlah unitnya.

## Outstanding PO/TR/TO di kartu SKU & Analisa (14 Nov 2026)

- `insight_live.attach_outstanding` kini juga menyimpan angka per SKU (`os_po`, `os_tr`, `os_to`, `os_tr_lain`, `os_total`), umur (`os_sejak`, `os_umur`, `os_minimal` dari riwayat snapshot) dan tanggal replenishment (`os_tanggal`).
- `insight_live.outstanding_plan`: kekurangan Site 10037 (kebutuhan 30 hari − stok) dikurangi outstanding dulu, sisanya baru diambil dari DC (10062 → 10036) lalu PO. `outstanding_verdict` memberi kesimpulan: belum ada outstanding / outstanding menutup kekurangan (tidak perlu transfer/PO baru) / masih kurang X → TR/TO dari DC + PO / stok cukup dan outstanding menambah stok. Outstanding > 7 hari (`STALE_DAYS`) diberi saran tindak lanjut ke Team DC/supplier.
- Kartu SKU (baris Stok DC): chip "Outstanding: PO · TR · TO · sejak (umur)", lalu "Outstanding menutup kekurangan" atau "Setelah outstanding masih kurang X unit"; chip merah "Belum ada outstanding PO/TR/TO" bila kurang dan tidak ada proses.
- Analisa (bagian stok): blok baru **Outstanding PO/TR/TO menuju Site 10037** (rincian per jenis, umur, kekurangan, sisa setelah outstanding, ambil DC/PO bersih, kesimpulan) sebelum blok Stok DC. Kesimpulan Stok DC diberi catatan bahwa hitungannya belum mengurangi outstanding. Kolom Ambil dari DC tetap rencana sebelum outstanding + keterangan outstanding.

## Grafik QTY & Sales SKU (bulan ini) dirapikan (14 Nov 2026)

- **Tanggal 1 s.d. kemarin lengkap**: batang terjual dan "Prediksi sebelumnya" diberi angka untuk setiap hari lewat, termasuk 0. Hari tanpa analisa tersimpan maupun uji mundur (SKU belum punya riwayat penjualan sebelum tanggal itu) = prediksi 0 dengan sumber "belum ada riwayat penjualan", bukan kosong.
- **Angka bulat**: label & hover batang memakai `_round_label` (QTY unit utuh, sales Rupiah utuh tanpa desimal, mis. 5.169.500).
- **Tidak tumpang tindih**: label batang tegak (textangle −90, ukuran tetap), ruang di atas batang tertinggi (sumbu Y × 1,35), "◀ aktual | prediksi ▶" di dalam area grafik, garis batas hari ini per panel (tidak menembus judul Proyeksi sisa stok), jarak antarpanel lebih besar (tinggi 760 px).
- **Tanggal tegak lurus** di kedua panel (sebelumnya panel atas miring −60°).
- **Proyeksi sisa stok mulai tanggal 1** (`past_stock_path`): garis abu-abu "Stok tanggal lalu (unggahan ± terjual)" dari riwayat unggahan Data stok Site 10037 SKU itu: hari unggahan = stok tercatat, hari sesudahnya = stok unggahan − terjual, hari sebelum unggahan pertama = perkiraan mundur (stok unggahan + terjual, barang masuk tidak diketahui). Titik hari ini = stok sekarang, disambung garis oranye proyeksi prediksi.
- **Lanjutan (14 Nov)**: label batang diganti satu anotasi tegak per tanggal di atas batang tertinggi (hari lewat "terjual / prediksi sebelumnya", hari mendatang "prediksi") karena label per batang masih saling menimpa (mis. "0 0", angka sales 10–13 Nov). Keterangan cara baca ditambahkan di bawah grafik.
- **QTY selalu bulat**: `fmt_qty` (src/ui/common.py) dan `format_qty` (app.py) kini selalu 0 desimal (mis. Prediksi sisa Nov 180,6 → 181 unit); laju harian di kartu SKU juga bulat (rata-rata 14,5 → 15 unit/hari, 11,36 → 11 unit/hari).
- **Lanjutan 2 (14 Nov)**: label tegak panjang (mis. "682.500 / 5.669.562") masih menembus judul. Batas atas sumbu Y kini dihitung dari panjang tiap label (`label_headroom`: Y ≥ tinggi batang ÷ (1 − panjang label px ÷ tinggi panel px)), dan teks "◀ aktual | prediksi ▶" di dalam grafik dihapus (diganti keterangan garis putus-putus di bawah grafik).

## Breakdown per tanggal: header beku, achievement & akurasi (14 Nov 2026)

- Tabel Breakdown per tanggal (Prediksi vs aktual harian) kini bergulir di dalam (tinggi maks. 640 px) sehingga judul kolom tetap terlihat; kolom Tanggal disematkan di kiri (`pinned`). Sebelumnya `max_height=10_000` membuat tabel memanjang dan header ikut tergulir.
- Kolom "% capaian" diberi nama **Achievement (% capaian)** (aktual ÷ prediksi) dan ditambah **Akurasi prediksi** (`prediksi_top.accuracy`: 100% − |aktual − prediksi| ÷ aktual per hari penuh; baris Total s.d. = 100% − Σ|selisih| ÷ Σ aktual).
- Sel kosong tanggal mendatang tampil "-" (sebelumnya "None": kolom bertipe object).

## Kartu Pantauan harian ↔ tabel Breakdown per tanggal (14 Nov 2026)

- Pertanyaan: kartu Kemarin/Hari ini/Besok (mis. 13 Nov prediksi Rp 106.207.490) tidak sama dengan tabel (Prediksi sales produk Rp 121.131.386). Sebab: kartu berbasis **sales bersih toko** (sama dengan target) = prediksi sales produk × faktor sales bersih ÷ sales produk bulan ini (±0,88); tabel berbasis sales produk.
- Tabel kini punya kolom **Prediksi sales bersih** (= angka kartu) dan **Achievement bersih** (Sales bersih toko ÷ Prediksi sales bersih = capaian kartu Kemarin), termasuk di baris Total. Kartu menulis jejaknya: "= prediksi sales produk Rp … × faktor 0,88".

## Menu & header bisa dibuka di tab baru (14 Nov 2026)

- Tombol menu (Ringkasan … Evaluasi model) dan tombol header (Hasil analisa, Upload data, Setting, Beranda) adalah `st.button`, jadi klik kanan → Buka di tab baru tidak membawa halaman tujuan (tab baru terbuka di Ringkasan). `link_buttons` (app.py) menaruh lapisan `<a href="?page=…&tab=…">` transparan di atas tombol: klik kanan/Ctrl-Cmd-klik/klik tengah membuka halaman itu di tab baru (rute dipulihkan oleh `sync_route`), klik kiri biasa diteruskan ke tombol Streamlit (tanpa muat ulang).

## Breakdown per tanggal ditata ulang (14 Nov 2026)

- Urutan & nama kolom (`prediksi_top._month_display`): Tanggal · Status · Hari (jenis hari + pola) → kelompok **Produk** (sales produk, dasar model): Prediksi, Aktual, Selisih, Achievement, Akurasi, Belum Bayar, Achievement + BB → kelompok **Bersih** (sales bersih toko, dasar target & kartu Pantauan harian): Target, Prediksi, Aktual, % target, Achievement → Sumber prediksi.
- Teks tidak terpotong: lebar kolom pasti dari teks terpanjang + judul (`_month_widths`), baris satu baris (tidak 68 px lagi). Status baris Total bulan = "Sebulan"; proyeksi akhir bulan ditulis di atas tabel (sebelumnya "Proyeksi bersih Rp …" terpotong).
- Hari Berjalan/Akan datang: selisih, achievement, akurasi, % target dikosongkan (aktual belum sehari penuh). Sel kosong ditulis "" agar st.dataframe tidak menampilkan "None".
- Keterangan kolom dipindah ke daftar penjelasan (Kelompok kolom, Achievement, Akurasi, Achievement + BB, Target, Hari, Berjalan).

## Breakdown per tanggal: kembali ke format angka & lebar semula + akurasi (14 Nov 2026)

- Sel kosong yang ditulis "" membuat kolom angka berubah jadi teks (angka mentah tanpa pemisah/Rp/% dan kolom sangat lebar). Dikembalikan: kolom angka tetap numerik (format Rp / % dari Styler), lebar otomatis; hanya kolom teks (Tanggal, Status, Hari, Sumber prediksi) diberi lebar pasti agar tidak terpotong.
- Deret kolom Produk dan Bersih disamakan: Prediksi · Aktual · Selisih · Achievement · Akurasi (Bersih menambah Selisih & Akurasi), lalu Bersih · Target · % target, Belum Bayar, Achievement + BB, Sumber prediksi.
- Kartu ringkas akurasi di atas tabel (`_accuracy_cards`): Akurasi prediksi produk & bersih (100% − Σ|selisih| ÷ Σ aktual hari penuh), Achievement s.d. hari penuh terakhir, jumlah hari tepat (achievement 90–110%).
- Link tab baru: kode overlay kini dipasang di dokumen utama (bukan di iframe komponen yang dibuang saat rerun, yang membuat timer/observer berhenti sehingga link tidak terpasang).

## Tabel Prediksi vs aktual per SKU: kolom tetap & istilah seragam (14 Nov 2026)

- SKU, Produk (320 px), Varian disematkan (`pinned`) sehingga tetap terlihat saat tabel digeser.
- Nama kolom diseragamkan dengan Breakdown per tanggal: QTY · Prediksi/Aktual (dibulatkan unit utuh), Produk · Prediksi/Aktual/Selisih/Achievement/Akurasi. "Selisih omzet" → "Produk · Selisih"; teks "omzet" di ringkasan penyebab → "sales produk". Akurasi per SKU & total ditambahkan.

## Top 5 tindakan segera: kolom Varian, kolom tetap, outstanding (14 Nov 2026)

- `priority_actions` kini mengisi kolom **Varian** terpisah (sebelumnya digabung ke Produk); Prioritas, Jenis, SKU, Produk, Varian disematkan di kiri.
- Tindakan restock ditambah keterangan outstanding Site 10037 (`month_track.outstanding_note`): "Outstanding PO 20 · TR 10 (sejak 05/11, 9 hari) → masih perlu 20 unit lagi" / "→ sudah menutup kebutuhan, pastikan segera diterima" / "Belum ada outstanding PO/TR/TO: segera buat TR/TO/PO".

## Tabel Top 50 / semua prediksi: Varian dibekukan, Ambil dari DC lengkap (14 Nov 2026)

- Kolom Varian ikut dibekukan (Grafik, Rank, SKU, Produk, Varian); kolom Ambil dari DC dilebarkan ke 300 px.
- `dc_take_label`: bila replenishment Site 10037 sudah diunggah, SKU yang perlu restock tanpa proses kini ditulis "… · Belum ada outstanding PO/TR/TO"; outstanding yang ada diberi umur "(sejak 05/11, 9 hari)". Tanpa unggahan replenishment, `attach_outstanding` tidak menambah kolom outstanding (tidak ada klaim "belum ada").

## Tabel wilayah (provinsi/kota): angka & nama diselaraskan (14 Nov 2026)

- Invoice total ternyata ≠ bersih + batal + retur (selisih = pesanan Belum Bayar, mis. 4.085 vs 4.060). Ditambah kolom **Invoice Belum Bayar** sehingga bersih + batal + retur + Belum Bayar = total; keterangan & kartu disesuaikan.
- "Sales value bersih" → **Sales produk bersih** (istilah sama dengan tabel Prediksi); ditambah **Kontribusi sales bersih** di samping Kontribusi invoice bersih (keduanya bisa berbeda, mis. Jawa Timur 17,1% invoice vs ±19% sales).
- Rank baris Total kosong (sebelumnya "None").
- **Lanjutan (14 Nov)**: Sales di tabel wilayah sebelumnya = sales produk (Harga Setelah Diskon × QTY, sebelum voucher), sehingga Total (mis. Rp 1.874.828.301) ≠ kartu Sales bersih di atasnya (Total Pembayaran − batal − Belum Bayar − retur). `region_summary` kini memakai definisi `order_metrics`: Sales bersih = Total Pembayaran sekali per pesanan (selain batal & Belum Bayar) − nilai unit retur; Invoice bersih = semua − batal − Belum Bayar − **retur penuh** (retur sebagian tetap bersih). Dicek dengan data Sep & Okt 2026: Total wilayah = kartu persis (Sales bersih, Pesanan bersih, QTY bersih). Kolom: Invoice retur penuh, % retur penuh, Sales bersih.

## Pembayaran & berat paket: baris Total + cek nilai (14 Nov 2026)

- Baris Total di atas tabel Per metode pembayaran dan Per berat paket (`order_ops.total_row`): % dihitung dari semua pesanan sekaligus (bukan rata-rata per baris). Dicek dengan data Okt 2026: Invoice 6.885, % batal 22,5%, Sales bersih Rp 2.848.905.957 = kartu halaman Data; AOV Rp 538.953 = Sales bersih ÷ 5.286 pesanan bersih. Invoice tanpa Total Berat disebut di atas tabel berat.

## app.py ikut terbarui tanpa Reboot (14 Nov 2026)

- Ternyata perubahan di app.py (bukan src/) tidak terpakai di Cloud setelah push: dengan `fileWatcherType = "none"`, Streamlit menyimpan bytecode app.py di `Runtime._script_cache` selamanya. Contoh: tabel Pembeli batal karena belum bayar masih tinggi dan link klik kanan menu belum aktif, padahal kodenya sudah di-push. `_refresh_app_bytecode()` (app.py) membandingkan waktu ubah app.py; bila berubah, cache dibersihkan lalu rerun. Perlu **satu kali Reboot** di share.streamlit.io agar pengecek ini sendiri terpasang; sesudahnya push app.py langsung aktif.

## Tinggi baris tabel dengan teks panjang (14 Nov 2026)

- `wrap_layout` menghitung jumlah baris teks dengan `WRAP_CHAR_PX = 5,6` px/huruf (sebelumnya `CHAR_PX` 7,2, padahal huruf tabel terukur ±4–5 px), sehingga baris tidak lagi dua kali lebih tinggi dari isinya (mis. Riwayat perubahan data: 108 px untuk teks 3 baris). Lebar kolom satu baris tetap memakai 7,2 agar tidak terpotong. Riwayat perubahan data: lebar kolom pasti (Perubahan 640 px).

## Rekomendasi nama & deskripsi: lengkap untuk upload (14 Nov 2026)

- Tabel 1 baris per produk (35 px), Kode produk & Nama saat ini dibekukan; kolom **Siap upload** (✅/⚠️) dan **Masih kurang**; Excel memuat Kekurangan listing saat ini, Dilengkapi otomatis, Kata kunci kompetitor.
- `complete_title` / `complete_description` (nlp_competitor): kekurangan hasil penilaian dilengkapi otomatis hanya dengan data produk sendiri + kata kunci judul kompetitor teratas (`allowed_keyword`): kata kunci utama ke awal judul, ukuran/material/kegunaan/garansi, SPESIFIKASI, INFORMASI PEMBELIAN (≥600 karakter), hashtag 3–10, hapus link/kontak. Yang tidak bisa dipastikan dari data (merek, ukuran) ditandai manual.
- Cek SEO dibenahi: label [INCLUDE PACKING KAYU] tidak dihitung panjang/pengulangan; kode tipe (L-XKS) satu kata; kepadatan kata kunci tidak menghitung hashtag, nama toko, SPESIFIKASI & PILIHAN VARIAN (`keyword_count`); merek berangka (Mitra10) bukan "kode tipe"; ringkasan deskripsi lama dipotong di akhir kalimat/kata.
- Data lokal (453 produk): siap upload 224 → 235; sisa terbanyak: deskripsi mirip produk lain (88), judul < 60 karakter karena data produk terbatas (70), merek tidak ada di data (44).

## Iklan kejar target dirombak (14 Nov 2026)

- **Urutan**: (1) FITUR KHUSUS · Setelan Anda di atas: target, **budget iklan total sebulan**, Target ROAS (Diatur sistem / Saya tentukan) → proyeksi, tambahan sales, budget, Target ROAS; (2) Rekomendasi sistem terpisah (tidak mengubah setelan; tombol "Pakai rekomendasi di Setelan Anda"); (3) Posisi target & evaluasi budget terpakai; (4) pemilihan produk & budget per iklan memakai setelan Anda. Kotak setelan lama (budget campaign, daya dorong) dan panel budget dikunci dihapus.
- **Budget sebulan** (`src/core/ads_month.py`): biaya yang sudah keluar = laporan iklan keseluruhan diprorata tgl 1 s.d. data terakhir (`ad_spend`); sisa = budget − terpakai, dibagi hari tersisa. Evaluasi: % budget terpakai vs % hari, omzet iklan, sales per Rp iklan.
- **Proyeksi & rekomendasi**: kurva respons toko `sales bersih bulanan = s0 + a·ln(1 + biaya bulanan/b)` dari bulan penuh (biaya iklan keseluruhan vs sales bersih; data lokal Mei–Okt 2026). Tambahan = (s(laju baru) − s(laju sekarang)) × porsi hari sisa. Rekomendasi = budget sebulan terkecil yang menutup 100% target; Target ROAS Shopee = ROAS yang menyerap sisa budget di rencana per iklan. Batas permintaan per iklan dilepas (`A.FREE_LIFT`), stok tetap membatasi; peringatan bila laju di luar riwayat, tidak terserap iklan yang ada, atau melebihi ruang stok.
- Data lokal (s.d. 12 Nov): terpakai Rp 121,8 jt; budget bawaan Rp 418 jt → 75,0%; rekomendasi Rp 1,22 M sebulan (±Rp 61 jt/hari sisa, Target ROAS 11,5) → 100%.

## 2026-11-14 — Buka di tab baru untuk sub-menu
- `link_buttons` dipindah dari app.py ke `src/ui/common.py`; `button_tabs(..., routes=...)` memasang link sungguhan di tiap sub-menu.
- Sub-menu Rekomendasi (Nama & deskripsi, Iklan, Flash sale toko, Exposure media sosial, Ranking kategori) → `?page=analisa&tab=rekomendasi&sub=<slug>`; tab Setting → `?page=setting&tab=<slug>`. Klik kanan → Buka di tab baru / Ctrl-klik / klik tengah kini membuka sub-menu yang sama.

## 2026-11-14 — Iklan: Fitur khusus, Rekomendasi sistem, Pantau rencana dipisah
- Rekomendasi › Iklan punya tiga tampilan (tombol sub-menu): **Fitur khusus · setelan Anda**, **Rekomendasi sistem**, **Pantau rencana tersimpan** (bila ada). Penomoran langkah mulai dari 1 di tiap tampilan.
- Fitur khusus: form target + budget iklan total sebulan + Target ROAS, tombol **Hitung rencana**. Setelan yang dikirim disimpan (`kv_setting` kunci `iklan-setelan:<periode>`) dan menjadi acuan. Biaya terpakai dari laporan iklan keseluruhan; sisa budget dibagi ke hari tersisa → evaluasi budget, hasil, pemilihan produk, budget per iklan, simpan. Tidak memakai/mengubah rekomendasi.
- Rekomendasi sistem: evaluasi kondisi saat ini + opsi A (laju sekarang), B (maksimal terserap iklan, bila 100% target melebihi daya serap), C (budget untuk 100% target / paling hemat bila target sudah aman). Opsi dipilih → rincian produk & budget per iklan → simpan.
- Rencana tersimpan menyimpan titik awal (sumber, sales bersih & biaya terpakai saat disimpan, tanggal data, hari sisa, proyeksi tanpa perubahan). `ads_month.plan_track` membandingkan sales bersih & biaya iklan terbaru dengan jalur rencana → On track / Tertinggal (banner di atas + kartu di Pantau rencana), evaluasi per iklan tetap ada.

## 2026-11-14 — Iklan: fokus ke produk penghasil sales besar
- `ads_strategy.potential_floors`: layak diiklankan bila potensi sales (maks. omzet iklan/hari 2 bulan, prediksi omzet/hari) ≥ omzet produk terakhir pembentuk 95% prediksi sales toko, ATAU prediksi qty ≥ maks(1 unit/hari, persentil 90).
- Produk yang semula "Pertahankan di grup / iklan tunggal" tapi di bawah dua batas itu → saran baru **Stop iklan · sales kecil** (dilepas dari grup / iklan tunggal dijeda; budget dipindah ke iklan lain). Produk belum diiklankan yang tidak lolos batas tidak diusulkan.
- Data 12 Nov: batas Rp 134 rb/hari atau 1,2 unit/hari; 479 produk distop (149 punya biaya, ±Rp 280 rb/hari, omzet iklan ±Rp 1,9 jt/hari). Kolom baru "Prediksi qty/hari" di Pemilihan produk.

## 2026-11-14 — Iklan: interpretasi proyeksi diperjelas
- Kartu "Proyeksi sales bersih akhir bulan" (seluruh penjualan toko, iklan + non-iklan, sesudah batal/Belum Bayar/retur) dan "Efek budget iklan setelan" (dulu "Tambahan sales bersih dari iklan") dengan penjelasan arah: sisa budget/hari vs laju iklan rata-rata bulan ini.
- Langkah 2 Fitur khusus: tabel rincian Aktual + Prediksi sisa bulan (laju iklan rata-rata) + Efek budget = Proyeksi, Target, Kurang/Lebih.
- Opsi rekomendasi: kolom "Efek budget iklan"; opsi A menyebut biaya iklan berjalan/hari.

## 2026-11-14 — Iklan: budget kelipatan Rp 25 rb & sel kosong "–"
- `ads_strategy.round_budget`: budget harian usulan per iklan (setiap rencana mingguan) dibulatkan ke kelipatan Rp 25.000 terdekat (min. Rp 25 rb), tetap dalam batas naik 2× / turun ½.
- `show_table(dash_missing=True)`: kolom angka yang punya sel kosong ditampilkan sebagai teks berformat dengan "–" (Streamlit 1.50 menampilkan NaN angka sebagai "None" walau Styler na_rep). Dipakai semua tabel halaman Iklan.

## 2026-11-14 — Iklan: biaya iklan % sales bruto, tabel rincian proyeksi dirapikan
- `month_outlook` mengembalikan `mtd_bruto` (sales bruto `order_metrics`). Kartu Fitur khusus "Biaya iklan % sales bersih · bruto" (data 12 Nov: 7,9% · 5,3%); Rekomendasi › kartu Biaya iklan terpakai juga menampilkan keduanya.
- Tabel rincian proyeksi: row_height 35, lebar kolom tetap, keterangan dipersingkat.

## 2026-11-14 — Iklan: daftar pengecualian produk & efisiensi minimum
- Daftar pengecualian (`kv_setting` kunci `iklan-kecualikan`: kode produk + kata kunci nama/merek), diedit di langkah Pemilihan produk. Produk di daftar → saran "Dikecualikan pengguna" (keluar dari grup / iklan tunggal dijeda) dan tidak diusulkan iklan baru. Kata kunci "dextone" = 17 produk.
- `allocate_target(min_marginal=5)`: iklan yang Rp terakhirnya kembali < Rp 5 omzet iklan dipangkas/dijeda; tambahan budget hanya bila tiap Rp 1 kembali ≥ Rp 5. Data 12 Nov, sisa ±Rp 21 jt/hari: biaya rencana −Rp 63 jt, ROAS 13,7 → 15,7 (sisa budget yang tidak efisien tidak dibelanjakan).
- Tabel Pemilihan produk & Budget per iklan: tinggi baris 35 px.

## 2026-11-14 — Pengecualian produk: centang + pencarian tepat
- Multiselect diganti kotak Cari (semua kata harus ada di nama/kode; "lem dextone silicon" → 8 produk) + tabel centang (data_editor CheckboxColumn), tombol Centang semua hasil / Hapus centang hasil, kata kunci otomatis opsional, tombol Simpan aktif hanya bila ada perubahan.

## 2026-11-14 — Audit halaman Iklan
- Proyeksi (Fitur khusus, opsi rekomendasi, Pantau rencana) kini memakai **biaya yang benar-benar dibelanjakan rencana per iklan** (sesudah pemilihan produk, pengecualian, batas naik 2×/minggu, efisiensi minimum), bukan budget nominal. Budget yang tidak terserap ditampilkan sebagai "hemat"; pengecualian produk ikut mengubah proyeksi bila biaya rencana berubah; Target ROAS manual yang terlalu tinggi tidak lagi memberi proyeksi terlalu optimis.
- Rekomendasi sistem: opsi A (laju sekarang), B (maksimal yang efisien, bila beda), H (hemat biaya, tiap Rp 1 kembali ≥ Rp 10), C (100% target, hanya bila masih efisien). Bila 100% target melebihi batas efisien, tampil kotak 🎯 dengan kekurangan dan cara lain menutupnya. Kolom Biaya efektif & Hemat.
- `min_marginal` diteruskan ke build_plan/ramp/_option_plan/_fixed_plan; rencana tersimpan menyimpan `biaya_harian_rencana` (jalur biaya pantauan) dan `efisiensi_min`; Pantau rencana menghitung proyeksi dengan cara yang sama seperti saat disimpan.
- Data 12 Nov: batas efisien ±Rp 425 jt/bulan (±Rp 17 jt/hari); 100% target menurut kurva toko butuh ±Rp 1,22 M → tidak efisien lewat iklan saja.

## 2026-11-14 — Iklan: syarat minimum Shopee 3% & ekonomi opsi
- Pemilihan produk tetap ATAU (sales besar → kejar target; qty laku banyak → kejar invoice/performa toko).
- `ads_month.SHOPEE_MIN_AD_PCT = 3` (% sales bruto). Opsi baru **M · Minimum 3% sales bruto** = 3% × proyeksi tanpa perubahan × rasio bruto/bersih (≥ yang sudah terpakai).
- Tiap opsi & Fitur khusus menampilkan biaya iklan % sales bruto proyeksi (✓/⚠️ syarat 3%) dan estimasi kontribusi sesudah iklan (sales bersih × kontribusi sebelum iklan dari file margin − biaya iklan). Peringatan bila laju biaya di luar riwayat kurva toko.
- Kotak 💰 Titik impas iklan: marginal kurva toko (data 12 Nov ±Rp 2,8 sales bersih per Rp 1) → kontribusi impas ≥ 35%, kontribusi produk terprediksi −8,5%.
- Opsi utama: sales tertinggi, kecuali opsi lain kalah ≤ 0,5% target dengan biaya lebih kecil.

## 2026-11-14 — Iklan: prioritas budget menurut margin
- `ads_strategy.priority(unit)`: bobot margin (positif 1+2×min(c,0,3); tak diketahui 1; minus 0,85 bila laku banyak, 0,6 bila tidak). Dipakai `allocate_target` di semua fase (pindah budget, pangkas, efisiensi = MIN_MARGINAL ÷ bobot, tambah budget).
- `restructure` menghitung ulang kontribusi, qty/hari, dan status laku banyak dari produk yang tinggal di tiap iklan.
- Data 12 Nov, budget Rp 10 jt/hari: biaya ke produk margin positif Rp 1,8 → 2,8 jt/hari, (kontribusi omzet iklan − biaya) membaik ±Rp 3,2 jt/hari, ROAS 21,6 → 21,2.
- Syarat 3% Shopee dikonfirmasi terhadap sales bruto.

## 2026-11-14 — Harga beli & bottom price (file merchandising per kuartal), kalkulator harga & promo
- Upload data › Target & margin › **Harga beli & bottom price**: `core/harga_beli.py` membaca sheet Marketplace (Item No, H.Beli, Bottom Price, dll.), disimpan di `kv_setting` kunci `harga-beli` (`ui/harga_beli_data.py`). File Q4 OKT–DES: 838 SKU, 662 berharga beli, 651 ber-bottom price, 671 dari 797 SKU katalog cocok.
- Margin: `MarginData.harga_beli`; `kotor_map(prices)` / `row_at(sku, price)` → margin kotor = (harga − harga beli) ÷ harga (rumus file, porsi pajak 0) bila harga beli ada, selain itu File margin (lalu rata-rata toko). Dipakai Kalkulator, Iklan (`_ads_inputs`), feature_data.
- Kalkulator: tab Parameter biaya › File margin dihapus (unggah di Upload data). `core/pricing.py`: histori harga 90 hari (harga awal, diskon median transaksi berpromo, porsi transaksi berpromo), rencana per SKU (harga impas termasuk iklan, harga sehat ≥ batas margin, harga jual disarankan = maks(harga normal, impas), promo disarankan = promo historis bila ≥ 20% transaksi berpromo, dibatasi ruang margin sehat lalu impas, harga & margin setelah promo). Kartu "Rekomendasi harga & promo" di Simulasi per SKU + unduhan Excel semua SKU (725 SKU periode 30 hari).
- Bottom price hanya untuk Flash sale & Exposure: harga flash/promo ≥ maks(harga impas, bottom price); bila tidak ada ruang, tepat di bottom price (flash min. diskon 5%); SKU dengan bottom ≥ harga normal tidak dijadwalkan. Kolom Bottom price di jadwal flash; Exposure punya kolom Harga normal, Bottom price, Harga promo (seller centre), Diskon promo.

## 2026-11-14 — Harga beli belum PPN; Laporan margin memakai harga beli
- Harga beli merchandising = belum termasuk PPN; PPN dari harga jual Shopee: margin kotor % = (harga × (1 − porsi PPN 1/11) − harga beli) ÷ harga (`margin_data.cost_margin_pct`, `harga_beli.margin_pct`), porsi pajak = DEFAULT_TAX_SHARE.
- Laporan margin: `margin_report.build(cost=…)` memakai harga beli bila ada, selain itu File margin; catatan "Memakai harga beli"; batas acuan & rata-rata toko ikut menghitung SKU berharga beli (`shopee_fee.portfolio`).
- Data 15 Okt–13 Nov: 558 SKU rugi, 126 rendah, 41 tinggi; margin bersih −18,8%.

## 2026-11-14 — Rekomendasi iklan: opsi berurutan & memakai budget Anda
- Opsi diberi huruf berurutan (A, B, C, …) sesuai urutan tampil. Opsi pertama = **Budget Anda** dari setelan Fitur khusus yang sudah dikirim (`_submitted_setting`, kv `iklan-setelan:<periode>`); lalu laju iklan sekarang diteruskan (dilewati bila ≈ budget Anda), maksimal efisien, hemat biaya, minimum 3% sales bruto, 100% target (bila efisien).
- Kolom baru **Asal angka budget** menjelaskan sumber tiap angka (mis. 412–418 jt = terpakai + iklan berjalan/hari × hari tersisa).
- Bulan berikutnya: target, budget setelan, biaya terpakai, kurva toko, dan pantauan rencana semuanya per periode (bulan data terakhir); tidak ada angka bulan yang dikunci di kode.

## 2026-11-14 — Nama & deskripsi: "Siap upload/Lengkapi" diganti Saran tindakan
- Tindakan per produk (`rekomendasi._action_of`): ✅ Sudah baik, pertahankan (SEO saat ini ≥ 90, atau nama Sangat baik dan rekomendasi menambah < 10 poin) · 🔁 Ganti dengan rekomendasi (rekomendasi lengkap) · ⚠️ Perbaiki, lengkapi data dulu (rekomendasi masih butuh data manual). Teks tindakan menyebut bagian yang diganti: nama, deskripsi saja (nama sudah baik), atau keduanya (dari kekurangan listing saat ini).
- Kolom baru "Yang diperbaiki" (kekurangan listing saat ini yang ditutup rekomendasi) dan "Masih kurang (isi manual)"; saringan & unduhan Excel ikut. Data: 5 pertahankan, 233 ganti (97 deskripsi saja), 215 lengkapi dulu.

## 2026-11-14 — Flash sale: riwayat tersimpan, ikut bottom price MD, skor volume & margin, unduhan format codif
- Campaign flash sale tersimpan menampilkan seluruh periodenya termasuk tanggal yang sudah lewat (kotak abu-abu "sudah lewat"); campaign yang sudah selesai/dihentikan bisa dibuka di expander "📅 Flash sale yang sudah diset sebelumnya" (kalender + tabel + unduhan).
- Harga flash = bottom price MD bila ≥ impas & diskon ≥ 5%; tanpa bottom MD → diskon 10/7/5% (≥ impas) dan dicatat sebagai usulan bottom price baru.
- Skor kandidat = 0,4 peringkat value + 0,3 peringkat qty/hari + 0,3 peringkat margin di harga flash. Kolom baru Margin (%) & Peringatan stok 10037 (stok toko kosong/tipis → tambah/transfer stok dulu).
- `harga_beli.codif_frame/codif_xlsx`: unduhan format Bottom Price (sheet Marketplace, judul & kolom sama) per SKU: Campaign = tanggal flash sale, Bottom Price = bottom MD atau usulan, Keterangan = peringatan stok/usulan baru, + kolom "Harga Flash Sale (Seller Centre)". Data: 39 SKU (17 bottom MD, 22 usulan baru), 14 SKU stok 10037 kosong/tipis.

## 2026-11-14 — Flash sale: hanya SKU ber-bottom price MD, strategi harga, barang murah
- Bila file bottom price sudah diunggah, kandidat flash sale hanya SKU yang ada di file itu (`candidates(require_bottom=True)`); unduhan codif tidak lagi berisi usulan baru, Category Name dari file MD.
- Harga normal = harga awal transaksi terakhir (bukan harga bersih rata-rata). `flash_offer`: target diskon per kelompok harga (<100 rb 20%, <500 rb 15%, <2 jt 12%, ≥2 jt 10%, habiskan stok +5), lebih murah dari harga transaksi terendah 90 hari, dibulatkan ke harga psikologis (`charm_price`), tidak di bawah bottom MD/impas, min. diskon 5%.
- Kelompok baru 🏷️ Barang murah (≤ Rp 100 rb & laku) dengan porsi slot (bawaan 30%); SKU per hari bawaan 8. Data: 59 SKU / 115 slot (sebelumnya 38 SKU).
- Tidak dijadwalkan diringkas per kelompok (kolom Kelompok), rincian tetap di kolom Alasan.

## 2026-11-14 — Exposure media sosial: kalender per bulan, riwayat, potensi viral
- Periode bawaan = bulan berjalan dari tanggal 1 s.d. akhir bulan (picker boleh mulai tanggal 1); konten baru dijadwalkan mulai hari ini, tanggal lewat tampil abu-abu "lewat". Campaign tersimpan menampilkan kalendernya sendiri; campaign selesai/dihentikan bisa dibuka di expander "📅 Konten yang sudah diset sebelumnya".
- Segmen baru 🚀 Potensi viral (`exposure.viral_score`: demo visual, before–after, masalah→solusi, fitur unik dari nama+deskripsi, + harga terjangkau). Skor: 30% prediksi omzet, 15% nilai produk (harga, video di-crawl jangka panjang), 15% viral, 15% margin, 15% tren, 5% stok, 5% bonus naik/stok lebih/viral.

## 2026-11-14 — Ranking kategori: KPI per periode (bulan/kuartal/semester/tahun), Home & Living + Elektronik
- Menu Rekomendasi › Ranking kategori kini 3 bagian: **Rekap KPI ranking**, **Peluang Top 10 per produk**, **Unggah & periode**.
- `src/core/ranking_kpi.py`: periode (`2026-07`, `2026-Q3`, `2026-S2`, `2026`), baca file ranking (ekspor Shopee 2 baris per produk atau tabel biasa, satu/banyak sheet; kolom Kategori, Dasar Ranking, Sales, Qty, Views, Periode opsional), ringkasan per kategori, rekap, catatan analisa.
- Simpan per periode di kv `ranking-kompetitor:data:<periode>` + indeks `ranking-kompetitor:index`; daftar kategori dipantau di `ranking-kompetitor:kategori` (bisa diubah). Unggahan ke periode yang sudah ada: tambah (kategori lain) atau ganti.
- Data Kompetitor lama (belum berperiode) bisa disimpan sebagai periode (bawaan Q3) dengan pemetaan daftar → kategori Shopee (tebakan dari kata kunci).
- Rekap: Home & Living semua kategori (yang belum ada data tampil "–"), Elektronik hanya kategori yang memuat produk kita. Periode tanpa unggahan langsung disusun dari periode di dalamnya (peringkat terakhir, terbaik, rata-rata, cakupan bulan). Sales/Qty/Views kita dibanding peringkat #10.
- Peluang Top 10 bisa memakai periode mana pun (atau data lama); kategori & kelompok mengikuti pemetaan.

## 2026-11-14 — Kalkulator margin: periode kalender = periode kartu
- Bawaan "Periode analisa" kini tanggal 1 bulan berjalan s.d. hari penuh terakhir data (sama dengan kartu Sales/Margin bersih aktual), bukan 30 hari terakhir.
- `date_range_picker`: tanpa pilihan pengguna, kalender mengikuti periode bawaan (ikut bergeser saat data bertambah); pilihan pengguna disimpan sampai diganti.

## 2026-11-14 — Kalkulator margin: kolom usulan harga untuk MD di daftar prioritas
- Setelah kolom Harga akhir (aktual): Harga beli / modal, Harga jual disarankan, Promo disarankan (kebiasaan promo transaksi), Harga setelah promo, Perubahan harga bayar vs aktual, Harga nett (setelah voucher, potongan Shopee, iklan), Profit/unit setelah promo, Margin setelah promo, Catatan harga. Sumber: perhitungan semua SKU (`_price_table`, sama dengan unduhan Simulasi).
- Baris Total: profit periode bila usulan dipakai dengan qty yang sama vs aktual SKU yang sama. Sel kosong tampil "–" (bukan None).

## 2026-11-14 — Kalkulator margin: semua angka bersih, istilah header seragam
- `_portfolio_rows` memakai `metrics.sold_lines` (selain batal & Belum Bayar, dikurangi retur; voucher penjual dikurangi sebanding unit retur) — sama dengan Sales produk bersih / QTY bersih di tabel Data & Prediksi. Sebelumnya hanya batal yang dikeluarkan.
- Header daftar prioritas: Omzet periode → **Sales produk bersih**, Terjual periode → **QTY bersih**; unduhan semua SKU: Terjual (periode) → QTY bersih (periode). Teks kartu & langkah memakai "sales produk bersih" (bukan omzet).

## 2026-11-14 — Kalender ikut berubah, tabel prioritas berkelompok, rekonsiliasi total
- `date_range_picker`: setelah pengguna memilih tanggal, halaman dijalankan ulang sekali agar teks kalender ikut berubah (sebelumnya angka berubah tetapi kalender masih menampilkan rentang lama).
- `show_table(groups=...)`: baris judul kelompok di atas header (MultiIndex). Daftar prioritas: Prioritas & tindakan · Aktual periode terpilih (bersih) · Usulan harga untuk MD · Keterangan.
- Keterangan total tabel: sales produk bersih & QTY bersih periode, + SKU nonaktif yang tidak ditampilkan = total sales produk bersih periode.

## 2026-11-14 — Kalkulator: tabel prioritas berkelompok (komponen HTML), promo selalu ada
- Daftar prioritas memakai komponen tabel berkelompok (`src/ui/grouped_table.py`, komponen top50_table): judul kelompok berwarna & tetap terlihat saat digeser (Produk · Tindakan · Aktual periode terpilih (bersih) · Usulan harga untuk MD · Keterangan), kolom Produk terkunci, angka minus merah, urut per kolom, halaman & Excel di dalam tabel.
- `pricing.plan`: promo selalu ada (min. 5%, maks. 30%): kebiasaan promo transaksi bila ≥ 20% transaksi berpromo, selain itu ruang margin sehat (maks. 10%) atau 5%. Harga normal disarankan dinaikkan bila perlu agar setelah promo margin ≥ batas sehat (min. 2%).
- Evaluasi hanya SKU yang bertransaksi pada periode terpilih (SKU tanpa transaksi tidak masuk daftar).

## 2026-11-14 — Kalkulator: satu sumber transaksi & jembatan Sales produk bersih → Sales bersih
- Kalkulator memakai semua transaksi tersimpan (`analysis.orders_all`, sama dengan kartu Sales bersih aktual & tab Data) untuk kalender, kartu, tabel, dan jembatan.
- `metrics.sales_bridge`: Sales produk bersih − voucher penjual − voucher Shopee/koin/diskon kartu + ongkir dibayar pembeli ± lain-lain = Sales bersih (Total Pembayaran), pesanan yang sama (tanpa batal & Belum Bayar, dikurangi retur). Ditampilkan di atas tabel prioritas, plus selisih SKU nonaktif ke baris Total tabel.
- Hint kartu Sales bersih aktual: "Total Pembayaran, sama dengan tab Data · Sales produk bersih … (dasar margin)".

## 2026-11-14 — Kalkulator › Simulasi per SKU dirombak
- Kartu "Margin bersih per unit · sekarang" (komposisi harga beli, PPN, potongan Shopee, iklan, profit) + kartu "Rekomendasi harga & promo" bergaya sama: harga beli, harga jual disarankan, promo, harga setelah promo, nett diterima, profit/unit, margin.
- Tabel "Kalkulator lengkap · sekarang vs rekomendasi": harga normal, promo, voucher, harga dibayar pembeli, PPN, admin kategori, tiap program Shopee, proses pesanan, affiliate, iklan, nett diterima, harga beli, profit, margin.
- Menu Skenario cepat, Rincian biaya lengkap, Analisa lengkap dihapus; histori promo, harga impas/sehat, catatan, dan tuas tanpa ubah harga ringkas di bawah tabel.
- Harga nett = dibayar pembeli − PPN − potongan Shopee − iklan (definisi sama di daftar prioritas).

## 2026-11-14 — Simulasi per SKU: input harga dihapus, program Shopee ditata, unduhan semua komponen
- Kolom isian Harga jual, Biaya iklan, Diskon tambahan, Voucher penjual dihapus; nilainya dari data (sama dengan Ringkasan), tampil sebagai kartu Data SKU.
- Program Shopee: program wajib sebagai label 🔒, program opsional sebagai toggle 2 kolom (tarif & batas di tooltip); Pengaturan lain: ukuran khusus, affiliate, unit per pesanan, kategori.
- Unduh semua SKU kini memuat semua komponen kalkulator per SKU (kolom "Sekarang · …" dan "Rekomendasi · …"), sama dengan tabel Kalkulator lengkap.

## 2026-11-14 — Laporan margin digabung ke Kalkulator › Ringkasan & prioritas
- Tab Setting › Laporan margin dihapus (URL lama diarahkan ke Kalkulator biaya).
- Ringkasan dirombak per bagian: (1) Penjualan & margin bulan berjalan (target), (2) Kondisi margin SKU aktif periode terpilih: kartu Sales produk bersih / Margin kotor / Margin bersih / Perlu ditindaklanjuti, chip potongan & batas, tabel Ringkasan per status (+Total), Langkah yang disarankan (gabungan), sebaran sales vs margin, (3) Daftar prioritas (jembatan sales di expander), (4) SKU nonaktif · potensi margin yang hilang.
- Semua angka dari mesin yang sama (`_portfolio_rows` + `shopee_fee.portfolio`, transaksi bersih). SKU nonaktif: seluruh riwayat, margin bersih ÷ bulan terjual, batas margin rendah = batas SKU aktif.

## 2026-11-14 — Kapasitas gudang › SKU di gudang 10037: outstanding & istilah bersih
- Tabel memakai komponen berkelompok: Produk · Penjualan & prediksi 30 hari · Stok Site 10037 · Outstanding PO/TR/TO · Tindakan · Keterangan (kolom Produk terkunci, Total, Excel).
- Outstanding dipecah PO / TR / TO / TR toko lain / Total + Umur outstanding (sejak & hari, dari riwayat snapshot replenishment) + Follow up outstanding (masih perlu X unit / sudah menutup kebutuhan / belum ada outstanding: segera buat TR/TO/PO / lewat 7 hari: kejar).
- `gudang.sales_summary` memakai `metrics.sold_lines` (tanpa batal & Belum Bayar, dikurangi retur). Header gudang: QTY bersih 30 hari, Sales produk bersih 30 hari, Tren sales, Prediksi sales 30 hari; "barang di jalan" → outstanding.

## 2026-11-14 — Audit Evaluasi model
Diuji ulang dengan data transaksi lokal (Jan–8 Nov 2026, 721–800 SKU, 5 lipatan walk-forward bulanan).
- **Temuan akar masalah**: (1) MAPE agregat & bias didominasi lipatan Okt 2026 (permintaan +54,6% dari 30 hari sebelumnya; galat semua model −36% s.d. −42%) — kejutan kampanye/pesanan proyek yang tidak terlihat dari riwayat; (2) pemilihan model dengan WAPE condong ke median → prediksi cenderung kurang pada permintaan berekor tebal; (3) safety stock memakai σ 28 hari + asumsi galat normal → tingkat layanan 64,6% vs target ±94%; (4) simulasi SS (σ 28 hari) tidak sama dengan produksi (σ residual 28 hari); (5) kartu & gauge memakai model terbaik in-sample, uji kesesuaian memakai model produksi (angka berbeda, mis. 14,5% vs 15,8%).
- **Perbaikan**: σ SS = simpangan harian 180 hari, sama di simulasi (`evaluate.SIGMA_DAYS`) dan produksi (`forecast.demand_sigma`): layanan 64,6% → 74,6% (stok 1,53× → 1,78× permintaan). Metode SS kedua "kuantil empiris" (split conformal per kelas ABC, `conformal_quantiles`): layanan 88,7% (stok 3,17×), dipilih di Setting › Kapasitas gudang › Parameter (`safety_stock.metode`, bawaan normal). Kartu/gauge/kerangka pengujian memakai model produksi. Tabel "Galat total toko per lipatan" (`record.per_lipatan`). Kekuatan/kelemahan/tindak lanjut dihitung dari angka (penyebab per uji). Tabel teks memakai `html_table` (tinggi baris mengikuti isi).
- **Dicoba, tidak dipakai**: XGBoost Poisson (WAPE luar sampel Ensemble per segmen 80,5% → 76,6% tetapi bias −15,8% → −22,5% dan MAPE agregat 15,3% → 20,3%); Croston/TSB (WAPE 88%); pemisahan pesanan proyek ≥ 10 unit (bias −16% → −10%, MAPE agregat tidak membaik); capping lonjakan. Target uji tidak diubah.

## 2026-11-14 · Uji pendorong permintaan eksternal (iklan, kalender kampanye)

Diuji dengan walk-forward bersarang yang sama (5 lipatan Jun–Okt 2026, 721 SKU, data salinan cloud):

| Varian XGBoost global | WAPE luar sampel | MAPE agregat | Bias |
|---|---|---|---|
| Tanpa fitur iklan (dasar) | 94,7% | 16,5% | −8,1% |
| + biaya iklan 28 hari lalu & perubahannya | 95,5% | 20,6% | −7,6% |
| + biaya iklan bulan target (oracle: biaya aktual dianggap rencana, 85% SKU terpetakan) | 96,5% | 22,3% | −6,9% |

- Korelasi perubahan biaya iklan per produk vs perubahan qty bulan berikutnya lemah (0,07–0,34 bulan yang sama; ≈0 untuk lag).
- Fitur kalender kampanye (tanggal kembar, gajian, harbolnas, Ramadan/Lebaran) dan momentum toko sudah diuji sebelumnya: tidak stabil (lipatan Juni +148%).
- Pesanan proyek terkonfirmasi belum punya sumber data terstruktur di aplikasi, sehingga belum bisa diuji.

Keputusan: tidak dipakai di produksi. Bahkan dengan informasi biaya iklan bulan depan yang sempurna, akurasi luar sampel tidak membaik. Model produksi tetap dipilih otomatis berdasarkan WAPE luar sampel terendah (saat ini Level terkini, 78,4%).

## 2026-11-14 · Laporan v2: lengkap, angka bersih konsisten, SWOT & fishbone visual

- Bagian laporan jadi 16: ditambah **Margin & profitabilitas** (mesin hitung Kalkulator: status rugi/rendah/tinggi, prioritas perbaikan, SKU margin tinggi, SKU nonaktif), **Akurasi model prediksi** (perbandingan 7 model, uji kesesuaian, galat per lipatan, kekuatan/kelemahan/tindak lanjut; sama dengan Evaluasi model › Ringkasan), **Gudang 10037 & outstanding** (status stok, outstanding PO/TR/TO, umur & follow up > 7 hari), **Ranking kompetitor** (periode tersimpan yang beririsan dengan rentang laporan, naik/turun vs periode sebelumnya).
- Angka bersih satu definisi: Ringkasan memuat kartu Sales bersih, **Sales produk bersih**, **QTY bersih**, Pesanan bersih + tabel jembatan Sales produk bersih → Sales bersih (`metrics.sales_bridge`). Produk terlaris kini dari `sold_lines` (semua status → tanpa batal/Belum Bayar, setelah retur), jadi jumlahnya = kartu Sales produk bersih; tabel bulanan memuat Sales produk bersih, Sales bersih, QTY bersih, pesanan bersih. Cek konsistensi margin: SKU aktif + nonaktif = Sales produk bersih.
- Diverifikasi pada data Okt 2026: Sales bersih Rp 2.848.905.957, Sales produk bersih Rp 3.285.099.861, QTY bersih 10.967 — kartu, harian, bulanan, produk terlaris, dan jembatan sama.
- SWOT (`src/core/report_analysis.swot`) & fishbone (`fishbone`) disusun dari fakta laporan (penjualan, target, margin, iklan, performa, ranking, stok, gudang, batal, akurasi model). Fishbone 6 tulang (Produk, Harga & Promosi, Tempat/Saluran, Pemasaran & Pengguna, Proses, Lingkungan/Eksternal) digambar SVG seperti contoh referensi, butir diberi tingkat masalah/waspada/aman; SWOT 4 kuadran berwarna dengan judul di tengah (`src/ui/report_visuals.py`).
- Semua tabel laporan memakai `html_table` (tinggi baris mengikuti isi, baris Total tebal, kolom panjang dibungkus) sehingga proporsional dan muat tanpa digulir mendatar. Grafik produk/iklan memakai label unik (nomor urut) agar SKU bernama mirip tidak tertumpuk; konversi mingguan ditimbang pengunjung (= kartu Konversi).
- Panduan kerja diperbarui ke menu yang ada sekarang (follow up outstanding, Kalkulator prioritas, unggah ranking, SKU nonaktif). Tindak lanjut Evaluasi model tidak lagi menyarankan fitur iklan/kalender (sudah diuji, tidak membantu); yang tersisa: pesanan proyek terkonfirmasi.
- Laporan tersimpan versi lama tetap bisa dibuka (bagian baru diberi keterangan).
- Algoritma: run cloud terakhir (#16) menjalankan 7 model (Level terkini, MA28, ES, XGBoost global, Prophet, Ensemble, Ensemble per segmen); produksi = ES (WAPE luar sampel 60,9%). xgboost, lightgbm, prophet, statsmodels terpasang.
