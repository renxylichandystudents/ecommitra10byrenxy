"""Campaign tersimpan untuk Rekomendasi › Iklan, Flash sale toko, dan Exposure media sosial.

Satu campaign = setelan + periode (mulai–selesai) + baris rencana yang dikunci. Campaign yang sedang berjalan atau
terjadwal dipakai sebagai acuan harian sampai dihentikan, diganti campaign baru, atau periodenya lewat. Disimpan di
`kv_setting` dengan kunci `campaign:<jenis>` sebagai daftar (terbaru di akhir).

Ads OS lifecycle (iklan): draft → exported → learning_locked → stable → scaling|holding|ending_proposed → ended.
Status operasional lama (Berjalan/Terjadwal/Dihentikan/Selesai) tetap dipakai untuk panel/riwayat.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

KINDS = {"iklan": "Iklan", "flash": "Flash sale toko", "exposure": "Exposure media sosial"}
RUNNING, SCHEDULED, STOPPED, DONE = "Berjalan", "Terjadwal", "Dihentikan", "Selesai"
KEEP = 30

# ---- Ads OS lifecycle (P0) ----
DRAFT = "draft"
EXPORTED = "exported"
LEARNING_LOCKED = "learning_locked"
STABLE = "stable"
SCALING = "scaling"
HOLDING = "holding"
ENDING_PROPOSED = "ending_proposed"
ENDED = "ended"

LIFECYCLE_STATES = (
    DRAFT, EXPORTED, LEARNING_LOCKED, STABLE, SCALING, HOLDING, ENDING_PROPOSED, ENDED,
)
LEARNING_DAYS = 7
AUTO_END_UNDERPERFORM_DAYS = 7

OVERRIDE_KEEP = "keep"
OVERRIDE_PAUSE = "pause"
OVERRIDE_EDIT = "edit"
OVERRIDE_SKIP_AUTO_END = "skip_auto_end"
OVERRIDE_KINDS = (OVERRIDE_KEEP, OVERRIDE_PAUSE, OVERRIDE_EDIT, OVERRIDE_SKIP_AUTO_END)

LIFECYCLE_LABEL = {
    DRAFT: "Draft",
    EXPORTED: "Diekspor ke SC",
    LEARNING_LOCKED: "Learning terkunci",
    STABLE: "Stabil",
    SCALING: "Scale",
    HOLDING: "Hold",
    ENDING_PROPOSED: "Usulan end",
    ENDED: "Selesai (SKU bebas)",
}


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


def learning_exit_date(campaign: dict) -> date:
    """Hari terakhir learning (~7 hari sejak mulai, inklusif)."""
    return as_date(campaign["mulai"]) + timedelta(days=LEARNING_DAYS - 1)


def in_learning(campaign: dict, today: date) -> bool:
    """True selama hari ke-1…7 sejak mulai (belum keluar learning)."""
    if status_of(campaign, today) not in (RUNNING, SCHEDULED):
        return False
    return today <= learning_exit_date(campaign)


def _override_of(campaign: dict) -> dict:
    raw = campaign.get("override") or {}
    return raw if isinstance(raw, dict) else {}


def _metrics_of(campaign: dict, metrics: dict | None = None) -> dict:
    base = dict(campaign.get("lifecycle_metrics") or {})
    if metrics:
        base.update({k: v for k, v in metrics.items() if v is not None})
    return base


def lifecycle_of(campaign: dict, today: date, *, metrics: dict | None = None) -> str:
    """Hitung state Ads OS. Manual override keep/pause menang; ending_proposed hanya usulan (bukan silent end)."""
    stored = str(campaign.get("lifecycle") or "").strip()
    if stored == ENDED or campaign.get("dihentikan") or status_of(campaign, today) in (STOPPED, DONE):
        return ENDED if stored == ENDED or campaign.get("dihentikan") or status_of(campaign, today) == STOPPED else ENDED

    ov = _override_of(campaign)
    kind = str(ov.get("kind") or "")
    if kind == OVERRIDE_PAUSE:
        return ENDING_PROPOSED if stored == ENDING_PROPOSED else HOLDING
    if kind == OVERRIDE_KEEP and stored == ENDING_PROPOSED:
        return STABLE

    if stored in (SCALING, HOLDING, ENDING_PROPOSED) and not in_learning(campaign, today):
        return stored

    if status_of(campaign, today) == SCHEDULED:
        return EXPORTED if stored in (EXPORTED, LEARNING_LOCKED, STABLE, SCALING, HOLDING, "") or not stored else stored

    if in_learning(campaign, today):
        return LEARNING_LOCKED

    # Setelah learning: scaling / holding dari metrik opsional, default stable
    m = _metrics_of(campaign, metrics)
    posture = str(m.get("posture") or stored or STABLE)
    if posture in (SCALING, HOLDING):
        return posture
    if stored in (SCALING, HOLDING, STABLE, EXPORTED, LEARNING_LOCKED, DRAFT, ""):
        return STABLE if stored in (EXPORTED, LEARNING_LOCKED, DRAFT, "") else (stored or STABLE)
    return STABLE


def mark_exported(campaign: dict, *, now: str | None = None) -> dict:
    """Setelah unduh/simpan Setelan SC: draft/exported → exported (learning mulai di tanggal mulai)."""
    out = {**campaign, "lifecycle": EXPORTED, "exported_at": now or campaign.get("exported_at") or campaign.get("dibuat")}
    return out


def set_override(campaign: dict, kind: str, *, username: str, now: str, note: str = "") -> dict:
    """M0: keep / pause / edit / skip_auto_end. Selalu tersimpan di campaign (audit)."""
    if kind not in OVERRIDE_KINDS:
        raise ValueError(f"override tidak dikenal: {kind}")
    out = {
        **campaign,
        "override": {
            "kind": kind,
            "oleh": username,
            "saat": now,
            "catatan": note or "",
        },
    }
    if kind == OVERRIDE_SKIP_AUTO_END:
        out["skip_auto_end"] = True
    if kind == OVERRIDE_PAUSE:
        out["lifecycle"] = HOLDING
    if kind == OVERRIDE_KEEP and out.get("lifecycle") == ENDING_PROPOSED:
        out["lifecycle"] = STABLE
        prop = dict(out.get("end_proposal") or {})
        if prop:
            prop = {**prop, "ditolak": now, "ditolak_oleh": username}
            out["end_proposal"] = prop
    return out


def clear_override(campaign: dict) -> dict:
    out = {**campaign}
    out.pop("override", None)
    return out


def product_codes_of(campaign: dict) -> set[str]:
    """SKU yang terkunci di rencana campaign (untuk free-after-end)."""
    codes: set[str] = set()
    for row in campaign.get("produk") or []:
        if not isinstance(row, dict):
            continue
        code = str(row.get("Kode produk") or row.get("kode") or "").strip()
        if code and code.lower() != "nan":
            codes.add(code)
    for row in campaign.get("iklan") or []:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or "")
        if ":" in key:
            codes.add(key.split(":", 1)[1].strip())
        raw = str(row.get("Kode produk") or "").strip()
        if raw and raw.lower() != "nan":
            for part in raw.replace(";", ",").split(","):
                p = part.strip()
                if p:
                    codes.add(p)
    return {c for c in codes if c}


def free_skus_after_end(campaign: dict) -> set[str]:
    """SKU yang dibebaskan setelah campaign ended (untuk Pick berikutnya)."""
    return product_codes_of(campaign)


def occupied_excluding_ended(occupied: frozenset | set, campaigns: list[dict], today: date) -> frozenset:
    """Occupied aktif dikurangi SKU dari campaign yang sudah ended (kapasitas bebas)."""
    base = set(occupied or ())
    for c in campaigns or []:
        if lifecycle_of(c, today) == ENDED:
            base -= free_skus_after_end(c)
    return frozenset(base)


def propose_auto_end(
    campaign: dict,
    today: date,
    *,
    roas: float | None = None,
    safe_bep: float | None = None,
    underperform_days: int = 0,
    stock_critical: bool = False,
    deepen_loss: bool = False,
    net_negative_streak: bool = False,
) -> dict | None:
    """Usulan end (bukan silent). None bila masih learning (kecuali stok kritis) / skip override / belum syarat.

    Syarat setelah keluar learning:
    - ROAS < BEP aman ≥ 7 hari, atau
    - stok kritis / OOS, atau
    - iklan memperdalam rugi (deepen_loss / net_negative_streak).
    """
    if campaign.get("skip_auto_end") or _override_of(campaign).get("kind") == OVERRIDE_SKIP_AUTO_END:
        return None
    if _override_of(campaign).get("kind") == OVERRIDE_KEEP:
        return None
    if lifecycle_of(campaign, today) == ENDED:
        return None

    reasons: list[str] = []
    emergency_stock = bool(stock_critical)
    if in_learning(campaign, today) and not emergency_stock:
        return None

    if emergency_stock:
        reasons.append("stok kritis / OOS — jeda di SC agar spend tidak buang")
    if not in_learning(campaign, today):
        if (
            roas is not None and safe_bep is not None
            and roas == roas and safe_bep == safe_bep and safe_bep > 0
            and roas < safe_bep
            and int(underperform_days or 0) >= AUTO_END_UNDERPERFORM_DAYS
        ):
            reasons.append(
                f"ROAS {roas:.1f} < BEP aman {safe_bep:.1f} selama ≥{AUTO_END_UNDERPERFORM_DAYS} hari setelah learning"
            )
        if deepen_loss or net_negative_streak:
            reasons.append("iklan memperdalam rugi (kontribusi negatif beruntun)")
    if not reasons:
        return None
    return {
        "saat": today.isoformat(),
        "alasan": reasons,
        "lifecycle": ENDING_PROPOSED,
        "konfirmasi_wajib": True,
        "skus": sorted(free_skus_after_end(campaign)),
    }


def apply_end_proposal(campaign: dict, proposal: dict | None) -> dict:
    """Tandai ending_proposed di campaign (tetap hidup sampai user konfirmasi)."""
    if not proposal:
        return campaign
    return {
        **campaign,
        "lifecycle": ENDING_PROPOSED,
        "end_proposal": proposal,
    }


def confirm_end(
    campaigns: list[dict],
    cid: int,
    *,
    username: str,
    now: str,
    reason: str = "konfirmasi auto-end",
) -> tuple[list[dict], dict | None]:
    """Konfirmasi end: stop campaign + lifecycle ended + catat SKU bebas. Mengembalikan (daftar, campaign ended)."""
    ended: dict | None = None
    out = []
    for c in campaigns:
        if int(c.get("id", 0)) == int(cid) and not c.get("dihentikan"):
            freed = sorted(free_skus_after_end(c))
            c = {
                **c,
                "dihentikan": now,
                "dihentikan_oleh": username,
                "alasan_berhenti": reason,
                "lifecycle": ENDED,
                "ended_at": now,
                "freed_skus": freed,
            }
            ended = c
        out.append(c)
    return out, ended


def hub_status(campaign: dict | None, today: date, *, metrics: dict | None = None) -> dict[str, Any]:
    """Ringkas status Ads OS home (A0): running / learning / siap end / antrian kosong."""
    if campaign is None:
        return {
            "state": "empty",
            "lifecycle": None,
            "label": "Antrian kosong",
            "blurb": "Belum ada campaign acuan. Mulai dari Rekomendasi sistem → Pick SKU Top N.",
            "learning": False,
            "can_end": False,
            "next_cta": True,
        }
    life = lifecycle_of(campaign, today, metrics=metrics)
    learning = in_learning(campaign, today)
    exit_d = learning_exit_date(campaign)
    proposal = campaign.get("end_proposal") if life == ENDING_PROPOSED else None
    if life == ENDING_PROPOSED:
        blurb = "Sistem mengusulkan end — konfirmasi jeda di SC atau override Keep."
    elif learning:
        blurb = f"Learning terkunci s.d. {exit_d.isoformat()} (~{LEARNING_DAYS} hari). Jangan ubah ROAS/budget di SC."
    elif life == SCALING:
        blurb = "Stabil & di atas BEP — boleh scale bertahap (±20% setelah learning)."
    elif life == HOLDING:
        blurb = "Hold: pertahankan setelan; tinjau stok/margin sebelum scale."
    elif life == ENDED:
        blurb = "Campaign ended — SKU bebas untuk Pick berikutnya."
    else:
        blurb = f"Campaign #{campaign.get('id')} · {status_of(campaign, today)} · lifecycle {LIFECYCLE_LABEL.get(life, life)}"
    return {
        "state": life,
        "lifecycle": life,
        "label": LIFECYCLE_LABEL.get(life, life),
        "blurb": blurb,
        "learning": learning,
        "learning_exit": exit_d.isoformat(),
        "can_end": life == ENDING_PROPOSED,
        "proposal": proposal,
        "next_cta": life == ENDED or status_of(campaign, today) in (STOPPED, DONE),
        "campaign_id": campaign.get("id"),
    }


def add(campaigns: list[dict], new: dict, *, today: date, username: str, now: str) -> tuple[list[dict], list[dict]]:
    """Tambah campaign; campaign berjalan/terjadwal yang periodenya bertabrakan dihentikan.

    Mengembalikan (daftar baru, campaign yang dihentikan)."""
    next_id = max((int(c.get("id", 0)) for c in campaigns), default=0) + 1
    life = str(new.get("lifecycle") or EXPORTED)
    if life not in LIFECYCLE_STATES:
        life = EXPORTED
    item = {**new, "id": next_id, "mulai": str(as_date(new["mulai"])), "selesai": str(as_date(new["selesai"])),
            "dibuat_oleh": username, "dibuat": now, "dihentikan": None,
            "lifecycle": life, "exported_at": new.get("exported_at") or now}
    stopped, out = [], []
    for c in campaigns:
        if status_of(c, today) in (RUNNING, SCHEDULED) and overlaps(c, item):
            freed = sorted(free_skus_after_end(c))
            c = {**c, "dihentikan": now, "dihentikan_oleh": username,
                 "alasan_berhenti": f"diganti campaign #{next_id}",
                 "lifecycle": ENDED, "ended_at": now, "freed_skus": freed}
            stopped.append(c)
        out.append(c)
    out.append(item)
    return out[-KEEP:], stopped


def stop(campaigns: list[dict], cid: int, *, username: str, now: str, reason: str = "dihentikan manual") -> list[dict]:
    out = []
    for c in campaigns:
        if int(c.get("id", 0)) == int(cid) and not c.get("dihentikan"):
            freed = sorted(free_skus_after_end(c))
            c = {**c, "dihentikan": now, "dihentikan_oleh": username, "alasan_berhenti": reason,
                 "lifecycle": ENDED, "ended_at": now, "freed_skus": freed}
        out.append(c)
    return out


def remove(campaigns: list[dict], cid: int) -> list[dict]:
    return [c for c in campaigns if int(c.get("id", 0)) != int(cid)]


def compare_budgets(saved, fresh, *, tolerance: float = 0.2):
    """Budget harian per iklan: campaign tersimpan vs saran hari ini (pandas DataFrame, kolom Iklan & Budget harian usulan).

    Berubah = selisih budget **efektif Seller Center** > tolerance × tersimpan efektif. Usulan di bawah minimum Shopee
    (25 rb tunggal / 100 rb grup) dianggap sama dengan minimum, supaya pantauan tidak salah tandai "berubah" hanya karena
    batas implementasi. Tindakan tidak dibandingkan."""
    import pandas as pd

    from src.core.ads_strategy import implementable_budget

    col = "Budget harian usulan"

    def side(frame):
        if frame is None or frame.empty or not {"Iklan", col} <= set(frame.columns):
            return pd.DataFrame(columns=["budget", "jenis"])
        work = frame.copy()
        work["_b"] = pd.to_numeric(work[col], errors="coerce").fillna(0.0)
        work["_j"] = work["Jenis"].astype(str) if "Jenis" in work.columns else "Produk tunggal"
        g = work.groupby(work["Iklan"].astype(str), sort=False)
        return pd.DataFrame({"budget": g["_b"].sum(), "jenis": g["_j"].first()})

    a, b = side(saved), side(fresh)
    names = sorted(set(a.index) | set(b.index))
    rows = []
    for name in names:
        sa = float(a.loc[name, "budget"]) if name in a.index else 0.0
        sb = float(b.loc[name, "budget"]) if name in b.index else 0.0
        kind = str(a.loc[name, "jenis"]) if name in a.index else (str(b.loc[name, "jenis"]) if name in b.index else "Produk tunggal")
        ea, eb = implementable_budget(sa, kind), implementable_budget(sb, kind)
        delta = eb - ea
        changed = abs(delta) > tolerance * max(ea, 1.0) and not (ea == 0 and eb == 0)
        rows.append({"Iklan": name, "Jenis": kind, "Budget tersimpan/hari": sa, "Budget saran hari ini/hari": sb,
                     "Efektif tersimpan/hari": ea, "Efektif saran/hari": eb, "Selisih/hari": delta, "Berubah": changed})
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(["Berubah", "Selisih/hari"], ascending=[False, False], key=lambda s: s.abs() if s.dtype != bool else s)


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
