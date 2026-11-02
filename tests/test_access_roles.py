import unittest

import pandas as pd

from auth.permissions import allowed_sheets
from src.core.access import ROLES, allowed, setting_tabs
from src.core.cancel_reasons import CATEGORIES, categorize, categorize_series
from src.ui.routing import PAGE_SETTING, SETTING_KEY, SUB_KEY, apply_route, route_from_state, sync_route

SHEETS = ["Ringkasan", "Prediksi", "Data", "Folder data", "Rekomendasi", "Laporan", "Evaluasi model"]


class RoleAccessTests(unittest.TestCase):
    def test_only_four_roles(self):
        self.assertEqual(set(ROLES), {"super_user", "ecommerce_specialist", "team_dc", "team_icmd"})

    def test_team_dc_sees_only_summary_prediction_and_two_setting_tabs(self):
        self.assertEqual(allowed_sheets("team_dc", SHEETS), ["Ringkasan", "Prediksi"])
        self.assertEqual([slug for slug, _l, _m in setting_tabs("team_dc")], ["kapasitas-gudang", "kedatangan-impor"])
        self.assertTrue(allowed("team_dc", "setting_kapasitas_gudang", "upload"))
        self.assertFalse(allowed("team_dc", "setting_kedatangan_impor", "write_note"))
        self.assertFalse(allowed("team_dc", "data_latih"))

    def test_team_icmd_writes_import_notes_but_not_layout(self):
        self.assertEqual(allowed_sheets("team_icmd", SHEETS), ["Ringkasan", "Prediksi"])
        self.assertTrue(allowed("team_icmd", "setting_kedatangan_impor", "write_note"))
        self.assertFalse(allowed("team_icmd", "setting_kapasitas_gudang", "upload"))
        self.assertFalse(allowed("team_icmd", "kelola_user"))

    def test_setting_never_contains_training_data(self):
        for role in ROLES:
            self.assertNotIn("data-latih", [slug for slug, _l, _m in setting_tabs(role)])

    def test_super_user_gets_all_setting_tabs(self):
        self.assertEqual(len(setting_tabs("super_user")), 6)


class SettingRoutingTests(unittest.TestCase):
    def test_setting_route_roundtrip(self):
        state = {}
        apply_route(state, (PAGE_SETTING, "kapasitas-gudang"), SHEETS)
        self.assertEqual(route_from_state(state, SHEETS), (PAGE_SETTING, "kapasitas-gudang"))
        self.assertEqual(state[SETTING_KEY], "kapasitas-gudang")

    def test_rekomendasi_sub_tab_from_url(self):
        state, params = {"analysis": object()}, {"page": "analisa", "tab": "rekomendasi", "sub": "exposure"}
        sync_route(state, params, SHEETS)
        self.assertEqual(state[SUB_KEY], "exposure")
        self.assertEqual(params.get("sub"), "exposure")


class CancelReasonTests(unittest.TestCase):
    def test_categories(self):
        self.assertEqual(CATEGORIES, ("Pembeli", "Belum bayar", "Penjual", "Sistem Shopee"))
        self.assertEqual(categorize("Need to change delivery address"), "Pembeli")
        self.assertEqual(categorize("teks yang tidak dikenal"), "Pembeli")
        self.assertEqual(categorize(None), "Pembeli")

    def test_series_only_known_categories(self):
        out = categorize_series(pd.Series(["Alasan Lainnya", "Belum dibayar", "", None]))
        self.assertTrue(set(out).issubset(set(CATEGORIES)))


if __name__ == "__main__":
    unittest.main()
