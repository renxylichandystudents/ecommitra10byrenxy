import unittest

from src.ui.routing import (
    FEATURE_ID,
    PAGE_HOME,
    PAGE_INPUT,
    PAGE_RESULT,
    PAGE_USERS,
    route_from_state,
    sync_route,
)

SHEETS = ["Ringkasan", "Prediksi", "Rekomendasi", "Evaluasi model"]


class RoutingTests(unittest.TestCase):
    def test_route_from_state(self):
        self.assertEqual(route_from_state({}, SHEETS), (PAGE_HOME, ""))
        state = {"active-feature": FEATURE_ID, "editing-input": True}
        self.assertEqual(route_from_state(state, SHEETS), (PAGE_INPUT, ""))
        state.update({"editing-input": False, "analysis": object(), "active-sheet": "Evaluasi model"})
        self.assertEqual(route_from_state(state, SHEETS), (PAGE_RESULT, "evaluasi-model"))
        state["auth-page"] = "users"
        self.assertEqual(route_from_state(state, SHEETS), (PAGE_USERS, ""))

    def test_refresh_restores_page_from_url(self):
        state, params = {"analysis": object()}, {"page": "analisa", "tab": "rekomendasi"}
        self.assertFalse(sync_route(state, params, SHEETS))
        self.assertEqual(state["active-feature"], FEATURE_ID)
        self.assertEqual(state["active-sheet"], "Rekomendasi")
        self.assertEqual(params, {"page": "analisa", "tab": "rekomendasi"})

    def test_navigation_writes_url_and_back_returns(self):
        state, params = {"analysis": object()}, {}
        sync_route(state, params, SHEETS)
        self.assertEqual(params, {})

        state.update({"active-feature": FEATURE_ID, "editing-input": False, "active-sheet": "Prediksi"})
        self.assertTrue(sync_route(state, params, SHEETS))
        self.assertEqual(params, {"page": "analisa", "tab": "prediksi"})

        state["active-sheet"] = "Rekomendasi"
        self.assertTrue(sync_route(state, params, SHEETS))
        self.assertEqual(params["tab"], "rekomendasi")

        params.update({"page": "analisa", "tab": "prediksi"})
        self.assertTrue(sync_route(state, params, SHEETS))
        self.assertEqual(state["active-sheet"], "Prediksi")

        params.clear()
        params["page"] = PAGE_HOME
        self.assertTrue(sync_route(state, params, SHEETS))
        self.assertEqual(state["active-feature"], "")
        self.assertFalse(sync_route(state, params, SHEETS))

    def test_auth_page_route_and_unknown_page(self):
        state, params = {}, {"page": "kelola-user"}
        sync_route(state, params, SHEETS)
        self.assertEqual(state["auth-page"], "users")
        state2, params2 = {}, {"page": "tidak-ada"}
        sync_route(state2, params2, SHEETS)
        self.assertEqual(params2, {"page": PAGE_HOME})


if __name__ == "__main__":
    unittest.main()
