import pandas as pd

from src.core.config import default_params
from src.core import nlp_competitor as nlp


def _own():
    return pd.DataFrame({
        "item_key": ["P1", "P2"], "product_code": ["P1", "P2"], "sku": ["1", "2"], "n_sku": [2, 1],
        "product_name": ["Kloset Duduk Tidy FSA0089 Garansi 15 Tahun [INCLUDE PACKING KAYU]", "Kran Wastafel Ceramax York FT810023MB Hitam"],
        "variants": [["Putih", "Hitam"], []], "variasi_tampil": ["", ""], "qty_total": [10, 5],
    })


def _comp():
    return pd.DataFrame({
        "Daftar": [7, 7, 7, 9, 9],
        "rank": ["1", "2", "3", "1", "2"],
        "rank_change": [0, 2, -1, 0, 0],
        "shop_name": ["A", "Mitra10 Official Store", "B", "C", "D"],
        "own_shop": [False, True, False, False, False],
        "product_name": ["Kloset Duduk One Piece Dual Flush Garansi 10 Tahun", "Kloset Duduk Tidy FSA0089 Garansi 15 Tahun",
                         "Toilet Kloset Duduk Keramik Garansi 5 Tahun", "Kran Wastafel Dapur Stainless", "Kran Air Wastafel Panas Dingin"],
    })


def test_competitor_list_and_usp():
    lists, _comp_frame = nlp.competitor_lists(_own(), _comp())
    assert lists["P1"]["daftar"] == "7" and lists["P1"]["posisi"] == 2 and len(lists["P1"]["pembanding"]) == 2
    assert lists["P2"]["daftar"] == "9"
    usp = nlp.usp_points(_own().iloc[0]["product_name"], "", "", ["Kloset Garansi 10 Tahun", "Kloset Garansi 5 Tahun"], ["tidy"])
    assert usp[0][1] and "lebih panjang" in usp[0][0]


def test_build_per_product_seo_and_uniqueness():
    out, note = nlp.build_name_recommendations(_own(), None, _comp(), {}, default_params())
    assert len(out) == 2 and "Daftar" in note
    first = out.iloc[0]
    assert first["Peringkat kita"] == 2 and first["Jumlah SKU"] == 2
    text = first["Rekomendasi deskripsi"]
    assert "PILIHAN VARIAN" in text and text.rstrip().split("\n")[-1].startswith("#")
    assert first["SEO deskripsi"]["Tanpa link/kontak"] and 0 <= first["Skor SEO"] <= 100
    sims, partner = nlp.description_similarity(["kloset duduk putih", "kloset duduk putih", "kran air dapur"])
    assert sims[0] > 0.99 and partner[0] == 1


def test_title_never_cut_mid_phrase():
    from src.core.naming import fit_title

    t = "Lem Silicone Sealant Tabung Multi Purpose Hitam/Putih/Bening 300ml - Dextone Glue Silikon Fleksibel, Tahan Suhu, Daya Rekat Kuat"
    out = fit_title(t, 120)
    assert len(out) <= 120 and out.endswith("Tahan Suhu")
    long = "Kloset " * 30
    assert len(fit_title(long, 120)) <= 255


def test_history_compare():
    from src.core import seo_history as sh

    out, _ = nlp.build_name_recommendations(_own(), None, _comp(), {}, default_params())
    prev = sh.snapshot_rows(out, "v1")
    now = out.copy()
    now.loc[0, "Nama produk saat ini"] = now.loc[0, "Rekomendasi nama baru"]
    now.loc[1, "Nama produk saat ini"] = "Kran Air Dapur Hitam Murah"
    res = sh.compare(now, sh.previous_snapshot(prev, "v2")).set_index("item_key")
    assert res.loc["P1", "perubahan"] == "Mengikuti rekomendasi"
    assert res.loc["P2", "perubahan"] == "Diubah di luar rekomendasi"
    same = sh.compare(out, sh.previous_snapshot(prev, "v2")).set_index("item_key")
    assert (same["perubahan"] == "Belum diubah").all()


def test_complete_title_and_description_fill_seo_gaps():
    from src.core.nlp_competitor import complete_description, complete_title, seo_description_checks, seo_title_checks

    vocab = {"kran", "wastafel", "ceramax", "chrome", "kamar", "mandi", "cuci", "gr", "85300cp"}
    title, notes = complete_title("Ceramax Kran Wastafel", name="Kran Wastafel Ceramax GR-85300CP Chrome", variation="",
                                  description="Kran untuk kamar mandi dan wastafel cuci tangan", primary=["kran wastafel"],
                                  supporting=["kamar mandi"], brands=["ceramax"], vocab=vocab, max_len=120)
    checks = seo_title_checks(title, ["kran wastafel"], ["ceramax"], max_len=120)
    assert checks["Kata kunci di awal judul"] and checks["Ada merek"]
    assert len(title) >= 40 and notes
    desc, dnotes = complete_description("Jual kran wastafel Ceramax.\nPesan sekarang di Mitra10 Official Store.\n\n#ceramax",
                                        title=title, name="Kran Wastafel Ceramax GR-85300CP Chrome", variation="", primary=["kran wastafel"],
                                        supporting=["kamar mandi"], brands=["ceramax"], max_chars=3000)
    d = seo_description_checks(desc, ["kran wastafel"], max_chars=3000)
    assert d["Panjang 600–3.000 karakter"] and d["Hashtag 3–10"] and d["Ada spesifikasi/ukuran"]
    assert desc.index("SPESIFIKASI") < desc.index("Pesan sekarang")


def test_keyword_density_ignores_shop_name_spec_and_variants():
    from src.core.nlp_competitor import keyword_count, seo_title_checks

    body = ("Jual shower Tidy di Mitra10 Official Store.\nSPESIFIKASI\n- Jenis: shower set\n- Hand shower\nPILIHAN VARIAN\n- Shower A\n\n"
            "KEGUNAAN\nUntuk shower kamar mandi.\n\n#shower")
    assert keyword_count(body, "shower") == 2
    assert keyword_count("Dikirim dari gudang Mitra10. Produk Mitra10.", "mitra10") == 1
    # Kode tipe & label packing kayu tidak dihitung sebagai kata berulang.
    checks = seo_title_checks("Aquamax Pompa Celup Xks Plastik L-XKS Cermin Kayu [INCLUDE PACKING KAYU]", ["pompa celup"], ["aquamax"], max_len=120)
    assert checks["Tanpa kata berulang"]
