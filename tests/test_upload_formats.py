import io
import unittest
import zipfile

import pandas as pd

from src.core.schemas import SOURCE_SPECS, canonicalize_frame, validation_report
from src.core.storage import read_upload_file

AD_CSV = (
    "\ufeffIklan Produk Otomatis Indonesia\n"
    "Username,toko\n"
    "Nama Toko,Toko Contoh\n"
    "Periode,01/10/2026 - 01/11/2026\n"
    "\n"
    "Urutan,Nama Produk,Kode Produk,Dilihat,Jumlah Klik,Biaya,Efektifitas Iklan\n"
    "1,Iklan Produk Otomatis,-,1000,50,20000,5.1\n"
    "2,Keran Air,10086189543,400,20,9000,3.2\n"
)


def shopee_template_xlsx(headers: list[str], rows: list[list[object]]) -> bytes:
    """Template mass update Shopee: kunci teknis, baris meta, header Indonesia, baris petunjuk, lalu data."""
    width = len(headers)
    body = [
        [f"et_title_{i}" for i in range(width)],
        ["sales_info"] + [None] * (width - 1),
        headers,
        ["Wajib" if "Stok" in h else None for h in headers],
        ["Masukkan stok" if "Stok" in h else None for h in headers],
        *rows,
    ]
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame(body).to_excel(writer, index=False, header=False)
        writer.sheets["Sheet1"].freeze_panes = "A5"
    source = zipfile.ZipFile(io.BytesIO(buffer.getvalue()))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for info in source.infolist():
            content = source.read(info.filename)
            if info.filename.startswith("xl/worksheets/"):
                content = content.replace(b'activePane="bottomLeft"', b'activePane="bottom_left"')
            target.writestr(info, content)
    return out.getvalue()


class UploadFormatTest(unittest.TestCase):
    def test_ads_csv_skips_preamble_and_keeps_period(self):
        spec = SOURCE_SPECS["ads_auto"]
        frame = read_upload_file(AD_CSV.encode("utf-8"), "auto.csv", spec)
        self.assertEqual(validation_report(frame, spec)["status"], "Siap")
        canon, mapping = canonicalize_frame(frame, spec)
        self.assertEqual(canon["period"].iloc[0], "2026-10-01")
        self.assertEqual(canon["product_code"].tolist(), ["-", "10086189543"])
        self.assertIn("roas", mapping)

    def test_stock_template_with_invalid_pane(self):
        spec = SOURCE_SPECS["stock"]
        data = shopee_template_xlsx(
            ["Kode Produk", "Nama Produk", "SKU Induk", "SKU", "Stok:DC Cikupa"],
            [[43319156425, "Handle Pintu", None, "0800022676", 35], [50614977873, "Kabinet", "200015023", None, 0]],
        )
        frame = read_upload_file(data, "produk.xlsx", spec)
        self.assertEqual(validation_report(frame, spec)["status"], "Siap")
        canon, _ = canonicalize_frame(frame, spec)
        self.assertEqual(len(canon), 2)
        self.assertEqual(canon["sku"].tolist(), ["800022676", "200015023"])
        self.assertEqual(canon["product_code"].tolist(), ["43319156425", "50614977873"])

    def test_description_template(self):
        spec = SOURCE_SPECS["product_descriptions"]
        data = shopee_template_xlsx(
            ["Kode Produk", "SKU Induk", "Nama Produk", "Deskripsi Produk"],
            [[1, None, "Keran", "Keran kuningan"], [2, None, "Kloset", "Kloset duduk"]],
        )
        frame = read_upload_file(data, "deskripsi.xlsx", spec)
        self.assertEqual(validation_report(frame, spec)["status"], "Siap")
        self.assertEqual(len(frame), 2)

    def test_competitor_ranked_listing_is_collapsed(self):
        spec = SOURCE_SPECS["competitors"]
        raw = pd.DataFrame(
            [
                ["Ranking", "Change of Rank", "Products Name", "Shop Name"],
                [None, "30", None, "Toko A"],
                [None, None, "Pompa Air A", None],
                ["4", "3", None, "Toko B"],
                [None, None, "Toren 1000 L", None],
                ["My Top3 Products Outside The Top20 Products", None, None, None],
                ["116", "My Shop", None, "Mitra10 Official Store"],
                [None, None, "Pompa Dorong Aquamax", None],
            ]
        )
        buffer = io.BytesIO()
        raw.to_excel(buffer, index=False, header=False)
        frame = read_upload_file(buffer.getvalue(), "kompetitor.xlsx", spec)
        self.assertEqual(validation_report(frame, spec)["status"], "Siap")
        canon, _ = canonicalize_frame(frame, spec)
        self.assertEqual(canon["product_name"].tolist(), ["Pompa Air A", "Toren 1000 L", "Pompa Dorong Aquamax"])
        self.assertEqual(canon["rank"].tolist(), ["1", "4", "116"])
        self.assertEqual(canon["own_shop"].tolist(), [False, False, True])


if __name__ == "__main__":
    unittest.main()
