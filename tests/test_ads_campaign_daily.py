"""Laporan all iklan satu hari untuk campaign, terpisah dari data latih MTD."""

from datetime import date

import pandas as pd

from src.core.ads_campaign_daily import apply_campaign_daily, merge_daily_reports, parse_daily_ad_file
from src.core.ads_monitor import campaign_daily_progress

ONE_DAY = """\
Nama Toko,Mitra10
Periode,16/11/2026 - 16/11/2026
,,,
Urutan,Nama Iklan,Status,Jenis Iklan,Kode Produk,Biaya,Omzet Penjualan
1,Kloset Toilet WC Duduk Tidy FSA0089,Berjalan,Iklan Produk,48213626135,2000000,42324999
2,Iklan Produk Otomatis,Berjalan,Iklan Produk,-,500000,8000000
""".encode()

MTD = """\
Periode,01/11/2026 - 16/11/2026
Urutan,Nama Iklan,Kode Produk,Biaya,Omzet Penjualan
1,Kloset,48213626135,44699730,866336737
""".encode()


def test_parse_one_day_file_uses_biaya_and_omzet():
    parsed = parse_daily_ad_file(ONE_DAY, "all iklan 1611.csv")
    assert parsed["tanggal"] == "2026-11-16"
    assert parsed["biaya"] == 2_500_000
    assert parsed["omzet"] == 50_324_999
    by_key = {row["key"]: row for row in parsed["iklan"]}
    assert by_key["produk:48213626135"]["biaya"] == 2_000_000
    assert by_key["produk:48213626135"]["omzet"] == 42_324_999
    assert by_key["auto"]["biaya"] == 500_000


def test_mtd_file_is_rejected():
    try:
        parse_daily_ad_file(MTD, "all iklan 1611.csv")
    except ValueError as exc:
        assert "MTD" in str(exc)
    else:
        raise AssertionError("file MTD harus ditolak")


def test_one_day_report_replaces_mtd_delta_for_that_date():
    mtd = pd.DataFrame([
        {"Tanggal": "2026-11-16", "Biaya": 3_204_825, "Omzet": 50_665_931, "Sumber": "selisih MTD"},
        {"Tanggal": "2026-11-17", "Biaya": 1_980_538, "Omzet": 45_891_973, "Sumber": "selisih MTD"},
    ])
    units = pd.DataFrame([
        {"Tanggal": "2026-11-16", "key": "produk:48213626135", "Biaya": 3_204_825, "Omzet": 50_665_931},
        {"Tanggal": "2026-11-17", "key": "produk:48213626135", "Biaya": 1_980_538, "Omzet": 45_891_973},
    ])
    campaign = merge_daily_reports({}, [parse_daily_ad_file(ONE_DAY, "16.csv")])
    store, unit = apply_campaign_daily(
        campaign, mtd, units, start=date(2026, 11, 16), end=date(2026, 11, 18),
    )
    day16 = store.loc[store["Tanggal"].astype(str).str[:10] == "2026-11-16"].iloc[0]
    day17 = store.loc[store["Tanggal"].astype(str).str[:10] == "2026-11-17"].iloc[0]
    assert day16["Biaya"] == 2_500_000
    assert day16["Sumber"] == "laporan 1 hari"
    assert day17["Biaya"] == 1_980_538
    assert day17["Sumber"] == "selisih MTD"
    product = unit.loc[
        (unit["Tanggal"].astype(str).str[:10] == "2026-11-16") & (unit["key"] == "produk:48213626135")
    ].iloc[0]
    assert product["Biaya"] == 2_000_000
    assert product["Omzet"] == 42_324_999


def test_progress_uses_daily_file_not_mtd_and_not_ad_omzet_as_sales():
    daily = pd.DataFrame([
        {"Tanggal": "2026-11-16", "Biaya": 2_000_000, "Omzet": 40_000_000, "Sumber": "laporan 1 hari"},
    ])
    mtd = pd.DataFrame([
        {"period": "2026-11-01", "period_range": "01/11/2026 - 16/11/2026", "cost": 9_000_000, "ad_sales": 1},
    ])
    camp = {"mulai": "2026-11-16", "selesai": "2026-11-22", "setelan": {"target_roas": 8, "biaya_harian_rencana": 2_000_000}}
    out = campaign_daily_progress(
        camp, set(),
        ads_overall=mtd, orders=None,
        daily_store=daily,
        window_start=date(2026, 11, 16), window_end=date(2026, 11, 18),
        today=date(2026, 11, 19),
    )
    row = out.loc[out["Tanggal"] == "2026-11-16"].iloc[0]
    assert float(row["Biaya iklan"]) == 2_000_000
    assert abs(float(row["ROAS iklan"]) - 20.0) < 0.01
    assert pd.isna(row["Sales produk"])
    assert pd.isna(row["Sales bersih"])
    assert pd.isna(out.loc[out["Tanggal"] == "2026-11-17", "Biaya iklan"]).all()
    assert float(out.attrs["total"]["Biaya iklan"]) == 2_000_000
    assert abs(float(out.attrs["total"]["ROAS iklan"]) - 20.0) < 0.01
