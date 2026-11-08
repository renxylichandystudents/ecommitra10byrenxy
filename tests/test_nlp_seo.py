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
