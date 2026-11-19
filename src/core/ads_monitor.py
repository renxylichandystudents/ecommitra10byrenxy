"""Pantauan campaign iklan tersimpan: status per iklan, saran perbaikan, item yang harus diiklankan.

Membaca hasil `ads_strategy.evaluate` + data prediksi/stok, lalu menyusun tindakan yang bisa dikerjakan di Seller Center
tanpa mengubah rumus prediksi atau safety stock.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from src.core import ads_strategy as A

_STATUS_RANK = {
    "Jeda / hentikan": 0,
    "Keluarkan anggota dari grup": 1,
    "Turunkan budget": 2,
    "Naikkan budget": 3,
    "Sudah diiklankan di tempat lain": 4,
    "Buat / aktifkan": 5,
    "Naikkan Target ROAS": 6,
    "Pertahankan": 7,
}

# Ambang mutlak: ada biaya berarti sudah terlihat di laporan (jangan pakai % budget rencana).
_ACTIVE_SPEND = 5_000.0


def _code_from_ad_key(key: str) -> str:
    k = str(key or "")
    if k.startswith(("produk:", "pisah:", "baru:")):
        return k.split(":", 1)[1].strip()
    return ""


def _alts_for_plan_key(key: str, units=None, members: pd.DataFrame | None = None) -> list[dict]:
    """Iklan lain yang memuat produk yang sama (untuk kunci rencana tunggal).

    - Rencana `produk:X`: abaikan alias pisah/baru/produk kode sama (itu slot yang sama).
    - Rencana `baru:X` / `pisah:X`: `produk:X` yang sudah jalan = sudah diiklankan di tempat lain.
    """
    code = _code_from_ad_key(key)
    if not code:
        return []
    found = _elsewhere_for_codes(members, units, group_key=str(key), codes={code})
    k = str(key)
    if k.startswith("produk:"):
        self_keys = {k, f"produk:{code}", f"pisah:{code}", f"baru:{code}"}
    else:
        # baru:/pisah: — jangan filter produk: yang sudah aktif
        self_keys = {k}
    return [a for a in (found.get(code) or []) if str(a.get("unit") or "") not in self_keys]


def _rp_hari(value: float) -> str:
    return f"Rp {value:,.0f}/hari".replace(",", ".")


def _rp(value: float) -> str:
    return f"Rp {value:,.0f}".replace(",", ".")


def classify_rows(
    frame: pd.DataFrame,
    *,
    target_roas: float,
    running_keys: set[str] | None = None,
    units=None,
    members: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Lengkapi baris evaluasi dengan Status goals, Status SC, Tindakan, Saran (bahasa manajer)."""
    if frame is None or frame.empty:
        return pd.DataFrame()
    out = frame.copy()
    running = running_keys or set()
    actions, goals, tips, sc = [], [], [], []
    for _, r in out.iterrows():
        key = str(r.get("_key") or "")
        plan = float(r.get("Budget usulan/hari") or 0)
        expected = float(r.get("Budget efektif Shopee/hari") or A.implementable_budget(plan, r.get("Jenis") or key))
        cost = float(r.get("Biaya aktual/hari") or 0)  # terpakai sejak campaign
        month = r.get("Biaya bulan ini/hari")
        month_v = float(month) if month == month and month is not None else float("nan")
        roas = float(r.get("ROAS aktual")) if r.get("ROAS aktual") == r.get("ROAS aktual") else float("nan")
        done = str(r.get("Rekomendasi dijalankan")) == "Ya"
        is_run = key in running or any(k for k in running if k == key or key.endswith(":" + k.split(":")[-1]))
        if not is_run and running:
            report = "produk:" + key.split(":", 1)[1] if key.startswith(("pisah:", "baru:")) else key
            is_run = report in running or key in running
        nama = str(r.get("Iklan") or key)
        total_sejak = float(r.get("Biaya sejak disimpan") or 0)
        omzet_sejak = float(r.get("Omzet iklan sejak disimpan") or 0)
        days_eval = int(r.get("Hari dievaluasi") or 0)
        if days_eval <= 0 and cost > 0 and total_sejak > 0:
            days_eval = max(int(round(total_sejak / cost)), 1)
        # Aktif di laporan = ada biaya/omzet (jangan pakai 30%×budget — itu menyesatkan "belum setup")
        has_month = month_v == month_v and month_v > _ACTIVE_SPEND
        has_since = cost > _ACTIVE_SPEND or total_sejak > _ACTIVE_SPEND or omzet_sejak > 0
        has_spend = has_month or has_since
        sc_label = "Berjalan" if is_run or has_spend else "Tidak aktif / rendah"
        weak = cost > 0 and roas == roas and target_roas > 0 and roas < target_roas * 0.9
        spend_bits = f"Terpakai sejak campaign {_rp_hari(cost)}"
        if month_v == month_v:
            spend_bits = f"Terpakai bulan ini {_rp_hari(month_v)}; sejak campaign {_rp_hari(cost)}"
        alts = _alts_for_plan_key(key, units=units, members=members) if not has_spend else []
        alt_label = "; ".join(
            f"{a['nama']} ({a['jenis']}"
            + (f", {_rp_hari(a['biaya'])}" if a.get("biaya") else "")
            + ")"
            for a in alts[:3]
        ) if alts else ""

        if expected <= 0:
            if done or cost <= 5_000:
                goal, act, tip = "Sesuai rencana", "Pertahankan", (
                    "Iklan ini tetap tercatat di campaign, tetapi budget rencananya Rp 0 "
                    "(sengaja dihentikan). Tidak perlu diubah."
                )
            else:
                # Jangan campur omzet dengan biaya; sebutkan hari agar rata-rata × hari = total masuk akal.
                biaya_bit = (
                    f"biaya {_rp(total_sejak)}"
                    + (f" / {days_eval} hari" if days_eval > 0 else "")
                    + f" (rata-rata {_rp_hari(cost)})"
                    if total_sejak > 0 else spend_bits
                )
                month_bit = f"; bulan ini rata-rata {_rp_hari(month_v)}" if month_v == month_v else ""
                omzet_bit = f"; omzet {_rp(omzet_sejak)}" if omzet_sejak > 0 else ""
                window_note = ""
                if month_v == month_v and cost > 0 and month_v + 1 < cost:
                    window_note = (
                        " Bulan ini boleh lebih kecil: dihitung dari tgl 1 "
                        "(termasuk hari sebelum campaign disimpan)."
                    )
                goal, act, tip = "Tidak sesuai rencana", "Jeda / hentikan", (
                    f"Budget rencana Rp 0 (sengaja dihentikan), tetapi laporan masih mencatat "
                    f"biaya pada iklan «{nama}» di Seller Center — {biaya_bit}{month_bit}{omzet_bit}. "
                    f"Pause / hentikan iklan «{nama}» di SC (cari nama yang sama)."
                    + window_note
                )
        elif sc_label.startswith("Tidak") and expected > 0 and alts:
            # Bukan belum setup: produk sudah jalan di iklan lain (grup/tunggal)
            goal, act, tip = "Sudah di tempat lain", "Sudah diiklankan di tempat lain", (
                f"Di rencana budget {_rp_hari(expected)}, tetapi produk sudah aktif di: {alt_label}. "
                "Jangan buat iklan baru sesuai nama rencana — itu dobel. "
                "Kelola iklan yang sudah jalan, atau pindahkan ke campaign yang benar."
            )
        elif sc_label.startswith("Tidak") and expected > 0:
            goal, act, tip = "Belum aktif", "Buat / aktifkan", (
                f"Di rencana budget {_rp_hari(expected)}, dan belum ada biaya/omzet di laporan "
                "untuk kunci iklan ini. Buat/aktifkan di Seller Center (atau pastikan nama/kode cocok), "
                "lalu unggah laporan."
            )
        elif has_month and not has_since and expected > 0:
            # Pintu-style: ada di laporan bulan ini, belum bertambah sejak campaign
            goal, act, tip = "Perlu dicek", "Naikkan budget", (
                f"Iklan ini SUDAH ada di laporan (bukan belum setup): terpakai bulan ini {_rp_hari(month_v)}, "
                f"tetapi sejak campaign ±Rp 0. Cek di SC apakah dijeda setelah campaign disimpan, "
                f"lalu naikkan/aktifkan budget ke {_rp_hari(expected)} bila ingin jalan sesuai rencana."
            )
        elif not done and cost > expected * 1.4:
            goal, act, tip = "Tidak sesuai rencana", "Turunkan budget", (
                f"{spend_bits} — lebih tinggi dari budget di Shopee ({_rp_hari(expected)}). "
                f"Di Seller Center, turunkan budget harian menjadi {_rp_hari(expected)}."
            )
        elif not done and cost < expected * 0.6:
            floor_note = (
                f" (rencana {_rp_hari(plan)}, dinaikkan ke minimum Shopee)"
                if expected > plan + 1 else ""
            )
            goal, act, tip = "Tidak sesuai rencana", "Naikkan budget", (
                f"{spend_bits} — masih di bawah budget di Shopee ({_rp_hari(expected)}){floor_note}. "
                "Naikkan budget harian di Seller Center, atau longgarkan Target ROAS agar budget terserap."
            )
        elif weak:
            goal, act, tip = "ROAS lemah", "Naikkan Target ROAS", (
                f"ROAS {roas:.1f}× masih di bawah target campaign {target_roas:.1f}×. "
                "Naikkan Target ROAS di Shopee atau pindahkan budget ke iklan yang lebih kuat."
            )
        elif done and expected > plan + 1:
            goal, act, tip = "Sesuai rencana", "Pertahankan", (
                f"Berjalan di batas minimum Shopee ({_rp_hari(expected)}) — wajar, bukan gagal rencana."
            )
        elif done:
            goal, act, tip = "Sesuai rencana", "Pertahankan", (
                f"{spend_bits}. Budget dan ROAS sejalan dengan rencana campaign."
            )
        else:
            goal, act, tip = "Perlu dicek", "Naikkan budget", (
                f"{spend_bits}. Samakan budget di Seller Center ke {_rp_hari(expected)}, lalu unggah laporan esok hari."
            )

        catatan = str(r.get("Catatan batas") or "")
        if "proporsional" in catatan.lower() and "proporsional" not in tip.lower():
            tip = (
                f"{tip} Angka terpakai memakai porsi proporsional bulan berjalan "
                "(baseline biaya iklan tidak terekam saat campaign disimpan — "
                "simpan ulang campaign agar selisih hari nyata)."
            ).strip()
        goals.append(goal)
        actions.append(act)
        tips.append(tip)
        sc.append(sc_label)
    out["Status SC"] = sc
    out["Status goals"] = goals
    out["Tindakan"] = actions
    out["Saran"] = tips
    out["_rank"] = out["Tindakan"].map(lambda t: _STATUS_RANK.get(t, 9))
    return out.sort_values(["_rank", "Biaya aktual/hari"], ascending=[True, False]).drop(columns=["_rank"])


def refresh_tips_after_month(
    frame: pd.DataFrame,
    *,
    target_roas: float,
    running_keys: set[str] | None = None,
    units=None,
    members: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Tulis ulang Status/Tindakan/Saran setelah `Biaya bulan ini/hari` terisi; urutan baris tetap."""
    if frame is None or frame.empty or "Biaya bulan ini/hari" not in getattr(frame, "columns", []):
        return frame if frame is not None else pd.DataFrame()
    core = frame.drop(columns=["Status SC", "Status goals", "Tindakan", "Saran"], errors="ignore")
    fresh = classify_rows(core, target_roas=target_roas, running_keys=running_keys, units=units, members=members)
    if fresh.empty or "_key" not in fresh.columns:
        return frame
    by_key = {str(k): r for k, r in fresh.set_index("_key", drop=False).iterrows()}
    tips, acts, goals, scs = [], [], [], []
    for key in frame["_key"].astype(str):
        row = by_key.get(str(key))
        if row is None:
            tips.append(str(frame.loc[frame["_key"].astype(str) == key, "Saran"].iloc[0]) if "Saran" in frame.columns else "")
            acts.append(str(frame.loc[frame["_key"].astype(str) == key, "Tindakan"].iloc[0]) if "Tindakan" in frame.columns else "")
            goals.append(str(frame.loc[frame["_key"].astype(str) == key, "Status goals"].iloc[0]) if "Status goals" in frame.columns else "")
            scs.append(str(frame.loc[frame["_key"].astype(str) == key, "Status SC"].iloc[0]) if "Status SC" in frame.columns else "")
            continue
        tips.append(str(row["Saran"]))
        acts.append(str(row["Tindakan"]))
        goals.append(str(row["Status goals"]))
        scs.append(str(row["Status SC"]))
    out = frame.copy()
    out["Saran"], out["Tindakan"], out["Status goals"], out["Status SC"] = tips, acts, goals, scs
    return out


def priority_actions(classified: pd.DataFrame, *, limit: int = 8) -> list[dict]:
    if classified is None or classified.empty:
        return []
    work = classified.loc[classified["Tindakan"] != "Pertahankan"].head(limit)
    out = []
    for _, r in work.iterrows():
        out.append({
            "iklan": str(r.get("Iklan") or r.get("_key") or ""),
            "jenis": str(r.get("Jenis") or ""),
            "tindakan": str(r["Tindakan"]),
            "saran": str(r["Saran"]),
            "biaya": float(r.get("Biaya aktual/hari") or 0),
            "efektif": float(r.get("Budget efektif Shopee/hari") or 0),
            "roas": float(r["ROAS aktual"]) if r.get("ROAS aktual") == r.get("ROAS aktual") else float("nan"),
        })
    return out


def budget_wallet(setelan: dict, *, spent_month: float, spent_since: float, days_since: int, days_left_plan: int) -> dict:
    """Kartu baca budget: total rencana, terpakai bulan, terpakai sejak disimpan, sisa, pembagian harian."""
    s = setelan or {}
    total = float(s.get("budget_bulan") or s.get("budget") or 0)
    daily = float(s.get("biaya_harian_rencana") or s.get("budget_harian") or 0)
    path_since = daily * max(days_since, 0)
    remaining = max(total - spent_month, 0.0)
    return {
        "budget_total": total,
        "terpakai_bulan": float(spent_month),
        "sisa_bulan": remaining,
        "rencana_harian": daily,
        "terpakai_sejak": float(spent_since),
        "jalur_sejak": path_since,
        "sisa_hari_rencana": max(int(days_left_plan), 0),
        "roas_target": float(s.get("roas") or 0),
    }


def must_advertise(products: pd.DataFrame, classified: pd.DataFrame | None, sel_saved: pd.DataFrame | None,
                   units, *, target_roas: float, daily_budget_room: float, limit: int = 12) -> pd.DataFrame:
    """Daftar item yang HARUS diiklankan / dinaikkan (bukan daftar 'jangan iklan').

    Urutan: (1) iklan berjalan ROAS kuat → pertahankan/naikkan, (2) produk prediksi tinggi + stok → buat baru,
    (3) iklan ROAS lemah berbiaya → jeda (maks 3 baris di akhir sebagai penghematan)."""
    cols = ["Prioritas", "Produk", "Kode / iklan", "Jenis", "Keputusan", "Budget/hari", "Alasan",
            "Prediksi omzet/hari", "Stok 10037", "Stok 10062", "Stok 10036", "ROAS terkini", "Biaya kini/hari"]
    rows: list[dict] = []

    # Peta performa iklan tunggal
    roas_by_code, cost_by_code = {}, {}
    weak_ads = []
    strong_ads = []
    if isinstance(classified, pd.DataFrame) and not classified.empty:
        for _, r in classified.iterrows():
            key = str(r.get("_key") or "")
            name = str(r.get("Iklan") or key)
            jenis = str(r.get("Jenis") or "")
            cost = float(r.get("Biaya aktual/hari") or 0)
            roas = float(r["ROAS aktual"]) if r.get("ROAS aktual") == r.get("ROAS aktual") else float("nan")
            expected = float(r.get("Budget efektif Shopee/hari") or 0)
            if key.startswith(("produk:", "pisah:", "baru:")):
                code = key.split(":", 1)[1]
                roas_by_code[code] = roas
                cost_by_code[code] = cost
            if expected > 0 and cost > 0 and roas == roas and roas >= target_roas * 0.9:
                strong_ads.append((name, key, jenis, cost, roas, expected))
            elif expected > 0 and cost > expected * 0.4 and roas == roas and roas < target_roas * 0.7:
                weak_ads.append((name, key, jenis, cost, roas, expected))

    in_plan = set()
    if isinstance(sel_saved, pd.DataFrame) and not sel_saved.empty and "Kode produk" in sel_saved.columns:
        in_plan = {str(c) for c in sel_saved["Kode produk"].astype(str) if c and c != "nan"}

    spent = 0.0
    room = max(float(daily_budget_room or 0), 0.0)

    # 1) Pertahankan / naikkan iklan kuat
    for name, key, jenis, cost, roas, expected in sorted(strong_ads, key=lambda x: -x[3])[:8]:
        bump = A.round_budget(max(cost, expected) * 1.15, min_floor=A.seller_min_budget(jenis))
        if room > 0 and spent + max(bump - cost, 0) > room + 1:
            bump = A.implementable_budget(cost, jenis)
        stock = stock_summary_for_ad(products, key)
        rows.append({
            "Prioritas": len(rows) + 1, "Produk": name, "Kode / iklan": key, "Jenis": jenis,
            "Keputusan": "Pertahankan / naikkan", "Budget/hari": bump,
            "Alasan": (
                f"ROAS {roas:.1f} ≥ target · iklan ini yang menopang omzet; naikkan bertahap hanya di Senin. "
                + stock["teks"]
            ),
            "Prediksi omzet/hari": np.nan,
            "Stok 10037": stock["stok_10037"], "Stok 10062": stock["stok_10062"], "Stok 10036": stock["stok_10036"],
            "ROAS terkini": roas, "Biaya kini/hari": cost,
        })
        spent += max(bump - cost, 0)

    # 2) Produk baru layak iklan (prediksi tinggi + stok toko 10037)
    if isinstance(products, pd.DataFrame) and not products.empty and "product_code" in products.columns:
        work = products.copy()
        work["product_code"] = work["product_code"].astype(str)
        work["omzet_harian"] = pd.to_numeric(work.get("omzet_harian"), errors="coerce").fillna(0.0)
        work["stok"] = pd.to_numeric(work.get("stok_10037", work.get("stok")), errors="coerce").fillna(0.0)
        work["stok_room"] = pd.to_numeric(work.get("stok_room"), errors="coerce").fillna(work["stok"])
        for col in ("stok_10062", "stok_10036"):
            if col not in work.columns:
                work[col] = np.nan
            else:
                work[col] = pd.to_numeric(work[col], errors="coerce")
        q = float(work["omzet_harian"].quantile(0.80)) if len(work) else 0.0
        cand = work.loc[(work["stok"] > 0) & (work["stok_room"] > 0) & (work["omzet_harian"] >= max(q, 1.0))]
        cand = cand.sort_values("omzet_harian", ascending=False)
        for r in cand.itertuples(index=False):
            if len([x for x in rows if str(x["Keputusan"]).startswith("Buat")]) >= 6:
                break
            code = str(r.product_code)
            if code in cost_by_code and cost_by_code[code] > 0:
                continue  # sudah punya iklan tunggal berjalan
            start = A.SHOPEE_MIN_SINGLE
            if room > 0 and spent + start > room + 1:
                break
            sig = _product_signal(products, code)
            rows.append({
                "Prioritas": len(rows) + 1, "Produk": str(getattr(r, "nama", code) or code),
                "Kode / iklan": code, "Jenis": "Produk tunggal (baru)",
                "Keputusan": "Buat iklan tunggal", "Budget/hari": start,
                "Alasan": (
                    f"Prediksi omzet tinggi (±{float(r.omzet_harian):,.0f}/hari), stok toko ada"
                    + (", belum di pemilihan rencana" if code not in in_plan else ", sudah di rencana tetapi belum aktif")
                    + f". Mulai {start:,.0f}/hari, Target ROAS {target_roas:.0f}. "
                    + stock_sites_text(sig, short=False)
                ).replace(",", "."),
                "Prediksi omzet/hari": float(r.omzet_harian),
                "Stok 10037": sig["stok_10037"], "Stok 10062": sig["stok_10062"], "Stok 10036": sig["stok_10036"],
                "ROAS terkini": roas_by_code.get(code, np.nan), "Biaya kini/hari": cost_by_code.get(code, 0.0),
            })
            spent += start

    # 3) Penghematan: max 3 iklan lemah
    for name, key, jenis, cost, roas, expected in sorted(weak_ads, key=lambda x: x[4])[:3]:
        stock = stock_summary_for_ad(products, key)
        rows.append({
            "Prioritas": len(rows) + 1, "Produk": name, "Kode / iklan": key, "Jenis": jenis,
            "Keputusan": "Jeda / alihkan budget", "Budget/hari": 0.0,
            "Alasan": (
                f"ROAS {roas:.1f} jauh di bawah target {target_roas:.1f} · pindahkan budget ke item di atas. "
                + stock["teks"]
            ),
            "Prediksi omzet/hari": np.nan,
            "Stok 10037": stock["stok_10037"], "Stok 10062": stock["stok_10062"], "Stok 10036": stock["stok_10036"],
            "ROAS terkini": roas, "Biaya kini/hari": cost,
        })

    # rapikan prioritas 1..n dan potong
    out = pd.DataFrame(rows[:limit], columns=cols)
    if not out.empty:
        out["Prioritas"] = range(1, len(out) + 1)
    return out


def active_plan_ads(acts_saved: pd.DataFrame, *, limit: int = 40) -> pd.DataFrame:
    """Hanya iklan rencana yang relevan: budget usulan > 0 atau ada perubahan, diurut budget terbesar."""
    if acts_saved is None or acts_saved.empty:
        return pd.DataFrame()
    work = acts_saved.copy()
    col = "Budget harian usulan"
    if col not in work.columns:
        return work.head(limit)
    work["_b"] = pd.to_numeric(work[col], errors="coerce").fillna(0.0)
    now = pd.to_numeric(work.get("Budget harian sekarang"), errors="coerce").fillna(0.0) if "Budget harian sekarang" in work.columns else 0.0
    focus = work.loc[(work["_b"] > 0) | (now > 0)].sort_values("_b", ascending=False)
    return focus.drop(columns=["_b"]).head(limit)


def selection_focus(sel_saved: pd.DataFrame, *, limit: int = 25) -> pd.DataFrame:
    """Pemilihan produk ringkas: prioritas tindakan aktif + prediksi tertinggi, bukan 600+ baris."""
    if sel_saved is None or sel_saved.empty:
        return pd.DataFrame()
    work = sel_saved.copy()
    if "Saran" in work.columns:
        hot = work["Saran"].astype(str).str.contains(
            r"Buat|Tambah|Pindah|Keluarkan|tunggal|naik|prioritas", case=False, na=False)
        prefer = work.loc[hot]
        rest = work.loc[~hot]
    else:
        prefer, rest = work, work.iloc[0:0]
    if "Prediksi omzet/hari" in work.columns:
        rest = rest.assign(_p=pd.to_numeric(rest["Prediksi omzet/hari"], errors="coerce").fillna(0)).sort_values("_p", ascending=False)
        prefer = prefer.assign(_p=pd.to_numeric(prefer["Prediksi omzet/hari"], errors="coerce").fillna(0)).sort_values("_p", ascending=False)
        rest = rest.drop(columns=["_p"], errors="ignore")
        prefer = prefer.drop(columns=["_p"], errors="ignore")
    out = pd.concat([prefer, rest], ignore_index=True).head(limit)
    return out


def week_window(today: date | None = None) -> tuple[date, date]:
    today = today or date.today()
    start = today
    end = today + timedelta(days=6)
    return start, end


def rollup(classified: pd.DataFrame, summary: dict, *, track: dict | None, target_roas: float,
           store_roas: float | None = None) -> dict:
    total = int(summary.get("iklan_aktif_rencana") or summary.get("iklan") or 0)
    done = int(summary.get("dijalankan") or 0)
    floor_hits = int(summary.get("batas_shopee") or 0)
    roas = float(store_roas) if store_roas == store_roas and store_roas is not None else (
        float(summary.get("roas")) if summary.get("roas") == summary.get("roas") else float("nan"))
    on_sales = track is None or track.get("status") in (None, "On track", "Menunggu data")
    actions = priority_actions(classified, limit=50)
    need = len(actions)
    roas_ok = not (roas == roas and target_roas > 0 and roas < target_roas * 0.9)

    if total == 0 and not summary:
        level, title, blurb = "info", "Menunggu laporan iklan baru", "Unggah laporan iklan Seller Center (hari kemarin) agar hasil campaign bisa dinilai hari ini."
    elif done / max(total, 1) >= 0.7 and roas_ok and on_sales and need <= max(2, total * 0.2):
        level, title, blurb = "ok", "Campaign on track", (
            f"{done}/{total} iklan aktif sesuai acuan"
            + (f" · {floor_hits} di min. Shopee" if floor_hits else "")
            + (f" · ROAS iklan {roas:.1f}" if roas == roas else "")
            + ". Lanjut; review besar di Senin."
        )
    elif done / max(total, 1) >= 0.7 and not roas_ok:
        level, title, blurb = "warn", "Budget jalan, ROAS masih lemah", (
            f"ROAS iklan {roas:.1f} vs target {target_roas:.1f}. Rapikan iklan lemah dulu (lihat tindakan prioritas)."
        )
    elif on_sales and need > 0:
        level, title, blurb = "warn", "Sales on track — rapikan pelaksanaan iklan", (
            f"{done}/{max(total, 1)} sesuai acuan · {need} iklan perlu tindakan hari ini di Seller Center."
        )
    else:
        level, title, blurb = "alert", "Perlu tindakan agar rencana berhasil", (
            f"Hanya {done}/{max(total, 1)} iklan sesuai acuan. Kerjakan prioritas, unggah laporan esok hari."
        )
    return {
        "level": level, "title": title, "blurb": blurb, "done": done, "total": max(total, 1) if summary else 0,
        "floor_hits": floor_hits, "need": need, "roas": roas, "roas_ok": roas_ok, "on_sales": on_sales,
    }


def spend_gap_tip(wallet: dict, store_since: dict, summary: dict) -> str:
    bits = []
    if store_since:
        bits.append(
            f"Sejak campaign: biaya Rp {store_since.get('biaya', 0):,.0f} · omzet dari iklan Rp {store_since.get('omzet', 0):,.0f}"
            .replace(",", ".")
        )
        if store_since.get("biaya", 0) > 0:
            bits.append(f"ROAS {store_since['omzet'] / store_since['biaya']:.1f}")
    if wallet.get("rencana_harian"):
        bits.append(
            f"Patokan harian Rp {wallet['rencana_harian']:,.0f} · "
            f"terpakai sejak campaign Rp {wallet['terpakai_sejak']:,.0f} "
            f"(patokan kumulatif Rp {wallet['jalur_sejak']:,.0f})".replace(",", ".")
        )
    if summary.get("batas_shopee"):
        bits.append(
            f"{summary['batas_shopee']} iklan memakai batas minimum Shopee "
            "(Rp 25.000 tunggal / Rp 100.000 grup) — itu wajar, bukan gagal rencana"
        )
    return " · ".join(bits)


def complete_plan_rows(
    classified: pd.DataFrame,
    planned: dict[str, float],
    *,
    names: dict[str, tuple[str, str]],
    target_roas: float,
    running_keys: set[str] | None = None,
    units=None,
    members: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Pastikan semua kunci campaign tersimpan muncul, meski belum ada di laporan terbaru."""
    have = set(classified["_key"].astype(str)) if isinstance(classified, pd.DataFrame) and not classified.empty and "_key" in classified.columns else set()
    rows = []
    for key, plan in (planned or {}).items():
        if str(key) in have:
            continue
        kind = (names.get(str(key)) or ("", "Grup" if str(key).startswith("grup:") else "Produk tunggal"))[1]
        nama = (names.get(str(key)) or (str(key), kind))[0]
        expected = A.implementable_budget(float(plan or 0), kind)
        rows.append({
            "_key": str(key), "Iklan": nama, "Jenis": kind, "Hari dievaluasi": 0,
            "Budget usulan/hari": float(plan or 0), "Budget efektif Shopee/hari": expected,
            "Biaya aktual/hari": 0.0, "Omzet iklan aktual/hari": 0.0,
            "Biaya sejak disimpan": 0.0, "Omzet iklan sejak disimpan": 0.0, "ROAS aktual": float("nan"),
            "Rasio vs efektif": float("nan"), "Status pelaksanaan": "Belum ada di laporan",
            "Rekomendasi dijalankan": "Belum", "Catatan batas": "",
        })
    extra = pd.DataFrame(rows)
    if extra.empty:
        frame = classified.copy() if isinstance(classified, pd.DataFrame) else pd.DataFrame()
    elif classified is None or classified.empty:
        frame = classify_rows(extra, target_roas=target_roas, running_keys=running_keys, units=units, members=members)
    else:
        frame = pd.concat(
            [classified, classify_rows(extra, target_roas=target_roas, running_keys=running_keys, units=units, members=members)],
            ignore_index=True,
        )
    return sort_by_omzet(frame)


def sort_by_omzet(frame: pd.DataFrame) -> pd.DataFrame:
    """Urut omzet iklan sejak disimpan terbesar (prioritas sales)."""
    if frame is None or frame.empty:
        return pd.DataFrame() if frame is None else frame
    out = frame.copy()
    col = "Omzet iklan sejak disimpan"
    if col not in out.columns:
        return out
    out["_omz"] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
    return out.sort_values("_omz", ascending=False).drop(columns=["_omz"]).reset_index(drop=True)


def report_alias(key: str) -> str:
    """Kunci laporan Seller Center untuk usulan pisah/baru → produk:kode."""
    k = str(key or "")
    if k.startswith(("pisah:", "baru:")):
        return "produk:" + k.split(":", 1)[1]
    return k


def plan_coverage(planned: dict[str, float] | None) -> set[str]:
    """Semua kunci yang dianggap 'dalam rencana' (termasuk alias laporan)."""
    covered: set[str] = set()
    for key in planned or {}:
        k = str(key)
        covered.add(k)
        covered.add(report_alias(k))
    return covered


def split_in_out_plan(
    classified: pd.DataFrame,
    planned: dict[str, float],
    current: dict[str, dict],
    baseline: dict[str, dict],
    *,
    names: dict[str, tuple[str, str]],
    kinds: dict[str, str],
    target_roas: float,
    running_keys: set[str] | None = None,
    units=None,
    members: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Pisah ketat: hanya kunci campaign → dalam rencana; berbiaya di SC tanpa kunci campaign → luar rencana."""
    planned = planned or {}
    plan_keys = {str(k) for k in planned}
    covered = plan_coverage(planned)
    in_plan = complete_plan_rows(
        classified, planned, names=names, target_roas=target_roas, running_keys=running_keys,
        units=units, members=members,
    )
    if not in_plan.empty and "_key" in in_plan.columns:
        # Pertahankan hanya kunci yang benar-benar tersimpan di campaign (bukan alias laporan).
        in_plan = sort_by_omzet(in_plan.loc[in_plan["_key"].astype(str).isin(plan_keys)].copy())

    # Di luar plan: ada di laporan sekarang, tidak tertutup kunci/alias campaign, dan ada biaya sejak baseline
    outsider_planned = {}
    for key, cur in (current or {}).items():
        k = str(key)
        if k in covered or report_alias(k) in covered:
            continue
        base = (baseline or {}).get(k) or {}
        if base and base.get("periode") == cur.get("periode"):
            days = int(cur.get("hari", 0)) - int(base.get("hari", 0))
            cost = float(cur.get("biaya", 0)) - float(base.get("biaya", 0))
        else:
            days, cost = int(cur.get("hari", 0)), float(cur.get("biaya", 0))
        if days > 0 and cost > 5_000:
            outsider_planned[k] = 0.0  # tidak di plan → acuan jeda

    out_frame = pd.DataFrame()
    if outsider_planned:
        frame, _ = A.evaluate(baseline or {}, current or {}, outsider_planned, target_roas=target_roas, jenis=kinds)
        if not frame.empty:
            frame.insert(1, "Iklan", frame["_key"].map(lambda k: (names.get(str(k)) or (str(k), ""))[0]))
            if "Jenis" not in frame.columns or frame["Jenis"].isna().all():
                frame["Jenis"] = frame["_key"].map(
                    lambda k: kinds.get(str(k)) or ((names.get(str(k)) or ("", "Produk tunggal"))[1]))
            out_frame = sort_by_omzet(classify_rows(
                frame, target_roas=target_roas, running_keys=running_keys, units=units, members=members,
            ))
            # Jaga-jaga: buang bila ternyata alias dari kunci rencana
            if not out_frame.empty:
                out_frame = out_frame.loc[
                    ~out_frame["_key"].astype(str).isin(covered)
                    & ~out_frame["_key"].astype(str).map(report_alias).isin(covered)
                ].copy()
                out_frame = sort_by_omzet(out_frame)
    return in_plan, out_frame


def partition_plan_rows(in_plan: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Sub-grup dalam rencana: belum setup / sudah di tempat lain / jeda / keluarkan anggota / pantau."""
    empty = pd.DataFrame()
    if in_plan is None or in_plan.empty or "Tindakan" not in in_plan.columns:
        return {
            "belum_setup": empty, "sudah_di_tempat_lain": empty, "jeda_tertinggal": empty,
            "keluarkan_anggota": empty, "pantau": empty,
        }
    act = in_plan["Tindakan"].astype(str)
    mask_belum = act == "Buat / aktifkan"
    mask_lain = act == "Sudah diiklankan di tempat lain"
    mask_jeda = act.str.startswith("Jeda")
    mask_keluar = act == "Keluarkan anggota dari grup"
    return {
        "belum_setup": sort_by_omzet(in_plan.loc[mask_belum].copy()),
        "sudah_di_tempat_lain": sort_by_omzet(in_plan.loc[mask_lain].copy()),
        "jeda_tertinggal": sort_by_omzet(in_plan.loc[mask_jeda].copy()),
        "keluarkan_anggota": sort_by_omzet(in_plan.loc[mask_keluar].copy()),
        "pantau": sort_by_omzet(
            in_plan.loc[~mask_belum & ~mask_lain & ~mask_jeda & ~mask_keluar].copy()
        ),
    }


_TIDAK_SESUAI_ACT = frozenset({
    "Buat / aktifkan",
    "Sudah diiklankan di tempat lain",
    "Jeda / hentikan",
    "Keluarkan anggota dari grup",
})


def partition_execution(in_plan: pd.DataFrame, *, target_roas: float = 0.0) -> dict[str, pd.DataFrame]:
    """Grouping pelaksanaan: sesuai plan (efektif / tidak efektif / boros) vs tidak sesuai plan.

    Sesuai plan = slot campaign sudah jalan di kunci yang sama (bukan dobel/belum setup/jeda/isi grup salah).
    Efektivitas diukur dari ROAS vs target + tindakan budget.
    """
    empty = pd.DataFrame()
    base = {
        "sesuai_efektif": empty, "sesuai_tidak_efektif": empty, "sesuai_boros": empty,
        "tidak_belum_setup": empty, "tidak_di_tempat_lain": empty,
        "tidak_jeda": empty, "tidak_isi_grup": empty,
    }
    if in_plan is None or in_plan.empty or "Tindakan" not in in_plan.columns:
        return base
    parts = partition_plan_rows(in_plan)
    pantau = parts.get("pantau", empty)
    if pantau is None or pantau.empty:
        sesuai_ok = sesuai_lemah = sesuai_boros = empty
    else:
        act = pantau["Tindakan"].astype(str)
        roas = pd.to_numeric(pantau.get("ROAS aktual"), errors="coerce")
        mask_boros = act.str.startswith("Turunkan")
        mask_lemah = (
            act.str.startswith("Naikkan Target ROAS")
            | act.str.startswith("Naikkan budget")
            | (
                (target_roas > 0)
                & roas.notna()
                & (roas < target_roas * 0.9)
                & ~mask_boros
            )
        )
        # Efektif: Pertahankan, atau pantau lain yang tidak lemah/boros
        mask_ok = act.eq("Pertahankan") | (~mask_boros & ~mask_lemah)
        # Hindari overlap: boros dulu, lalu lemah, sisanya efektif
        sesuai_boros = sort_by_omzet(pantau.loc[mask_boros].copy())
        sesuai_lemah = sort_by_omzet(pantau.loc[mask_lemah & ~mask_boros].copy())
        sesuai_ok = sort_by_omzet(pantau.loc[mask_ok & ~mask_boros & ~mask_lemah].copy())
    return {
        "sesuai_efektif": sesuai_ok,
        "sesuai_tidak_efektif": sesuai_lemah,
        "sesuai_boros": sesuai_boros,
        "tidak_belum_setup": parts.get("belum_setup", empty),
        "tidak_di_tempat_lain": parts.get("sudah_di_tempat_lain", empty),
        "tidak_jeda": parts.get("jeda_tertinggal", empty),
        "tidak_isi_grup": parts.get("keluarkan_anggota", empty),
    }


def execution_ringkas(counts: dict | None, *, luar: int = 0) -> str:
    """Satu kalimat dengan istilah yang sama seperti judul analisa di bawah tabel."""
    c = counts or {}
    bits = []
    for label, key in (
        ("Efektif", "efektif"),
        ("Tidak efektif", "tidak_efektif"),
        ("Boros", "boros"),
        ("Belum di-setup", "belum_setup"),
        ("Sudah diiklankan di tempat lain", "di_tempat_lain"),
        ("Jeda", "jeda"),
        ("Isi grup salah", "isi_grup"),
    ):
        n = int(c.get(key) or 0)
        if n:
            bits.append(f"{label} {n}")
    if luar:
        bits.append(f"Di luar plan {int(luar)}")
    return " · ".join(bits)


def execution_counts(parts: dict[str, pd.DataFrame]) -> dict[str, int]:
    """Ringkas jumlah iklan per bucket pelaksanaan."""
    def n(key: str) -> int:
        f = parts.get(key)
        return 0 if f is None or getattr(f, "empty", True) else len(f)

    sesuai = n("sesuai_efektif") + n("sesuai_tidak_efektif") + n("sesuai_boros")
    tidak = n("tidak_belum_setup") + n("tidak_di_tempat_lain") + n("tidak_jeda") + n("tidak_isi_grup")
    return {
        "sesuai": sesuai,
        "tidak": tidak,
        "efektif": n("sesuai_efektif"),
        "tidak_efektif": n("sesuai_tidak_efektif"),
        "boros": n("sesuai_boros"),
        "belum_setup": n("tidak_belum_setup"),
        "di_tempat_lain": n("tidak_di_tempat_lain"),
        "jeda": n("tidak_jeda"),
        "isi_grup": n("tidak_isi_grup"),
    }


PROGRESS_COLS = [
    "Tanggal",
    "Budget di rencana/hari",
    "Biaya iklan",
    "Omzet iklan",
    "ROAS iklan",
    "Sales bruto",
    "Sales produk",
    "Sales bersih",
    "Saran",
]
# Nama kelompok dan kolom memakai istilah yang sudah ada di kartu dan analisa iklan.
PROGRESS_GROUPS = {
    "Di rencana": ("Budget di rencana/hari",),
    "Sejak campaign": ("Biaya iklan", "Omzet iklan", "ROAS iklan", "Sales bruto", "Sales produk", "Sales bersih"),
}


def _finite(value, default: float = float("nan")) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return v if v == v else default


def _as_day(value) -> date | None:
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except Exception:
        return None


def campaign_eval_start(campaign: dict | None) -> date | None:
    """Hari pertama evaluasi = **awal periode campaign** yang di-set di fitur (`mulai`).

    Fallback: `setelan.data_sampai` + 1 hari (hari pertama setelah Simpan rencana).
    Bukan tanggal buat iklan di Seller Center.
    """
    if not campaign:
        return None
    mulai = _as_day(campaign.get("mulai"))
    if mulai is not None:
        return mulai
    s = campaign.get("setelan") or {}
    d0 = _as_day(s.get("data_sampai"))
    if d0 is not None:
        return d0 + timedelta(days=1)
    return None


def campaign_eval_end(campaign: dict | None, *, today: date | None = None) -> date | None:
    """Hari terakhir penuh dalam periode campaign: min(selesai, kemarin).

    Hari ini tidak ikut — hasil all iklan belum penuh.
    """
    if not campaign:
        return None
    today_d = _as_day(today) or date.today()
    last_full = today_d - timedelta(days=1)
    selesai = _as_day(campaign.get("selesai"))
    if selesai is None:
        return last_full
    return min(selesai, last_full)


def day_decision_note(
    *,
    plan_hari: float,
    realisasi_hari: float,
    biaya_sejak: float,
    sales_iklan: float,
    sales_all: float,
    target_roas: float = 0.0,
) -> str:
    """Saran toko dengan aturan yang sama seperti analisa iklan: 60% / 140% budget, ROAS 90% target."""
    del sales_all  # Sales bersih tidak dipakai di Saran iklan; tetap di kartu Persentase biaya vs sales bersih
    roas = sales_iklan / biaya_sejak if biaya_sejak == biaya_sejak and biaya_sejak > 0 else float("nan")
    roas_bit = f" ROAS aktual {roas:.1f}×." if roas == roas else ""
    if plan_hari == plan_hari and plan_hari > 0 and realisasi_hari == realisasi_hari and realisasi_hari >= 0:
        if realisasi_hari > plan_hari * 1.4:
            return f"Tidak sesuai rencana. Turunkan budget.{roas_bit}"
        if realisasi_hari < plan_hari * 0.6:
            return f"Tidak sesuai rencana. Naikkan budget.{roas_bit}"
    if roas == roas and target_roas > 0 and roas < target_roas * 0.9:
        return f"ROAS lemah. Naikkan Target ROAS. ROAS aktual {roas:.1f}×, target {target_roas:.1f}×."
    if (biaya_sejak == biaya_sejak and biaya_sejak > 0) or (realisasi_hari == realisasi_hari and realisasi_hari > 0):
        return f"Sesuai rencana. Pertahankan.{roas_bit}"
    return "Belum ada di laporan."


def _daily_store_sales(
    orders,
    start: date,
    end: date,
    *,
    performance=None,
) -> dict[str, dict[str, float]]:
    """Sales produk & sales bersih per tanggal — istilah sama Ringkasan.

    Urutan sumber:
    1. Data pesanan (sama month_outlook / Ringkasan): Sales produk = net_sku_sales,
       Sales bersih = order_metrics.sales_bersih.
    2. Bila pesanan belum mencakup tanggal itu: Data performa toko harian
       (Total Penjualan = Sales produk; kolom `_sales_bersih_hari` atau Pesanan Dibayar
       bila ada = Sales bersih).
    """
    out: dict[str, dict[str, float]] = {}
    if end < start:
        return out
    if orders is not None and isinstance(orders, pd.DataFrame) and not orders.empty:
        from src.core.metrics import net_sku_sales, normalize_lines, order_metrics

        lines = normalize_lines(orders)
        day = start
        while day <= end:
            key = day.isoformat()
            m = order_metrics(lines, day, day, normalized=True)
            produk = float(net_sku_sales(lines, day, day, normalized=True)["sales"].sum())
            bersih = float(m.get("sales_bersih") or 0.0)
            bruto = float(m.get("sales_bruto") or 0.0)
            if produk > 0 or bersih > 0 or bruto > 0:
                out[key] = {"produk": produk, "bersih": bersih, "bruto": bruto, "sumber": "transaksi"}
            day += timedelta(days=1)

    # Lengkapi hari kosong dari performa toko (unggahan harian / hasil selisih MTD)
    if performance is not None and isinstance(performance, pd.DataFrame) and not performance.empty:
        from src.core.performance import clean_performance, perf_number

        work = performance.copy()
        if "date" in work.columns:
            work = clean_performance(work)
        elif "Tanggal" in work.columns:
            work = work.copy()
            work["date"] = pd.to_datetime(work["Tanggal"], dayfirst=True, errors="coerce")
            work = work.loc[work["date"].notna()]
        if not work.empty:
            for _, row in work.iterrows():
                raw = row["date"]
                if isinstance(raw, date) and not isinstance(raw, datetime):
                    day_d = raw
                else:
                    ts = pd.Timestamp(raw)
                    day_d = ts.date() if pd.notna(ts) else None
                if day_d is None or day_d < start or day_d > end:
                    continue
                key = day_d.isoformat()
                if key in out and out[key].get("sumber") == "transaksi":
                    continue
                # Performa: Total Penjualan harian = Sales bruto (Pesanan Dibuat).
                # _sales_bersih_hari = Pesanan Dibayar. Bukan Sales produk (itu dari transaksi).
                bruto = 0.0
                if "Total Penjualan (IDR)" in work.columns:
                    bruto = float(perf_number(pd.Series([row["Total Penjualan (IDR)"]])).iloc[0] or 0)
                elif "sales" in work.columns:
                    bruto = float(perf_number(pd.Series([row["sales"]])).iloc[0] or 0)
                bersih = bruto
                if "_sales_bersih_hari" in work.columns and pd.notna(row.get("_sales_bersih_hari")):
                    bersih = float(row["_sales_bersih_hari"])
                if bruto <= 0 and bersih <= 0:
                    continue
                out[key] = {"produk": 0.0, "bersih": bersih, "bruto": bruto, "sumber": "performa"}
    return out


def campaign_daily_progress(
    campaign: dict | None,
    plan_keys: set[str] | frozenset | None = None,
    *,
    live_toko: dict | None = None,
    live_tanggal: str | date | None = None,
    target_roas: float = 0.0,
    ads_overall=None,
    orders=None,
    performance=None,
    window_start: date | None = None,
    window_end: date | None = None,
    factor: float = 0.0,
    today: date | None = None,
    ringkas: str = "",
) -> pd.DataFrame:
    """Progress harian dalam periode campaign (hari penuh saja).

    Biaya iklan, Omzet iklan, dan ROAS iklan = kumulatif sejak tanggal campaign
    (hari terakhir = kartu Biaya iklan / Omzet iklan / ROAS iklan).
    Sales bruto, Sales bersih, Sales produk = kumulatif dari pesanan, istilah Ringkasan.
    Saran memakai aturan yang sama dengan analisa iklan di bawah.
    Hari ini tidak ditampilkan.
    """
    from src.core import ads_month as _AM

    del factor  # faktor toko tidak dipakai untuk "bersih" di sini — angka ikut Ringkasan/orders
    cols = list(PROGRESS_COLS)
    start = _as_day(window_start) or campaign_eval_start(campaign)
    today_d = _as_day(today) or date.today()
    last_full = today_d - timedelta(days=1)
    live_day = str(live_tanggal or "")[:10] if live_tanggal is not None else ""
    live_d = _as_day(live_day)
    # Batas data penuh: min(akhir campaign, kemarin, live) — jangan pakai hari ini
    end_cap = campaign_eval_end(campaign, today=today_d) or last_full
    end_cap = min(end_cap, last_full)
    we = _as_day(window_end)
    if we is not None:
        end_cap = min(end_cap, we)
    if live_d is not None:
        end_cap = min(end_cap, live_d)
    if start is None or end_cap < start:
        return pd.DataFrame(columns=cols)

    daily = _AM.daily_ad_totals(ads_overall, start=start, end=end_cap)
    store_daily = _daily_store_sales(orders, start, end_cap, performance=performance)
    # Meta dari pantau_harian / live untuk plan & MTD saja
    meta: dict[str, dict] = {}
    for entry in list((campaign or {}).get("pantau_harian") or []):
        day = str(entry.get("tanggal") or "")[:10]
        if not day:
            continue
        toko = dict(entry.get("toko") or {})
        items = list(entry.get("items") or [])
        if plan_keys is not None:
            keys = {str(k) for k in plan_keys}
            items = [it for it in items if str(it.get("key") or "") in keys]
        meta[day] = {"toko": toko, "items": items}
    if live_toko and live_day and live_d is not None and live_d <= last_full:
        prev_meta = meta.get(live_day) or {}
        prev_toko = prev_meta.get("toko") or {}
        meta[live_day] = {
            "toko": {**prev_toko, **dict(live_toko)},
            "items": prev_meta.get("items") or [],
        }

    # Semua hari kalender dalam periode campaign (penuh) — mis. 15–18 saat hari ini 19
    day_list = [(start + timedelta(days=i)).isoformat() for i in range((end_cap - start).days + 1)]
    if not day_list:
        return pd.DataFrame(columns=cols)

    daily_map = {}
    if not daily.empty:
        for _, r in daily.iterrows():
            daily_map[str(r["Tanggal"])[:10]] = {
                "biaya": float(r["Biaya"]),
                "omzet": float(r["Omzet"]),
                "sumber": str(r.get("Sumber") or ""),
            }

    setelan = ((campaign or {}).get("setelan") or {})
    plan_default = _finite(setelan.get("biaya_harian_rencana"))
    if plan_default != plan_default or plan_default <= 0:
        plan_default = _finite(setelan.get("budget_harian"), 0.0)
    rows = []
    cum_biaya = 0.0
    cum_omzet = 0.0
    cum_produk = 0.0
    cum_bersih = 0.0
    cum_bruto = 0.0
    seen_produk = False
    seen_bersih = False
    seen_bruto = False
    for day in day_list:
        day_d = _as_day(day)
        if day_d is None or day_d > last_full:
            continue
        toko = (meta.get(day) or {}).get("toko") or {}
        items = (meta.get(day) or {}).get("items") or []
        plan = _finite(toko.get("budget_plan_hari"), float(sum(float(it.get("budget_plan") or 0) for it in items)))
        if plan != plan or plan <= 0:
            plan = plan_default
        hit = daily_map.get(day)
        if hit is not None and float(hit["biaya"]) >= 0 and float(hit["omzet"]) >= 0:
            realisasi = float(hit["biaya"])
            omzet_hari = float(hit["omzet"])
            cum_biaya += realisasi
            cum_omzet += omzet_hari
        else:
            realisasi = float("nan")
            omzet_hari = float("nan")
        biaya_show = cum_biaya if cum_biaya > 0 else float("nan")
        omzet_show = cum_omzet if cum_omzet > 0 else float("nan")
        store = store_daily.get(day)
        if store is not None:
            if store.get("sumber") == "transaksi":
                cum_produk += float(store.get("produk") or 0.0)
                seen_produk = True
            cum_bruto += float(store.get("bruto") or 0.0)
            cum_bersih += float(store.get("bersih") or 0.0)
            seen_bruto = True
            seen_bersih = True
            sales_bruto = cum_bruto
            sales_bersih = cum_bersih
            sales_produk = cum_produk if seen_produk else float("nan")
        else:
            sales_bruto = cum_bruto if seen_bruto else float("nan")
            sales_bersih = cum_bersih if seen_bersih else float("nan")
            sales_produk = cum_produk if seen_produk else float("nan")
        # ROAS iklan = Omzet iklan ÷ Biaya iklan sejak campaign. Sama dengan ROAS aktual di analisa iklan.
        roas_iklan = (
            omzet_show / biaya_show
            if biaya_show == biaya_show and biaya_show > 0 and omzet_show == omzet_show
            else float("nan")
        )
        if hit is None or realisasi != realisasi:
            note = "Belum ada di laporan." if not (biaya_show == biaya_show and biaya_show > 0) else day_decision_note(
                plan_hari=plan,
                realisasi_hari=float("nan"),
                biaya_sejak=cum_biaya,
                sales_iklan=cum_omzet,
                sales_all=float("nan"),
                target_roas=target_roas,
            )
        else:
            note = day_decision_note(
                plan_hari=plan,
                realisasi_hari=realisasi,
                biaya_sejak=cum_biaya,
                sales_iklan=cum_omzet,
                sales_all=float("nan"),
                target_roas=target_roas,
            )
        rows.append({
            "Tanggal": day,
            "Budget di rencana/hari": plan,
            "Biaya iklan": biaya_show,
            "Omzet iklan": omzet_show,
            "ROAS iklan": roas_iklan,
            "Sales bruto": sales_bruto,
            "Sales produk": sales_produk,
            "Sales bersih": sales_bersih,
            "Saran": note,
        })
    if rows and ringkas:
        rows[-1]["Saran"] = f"{rows[-1]['Saran']} {ringkas}".strip()
    return pd.DataFrame(rows, columns=cols)


AD_DAILY_COLS = [
    "Tanggal",
    "Budget di rencana/hari",
    "Budget di Shopee/hari",
    "Biaya iklan",
    "Omzet iklan",
    "ROAS iklan",
    "Saran",
]


def _daily_keys_for(key: str) -> set[str]:
    k = str(key or "")
    keys = {k, report_alias(k)}
    return {item for item in keys if item}


def _rows_for_key(unit_daily: pd.DataFrame, key: str) -> pd.DataFrame:
    if unit_daily is None or unit_daily.empty or "key" not in unit_daily.columns:
        return pd.DataFrame(columns=getattr(unit_daily, "columns", []))
    wanted = _daily_keys_for(key)
    return unit_daily.loc[unit_daily["key"].astype(str).isin(wanted)]


def apply_daily_ad_window(
    frame: pd.DataFrame,
    unit_daily: pd.DataFrame,
    *,
    start: date | None,
    end: date | None,
    month_start: date | None = None,
) -> pd.DataFrame:
    """Ganti biaya/omzet sejak campaign dengan jumlah harian all iklan pada jendela yang sama dengan progress.

    Hari tanpa selisih laporan tidak dijumlah. Rata-rata = jumlah ÷ tanggal yang ada angkanya.
    `Rekomendasi dijalankan` ikut dihitung ulang (60–140% budget di Shopee) supaya saran tidak
    memakai jendela baseline yang mencakup hari ini.
    """
    if (
        frame is None or frame.empty or unit_daily is None or unit_daily.empty
        or start is None or end is None or end < start or "_key" not in frame.columns
    ):
        return frame if frame is not None else pd.DataFrame()
    out = frame.copy()
    daily = unit_daily.copy()
    daily["Tanggal"] = daily["Tanggal"].astype(str).str[:10]
    month_lo = month_start or date(end.year, end.month, 1)
    lo, hi = start.isoformat(), end.isoformat()
    month_lo_s = month_lo.isoformat()
    biaya_s, omzet_s, hari_s, rate_s, sales_s, roas_s = [], [], [], [], [], []
    month_s, done_s, notes, ratios = [], [], [], []
    for _, row in out.iterrows():
        part = _rows_for_key(daily, str(row.get("_key") or ""))
        win = part.loc[(part["Tanggal"] >= lo) & (part["Tanggal"] <= hi)] if not part.empty else part
        if win.empty:
            # Jangan menuliskan nol bila iklan ini tidak ada di deret harian.
            biaya_s.append(float(row.get("Biaya sejak disimpan") or 0))
            omzet_s.append(float(row.get("Omzet iklan sejak disimpan") or 0))
            hari_s.append(int(row.get("Hari dievaluasi") or 0))
            rate_s.append(float(row.get("Biaya aktual/hari") or 0))
            sales_s.append(float(row.get("Omzet iklan aktual/hari") or 0))
            roas_raw = row.get("ROAS aktual")
            roas_s.append(float(roas_raw) if roas_raw == roas_raw and roas_raw is not None else float("nan"))
            month_raw = row.get("Biaya bulan ini/hari")
            month_s.append(float(month_raw) if month_raw == month_raw and month_raw is not None else float("nan"))
            done_s.append(str(row.get("Rekomendasi dijalankan") or "Belum"))
            notes.append(str(row.get("Catatan batas") or ""))
            ratio_raw = row.get("Rasio vs efektif")
            ratios.append(float(ratio_raw) if ratio_raw == ratio_raw and ratio_raw is not None else float("nan"))
            continue
        biaya = float(win["Biaya"].sum())
        omzet = float(win["Omzet"].sum())
        hari = int(len(win))
        rate = biaya / hari if hari else 0.0
        sales_d = omzet / hari if hari else 0.0
        expected = float(row.get("Budget efektif Shopee/hari") or 0)
        if expected <= 0:
            done = rate <= _ACTIVE_SPEND
        else:
            done = 0.6 <= rate / expected <= 1.4
        mon = part.loc[(part["Tanggal"] >= month_lo_s) & (part["Tanggal"] <= hi)] if not part.empty else part
        month_rate = float(mon["Biaya"].sum()) / len(mon) if not mon.empty else float("nan")
        note = str(row.get("Catatan batas") or "")
        for phrase in (
            "baseline iklan tidak terekam — porsi proporsional bulan berjalan",
            "baseline tanpa biaya terekam — porsi proporsional bulan berjalan",
        ):
            note = note.replace(phrase, "")
        note = note.strip(" ;")
        biaya_s.append(biaya)
        omzet_s.append(omzet)
        hari_s.append(hari)
        rate_s.append(rate)
        sales_s.append(sales_d)
        roas_s.append(omzet / biaya if biaya > 0 else float("nan"))
        month_s.append(month_rate)
        done_s.append("Ya" if done else "Belum")
        notes.append(note)
        ratios.append(rate / expected if expected > 0 else float("nan"))
    out["Biaya sejak disimpan"] = biaya_s
    out["Omzet iklan sejak disimpan"] = omzet_s
    out["Hari dievaluasi"] = hari_s
    out["Biaya aktual/hari"] = rate_s
    if "Omzet iklan aktual/hari" in out.columns:
        out["Omzet iklan aktual/hari"] = sales_s
    out["ROAS aktual"] = roas_s
    out["Biaya bulan ini/hari"] = month_s
    if "Rekomendasi dijalankan" in out.columns:
        out["Rekomendasi dijalankan"] = done_s
    if "Catatan batas" in out.columns:
        out["Catatan batas"] = notes
    if "Rasio vs efektif" in out.columns:
        out["Rasio vs efektif"] = ratios
    return out


def execution_summary(frame: pd.DataFrame, summary: dict | None) -> dict:
    """Hitung ulang ringkasan pelaksanaan dari baris yang sudah memakai angka harian."""
    out = dict(summary or {})
    if frame is None or frame.empty:
        return out
    if "Rekomendasi dijalankan" in frame.columns:
        out["dijalankan"] = int((frame["Rekomendasi dijalankan"].astype(str) == "Ya").sum())
    active = frame
    if "Budget efektif Shopee/hari" in frame.columns:
        expected = pd.to_numeric(frame["Budget efektif Shopee/hari"], errors="coerce").fillna(0)
        picked = frame.loc[expected > 0]
        if not picked.empty:
            active = picked
    if "Biaya aktual/hari" in active.columns:
        out["biaya_harian"] = float(pd.to_numeric(active["Biaya aktual/hari"], errors="coerce").fillna(0).sum())
    if "Omzet iklan aktual/hari" in active.columns:
        out["omzet_harian"] = float(pd.to_numeric(active["Omzet iklan aktual/hari"], errors="coerce").fillna(0).sum())
    if "Biaya sejak disimpan" in active.columns:
        out["biaya_total"] = float(pd.to_numeric(active["Biaya sejak disimpan"], errors="coerce").fillna(0).sum())
    if "Omzet iklan sejak disimpan" in active.columns:
        out["omzet_total"] = float(pd.to_numeric(active["Omzet iklan sejak disimpan"], errors="coerce").fillna(0).sum())
    biaya_t = float(out.get("biaya_total") or 0)
    omzet_t = float(out.get("omzet_total") or 0)
    out["roas"] = omzet_t / biaya_t if biaya_t > 0 else float("nan")
    if "Hari dievaluasi" in frame.columns:
        hari = pd.to_numeric(frame["Hari dievaluasi"], errors="coerce")
        out["hari"] = int(hari.max()) if hari.notna().any() else 0
    return out


def ad_daily_progress(
    unit_daily: pd.DataFrame | None,
    key: str,
    *,
    start: date | None,
    end: date | None,
    budget_plan: float = 0.0,
    budget_setup: float = 0.0,
    target_roas: float = 0.0,
) -> pd.DataFrame:
    """Satu baris per tanggal penuh sejak campaign, untuk satu iklan.

    Biaya iklan, Omzet iklan, dan ROAS iklan terkumpul sejak tanggal campaign
    (baris terakhir = angka di kartu iklan). Saran memakai aturan yang sama
    dengan progress toko dan analisa iklan.
    """
    cols = list(AD_DAILY_COLS)
    if start is None or end is None or end < start:
        return pd.DataFrame(columns=cols)
    part = _rows_for_key(unit_daily if unit_daily is not None else pd.DataFrame(), key)
    by_day: dict[str, tuple[float, float]] = {}
    if not part.empty:
        for row in part.itertuples(index=False):
            by_day[str(row.Tanggal)[:10]] = (float(row.Biaya), float(row.Omzet))
    plan_hari = float(budget_setup or 0) if float(budget_setup or 0) > 0 else float(budget_plan or 0)
    rows = []
    cum_biaya = 0.0
    cum_omzet = 0.0
    seen = False
    day = start
    while day <= end:
        hit = by_day.get(day.isoformat())
        if hit is not None:
            realisasi, omzet_hari = hit
            cum_biaya += realisasi
            cum_omzet += omzet_hari
            seen = True
        else:
            realisasi = float("nan")
        biaya_show = cum_biaya if seen else float("nan")
        omzet_show = cum_omzet if seen else float("nan")
        roas = (
            omzet_show / biaya_show
            if biaya_show == biaya_show and biaya_show > 0 and omzet_show == omzet_show
            else float("nan")
        )
        if plan_hari <= 0 and realisasi == realisasi and realisasi > _ACTIVE_SPEND:
            note = "Tidak sesuai rencana. Jeda / hentikan."
        elif hit is None and not seen:
            note = "Belum ada di laporan."
        else:
            note = day_decision_note(
                plan_hari=plan_hari,
                realisasi_hari=realisasi,
                biaya_sejak=cum_biaya,
                sales_iklan=cum_omzet,
                sales_all=float("nan"),
                target_roas=target_roas,
            )
        rows.append({
            "Tanggal": day.isoformat(),
            "Budget di rencana/hari": float(budget_plan or 0),
            "Budget di Shopee/hari": float(budget_setup or 0),
            "Biaya iklan": biaya_show,
            "Omzet iklan": omzet_show,
            "ROAS iklan": roas,
            "Saran": note,
        })
        day += timedelta(days=1)
    return pd.DataFrame(rows, columns=cols)


def build_toko_snapshot(
    *,
    budget_plan_hari: float = 0.0,
    budget_actual_hari: float = 0.0,
    biaya_sejak: float = 0.0,
    omzet_kotor_sejak: float = 0.0,
    bersih_sejak: float = float("nan"),
    produk_sejak: float = float("nan"),
    produk_mtd: float = float("nan"),
    bersih_mtd: float = float("nan"),
    iklan_tercatat: int = 0,
    realisasi_biaya_hari: float = float("nan"),
    target_roas: float = 0.0,
) -> dict:
    """Ringkasan toko untuk checkpoint progress (MTD/sales all = angka ringkasan Pantau yang sama)."""
    analisa = day_decision_note(
        plan_hari=float(budget_plan_hari or 0),
        realisasi_hari=_finite(realisasi_biaya_hari),
        biaya_sejak=float(biaya_sejak or 0),
        sales_iklan=float(omzet_kotor_sejak or 0),
        sales_all=_finite(produk_sejak),
        target_roas=float(target_roas or 0),
    )
    return {
        "budget_plan_hari": round(float(budget_plan_hari or 0), 2),
        "budget_actual_hari": round(float(budget_actual_hari or 0), 2),
        "biaya_sejak": round(float(biaya_sejak or 0), 2),
        "omzet_kotor_sejak": round(float(omzet_kotor_sejak or 0), 2),
        "bersih_sejak": None if _finite(bersih_sejak) != _finite(bersih_sejak) else round(float(bersih_sejak), 2),
        "produk_sejak": None if _finite(produk_sejak) != _finite(produk_sejak) else round(float(produk_sejak), 2),
        "produk_mtd": None if _finite(produk_mtd) != _finite(produk_mtd) else round(float(produk_mtd), 2),
        "bersih_mtd": None if _finite(bersih_mtd) != _finite(bersih_mtd) else round(float(bersih_mtd), 2),
        "iklan_tercatat": int(iklan_tercatat or 0),
        "realisasi_biaya_hari": (
            None if _finite(realisasi_biaya_hari) != _finite(realisasi_biaya_hari)
            else round(float(realisasi_biaya_hari), 2)
        ),
        "analisa": analisa,
    }


def record_daily_checkpoint(
    campaign: dict,
    *,
    report_date: date | None,
    rows: pd.DataFrame,
    toko: dict | None = None,
) -> tuple[dict, bool]:
    """Simpan/timpa checkpoint harian per iklan + ringkasan toko di campaign['pantau_harian']."""
    if report_date is None or rows is None or (isinstance(rows, pd.DataFrame) and rows.empty):
        return campaign, False
    day = report_date.isoformat()
    items = []
    for _, r in rows.iterrows():
        key = str(r.get("_key") or "")
        if not key:
            continue
        biaya = float(r.get("Biaya sejak disimpan") or 0)
        omzet = float(r.get("Omzet iklan sejak disimpan") or 0)
        month = r.get("Biaya bulan ini/hari")
        month_v = float(month) if month == month and month is not None else None
        hari = int(r.get("Hari dievaluasi") or 0)
        if hari <= 0:
            rate = float(r.get("Biaya aktual/hari") or 0)
            if rate > 0 and biaya > 0:
                hari = max(int(round(biaya / rate)), 1)
        items.append({
            "key": key,
            "iklan": str(r.get("Iklan") or key),
            "biaya": round(biaya, 2),
            "omzet": round(omzet, 2),
            "roas": round(omzet / biaya, 4) if biaya > 0 else None,
            "biaya_hari": round(float(r.get("Biaya aktual/hari") or 0), 2),
            "biaya_bulan_hari": round(month_v, 2) if month_v is not None else None,
            "budget_plan": round(float(r.get("Budget usulan/hari") or 0), 2),
            "budget_setup": round(float(r.get("Budget efektif Shopee/hari") or 0), 2),
            "hari": hari,
            "tindakan": str(r.get("Tindakan") or ""),
        })
    # Lengkapi toko dari agregat items bila pemanggil belum mengisi budget/biaya/omzet
    snap = dict(toko or {})
    if items:
        snap.setdefault("budget_plan_hari", round(sum(float(it["budget_plan"]) for it in items), 2))
        snap.setdefault("budget_actual_hari", round(sum(float(it["budget_setup"]) for it in items), 2))
        snap.setdefault("biaya_sejak", round(sum(float(it["biaya"]) for it in items), 2))
        snap.setdefault("omzet_kotor_sejak", round(sum(float(it["omzet"]) for it in items), 2))
        snap.setdefault("iklan_tercatat", len(items))
    log = list(campaign.get("pantau_harian") or [])
    # Realisasi hari itu = kenaikan biaya kumulatif vs catatan Pantau sebelumnya (bukan budget setup SC)
    if snap.get("realisasi_biaya_hari") is None and snap.get("biaya_sejak") is not None:
        prev_other = [
            e for e in log
            if str(e.get("tanggal") or "")[:10] < day and (e.get("toko") or e.get("items"))
        ]
        if prev_other:
            prev_e = sorted(prev_other, key=lambda e: str(e.get("tanggal") or ""))[-1]
            prev_toko = prev_e.get("toko") or {}
            prev_biaya = prev_toko.get("biaya_sejak")
            if prev_biaya is None:
                prev_items = list(prev_e.get("items") or [])
                prev_biaya = sum(float(it.get("biaya") or 0) for it in prev_items)
            snap["realisasi_biaya_hari"] = round(float(snap["biaya_sejak"]) - float(prev_biaya or 0), 2)
    if not snap.get("analisa"):
        snap["analisa"] = day_decision_note(
            plan_hari=_finite(snap.get("budget_plan_hari"), 0.0),
            realisasi_hari=_finite(snap.get("realisasi_biaya_hari")),
            biaya_sejak=_finite(snap.get("biaya_sejak"), 0.0),
            sales_iklan=_finite(snap.get("omzet_kotor_sejak"), 0.0),
            sales_all=_finite(snap.get("produk_sejak")),
            target_roas=float((campaign.get("setelan") or {}).get("roas") or 0),
        )
    entry = {"tanggal": day, "items": items, "toko": snap}
    prev = next((e for e in log if str(e.get("tanggal") or "")[:10] == day), None)
    if prev is not None and prev.get("items") == items and (prev.get("toko") or {}) == snap:
        return campaign, False
    log = [e for e in log if str(e.get("tanggal") or "")[:10] != day]
    log.append(entry)
    log = sorted(log, key=lambda e: str(e.get("tanggal") or ""))[-60:]
    return {**campaign, "pantau_harian": log}, True


def daily_history_for(campaign: dict, key: str, *, baseline_row: dict | None = None,
                      today_row: dict | None = None) -> pd.DataFrame:
    """Riwayat evaluasi campaign per tanggal catatan Pantau (bukan buku harian Shopee).

    Kolom:
    - Budget di rencana/Shopee = yang diset di campaign (bukan uang terpakai)
    - Naik sejak catatan lalu = selisih total kumulatif vs baris sebelumnya (bisa > 1 hari laporan)
    - Total sejak campaign = akumulasi sejak campaign disimpan
    - Rata-rata biaya/hari = total ÷ hari evaluasi (bukan sama dengan kolom naik)
    """
    raw: list[dict] = []
    for entry in campaign.get("pantau_harian") or []:
        day = str(entry.get("tanggal") or "")[:10]
        for it in entry.get("items") or []:
            if str(it.get("key")) != str(key):
                continue
            month = it.get("biaya_bulan_hari")
            hari = int(it.get("hari") or 0)
            biaya_v = float(it.get("biaya") or 0)
            rate = float(it.get("biaya_hari") or 0)
            if hari <= 0 and rate > 0 and biaya_v > 0:
                hari = max(int(round(biaya_v / rate)), 1)
            raw.append({
                "tanggal": day,
                "biaya": biaya_v,
                "omzet": float(it.get("omzet") or 0),
                "roas": it.get("roas"),
                "biaya_hari": rate,
                "biaya_bulan_hari": float(month) if month is not None and month == month else float("nan"),
                "budget_plan": float(it.get("budget_plan") or 0),
                "budget_setup": float(it.get("budget_setup") or 0),
                "hari": hari,
                "tindakan": str(it.get("tindakan") or ""),
            })
    if not raw and baseline_row is not None:
        raw.append({
            "tanggal": str(baseline_row.get("tanggal") or "baseline")[:10],
            "biaya": 0.0, "omzet": 0.0, "roas": None, "biaya_hari": 0.0,
            "biaya_bulan_hari": float("nan"),
            "budget_plan": float(baseline_row.get("budget_plan") or 0),
            "budget_setup": float(baseline_row.get("budget_setup") or 0),
            "hari": 0,
            "tindakan": "titik awal campaign",
        })
    if today_row is not None:
        day = str(today_row.get("tanggal") or "")[:10]
        if day and not any(r["tanggal"] == day for r in raw):
            month = today_row.get("biaya_bulan_hari")
            biaya_v = float(today_row.get("biaya") or 0)
            rate = float(today_row.get("biaya_hari") or 0)
            hari = int(today_row.get("hari") or 0)
            if hari <= 0 and rate > 0 and biaya_v > 0:
                hari = max(int(round(biaya_v / rate)), 1)
            raw.append({
                "tanggal": day or "hari ini",
                "biaya": biaya_v,
                "omzet": float(today_row.get("omzet") or 0),
                "roas": today_row.get("roas"),
                "biaya_hari": rate,
                "biaya_bulan_hari": float(month) if month is not None and month == month else float("nan"),
                "budget_plan": float(today_row.get("budget_plan") or 0),
                "budget_setup": float(today_row.get("budget_setup") or 0),
                "hari": hari,
                "tindakan": str(today_row.get("tindakan") or ""),
            })
    raw = sorted(raw, key=lambda r: str(r.get("tanggal") or ""))
    rows = []
    prev = None
    for item in raw:
        biaya = float(item["biaya"])
        omzet = float(item["omzet"])
        hari = int(item.get("hari") or 0)
        if prev is None:
            add_biaya = float("nan")
            add_omzet = float("nan")
            add_hari = float("nan")
        else:
            add_biaya = biaya - float(prev["biaya"])
            add_omzet = omzet - float(prev["omzet"])
            prev_hari = int(prev.get("hari") or 0)
            add_hari = float(hari - prev_hari) if hari > 0 and prev_hari > 0 else float("nan")
        roas = item.get("roas")
        rows.append({
            "Tanggal catatan Pantau": item["tanggal"],
            "Hari laporan sejak campaign": hari if hari > 0 else float("nan"),
            "Budget di rencana/hari": float(item["budget_plan"]),
            "Budget di Shopee/hari": float(item["budget_setup"]),
            "Naik biaya sejak catatan lalu": add_biaya,
            "Naik omzet sejak catatan lalu": add_omzet,
            "Hari laporan di antara catatan": add_hari,
            "Total biaya sejak campaign": biaya,
            "Total omzet sejak campaign": omzet,
            "ROAS sejak campaign": float(roas) if roas is not None and roas == roas else float("nan"),
            "Rata-rata biaya/hari sejak campaign": float(item["biaya_hari"]),
            "Rata-rata biaya/hari bulan ini": float(item["biaya_bulan_hari"]),
            "Saran saat itu": item["tindakan"],
        })
        prev = item
    return pd.DataFrame(rows)


_MEMBER_RANK = {
    "Sudah diiklankan di tempat lain": 0,
    "Tidak perlu di-setup": 1,
    "Keluarkan dari grup": 2,
    "Kurangi porsi / tinjau": 3,
    "Pisahkan jadi iklan tunggal": 4,
    "Layak di-setup di grup ini": 5,
    "Pertahankan di grup": 6,
}

_TAKEOUT = {"Keluarkan dari grup", "Sudah diiklankan di tempat lain"}

# Grup belum setup: tampilkan dulu yang masih perlu keputusan setup (layak), baru yang tidak perlu / sudah di tempat lain.
_MEMBER_RANK_SETUP = {
    "Layak di-setup di grup ini": 0,
    "Tidak perlu di-setup": 1,
    "Sudah diiklankan di tempat lain": 2,
}


def _member_unit_slice(members: pd.DataFrame, group_key: str) -> pd.DataFrame:
    key = str(group_key)
    work = members.loc[members["unit"].astype(str) == key]
    if not work.empty:
        return work
    tail = key.split(":", 1)[-1].strip().lower()
    return members.loc[
        members["unit"].astype(str).str.startswith("grup:")
        & members["unit"].astype(str).str.lower().str.endswith(tail)
    ]


def _elsewhere_for_codes(
    members: pd.DataFrame | None,
    units,
    *,
    group_key: str,
    codes: set[str],
) -> dict[str, list[dict]]:
    """Iklan lain (tunggal/grup) yang memuat kode produk yang sama dan sedang berbiaya / berjalan."""
    out: dict[str, list[dict]] = {c: [] for c in codes}
    if not codes:
        return out
    by_unit = {getattr(u, "key", ""): u for u in (units or [])}
    # Unit produk tunggal langsung dari daftar unit (berjalan / masih berbiaya / ada omzet)
    for code in codes:
        for prefix in ("produk:", "pisah:", "baru:"):
            ukey = f"{prefix}{code}"
            unit = by_unit.get(ukey)
            if unit is None:
                continue
            biaya_u = float(getattr(unit, "daily_cost", 0) or 0)
            omzet_u = float(getattr(unit, "daily_sales", 0) or 0)
            running = bool(A._running(unit))
            if not running and biaya_u <= 0 and omzet_u <= 0:
                continue
            out[code].append({
                "unit": ukey,
                "nama": str(getattr(unit, "nama", "") or ukey),
                "jenis": "Produk tunggal",
                "biaya": biaya_u,
                "omzet": omzet_u,
            })
    # Cadangan: unit tunggal yang members-nya memuat kode (nama kunci tidak selalu = kode)
    for unit in (units or []):
        ukey = str(getattr(unit, "key", "") or "")
        if not ukey.startswith(("produk:", "pisah:", "baru:")):
            continue
        biaya_u = float(getattr(unit, "daily_cost", 0) or 0)
        omzet_u = float(getattr(unit, "daily_sales", 0) or 0)
        if not A._running(unit) and biaya_u <= 0 and omzet_u <= 0:
            continue
        for code in getattr(unit, "members", None) or []:
            c = str(code)
            if c not in codes:
                continue
            if any(x["unit"] == ukey for x in out.get(c, [])):
                continue
            out.setdefault(c, []).append({
                "unit": ukey,
                "nama": str(getattr(unit, "nama", "") or ukey),
                "jenis": "Produk tunggal",
                "biaya": biaya_u,
                "omzet": omzet_u,
            })
    if members is None or getattr(members, "empty", True):
        return out
    need = {"unit", "periode", "product_code", "biaya", "omzet"}
    if not need <= set(members.columns):
        return out
    other = members.loc[
        members["product_code"].astype(str).isin(codes)
        & (members["unit"].astype(str) != str(group_key))
        & (members["unit"].astype(str) != "auto")
    ]
    if other.empty:
        return out
    latest = other.loc[other["periode"] == other.groupby("unit")["periode"].transform("max")]
    for r in latest.itertuples(index=False):
        code = str(r.product_code)
        ukey = str(r.unit)
        if ukey.startswith(("produk:", "pisah:", "baru:")):
            continue  # sudah dari units
        biaya = float(r.biaya or 0)
        omzet = float(r.omzet or 0)
        unit = by_unit.get(ukey)
        running = bool(unit is not None and A._running(unit) and float(getattr(unit, "daily_cost", 0) or 0) > 0)
        if not running and biaya <= 0 and omzet <= 0:
            continue
        nama = str(getattr(unit, "nama", "") or ukey.split(":", 1)[-1])
        # hindari duplikat unit
        if any(x["unit"] == ukey for x in out.get(code, [])):
            continue
        out.setdefault(code, []).append({
            "unit": ukey,
            "nama": nama,
            "jenis": "Grup" if ukey.startswith("grup:") else "Iklan lain",
            "biaya": biaya if biaya > 0 else float(getattr(unit, "daily_cost", 0) or 0),
            "omzet": omzet if omzet > 0 else float(getattr(unit, "daily_sales", 0) or 0),
        })
    return out


def _num_cell(row, *names: str) -> float:
    for name in names:
        if name in getattr(row, "index", []) or (hasattr(row, "__contains__") and name in row):
            try:
                val = row[name]
            except Exception:
                continue
            if val is not None and val == val:
                try:
                    return float(val)
                except (TypeError, ValueError):
                    continue
    return float("nan")


def _product_signal(products: pd.DataFrame | None, code: str) -> dict:
    """Sinyal produk + triad stok Site 10037 (toko) / 10062 (DC Cikupa) / 10036 (DC Cipeucang)."""
    empty = {
        "omzet_harian": float("nan"), "qty_harian": float("nan"),
        "stok": float("nan"), "stok_room": float("nan"), "nama": "",
        "stok_10037": float("nan"), "stok_10062": float("nan"), "stok_10036": float("nan"),
    }
    if products is None or getattr(products, "empty", True) or "product_code" not in products.columns:
        return empty
    hit = products.loc[products["product_code"].astype(str) == str(code)]
    if hit.empty:
        return empty
    row = hit.iloc[0]
    s37 = _num_cell(row, "stok_10037", "stok")
    s62 = _num_cell(row, "stok_10062")
    s36 = _num_cell(row, "stok_10036")
    return {
        "omzet_harian": _num_cell(row, "omzet_harian"),
        "qty_harian": _num_cell(row, "qty_harian"),
        "stok": s37,
        "stok_room": _num_cell(row, "stok_room"),
        "nama": str(row["nama"]) if "nama" in hit.columns else "",
        "stok_10037": s37,
        "stok_10062": s62,
        "stok_10036": s36,
    }


def stock_sites_text(sig: dict | None, *, short: bool = False) -> str:
    """Teks stok 10037/10062/10036 untuk kartu & saran kelayakan iklan."""
    if not sig:
        return "Stok 10037/10062/10036: belum ada data"
    def _u(v: float) -> str:
        if v != v:
            return "–"
        return f"{v:,.0f}".replace(",", ".")

    s37, s62, s36 = sig.get("stok_10037", float("nan")), sig.get("stok_10062", float("nan")), sig.get("stok_10036", float("nan"))
    if short:
        return f"10037 {_u(s37)} · 10062 {_u(s62)} · 10036 {_u(s36)}"
    return f"Stok Site 10037 {_u(s37)} · Site 10062 {_u(s62)} · Site 10036 {_u(s36)}"


def stock_worthiness(sig: dict | None) -> tuple[str, str]:
    """(status, penjelasan singkat) kelayakan iklan dari triad stok harian.

    status: ada_toko | isi_dari_dc | kosong | belum_data
    """
    if not sig:
        return "belum_data", "Stok 10037/10062/10036 belum terbaca — unggah Data stok harian."
    s37 = sig.get("stok_10037", float("nan"))
    s62 = sig.get("stok_10062", float("nan"))
    s36 = sig.get("stok_10036", float("nan"))
    if s37 != s37 and s62 != s62 and s36 != s36:
        return "belum_data", "Stok 10037/10062/10036 belum terbaca — unggah Data stok harian."
    toko = s37 if s37 == s37 else 0.0
    dc = (s62 if s62 == s62 else 0.0) + (s36 if s36 == s36 else 0.0)
    if toko > 0:
        return "ada_toko", f"{stock_sites_text(sig, short=True)} — stok toko ada, iklan bisa jalan."
    if dc > 0:
        return "isi_dari_dc", (
            f"{stock_sites_text(sig, short=True)} — toko kosong, tetapi DC ada. "
            "Restock/TR dulu ke Site 10037 sebelum naikkan budget iklan."
        )
    return "kosong", (
        f"{stock_sites_text(sig, short=True)} — toko & DC kosong. "
        "Iklan tidak layak diaktifkan sampai ada stok."
    )


def codes_for_ad_key(key: str, units=None, members: pd.DataFrame | None = None) -> list[str]:
    """Kode produk yang terkait satu kunci iklan (tunggal / anggota grup)."""
    k = str(key or "")
    if k.startswith(("produk:", "pisah:", "baru:")):
        return [k.split(":", 1)[1]]
    if units:
        for u in units:
            if getattr(u, "key", "") == k and getattr(u, "members", None):
                return [str(c) for c in u.members]
    if members is not None and not getattr(members, "empty", True) and k.startswith("grup:"):
        work = _member_unit_slice(members, k)
        if not work.empty and "product_code" in work.columns:
            return sorted({str(c) for c in work["product_code"].astype(str) if c and c != "nan"})
    return []


def stock_summary_for_ad(
    products: pd.DataFrame | None,
    key: str,
    *,
    units=None,
    members: pd.DataFrame | None = None,
) -> dict:
    """Ringkasan triad stok untuk satu iklan (agregat anggota bila grup)."""
    codes = codes_for_ad_key(key, units=units, members=members)
    if not codes:
        return {
            "stok_10037": float("nan"), "stok_10062": float("nan"), "stok_10036": float("nan"),
            "status": "belum_data", "teks": "Stok 10037/10062/10036: belum terpetakan ke produk",
            "n": 0, "kosong": 0, "dc_only": 0,
        }
    s37 = s62 = s36 = 0.0
    known37 = known62 = known36 = False
    kosong = dc_only = 0
    for code in codes:
        sig = _product_signal(products, code)
        st, _ = stock_worthiness(sig)
        if st == "kosong":
            kosong += 1
        elif st == "isi_dari_dc":
            dc_only += 1
        if sig["stok_10037"] == sig["stok_10037"]:
            s37 += sig["stok_10037"]; known37 = True
        if sig["stok_10062"] == sig["stok_10062"]:
            s62 += sig["stok_10062"]; known62 = True
        if sig["stok_10036"] == sig["stok_10036"]:
            s36 += sig["stok_10036"]; known36 = True
    sig = {
        "stok_10037": s37 if known37 else float("nan"),
        "stok_10062": s62 if known62 else float("nan"),
        "stok_10036": s36 if known36 else float("nan"),
    }
    status, _tip = stock_worthiness(sig)
    bits = [stock_sites_text(sig, short=False)]
    if len(codes) > 1:
        bits.append(f"{len(codes)} produk")
        if kosong:
            bits.append(f"{kosong} kosong total")
        if dc_only:
            bits.append(f"{dc_only} hanya ada di DC")
    return {
        **sig, "status": status, "teks": " · ".join(bits),
        "n": len(codes), "kosong": kosong, "dc_only": dc_only,
    }


def _hist_perf_for_code(work: pd.DataFrame, code: str) -> tuple[float, float, float]:
    """Rata-rata biaya/omzet/ROAS historis saat produk pernah berbiaya di grup ini (campaign sebelumnya)."""
    part = work.loc[work["product_code"].astype(str) == str(code)]
    if part.empty:
        return 0.0, 0.0, float("nan")
    active = part.loc[(part["biaya"].fillna(0) > 0) | (part["omzet"].fillna(0) > 0)]
    use = active if not active.empty else part
    biaya = float(use["biaya"].mean() or 0)
    omzet = float(use["omzet"].mean() or 0)
    roas = omzet / biaya if biaya > 0 else float("nan")
    return biaya, omzet, roas


def group_members_review(
    members: pd.DataFrame | None,
    group_key: str,
    *,
    target_roas: float,
    contribution: dict[str, float] | None = None,
    group_active: bool = True,
    units=None,
    products: pd.DataFrame | None = None,
    planned_singles: set[str] | frozenset | None = None,
) -> pd.DataFrame:
    """Performa + saran tiap produk di dalam satu iklan grup.

    - Grup aktif: evaluasi biaya/omzet periode terakhir; jika sudah jadi iklan tunggal → keluarkan
      (prioritas di atas turunkan budget grup).
    - Grup belum di-setup: urut Layak → Tidak perlu → Sudah di tempat lain. Layak hanya bila
      prediksi mendorong target (batas 95% sales toko / qty laku) atau histori ROAS kuat + stok toko;
      saran menjelaskan kenapa harus diiklankan.

    Angka Biaya/Omzet di tabel = laporan iklan grup periode terakhir (bukan rata-rata kartu campaign).
    """
    cols = [
        "Produk", "Kode produk",
        "Stok 10037", "Stok 10062", "Stok 10036",
        "Prediksi omzet/hari", "Biaya di grup/hari", "Omzet di grup/hari", "ROAS di grup",
        "Porsi omzet grup", "Porsi biaya grup", "Iklan lain", "Tindakan", "Saran",
    ]
    if members is None or getattr(members, "empty", True) or not group_key:
        return pd.DataFrame(columns=cols)
    key = str(group_key)
    if not key.startswith("grup:"):
        return pd.DataFrame(columns=cols)
    need = {"unit", "periode", "product_code", "nama", "biaya", "omzet"}
    if not need <= set(members.columns):
        return pd.DataFrame(columns=cols)
    work = _member_unit_slice(members, key)
    if work.empty:
        return pd.DataFrame(columns=cols)
    latest = str(sorted(work["periode"].astype(str).unique())[-1])
    part = (
        work.loc[work["periode"].astype(str) == latest]
        .groupby("product_code", as_index=False)
        .agg(nama=("nama", "last"), biaya=("biaya", "mean"), omzet=("omzet", "mean"))
    )
    if part.empty:
        return pd.DataFrame(columns=cols)
    # Bila periode terakhir semua nol (grup belum setup), pakai histori berbiaya bila ada
    if float(part["biaya"].sum()) <= 0 and float(part["omzet"].sum()) <= 0:
        hist_rows = []
        for code in part["product_code"].astype(str):
            b, o, _ = _hist_perf_for_code(work, code)
            nama = str(part.loc[part["product_code"].astype(str) == code, "nama"].iloc[0])
            hist_rows.append({"product_code": code, "nama": nama, "biaya": b, "omzet": o})
        if any(r["biaya"] > 0 or r["omzet"] > 0 for r in hist_rows):
            part = pd.DataFrame(hist_rows)

    total_omzet = float(part["omzet"].sum())
    total_biaya = float(part["biaya"].sum())
    group_roas = total_omzet / total_biaya if total_biaya > 0 else float("nan")
    contrib = contribution or {}
    codes = set(part["product_code"].astype(str))
    elsewhere = _elsewhere_for_codes(members, units, group_key=key, codes=codes)
    planned = {str(c) for c in (planned_singles or set())}
    sales_floor, qty_floor = A.potential_floors(products) if products is not None else (0.0, float("inf"))
    rows = []
    for r in part.itertuples(index=False):
        code = str(r.product_code)
        biaya = float(r.biaya or 0)
        omzet = float(r.omzet or 0)
        roas = omzet / biaya if biaya > 0 else float("nan")
        share_o = omzet / total_omzet if total_omzet > 0 else 0.0
        share_c = biaya / total_biaya if total_biaya > 0 else 0.0
        margin = contrib.get(code)
        alts = list(elsewhere.get(code) or [])
        if code in planned and not any(a.get("jenis") == "Di rencana campaign" for a in alts):
            alts.append({
                "unit": f"pisah:{code}",
                "nama": "Iklan tunggal di rencana campaign",
                "jenis": "Di rencana campaign",
                "biaya": 0.0,
                "omzet": 0.0,
            })
        alt_label = "; ".join(
            f"{a['nama']} ({a['jenis']}"
            + (f", {_rp_hari(a['biaya'])}" if a.get("biaya") else "")
            + ")"
            for a in alts[:3]
        ) if alts else "–"

        sig = _product_signal(products, code)
        stock_status, stock_tip = stock_worthiness(sig)
        demand = sig["omzet_harian"]
        qty_day = sig["qty_harian"]
        demand_v = demand if demand == demand else 0.0
        qty_v = qty_day if qty_day == qty_day else 0.0
        pushes_target = (
            (sales_floor > 0 and demand_v >= sales_floor)
            or (qty_floor < float("inf") and qty_v >= qty_floor)
        )

        if not group_active:
            # Mode belum di-setup: jangan bilang "pertahankan" — bandingkan setup & kelayakan
            if alts:
                act = "Sudah diiklankan di tempat lain"
                tip = (
                    f"Sudah aktif di: {alt_label}. "
                    "Jangan masukkan lagi ke grup ini agar budget tidak dobel. "
                    + stock_tip
                )
            else:
                hist_b, hist_o, hist_roas = _hist_perf_for_code(work, code)
                strong_hist = (
                    hist_b > 0
                    and hist_o > 0
                    and hist_roas == hist_roas
                    and target_roas > 0
                    and hist_roas >= target_roas * 0.8
                )
                ok_hist = (
                    hist_o > 0
                    and (
                        hist_roas != hist_roas
                        or hist_roas >= max(target_roas * 0.5, 1.0)
                    )
                )
                if margin is not None and margin <= 0:
                    act = "Tidak perlu di-setup"
                    tip = (
                        "Margin kotor di bawah potongan Shopee — rugi bila diiklankan. "
                        "Jangan masukkan ke grup baru. " + stock_tip
                    )
                elif stock_status == "kosong":
                    act = "Tidak perlu di-setup"
                    tip = stock_tip
                elif hist_b > 0 and hist_o <= 0:
                    act = "Tidak perlu di-setup"
                    tip = (
                        f"Di campaign/grup sebelumnya berbiaya {_rp_hari(hist_b)} tanpa omzet. "
                        "Jangan ikut di-setup di grup ini. " + stock_tip
                    )
                elif hist_b > 0 and hist_roas == hist_roas and target_roas > 0 and hist_roas < target_roas * 0.5:
                    act = "Tidak perlu di-setup"
                    tip = (
                        f"Histori di grup ini ROAS {hist_roas:.1f}× jauh di bawah target {target_roas:.1f}×. "
                        "Tidak layak di-setup ulang di grup ini. " + stock_tip
                    )
                elif stock_status == "isi_dari_dc":
                    act = "Tidak perlu di-setup"
                    tip = (
                        stock_tip
                        + " Setelah stok masuk Site 10037, baru masukkan ke grup."
                    )
                elif not pushes_target and not strong_hist:
                    # Prediksi tidak mendorong target → tidak perlu setup
                    floor_txt = (
                        f"≥ {_rp_hari(sales_floor)} (produk pembentuk 95% sales toko)"
                        if sales_floor > 0 else "batas sales toko"
                    )
                    qty_txt = (
                        f" atau ≥ {qty_floor:.1f} unit/hari".replace(".", ",")
                        if qty_floor < float("inf") else ""
                    )
                    tip = (
                        f"Prediksi sales {_rp_hari(demand_v)}"
                        + (f" ({qty_v:.1f} unit/hari)".replace(".", ",") if qty_v > 0 else "")
                        + f" di bawah batas kejar target ({floor_txt}{qty_txt}). "
                        "Tidak mendorong target — tidak perlu di-setup di grup ini. "
                        + stock_tip
                    )
                    act = "Tidak perlu di-setup"
                elif stock_status == "ada_toko" and (pushes_target or strong_hist or ok_hist):
                    act = "Layak di-setup di grup ini"
                    why = ["belum diiklankan di tempat lain"]
                    if pushes_target:
                        why.append(
                            f"prediksi sales {_rp_hari(demand_v)}"
                            + (f" / {qty_v:.1f} unit".replace(".", ",") if qty_v > 0 else "")
                            + " mendorong target"
                            + (f" (≥ {_rp_hari(sales_floor)} = 95% sales toko)" if sales_floor > 0 else "")
                        )
                    if strong_hist or (ok_hist and hist_roas == hist_roas and hist_b > 0):
                        why.append(
                            f"histori di grup ini ROAS {hist_roas:.1f}×"
                            + (f" vs target {target_roas:.1f}×" if target_roas > 0 else "")
                            + f" (biaya {_rp_hari(hist_b)} → omzet {_rp_hari(hist_o)})"
                        )
                    elif ok_hist and hist_o > 0:
                        why.append(f"pernah menghasilkan omzet iklan {_rp_hari(hist_o)} di grup ini")
                    why.append(stock_sites_text(sig, short=True) + " — stok toko ada")
                    tip = (
                        "Kenapa harus diiklankan: " + "; ".join(why) + ". "
                        "Masukkan produk ini saat grup diaktifkan di Seller Center."
                    )
                else:
                    act = "Tidak perlu di-setup"
                    tip = (
                        "Belum ada bukti kuat (prediksi mendorong target / histori ROAS / stok toko) "
                        "bahwa produk ini layak ikut grup baru. Tunda dulu; fokus ke item yang sudah jelas. "
                        + stock_tip
                    )
        elif alts:
            # Sudah jadi iklan tunggal / di tempat lain → selalu keluarkan dari grup (meski masih berbiaya di sini)
            if biaya > 0 or omzet > 0:
                act = "Keluarkan dari grup"
                tip = (
                    f"Sudah diiklankan di tempat lain: {alt_label}. "
                    f"Masih berbiaya di grup ini {_rp_hari(biaya)}"
                    + (f" / omzet {_rp_hari(omzet)}" if omzet > 0 else " tanpa omzet di grup")
                    + ". Keluarkan dari grup agar budget tidak dobel — kelola di iklan tunggalnya. "
                    + stock_tip
                )
            else:
                act = "Sudah diiklankan di tempat lain"
                tip = (
                    f"Sudah aktif di: {alt_label}. "
                    "Di grup ini belum berbiaya — keluarkan agar tidak ikut terisi lagi. "
                    + stock_tip
                )
        elif stock_status == "kosong" and biaya > 0:
            act = "Keluarkan dari grup"
            tip = (
                f"Masih berbiaya {_rp_hari(biaya)} padahal {stock_tip} "
                "Keluarkan dari grup / jeda sampai ada stok."
            )
        elif biaya > 0 and omzet <= 0:
            act = "Keluarkan dari grup"
            tip = (
                f"Ada biaya {_rp_hari(biaya)} tanpa omzet di laporan terakhir. "
                "Keluarkan dari grup agar tidak menyerap budget anggota lain. " + stock_tip
            )
        elif margin is not None and margin <= 0 and biaya > 0:
            act = "Keluarkan dari grup"
            tip = (
                "Margin kotor di bawah potongan Shopee (rugi per unit) tetapi masih berbiaya di grup. "
                "Keluarkan dari grup. " + stock_tip
            )
        elif (
            biaya > 0
            and roas == roas
            and (
                (target_roas > 0 and roas < target_roas * 0.5)
                or (group_roas == group_roas and roas < group_roas * 0.4)
            )
        ):
            act = "Keluarkan dari grup"
            tip = (
                f"ROAS {roas:.1f}× jauh di bawah "
                + (f"target {target_roas:.1f}×" if target_roas > 0 else "acuan")
                + (f" dan rata-rata grup {group_roas:.1f}×" if group_roas == group_roas else "")
                + f". Porsi biaya {share_c * 100:.0f}% — keluarkan agar grup tidak menopang item lemah. "
                + stock_tip
            )
        elif (
            biaya > 0
            and roas == roas
            and (
                (target_roas > 0 and roas < target_roas * 0.9)
                or (group_roas == group_roas and roas < group_roas * 0.7)
            )
        ):
            act = "Kurangi porsi / tinjau"
            tip = (
                f"ROAS {roas:.1f}× masih lemah vs grup"
                + (f" ({group_roas:.1f}×)" if group_roas == group_roas else "")
                + ". Jangan naikkan budget grup demi item ini; tinjau di Seller Center atau keluarkan bila tetap lemah. "
                + stock_tip
            )
        elif (
            share_o >= 0.3
            and len(part) > 2
            and roas == roas
            and (
                (target_roas > 0 and roas >= target_roas * 0.8)
                or (group_roas == group_roas and roas >= group_roas)
            )
        ):
            act = "Pisahkan jadi iklan tunggal"
            tip = (
                f"Andalan grup ({share_o * 100:.0f}% omzet, ROAS {roas:.1f}×). "
                "Pertimbangkan iklan produk tunggal agar budget & Target ROAS dikendalikan sendiri. "
                + stock_tip
            )
        else:
            act = "Pertahankan di grup"
            if biaya <= 0 and omzet <= 0:
                tip = "Belum ada biaya/omzet di laporan terakhir — belum menyerap budget grup. " + stock_tip
            elif roas == roas:
                tip = (
                    f"ROAS {roas:.1f}× sejalan dengan grup"
                    + (f" ({group_roas:.1f}×)" if group_roas == group_roas else "")
                    + f". Porsi omzet {share_o * 100:.0f}% — aman dilanjutkan di grup. "
                    + stock_tip
                )
            else:
                tip = "Belum cukup data ROAS; pantau lagi setelah laporan berikutnya. " + stock_tip
        rows.append({
            "Produk": str(r.nama or code),
            "Kode produk": code,
            "Stok 10037": sig.get("stok_10037", float("nan")),
            "Stok 10062": sig.get("stok_10062", float("nan")),
            "Stok 10036": sig.get("stok_10036", float("nan")),
            "Prediksi omzet/hari": demand if demand == demand else float("nan"),
            "Biaya di grup/hari": biaya,
            "Omzet di grup/hari": omzet,
            "ROAS di grup": roas,
            "Porsi omzet grup": share_o * 100,
            "Porsi biaya grup": share_c * 100,
            "Iklan lain": alt_label,
            "Tindakan": act,
            "Saran": tip,
        })
    frame = pd.DataFrame(rows, columns=cols)
    if frame.empty:
        return frame
    rank_map = _MEMBER_RANK_SETUP if not group_active else _MEMBER_RANK
    frame["_rank"] = frame["Tindakan"].map(lambda t: rank_map.get(t, 9))
    # Belum setup: dalam blok Layak urut prediksi tertinggi dulu (yang paling mendorong target).
    sort_key = "Prediksi omzet/hari" if not group_active else "Biaya di grup/hari"
    sort_cols = ["_rank", sort_key]
    return (
        frame.sort_values(sort_cols, ascending=[True, False], na_position="last")
        .drop(columns=["_rank"])
        .reset_index(drop=True)
    )


def group_members_summary(member_frame: pd.DataFrame) -> str:
    """Satu kalimat ringkas untuk kartu grup dari hasil `group_members_review`."""
    if member_frame is None or member_frame.empty or "Tindakan" not in member_frame.columns:
        return ""
    acts = member_frame["Tindakan"].astype(str)
    already = int((acts == "Sudah diiklankan di tempat lain").sum())
    skip = int((acts == "Tidak perlu di-setup").sum())
    layak = int((acts == "Layak di-setup di grup ini").sum())
    out = int((acts == "Keluarkan dari grup").sum())
    tinjau = int((acts == "Kurangi porsi / tinjau").sum())
    andalan = int((acts == "Pisahkan jadi iklan tunggal").sum())
    ok = int((acts == "Pertahankan di grup").sum())
    bits = []
    # Urutan sama dengan tabel belum-setup: layak (belum di-setting) dulu.
    if layak:
        bits.append(f"{layak} produk belum di-setup & layak ikut saat grup diaktifkan")
    if skip:
        bits.append(f"{skip} produk tidak perlu di-setup di grup ini")
    if already:
        bits.append(f"{already} produk sudah diiklankan di tempat lain (jangan dobel)")
    if out:
        bits.append(f"{out} produk harus dikeluarkan dari grup dulu")
    if tinjau:
        bits.append(f"{tinjau} produk lemah — jangan naikkan budget grup demi item ini")
    if andalan:
        bits.append(f"{andalan} andalan layak dipertimbangkan jadi iklan tunggal")
    if not bits and ok:
        return f"Isi grup sehat: {ok} produk sejalan dengan performa grup."
    if not bits:
        return ""
    return "Anggota grup: " + "; ".join(bits) + "."


def planned_single_codes(acts_saved: pd.DataFrame | None) -> set[str]:
    """Kode produk yang di campaign sudah dijadwalkan sebagai iklan tunggal (produk:/pisah:/baru:)."""
    out: set[str] = set()
    if acts_saved is None or getattr(acts_saved, "empty", True):
        return out
    key_col = "key" if "key" in acts_saved.columns else ("_key" if "_key" in acts_saved.columns else None)
    if not key_col:
        return out
    for key in acts_saved[key_col].astype(str):
        if key.startswith(("produk:", "pisah:", "baru:")):
            code = key.split(":", 1)[1].strip()
            if code:
                out.add(code)
    return out


def group_card_from_members(
    member_frame: pd.DataFrame,
    *,
    act: str,
    tip: str,
    expected: float = 0.0,
    cost_since: float = 0.0,
    cost_month: float = float("nan"),
) -> tuple[str, str]:
    """Prioritas tindakan kartu grup: keluarkan anggota dulu, baru turunkan/naikkan budget.

    Bila ≥ setengah anggota harus keluar / sudah di tempat lain, jangan hanya bilang 'Turunkan budget'.
    """
    if member_frame is None or member_frame.empty or "Tindakan" not in member_frame.columns:
        return act, tip
    acts = member_frame["Tindakan"].astype(str)
    n = len(acts)
    take = int(acts.isin(_TAKEOUT).sum())
    if n <= 0 or take < max(1, (n + 1) // 2):
        return act, tip
    member_note = group_members_summary(member_frame)
    spend = cost_since
    if cost_month == cost_month and cost_month > spend:
        spend = cost_month
    budget_bit = ""
    if expected > 0 and spend > expected * 1.4:
        budget_bit = (
            f" Setelah anggota dibersihkan, samakan budget grup di SC ke {_rp_hari(expected)} "
            f"(sekarang terpakai ±{_rp_hari(spend)})."
        )
    elif expected <= 0 and spend > 5_000:
        budget_bit = f" Lalu jeda/hentikan grup di SC bila sudah tidak dipakai (terpakai ±{_rp_hari(spend)})."
    new_act = "Keluarkan anggota dari grup"
    new_tip = (
        f"Prioritas: keluarkan {take}/{n} produk dari grup di Seller Center "
        f"(sudah jadi iklan tunggal / menyedot budget tanpa hasil). "
        f"Jangan hanya turunkan budget grup — isi grupnya yang salah. "
        + (member_note + " " if member_note else "")
        + budget_bit
    ).strip()
    return new_act, new_tip


def enrich_group_actions(
    frame: pd.DataFrame,
    members: pd.DataFrame | None,
    *,
    target_roas: float,
    units=None,
    products: pd.DataFrame | None = None,
    contribution: dict | None = None,
    planned_singles: set[str] | frozenset | None = None,
) -> pd.DataFrame:
    """Timpa Tindakan/Saran baris grup bila mayoritas anggota harus dikeluarkan."""
    if frame is None or frame.empty or "_key" not in frame.columns:
        return frame if frame is not None else pd.DataFrame()
    out = frame.copy()
    tips, acts = [], []
    for _, r in out.iterrows():
        key = str(r.get("_key") or "")
        act = str(r.get("Tindakan") or "")
        tip = str(r.get("Saran") or "")
        is_group = key.startswith("grup:") or str(r.get("Jenis") or "").lower().startswith("grup")
        if not is_group:
            tips.append(tip)
            acts.append(act)
            continue
        cost = float(r.get("Biaya aktual/hari") or r.get("Terpakai sejak campaign/hari") or 0)
        month = r.get("Biaya bulan ini/hari")
        month_v = float(month) if month == month and month is not None else float("nan")
        expected = float(r.get("Budget efektif Shopee/hari") or r.get("Budget di Shopee/hari") or 0)
        group_active = not (
            act == "Buat / aktifkan"
            or (cost <= 5_000 and (month_v != month_v or month_v <= 5_000)
                and float(r.get("Omzet iklan sejak disimpan") or 0) <= 0)
        )
        mem = group_members_review(
            members, key, target_roas=target_roas, contribution=contribution,
            group_active=group_active, units=units, products=products,
            planned_singles=planned_singles,
        )
        new_act, new_tip = group_card_from_members(
            mem, act=act, tip=tip, expected=expected, cost_since=cost, cost_month=month_v,
        )
        # Hindari dobel ringkasan anggota bila tip sudah dari override
        if new_act == act and group_members_summary(mem):
            note = group_members_summary(mem)
            if note and note not in tip:
                new_tip = f"{tip} {note}".strip()
        tips.append(new_tip)
        acts.append(new_act)
    out["Saran"] = tips
    out["Tindakan"] = acts
    if "_rank" in out.columns:
        out = out.drop(columns=["_rank"])
    out["_rank"] = out["Tindakan"].map(lambda t: _STATUS_RANK.get(t, 9))
    cost_col = (
        "Biaya aktual/hari" if "Biaya aktual/hari" in out.columns
        else ("Terpakai sejak campaign/hari" if "Terpakai sejak campaign/hari" in out.columns else None)
    )
    if cost_col:
        return out.sort_values(["_rank", cost_col], ascending=[True, False], na_position="last").drop(columns=["_rank"])
    return out.sort_values(["_rank"], ascending=[True], na_position="last").drop(columns=["_rank"])


def attach_month_daily(frame: pd.DataFrame, current: dict[str, dict] | None) -> pd.DataFrame:
    """Tambah `Biaya bulan ini/hari` = total biaya laporan bulan berjalan ÷ hari laporan.

    Berbeda dari `Biaya aktual/hari` (rata-rata sejak campaign disimpan)."""
    if frame is None or frame.empty:
        return frame if frame is not None else pd.DataFrame()
    out = frame.copy()
    cur_map = current or {}

    def lookup(key: str) -> dict | None:
        if key in cur_map:
            return cur_map[key]
        tail = key.split(":", 1)[-1]
        for k, v in cur_map.items():
            if str(k).split(":", 1)[-1] == tail:
                return v
        return None

    existing = (
        pd.to_numeric(out["Biaya bulan ini/hari"], errors="coerce")
        if "Biaya bulan ini/hari" in out.columns else None
    )
    vals = []
    keys = list(out["_key"].astype(str)) if "_key" in out.columns else []
    for i, key in enumerate(keys):
        if existing is not None and pd.notna(existing.iloc[i]):
            vals.append(float(existing.iloc[i]))
            continue
        cur = lookup(str(key))
        days = int((cur or {}).get("hari") or 0)
        vals.append(float(cur["biaya"]) / days if cur and days > 0 else float("nan"))
    if "_key" in out.columns:
        out["Biaya bulan ini/hari"] = vals
    return out


def rename_budget_triad(frame: pd.DataFrame) -> pd.DataFrame:
    """Label baku untuk tabel unduhan."""
    if frame is None or frame.empty:
        return frame if frame is not None else pd.DataFrame()
    out = frame.copy()
    rename = {
        "Budget usulan/hari": "Budget di rencana/hari",
        "Budget efektif Shopee/hari": "Budget di Shopee/hari",
        "Biaya bulan ini/hari": "Terpakai bulan ini/hari",
        "Biaya aktual/hari": "Terpakai sejak campaign/hari",
    }
    return out.rename(columns={k: v for k, v in rename.items() if k in out.columns})
