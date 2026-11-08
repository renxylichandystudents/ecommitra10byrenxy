"""Campaign tersimpan untuk Rekomendasi › Iklan, Flash sale toko, dan Exposure media sosial.

Satu campaign = setelan + periode (mulai–selesai) + baris rencana yang dikunci. Campaign yang sedang berjalan atau
terjadwal dipakai sebagai acuan harian sampai dihentikan, diganti campaign baru, atau periodenya lewat. Disimpan di
`kv_setting` dengan kunci `campaign:<jenis>` sebagai daftar (terbaru di akhir).
"""

from __future__ import annotations

from datetime import date, datetime

KINDS = {"iklan": "Iklan", "flash": "Flash sale toko", "exposure": "Exposure media sosial"}
RUNNING, SCHEDULED, STOPPED, DONE = "Berjalan", "Terjadwal", "Dihentikan", "Selesai"
KEEP = 30


def as_date(value) -> date:
    return value if isinstance(value, date) and not isinstance(value, datetime) else date.fromisoformat(str(value)[:10])


def status_of(campaign: dict, today: date) -> str:
    if campaign.get("dihentikan"):
        return STOPPED
    if today > as_date(campaign["selesai"]):
        return DONE
    if today < as_date(campaign["mulai"]):
        return SCHEDULED
    return RUNNING


def current(campaigns: list[dict], today: date) -> dict | None:
    """Campaign acuan: yang berjalan hari ini, atau terjadwal paling dekat; None bila tidak ada."""
    live = [c for c in campaigns if status_of(c, today) in (RUNNING, SCHEDULED)]
    if not live:
        return None
    return sorted(live, key=lambda c: (status_of(c, today) != RUNNING, as_date(c["mulai"]), -int(c.get("id", 0))))[0]


def overlaps(a: dict, b: dict) -> bool:
    return as_date(a["mulai"]) <= as_date(b["selesai"]) and as_date(b["mulai"]) <= as_date(a["selesai"])


def add(campaigns: list[dict], new: dict, *, today: date, username: str, now: str) -> tuple[list[dict], list[dict]]:
    """Tambah campaign; campaign berjalan/terjadwal yang periodenya bertabrakan dihentikan.

    Mengembalikan (daftar baru, campaign yang dihentikan)."""
    next_id = max((int(c.get("id", 0)) for c in campaigns), default=0) + 1
    item = {**new, "id": next_id, "mulai": str(as_date(new["mulai"])), "selesai": str(as_date(new["selesai"])),
            "dibuat_oleh": username, "dibuat": now, "dihentikan": None}
    stopped, out = [], []
    for c in campaigns:
        if status_of(c, today) in (RUNNING, SCHEDULED) and overlaps(c, item):
            c = {**c, "dihentikan": now, "dihentikan_oleh": username, "alasan_berhenti": f"diganti campaign #{next_id}"}
            stopped.append(c)
        out.append(c)
    out.append(item)
    return out[-KEEP:], stopped


def stop(campaigns: list[dict], cid: int, *, username: str, now: str, reason: str = "dihentikan manual") -> list[dict]:
    return [{**c, "dihentikan": now, "dihentikan_oleh": username, "alasan_berhenti": reason} if int(c.get("id", 0)) == int(cid) and not c.get("dihentikan") else c
            for c in campaigns]


def remove(campaigns: list[dict], cid: int) -> list[dict]:
    return [c for c in campaigns if int(c.get("id", 0)) != int(cid)]


def compare_budgets(saved, fresh, *, tolerance: float = 0.2):
    """Budget harian per iklan: campaign tersimpan vs saran hari ini (pandas DataFrame, kolom Iklan & Budget harian usulan).

    Berubah = selisih > tolerance × budget tersimpan, atau iklan hanya ada di salah satu sisi dengan budget > 0. Tindakan
    tidak dibandingkan karena relatif terhadap budget saat itu (iklan yang sudah dinaikkan akan disarankan "Pertahankan")."""
    import pandas as pd

    col = "Budget harian usulan"

    def side(frame):
        if frame is None or frame.empty or not {"Iklan", col} <= set(frame.columns):
            return pd.Series(dtype=float)
        return pd.to_numeric(frame[col], errors="coerce").fillna(0.0).groupby(frame["Iklan"].astype(str)).sum()

    a, b = side(saved), side(fresh)
    out = pd.DataFrame({"Budget tersimpan/hari": a, "Budget saran hari ini/hari": b}).fillna(0.0)
    out["Selisih/hari"] = out["Budget saran hari ini/hari"] - out["Budget tersimpan/hari"]
    base = out["Budget tersimpan/hari"]
    out["Berubah"] = (out["Selisih/hari"].abs() > tolerance * base) & ~((base == 0) & (out["Budget saran hari ini/hari"] == 0))
    return out.rename_axis("Iklan").reset_index().sort_values(["Berubah", "Selisih/hari"], ascending=[False, False], key=lambda s: s.abs() if s.dtype != bool else s)


class Store:
    """Pembungkus `FeatureStore.get_json/set_json` per jenis campaign."""

    def __init__(self, features, kind: str):
        self.features, self.kind = features, kind

    @property
    def key(self) -> str:
        return f"campaign:{self.kind}"

    def all(self) -> list[dict]:
        if self.features is None:
            return []
        value = self.features.get_json(self.key, []) or []
        return [c for c in value if isinstance(c, dict) and c.get("mulai") and c.get("selesai")]

    def save(self, campaigns: list[dict], *, username: str) -> None:
        self.features.set_json(self.key, campaigns, username=username)
