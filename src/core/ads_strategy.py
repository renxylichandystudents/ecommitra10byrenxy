"""Strategi iklan Shopee untuk mengejar target penjualan: iklan grup & iklan produk tunggal.

Data: laporan iklan grup (baris grup diikuti baris produk anggotanya, per bulan), laporan iklan keseluruhan (iklan produk
tunggal & otomatis), File margin (margin kotor per SKU), parameter biaya Shopee, dan stok/prediksi per SKU.

Per unit iklan (grup / produk tunggal / otomatis):
- Kurva respons omzet harian  s(c) = a · ln(1 + c / b)  (hasil berkurang): b = median biaya harian unit, a = kuadrat terkecil
  dari riwayat bulanan (biaya, omzet per hari). Bila riwayat < 2 bulan berbiaya, a dikalibrasi dari ROAS terakhir.
  ROAS marginal pada biaya c = a / (b + c).
- Kontribusi sebelum iklan (% omzet) = margin kotor (File margin) − potongan Shopee, rata-rata tertimbang omzet anggota.
  ROAS impas = 1 ÷ kontribusi (di bawahnya, Rp 1 iklan menghasilkan margin < Rp 1).

Tiga strategi (alokasi serakah kenaikan Rp per hari ke unit dengan ROAS marginal tertinggi, berhenti di batas ROAS):
- Efisien     : hanya tambah selama ROAS marginal ≥ ROAS impas × 1,2 (dan ≥ ROAS minimum) → untung.
- Seimbang    : tambah selama ROAS marginal ≥ max(ROAS impas, ROAS minimum) → tidak menambah rugi; berhenti bila target tercapai.
- Kejar target: tambah selama ROAS marginal ≥ ROAS minimum (ditetapkan user) sampai target tercapai; dampak margin ditampilkan.
Penurunan: semua strategi menurunkan iklan dengan ROAS marginal < ROAS minimum; Efisien juga menurunkan iklan di bawah ROAS impas
(maks. 50% per siklus). Iklan berjalan lain dipertahankan.
Batas tambahan per unit: 3× biaya saat ini (unit aktif) dan stok tersedia anggota.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace
from datetime import date, timedelta

import numpy as np
import pandas as pd

STEP_DAILY = 25_000.0     # kenaikan alokasi per langkah (Rp/hari)
MAX_MULTIPLE = 3.0        # tambahan maksimal per unit = 3× biaya harian saat ini
MAX_CHANGE = 2.0          # Shopee: budget harian naik maks. 2× / turun ke ≥ ½ per evaluasi agar ROAS protection tetap aktif
MAX_SHOPEE_ROAS = 30.0    # Shopee: Target ROAS maks. 30 (di atasnya ROAS protection mati)
NEW_DAILY = 50_000.0      # budget awal iklan produk tunggal baru (Rp/hari)
DEMAND_LIFT = 0.5         # tambahan omzet sebuah iklan maks. 50% dari prediksi omzet produk anggotanya (analisa)
FREE_LIFT = 20.0          # fitur Iklan kejar target: batas permintaan per iklan dilepas (proyeksi memakai kurva respons toko; stok tetap membatasi)
EFFICIENT_MARGIN = 1.2    # Efisien: ROAS marginal ≥ 1,2 × ROAS impas
STRATEGIES = ("Kejar target", "Seimbang", "Efisien")


def _num(series: pd.Series) -> pd.Series:
    if series.dtype != object:
        return pd.to_numeric(series, errors="coerce").fillna(0.0)
    text = series.astype(str).str.replace("%", "", regex=False).str.strip()
    return pd.to_numeric(text, errors="coerce").fillna(0.0)


def _days(text: object) -> int:
    found = re.findall(r"(\d{2})/(\d{2})/(\d{4})", str(text or ""))
    if len(found) >= 2:
        a = pd.Timestamp(int(found[0][2]), int(found[0][1]), int(found[0][0]))
        b = pd.Timestamp(int(found[1][2]), int(found[1][1]), int(found[1][0]))
        return max((b - a).days + 1, 1)
    return 30


def _code(value: object) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\.0+$", "", text)
    return text if text.isdigit() else ""


@dataclass
class Unit:
    key: str
    nama: str
    jenis: str                    # "Grup" / "Produk tunggal" / "Otomatis" / "Produk tunggal (baru)"
    status: str
    mode: str
    daily_cost: float             # biaya harian bulan terakhir
    daily_sales: float            # omzet iklan harian bulan terakhir
    a: float
    b: float
    spread: float                 # ketidakpastian relatif (±) omzet
    members: list[str] = field(default_factory=list)   # product_code
    history: list[tuple[str, float, float]] = field(default_factory=list)  # (periode, biaya/hari, omzet/hari)
    contribution: float = float("nan")   # kontribusi sebelum iklan (pecahan omzet)
    stock_room: float = float("inf")     # tambahan omzet harian maksimal karena stok (Rp/hari)
    demand: float = float("inf")         # prediksi omzet harian produk anggota (analisa, semua kanal)
    locked: bool = False                 # dijeda oleh pemilihan produk (stok 0 / dipindah ke grup)
    origin: str = ""                     # keterangan asal (mis. grup asal iklan tunggal hasil pisah)
    lift: float = DEMAND_LIFT            # batas tambahan omzet iklan sebagai pecahan prediksi omzet anggota
    last_days: int = 0                   # jumlah hari laporan periode terakhir (laporan bulan berjalan = s.d. tanggal laporan)

    @property
    def roas(self) -> float:
        return self.daily_sales / self.daily_cost if self.daily_cost > 0 else float("nan")

    @property
    def roas_impas(self) -> float:
        return 1.0 / self.contribution if self.contribution and self.contribution > 0 else float("inf")

    def sales_at(self, cost: float) -> float:
        return self.a * math.log1p(max(cost, 0.0) / self.b) if self.b > 0 else 0.0

    def marginal(self, cost: float) -> float:
        return self.a / (self.b + max(cost, 0.0)) if self.b > 0 else 0.0

    def cost_for_marginal(self, floor: float) -> float:
        """Biaya harian di mana ROAS marginal = floor."""
        if floor <= 0 or not np.isfinite(floor):
            return 0.0 if not np.isfinite(floor) else float("inf")
        return max(self.a / floor - self.b, 0.0)


def _fit(points: list[tuple[float, float]], last_cost: float, last_sales: float) -> tuple[float, float, float]:
    """(a, b, spread) kurva a·ln(1 + c/b) dari titik (biaya/hari, omzet/hari)."""
    used = [(c, s) for c, s in points if c > 0]
    b = float(np.median([c for c, _s in used])) if used else max(last_cost, 1.0)
    b = max(b, 1.0)
    if len(used) >= 2:
        x = np.array([math.log1p(c / b) for c, _s in used])
        y = np.array([s for _c, s in used])
        a = float((x * y).sum() / max((x * x).sum(), 1e-9))
        pred = a * x
        rel = np.abs(y - pred) / np.maximum(pred, 1.0)
        spread = float(np.clip(np.median(rel), 0.15, 0.6))
    else:
        base = math.log1p(last_cost / b) if last_cost > 0 else math.log(2)
        a = last_sales / base if base > 0 else 0.0
        spread = 0.35
    return max(a, 0.0), b, spread


def parse_units(ads_group: pd.DataFrame | None, ads_overall: pd.DataFrame | None, ads_auto: pd.DataFrame | None = None) -> tuple[list[Unit], pd.DataFrame]:
    """Unit iklan dari laporan grup (baris grup + anggotanya) dan laporan keseluruhan (produk tunggal & otomatis).

    Mengembalikan (units, members) — members: unit, periode, product_code, nama, biaya, omzet, terjual (per bulan)."""
    hist: dict[str, dict] = {}
    member_rows: list[dict] = []

    def add(key: str, nama: str, jenis: str, period: str, days: int, cost: float, sales: float, status: str, mode: str) -> None:
        item = hist.setdefault(key, {"nama": nama, "jenis": jenis, "points": {}, "status": status, "mode": mode, "period": "", "days": {}})
        item["days"][period] = days
        prev = item["points"].get(period, (0.0, 0.0))
        item["points"][period] = (prev[0] + cost / days, prev[1] + sales / days)
        if period >= item["period"]:
            item["period"], item["status"], item["mode"] = period, status or item["status"], mode or item["mode"]

    if ads_group is not None and not ads_group.empty:
        g = ads_group.copy()
        g["_cost"], g["_sales"], g["_sold"] = _num(g.get("cost", 0)), _num(g.get("ad_sales", 0)), _num(g.get("products_sold", 0))
        name_col = "Nama Iklan/Produk" if "Nama Iklan/Produk" in g.columns else "product_name"
        for (period, text), part in g.groupby(["period", "Periode laporan (teks)"], sort=False):
            days = _days(text)
            order = part.sort_values("Urutan", key=lambda s: pd.to_numeric(s, errors="coerce")) if "Urutan" in part.columns else part
            current = None
            for row in order.to_dict("records"):
                code = _code(row.get("product_code", ""))
                name = str(row.get(name_col, ""))
                if not code:
                    current = f"grup:{name}"
                    add(current, name, "Grup", str(period), days, row["_cost"], row["_sales"], str(row.get("Status", "")), str(row.get("Mode Bidding", "")))
                elif current:
                    member_rows.append({"unit": current, "periode": str(period), "product_code": code, "nama": name,
                                        "biaya": row["_cost"] / days, "omzet": row["_sales"] / days, "terjual": row["_sold"]})
    for frame, jenis in ((ads_overall, "Produk tunggal"), (ads_auto, "Otomatis")):
        if frame is None or frame.empty:
            continue
        f = frame.copy()
        f["_cost"], f["_sales"] = _num(f.get("cost", 0)), _num(f.get("ad_sales", 0))
        name_col = "Nama Iklan" if "Nama Iklan" in f.columns else ("Nama Produk" if "Nama Produk" in f.columns else "product_name")
        for row in f.to_dict("records"):
            code = _code(row.get("product_code"))
            name = str(row.get(name_col, ""))
            days = _days(row.get("Periode laporan (teks)"))
            period = str(row.get("period", ""))
            if jenis == "Otomatis":
                if code:  # baris produk di dalam iklan otomatis: dicatat sebagai anggota
                    member_rows.append({"unit": "auto", "periode": period, "product_code": code, "nama": name,
                                        "biaya": row["_cost"] / days, "omzet": row["_sales"] / days, "terjual": 0.0})
                else:
                    add("auto", "Iklan Produk Otomatis", "Otomatis", period, days, row["_cost"], row["_sales"], str(row.get("Status", "Berjalan")), "Otomatis")
                continue
            if not code:
                if "otomatis" in name.lower():
                    continue
                continue  # baris grup sudah dihitung dari laporan grup
            key = f"produk:{code}"
            add(key, name, "Produk tunggal", period, days, row["_cost"], row["_sales"], str(row.get("Status", "")), str(row.get("Mode Bidding", "")))
            member_rows.append({"unit": key, "periode": period, "product_code": code, "nama": name,
                                "biaya": row["_cost"] / days, "omzet": row["_sales"] / days, "terjual": 0.0})
    units: list[Unit] = []
    for key, item in hist.items():
        points = sorted(item["points"].items())
        last_period, (cost, sales) = points[-1]
        a, b, spread = _fit([p for _k, p in points], cost, sales)
        members = sorted({m["product_code"] for m in member_rows if m["unit"] == key})
        units.append(Unit(key, item["nama"], item["jenis"], item["status"], item["mode"], cost, sales, a, b, spread, members,
                          [(k, c, s) for k, (c, s) in points], last_days=int(item["days"].get(last_period, 0))))
    return units, pd.DataFrame(member_rows, columns=["unit", "periode", "product_code", "nama", "biaya", "omzet", "terjual"])


def attach_economics(units: list[Unit], members: pd.DataFrame, contribution_by_code: dict[str, float], room_by_code: dict[str, float]) -> None:
    """Kontribusi sebelum iklan & ruang stok per unit (tertimbang omzet anggota bulan terakhir)."""
    latest = members.loc[members["periode"] == members.groupby("unit")["periode"].transform("max")] if not members.empty else members
    for unit in units:
        part = latest.loc[latest["unit"] == unit.key] if not latest.empty else latest
        weights = {c: float(w) for c, w in zip(part.get("product_code", []), part.get("omzet", []))}
        codes = unit.members or list(weights)
        vals = [(contribution_by_code.get(c), max(weights.get(c, 0.0), 1.0)) for c in codes if contribution_by_code.get(c) is not None]
        if vals:
            unit.contribution = float(sum(v * w for v, w in vals) / sum(w for _v, w in vals))
        rooms = [room_by_code[c] for c in codes if c in room_by_code]
        if rooms:
            unit.stock_room = float(sum(rooms))


def new_single_candidates(units: list[Unit], products: pd.DataFrame, contribution_by_code: dict[str, float], *, limit: int = 15,
                          store_roas: float = 8.0, require_margin: bool = True, require_stock: bool = True) -> list[Unit]:
    """Produk laris tanpa iklan sama sekali → usulan iklan produk tunggal baru.

    Bawaan: kontribusi positif & stok ada. Mode kejar target (require_* = False): margin dan stok tidak menyaring,
    hanya dicatat. products: product_code, nama, omzet_harian (organik), stok_room (Rp/hari)."""
    advertised = {c for u in units for c in u.members}
    out = []
    pool = products.loc[~products["product_code"].isin(advertised)].sort_values("omzet_harian", ascending=False)
    for row in pool.itertuples(index=False):
        contrib = contribution_by_code.get(row.product_code)
        if row.omzet_harian <= 0:
            continue
        if require_margin and (contrib is None or contrib <= 0):
            continue
        if require_stock and not (row.stok_room > 0):
            continue
        roas0 = max(store_roas * 0.7, 1.0)  # iklan baru: ROAS konservatif 70% ROAS toko
        a = roas0 * NEW_DAILY / math.log(2)
        room = float("inf") if pd.isna(row.stok_room) else float(row.stok_room)
        unit = Unit(f"baru:{row.product_code}", row.nama, "Produk tunggal (baru)", "Usulan", "GMV Max ROAS", 0.0, 0.0, a, NEW_DAILY, 0.5,
                    [row.product_code], [], float(contrib) if contrib is not None else float("nan"), room)
        out.append(unit)
        if len(out) >= limit:
            break
    return out


@dataclass
class Plan:
    name: str
    cost: dict[str, float]        # biaya harian usulan per unit
    floor: dict[str, float]       # batas ROAS per unit


def _floor(unit: Unit, strategy: str, roas_min: float) -> float:
    impas = unit.roas_impas
    if strategy == "Efisien":
        return max(impas * EFFICIENT_MARGIN, roas_min)
    if strategy == "Seimbang":
        return max(impas, roas_min)
    return roas_min


def allocate(units: list[Unit], strategy: str, *, gap_daily: float, roas_min: float, budget_cap_daily: float | None = None) -> Plan:
    """Alokasi biaya harian per unit. gap_daily = kekurangan omzet harian ke target (≤ 0 berarti target tercapai)."""
    cost = {}
    floor = {u.key: _floor(u, strategy, roas_min) for u in units}
    for u in units:
        base = u.daily_cost if u.status.lower().startswith(("berjalan", "aktif", "ongoing")) or u.jenis == "Otomatis" else 0.0
        # Penurunan: iklan dengan ROAS marginal di bawah ROAS minimum diturunkan sampai ROAS marginal = ROAS minimum (semua strategi).
        # Efisien juga menurunkan iklan di bawah ROAS impasnya, maksimal 50% per siklus agar algoritma Shopee tidak "belajar ulang" dari nol.
        if base > 0 and u.marginal(base) < roas_min:
            base = min(base, u.cost_for_marginal(roas_min))
        if strategy == "Efisien" and base > 0 and u.marginal(base) < floor[u.key]:
            base = max(min(base, u.cost_for_marginal(floor[u.key])), base * 0.5)
        cost[u.key] = base
    gained = sum(u.sales_at(cost[u.key]) - u.sales_at(u.daily_cost) for u in units)  # negatif bila ada unit diturunkan
    caps = {}
    for u in units:
        current = max(u.daily_cost, NEW_DAILY if u.daily_cost <= 0 else 0.0)
        caps[u.key] = current * (1 + MAX_MULTIPLE) if u.daily_cost > 0 else NEW_DAILY * 2
    spent = sum(cost.values())
    chase = strategy != "Efisien"
    target_left = gap_daily - gained
    for _ in range(4000):
        if chase and target_left <= 0:
            break
        if budget_cap_daily is not None and spent >= budget_cap_daily:
            break
        best, best_m = None, 0.0
        for u in units:
            c = cost[u.key]
            if c + STEP_DAILY > caps[u.key]:
                continue
            extra_sales = u.sales_at(c + STEP_DAILY) - u.sales_at(u.daily_cost)
            if extra_sales > u.stock_room:
                continue
            m = (u.sales_at(c + STEP_DAILY) - u.sales_at(c)) / STEP_DAILY
            if m >= floor[u.key] and m > best_m:
                best, best_m = u, m
        if best is None:
            break
        before = best.sales_at(cost[best.key])
        cost[best.key] += STEP_DAILY
        spent += STEP_DAILY
        target_left -= best.sales_at(cost[best.key]) - before
    return Plan(strategy, cost, floor)


# ---------------------------------------------------------------- Kejar target: ROAS & budget dari pengguna

TARGET_KINDS = ("Produk tunggal", "Grup", "Produk tunggal (baru)")


def _running(u: Unit) -> bool:
    return u.status.lower().startswith(("berjalan", "aktif", "ongoing"))


def _base(u: Unit) -> float:
    """Biaya harian yang sedang berjalan; iklan dijeda/selesai saat ini tidak menghasilkan omzet."""
    return u.daily_cost if _running(u) else 0.0


def _now_sales(u: Unit) -> float:
    return u.daily_sales if _running(u) else 0.0


def uplift_cap(u: Unit) -> float:
    return u.lift * u.demand if np.isfinite(u.demand) else float("inf")


def ad_sales(u: Unit, cost: float) -> float:
    """Omzet iklan harian pada biaya `cost`: omzet aktual sekarang + perubahan menurut kurva respons.

    Kenaikan dibatasi `DEMAND_LIFT` × prediksi omzet produk anggota, supaya rencana tidak menjanjikan omzet iklan
    di luar permintaan produknya."""
    if u.locked:
        return 0.0
    delta = u.sales_at(cost) - u.sales_at(_base(u))
    return max(_now_sales(u) + min(delta, uplift_cap(u)), 0.0)


def allocate_target(units: list[Unit], *, gap_daily: float, target_roas: float, budget_daily: float | None = None,
                    max_change: float = MAX_CHANGE) -> Plan:
    """Rencana mengejar target dengan ROAS & budget yang ditetapkan pengguna (margin dan stok tidak membatasi).

    Target ROAS = ROAS rata-rata seluruh iklan di rencana (total omzet iklan / total biaya iklan), sama dengan arti
    Target ROAS di Shopee. Batas Shopee: budget harian iklan berjalan hanya boleh naik maks. `max_change`× atau turun ke
    ≥ 1/`max_change` per evaluasi (lebih dari itu ROAS protection mati), selain dijeda.
    1. Budget dipindah dari iklan dengan tambahan omzet per Rp terendah ke yang tertinggi selama omzet naik.
    2. Bila biaya di atas budget atau ROAS rata-rata di bawah target, iklan yang paling tidak efektif dipangkas dulu.
    3. Sisa budget ditambahkan bertahap (Rp 25 rb/hari) ke iklan paling efektif sampai kekurangan omzet harian
       tertutup, selama ROAS rata-rata tetap ≥ target.
    """
    floor = {u.key: float(target_roas) for u in units}
    cost = {u.key: 0.0 if u.locked else _base(u) for u in units}
    caps = {u.key: 0.0 if u.locked else max(u.daily_cost * max_change if u.daily_cost > 0 else NEW_DAILY * 2, cost[u.key]) for u in units}
    lower = {u.key: cost[u.key] / max_change for u in units}
    sales = {u.key: ad_sales(u, cost[u.key]) for u in units}
    total_cost, total_sales = sum(cost.values()), sum(sales.values())
    target_left = gap_daily - sum(sales[u.key] - _now_sales(u) for u in units)

    def cut_step(u: Unit) -> float:
        c, lo = cost[u.key], lower[u.key]
        return c if c <= lo + 1e-6 else min(STEP_DAILY, c - lo)

    def add_step(u: Unit, step: float) -> float:
        return max(lower[u.key], step) if cost[u.key] <= 0 else step

    def gain(u: Unit, step: float) -> float:
        return ad_sales(u, cost[u.key] + step) - sales[u.key]

    def loss(u: Unit, step: float) -> float:
        return sales[u.key] - ad_sales(u, cost[u.key] - step)

    def loss_rate(u: Unit) -> float:
        step = cut_step(u)
        return loss(u, step) / step if step > 0 else float("inf")

    def move(u: Unit, delta: float) -> None:
        nonlocal total_cost, total_sales, target_left
        before = sales[u.key]
        cost[u.key] = max(cost[u.key] + delta, 0.0)
        sales[u.key] = ad_sales(u, cost[u.key])
        total_cost += delta
        total_sales += sales[u.key] - before
        target_left -= sales[u.key] - before

    for _ in range(8000):
        live = [u for u in units if cost[u.key] > 0]
        if not live:
            break
        donor = min(live, key=loss_rate)
        freed = cut_step(donor)
        lost = loss(donor, freed)
        best, best_gain, best_step = None, 0.0, 0.0
        for u in units:
            step = add_step(u, freed)
            if u.key != donor.key and step <= freed + 1e-6 and cost[u.key] + step <= caps[u.key] + 1e-6:
                g = gain(u, step)
                if g > best_gain:
                    best, best_gain, best_step = u, g, step
        if best is None or best_gain <= lost + 1.0:
            break
        move(donor, -freed)
        move(best, best_step)

    for _ in range(20_000):
        over_budget = budget_daily is not None and total_cost > budget_daily + 1e-6
        under_roas = total_cost > 0 and total_sales / total_cost < target_roas
        if not (over_budget or under_roas):
            break
        live = [u for u in units if cost[u.key] > 0]
        if not live:
            break
        worst = min(live, key=loss_rate)
        move(worst, -cut_step(worst))

    for _ in range(8000):
        if target_left <= 0:
            break
        room = None if budget_daily is None else budget_daily - total_cost
        if room is not None and room < 1:
            break
        base_step = STEP_DAILY if room is None else min(STEP_DAILY, room)
        best, best_gain, best_step = None, 0.0, 0.0
        for u in units:
            step = add_step(u, base_step)
            if (room is None or step <= room + 1e-6) and cost[u.key] + step <= caps[u.key] + 1e-6:
                g = gain(u, step)
                if g / step > (best_gain / best_step if best_step else 0.0):
                    best, best_gain, best_step = u, g, step
        if best is None or (total_sales + best_gain) < target_roas * (total_cost + best_step):
            break
        move(best, best_step)
    return Plan("Kejar target", cost, floor)


def plan_effect(units: list[Unit], plan: Plan, *, days: int) -> dict:
    """Angka sisa bulan: biaya total, tambahan biaya, tambahan omzet (+ rentang), ROAS rencana, dampak margin (info)."""
    d_cost = sum(plan.cost[u.key] - _base(u) for u in units) * days
    d_sales_daily = [ad_sales(u, plan.cost[u.key]) - _now_sales(u) for u in units]
    d_sales = sum(d_sales_daily) * days
    lo = sum(d * (1 - u.spread) for d, u in zip(d_sales_daily, units)) * days
    hi = sum(d * (1 + u.spread) for d, u in zip(d_sales_daily, units)) * days
    total_cost = sum(plan.cost.values()) * days
    total_sales = sum(ad_sales(u, plan.cost[u.key]) for u in units) * days
    margin, known = 0.0, True
    for d, u in zip(d_sales_daily, units):
        dc = (plan.cost[u.key] - _base(u)) * days
        if np.isfinite(u.contribution):
            margin += d * days * u.contribution - dc
        else:
            known = False
            margin -= dc
    return {
        "biaya_total": total_cost, "biaya_tambahan": d_cost, "omzet_tambahan": d_sales, "rentang": (min(lo, hi), max(lo, hi)),
        "omzet_iklan": total_sales, "roas_rencana": total_sales / total_cost if total_cost > 0 else float("nan"),
        "dampak_margin": margin, "margin_lengkap": known,
    }


def target_actions(units: list[Unit], plan: Plan, *, target_roas: float) -> pd.DataFrame:
    """Tindakan per iklan untuk rencana Kejar target: urut Naikkan → Buat baru → Aktifkan → Turunkan → Jeda → Pertahankan."""
    rows = []
    for u in units:
        new, now = plan.cost[u.key], _base(u)
        running = _running(u)
        if u.locked:
            if now <= 0:
                continue
            act = "Jeda"
        elif u.jenis.endswith("(baru)"):
            if new <= 0:
                continue
            act = "Buat iklan baru"
        elif u.jenis.endswith("(dari grup)"):
            if new <= 0:
                continue
            act = "Pisahkan jadi iklan tunggal"
        elif new <= 0 and now > 0:
            act = "Jeda"
        elif new <= 0:
            continue
        elif not running:
            act = "Aktifkan kembali"
        elif new > now * 1.05:
            act = "Naikkan budget"
        elif new < now * 0.95:
            act = "Turunkan budget"
        else:
            act = "Pertahankan"
        d_sales = ad_sales(u, new) - _now_sales(u)
        notes = []
        if u.locked:
            notes.append({"Jeda sampai restock": "stok 0: jeda sampai barang masuk (lihat Pemilihan produk)",
                          "Pindahkan ke grup": "produk dipindah ke grup (lihat Pemilihan produk)",
                          "Keluarkan dari grup": "produk sudah diiklankan di iklan lain (lihat Pemilihan produk)"}.get(u.origin, f"{u.origin} (lihat Pemilihan produk)"))
        elif act in {"Turunkan budget", "Jeda"}:
            notes.append(f"tiap Rp 1 terakhir hanya kembali Rp {u.marginal(new):.1f}: dananya dipindah ke iklan yang lebih efektif".replace(".", ","))
        elif act in {"Naikkan budget", "Aktifkan kembali", "Buat iklan baru", "Pisahkan jadi iklan tunggal"}:
            notes.append(f"tiap Rp 1 tambahan kembali ±Rp {u.marginal(new):.1f}".replace(".", ","))
        if act == "Pisahkan jadi iklan tunggal" and u.origin:
            notes.append(f"budget awal diambil dari grup {u.origin}")
        elif u.jenis == "Grup" and u.origin and not u.locked:
            notes.append(u.origin)
        if np.isfinite(u.demand) and not u.locked and d_sales >= uplift_cap(u) - 1 and d_sales > 0:
            notes.append("tambahan omzet sudah di batas permintaan produk (+50% prediksi): budget lebih tidak menambah omzet")
        if np.isfinite(u.stock_room) and d_sales > u.stock_room + 1:
            notes.append("⚠️ stok kurang untuk tambahan omzet ini: siapkan restock/PO")
        if np.isfinite(u.contribution) and u.contribution <= 0 and d_sales > 0:
            notes.append("margin minus: tambahan omzet ikut menambah rugi")
        planned = ad_sales(u, new)
        roas_shopee = planned / new if new > 0 else np.nan
        if roas_shopee == roas_shopee and roas_shopee > MAX_SHOPEE_ROAS:
            estimate = f"{roas_shopee:.1f}".replace(".", ",")
            notes.append(f"Target ROAS diisi {MAX_SHOPEE_ROAS:.0f} (maks. Shopee); perkiraan ROAS iklan ini {estimate}")
            roas_shopee = MAX_SHOPEE_ROAS
        rows.append({
            "key": u.key, "Tindakan": act, "Iklan": u.nama, "Jenis": "Produk tunggal" if u.jenis.startswith("Produk tunggal") else u.jenis,
            "Anggota": len(u.members), "Budget harian sekarang": now, "Budget harian usulan": new,
            "Perubahan/hari": new - now, "Target ROAS Shopee": round(roas_shopee, 1) if roas_shopee == roas_shopee else np.nan,
            "ROAS bulan terakhir": u.roas, "Prediksi omzet produk/hari": u.demand if np.isfinite(u.demand) else np.nan,
            "Omzet iklan usulan/hari": planned, "Tambahan omzet/hari": d_sales, "Catatan": "; ".join(notes),
        })
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    order = {"Naikkan budget": 0, "Pisahkan jadi iklan tunggal": 1, "Buat iklan baru": 2, "Aktifkan kembali": 3, "Turunkan budget": 4,
             "Jeda": 5, "Pertahankan": 6}
    frame["_o"] = frame["Tindakan"].map(order).fillna(9)
    frame["_v"] = frame["Tambahan omzet/hari"].abs()
    return frame.sort_values(["_o", "_v"], ascending=[True, False]).drop(columns=["_o", "_v"]).reset_index(drop=True)


def _extra(units: list[Unit], plan: Plan) -> float:
    return sum(ad_sales(u, plan.cost[u.key]) - _now_sales(u) for u in units)


def budget_needed(units: list[Unit], *, gap_daily: float, target_roas: float) -> tuple[float | None, float]:
    """Budget harian yang dibutuhkan untuk menutup gap pada target ROAS ini (None bila tidak terkejar), dan omzet tambahan harian maksimal."""
    plan = allocate_target(units, gap_daily=gap_daily, target_roas=target_roas, budget_daily=None)
    extra = _extra(units, plan)
    return (sum(plan.cost.values()) if extra >= gap_daily - 1 else None), extra


def roas_for_budget(units: list[Unit], *, gap_daily: float, budget_daily: float, lo: float = 1.0, hi: float = 50.0) -> float | None:
    """Target ROAS tertinggi yang masih menutup gap dengan budget harian ini (None bila ROAS 1 pun tidak cukup)."""
    def closes(roas: float) -> bool:
        return _extra(units, allocate_target(units, gap_daily=gap_daily, target_roas=roas, budget_daily=budget_daily)) >= gap_daily - 1

    if not closes(lo):
        return None
    if closes(hi):
        return hi
    for _ in range(14):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if closes(mid) else (lo, mid)
    return math.floor(lo * 2) / 2


def summarize(units: list[Unit], plan: Plan, *, days: int, target: float, predicted: float) -> dict:
    """Ringkasan strategi untuk `days` hari tersisa di bulan target."""
    d_cost = sum(plan.cost[u.key] - u.daily_cost for u in units) * days
    d_sales = sum(u.sales_at(plan.cost[u.key]) - u.sales_at(u.daily_cost) for u in units) * days
    lo = sum((u.sales_at(plan.cost[u.key]) - u.sales_at(u.daily_cost)) * (1 - u.spread) for u in units) * days
    hi = sum((u.sales_at(plan.cost[u.key]) - u.sales_at(u.daily_cost)) * (1 + u.spread) for u in units) * days
    margin = 0.0
    known = True
    for u in units:
        ds = (u.sales_at(plan.cost[u.key]) - u.sales_at(u.daily_cost)) * days
        dc = (plan.cost[u.key] - u.daily_cost) * days
        if np.isfinite(u.contribution):
            margin += ds * u.contribution - dc
        else:
            known = False
            margin -= dc
    total_cost = sum(plan.cost.values()) * days
    return {
        "Strategi": plan.name,
        "Perubahan budget": d_cost,
        "Budget iklan total": total_cost,
        "Omzet tambahan": d_sales,
        "Rentang omzet": (min(lo, hi), max(lo, hi)),
        "ROAS tambahan": d_sales / d_cost if d_cost > 0 else float("nan"),
        "% target": (predicted + d_sales) / target * 100 if target > 0 else float("nan"),
        "Dampak margin": margin,
        "margin_lengkap": known,
    }


def actions(units: list[Unit], plan: Plan) -> pd.DataFrame:
    """Tindakan per unit iklan, urut dampak omzet."""
    rows = []
    for u in units:
        new = plan.cost[u.key]
        old = u.daily_cost
        floor = plan.floor[u.key]
        d_sales = u.sales_at(new) - u.sales_at(old)
        running = u.status.lower().startswith(("berjalan", "aktif")) or u.jenis == "Otomatis"
        if u.jenis.endswith("(baru)"):
            act = "Buat iklan produk tunggal" if new > 0 else "Belum perlu"
        elif new <= 0 and old > 0:
            act = "Jeda"
        elif not running and new > 0:
            act = "Aktifkan kembali"
        elif new > old * 1.05:
            act = "Naikkan budget"
        elif new < old * 0.95:
            act = "Turunkan budget"
        else:
            act = "Pertahankan"
        if act in {"Belum perlu"} and old <= 0:
            continue
        impas = u.roas_impas
        reason = []
        if np.isfinite(u.roas):
            reason.append(f"ROAS bulan terakhir {u.roas:.1f}".replace(".", ","))
        reason.append(f"ROAS marginal {u.marginal(old):.1f}".replace(".", ",") + f" vs batas {floor:.1f}".replace(".", ",") if np.isfinite(floor) else "kontribusi minus: tiap penjualan rugi")
        if np.isfinite(impas):
            reason.append(f"impas di ROAS {impas:.1f}".replace(".", ","))
        elif np.isfinite(u.contribution):
            reason.append("margin kotor < potongan Shopee (rugi sebelum iklan)")
        if np.isfinite(u.stock_room) and u.stock_room < d_sales + 1:
            reason.append("dibatasi stok")
        target_roas = max(floor if np.isfinite(floor) else 0, u.marginal(new) if new > 0 else 0)
        rows.append({
            "key": u.key, "Unit iklan": u.nama, "Jenis": u.jenis, "Status": u.status, "Anggota": len(u.members), "Tindakan": act,
            "Budget harian sekarang": old, "Budget harian usulan": new, "Omzet iklan harian (est.)": u.sales_at(new),
            "Tambahan omzet harian": d_sales, "ROAS bulan terakhir": u.roas, "ROAS impas": impas if np.isfinite(impas) else np.nan,
            "Target ROAS Shopee": round(target_roas, 1) if target_roas > 0 else np.nan, "Alasan": "; ".join(reason),
        })
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    order = {"Naikkan budget": 0, "Aktifkan kembali": 1, "Buat iklan produk tunggal": 2, "Turunkan budget": 3, "Jeda": 4, "Pertahankan": 5}
    frame["_o"] = frame["Tindakan"].map(order).fillna(9)
    frame["_v"] = frame["Tambahan omzet harian"].abs()
    return frame.sort_values(["_o", "_v"], ascending=[True, False]).drop(columns=["_o", "_v"]).reset_index(drop=True)


def group_hygiene(members: pd.DataFrame, units: list[Unit], contribution_by_code: dict[str, float]) -> pd.DataFrame:
    """Rapikan grup: keluarkan anggota yang memakan biaya tanpa omzet (2 bulan terakhir) atau rugi; pisahkan anggota andalan jadi iklan tunggal."""
    cols = ["Grup", "SKU/Produk", "Kode produk", "Biaya/hari", "Omzet/hari", "ROAS", "Porsi omzet grup", "Saran"]
    if members.empty:
        return pd.DataFrame(columns=cols)
    groups = {u.key: u for u in units if u.jenis == "Grup"}
    work = members.loc[members["unit"].isin(groups)]
    if work.empty:
        return pd.DataFrame(columns=cols)
    periods = sorted(work["periode"].unique())[-2:]
    recent = work.loc[work["periode"].isin(periods)].groupby(["unit", "product_code"], as_index=False).agg(nama=("nama", "last"), biaya=("biaya", "mean"), omzet=("omzet", "mean"))
    rows = []
    for unit_key, part in recent.groupby("unit"):
        unit = groups[unit_key]
        total = float(part["omzet"].sum())
        group_roas = total / float(part["biaya"].sum()) if part["biaya"].sum() > 0 else float("nan")
        for r in part.itertuples(index=False):
            roas = r.omzet / r.biaya if r.biaya > 0 else float("nan")
            share = r.omzet / total if total > 0 else 0.0
            contrib = contribution_by_code.get(r.product_code)
            advice = ""
            if r.biaya > 0 and r.omzet <= 0:
                advice = "Keluarkan dari grup: ada biaya, tidak ada omzet 2 bulan terakhir"
            elif contrib is not None and contrib <= 0 and r.biaya > 0:
                advice = "Keluarkan dari grup: margin kotor < potongan Shopee (rugi per unit)"
            elif share >= 0.4 and len(part) > 2 and np.isfinite(roas) and np.isfinite(group_roas) and roas >= group_roas:
                advice = "Pisahkan jadi iklan produk tunggal: andalan grup, kendalikan budget & target ROAS sendiri"
            elif np.isfinite(roas) and np.isfinite(group_roas) and roas < group_roas * 0.4 and r.biaya > 0:
                advice = "Tinjau: ROAS jauh di bawah rata-rata grup"
            if advice:
                rows.append({"Grup": unit.nama, "SKU/Produk": r.nama, "Kode produk": r.product_code, "Biaya/hari": r.biaya, "Omzet/hari": r.omzet,
                             "ROAS": roas, "Porsi omzet grup": share * 100, "Saran": advice})
    frame = pd.DataFrame(rows, columns=cols)
    return frame.sort_values("Biaya/hari", ascending=False).reset_index(drop=True)


SELECTION_ORDER = ("Buat iklan tunggal", "Jadikan iklan tunggal", "Pertahankan iklan tunggal", "Tambahkan ke grup", "Pertahankan di grup",
                   "Pindahkan ke grup", "Keluarkan dari grup", "Jeda sampai restock", "Sudah di iklan lain")
MOVE_OUT = ("Keluarkan dari grup", "Jadikan iklan tunggal", "Jeda sampai restock", "Pindahkan ke grup", "Sudah di iklan lain")
NEW_KINDS = ("Produk tunggal (baru)", "Produk tunggal (dari grup)")


def product_selection(members: pd.DataFrame, units: list[Unit], products: pd.DataFrame, contribution_by_code: dict[str, float], *,
                      target_roas: float, plan: Plan | None = None, top_single: int = 15, top_group: int = 60,
                      max_promote: int = 10) -> pd.DataFrame:
    """Pemilihan produk untuk iklan produk tunggal vs iklan grup, per Kode Produk (satu produk = satu iklan).

    Dasar: hasil iklan 2 bulan terakhir per produk (biaya, omzet, ROAS, porsi omzet di grup), prediksi omzet harian dari
    analisa (permintaan), stok, dan margin (catatan). target_roas = target ROAS pengguna (maks. 30).
    - Produk yang ada di beberapa iklan: tetap di iklan dengan omzet tertinggi, iklan lain melepasnya (budget tidak dobel).
    - Jadikan iklan tunggal: andalan grup (porsi omzet ≥ 30% di grup > 2 produk, ROAS ≥ 80% target) atau omzet iklan
      tertinggi dengan ROAS ≥ target → budget & target ROAS dikendalikan sendiri (maks. `max_promote` per minggu, sisanya kandidat).
    - Keluarkan dari grup: ada biaya tanpa omzet, atau ROAS < 50% target.
    - Pindahkan ke grup: iklan tunggal dengan ROAS < 50% target dan omzet di bawah median iklan tunggal.
    - Buat iklan tunggal / Tambahkan ke grup: produk belum diiklankan & stok ada, urut prediksi omzet tertinggi
      (urutan 1..top_single / berikutnya sampai top_group).
    - Jeda sampai restock: produk diiklankan yang stoknya 0.
    Kolom `_unit` = kunci iklan asal (kosong untuk produk belum diiklankan); dipakai `restructure`.
    """
    cols = ["Saran", "Produk", "Kode produk", "Iklan sekarang", "Biaya iklan/hari", "Omzet iklan/hari", "ROAS 2 bulan", "Porsi omzet grup",
            "Prediksi omzet/hari", "Stok", "Alasan", "_unit"]
    target = min(float(target_roas), MAX_SHOPEE_ROAS)
    by_key = {u.key: u for u in units}
    prod = products.set_index("product_code") if not products.empty else pd.DataFrame(columns=["nama", "omzet_harian", "stok_room", "stok"])
    demand = prod["omzet_harian"].fillna(0.0) if "omzet_harian" in prod.columns else pd.Series(dtype=float)

    hist = pd.DataFrame(columns=["unit", "product_code", "nama", "biaya", "omzet"])
    if not members.empty:
        periods = sorted(members["periode"].unique())[-2:]
        recent = members.loc[members["periode"].isin(periods) & (members["unit"] != "auto")]
        if not recent.empty:
            per = recent.groupby(["unit", "product_code", "periode"], as_index=False).agg(nama=("nama", "last"), biaya=("biaya", "sum"), omzet=("omzet", "sum"))
            hist = per.groupby(["unit", "product_code"], as_index=False).agg(nama=("nama", "last"), biaya=("biaya", "mean"), omzet=("omzet", "mean"))
    group_total = hist.loc[hist["unit"].str.startswith("grup:")].groupby("unit")["omzet"].sum().to_dict() if not hist.empty else {}
    group_size = hist.loc[hist["unit"].str.startswith("grup:")].groupby("unit")["product_code"].nunique().to_dict() if not hist.empty else {}
    singles = hist.loc[hist["unit"].str.startswith("produk:")] if not hist.empty else hist
    single_median = float(singles["omzet"].median()) if not singles.empty else 0.0
    top_ads = float(hist["omzet"].quantile(0.9)) if len(hist) >= 10 else float("inf")

    def label_of(key: str) -> str:
        unit = by_key.get(key)
        name = f"Grup: {unit.nama if unit else key[5:]}" if key.startswith("grup:") else "Iklan tunggal"
        return name + ("" if unit is not None and _running(unit) else " (dijeda)")

    home: dict[str, str] = {}
    if not hist.empty:
        ranked = hist.assign(_run=[1 if by_key.get(k) is not None and _running(by_key[k]) else 0 for k in hist["unit"]])
        ranked = ranked.sort_values(["omzet", "_run", "biaya"], ascending=[False, False, True])
        home = ranked.drop_duplicates("product_code").set_index("product_code")["unit"].astype(str).to_dict()

    def stock_of(code: str) -> tuple[float, float]:
        if code not in prod.index:
            return float("nan"), float("nan")
        row = prod.loc[code]
        return float(row.get("stok", np.nan)), float(row.get("stok_room", np.nan))

    def notes_for(code: str, base: list[str]) -> str:
        contrib = contribution_by_code.get(code)
        stok, room = stock_of(code)
        out = list(base)
        if room == room and room <= 0 and not (stok == stok and stok <= 0):
            out.append("stok hanya cukup untuk penjualan biasa: siapkan restock bila iklan dinaikkan")
        if contrib is not None and contrib <= 0:
            out.append("margin minus (info)")
        return "; ".join(out)

    rows, seen = [], set()
    for r in hist.itertuples(index=False):
        unit = by_key.get(r.unit)
        code = str(r.product_code)
        roas = r.omzet / r.biaya if r.biaya > 0 else float("nan")
        stok, _room = stock_of(code)
        running = unit is not None and _running(unit)
        is_group = r.unit.startswith("grup:")
        share = r.omzet / group_total[r.unit] if is_group and group_total.get(r.unit, 0) > 0 else float("nan")
        reason: list[str] = []
        if home.get(code, r.unit) != r.unit and not running:
            act, reason = "Sudah di iklan lain", [f"iklan ini tidak berjalan; produk dihitung di {label_of(home[code])}"]
        elif home.get(code, r.unit) != r.unit:
            act = "Keluarkan dari grup" if is_group else "Pindahkan ke grup"
            reason = [f"sudah diiklankan di {label_of(home[code])}: satu produk cukup di satu iklan agar budget tidak dobel"]
        elif stok == stok and stok <= 0 and running:
            act, reason = "Jeda sampai restock", ["stok 0: iklan tidak bisa menghasilkan penjualan; aktifkan lagi setelah barang masuk"]
        elif is_group:
            if r.biaya > 0 and r.omzet <= 0:
                act, reason = "Keluarkan dari grup", ["ada biaya tanpa omzet 2 bulan terakhir"]
            elif roas == roas and roas < target * 0.5 and r.biaya >= 5_000:
                act, reason = "Keluarkan dari grup", [f"ROAS {roas:.1f} < 50% target {target:.1f}: menyedot budget grup".replace(".", ",")]
            elif (share == share and share >= 0.3 and group_size.get(r.unit, 0) > 2 and roas == roas and roas >= target * 0.8) or \
                    (r.omzet >= top_ads and roas == roas and roas >= target):
                act, reason = "Jadikan iklan tunggal", [f"andalan grup ({share * 100:.0f}% omzet grup, ROAS {roas:.1f}): budget & target ROAS dikendalikan sendiri".replace(".", ",")
                                                        if share == share else f"omzet iklan tertinggi dengan ROAS {roas:.1f}".replace(".", ",")]
            else:
                act, reason = "Pertahankan di grup", []
        else:
            if r.biaya > 0 and r.omzet <= 0:
                act, reason = "Pindahkan ke grup", ["ada biaya tanpa omzet: tidak layak budget sendiri"]
            elif roas == roas and roas < target * 0.5 and r.omzet < single_median:
                act, reason = "Pindahkan ke grup", [f"ROAS {roas:.1f} < 50% target dan omzet kecil: lebih efisien ditopang produk lain di grup".replace(".", ",")]
            else:
                act, reason = "Pertahankan iklan tunggal", []
        seen.add(code)
        name = str(r.nama) or (str(prod.loc[code, "nama"]) if code in prod.index else code)
        rows.append({"Saran": act, "Produk": name, "Kode produk": code, "Iklan sekarang": label_of(r.unit), "Biaya iklan/hari": r.biaya,
                     "Omzet iklan/hari": r.omzet, "ROAS 2 bulan": roas, "Porsi omzet grup": share * 100 if share == share else np.nan,
                     "Prediksi omzet/hari": float(demand.get(code, np.nan)) if code in demand.index else np.nan, "Stok": stok,
                     "Alasan": notes_for(code, reason), "_unit": r.unit})
    advertised = {c for u in units if u.jenis in ("Produk tunggal", "Grup") for c in u.members} | seen
    position = 0
    for code in demand.sort_values(ascending=False).index:
        code = str(code)
        if code in advertised or demand.get(code, 0) <= 0:
            continue
        stok, _room = stock_of(code)
        if stok == stok and stok <= 0:
            continue
        position += 1
        if position <= top_single:
            act, reason = "Buat iklan tunggal", [f"urutan {position} prediksi omzet di antara produk belum diiklankan"]
        elif position <= top_group:
            act, reason = "Tambahkan ke grup", [f"urutan {position} prediksi omzet di antara produk belum diiklankan: masukkan ke grup produk sejenis"]
        else:
            break
        rows.append({"Saran": act, "Produk": str(prod.loc[code, "nama"]), "Kode produk": code, "Iklan sekarang": "Belum diiklankan",
                     "Biaya iklan/hari": 0.0, "Omzet iklan/hari": 0.0, "ROAS 2 bulan": np.nan, "Porsi omzet grup": np.nan,
                     "Prediksi omzet/hari": float(demand[code]), "Stok": stok, "Alasan": notes_for(code, reason), "_unit": ""})
    frame = pd.DataFrame(rows, columns=cols)
    if frame.empty:
        return frame
    promote = frame.loc[frame["Saran"] == "Jadikan iklan tunggal"]
    promote = promote.assign(_v=promote["Omzet iklan/hari"].fillna(0) + promote["Prediksi omzet/hari"].fillna(0)).sort_values("_v", ascending=False)
    later = promote.index[max_promote:]
    frame.loc[later, "Saran"] = "Pertahankan di grup"
    frame.loc[later, "Alasan"] = "kandidat iklan tunggal minggu berikutnya: " + frame.loc[later, "Alasan"].astype(str)
    return _sort_selection(frame)


def _sort_selection(frame: pd.DataFrame) -> pd.DataFrame:
    removal = frame["Saran"].isin(["Keluarkan dari grup", "Pindahkan ke grup", "Jeda sampai restock", "Sudah di iklan lain"])
    value = (frame["Omzet iklan/hari"].fillna(0) + frame["Prediksi omzet/hari"].fillna(0)).where(~removal, frame["Biaya iklan/hari"].fillna(0))
    order = frame["Saran"].map({k: i for i, k in enumerate(SELECTION_ORDER)}).fillna(99)
    return frame.assign(_o=order, _v=value).sort_values(["_o", "_v"], ascending=[True, False]).drop(columns=["_o", "_v"]).reset_index(drop=True)


def _store_roas(units: list[Unit]) -> float:
    run = [u for u in units if _running(u) and u.daily_cost > 0]
    cost = sum(u.daily_cost for u in run)
    return sum(u.daily_sales for u in run) / cost if cost > 0 else 8.0


def restructure(units: list[Unit], selection: pd.DataFrame, products: pd.DataFrame, contribution_by_code: dict[str, float]) -> list[Unit]:
    """Unit iklan sesudah keputusan pemilihan produk, supaya rencana budget memakai susunan iklan yang sama.

    - Grup: anggota yang keluar / dipisah / dijeda dilepas; biaya & omzet grup berkurang sebesar porsi biaya & omzet
      anggota itu (2 bulan terakhir), kurva respons ikut diskalakan.
    - Iklan tunggal yang dipindah ke grup / dijeda sampai restock: dikunci 0.
    - Jadikan iklan tunggal: iklan tunggal baru yang mulai dari biaya & omzet produk itu di grup asal.
    - Buat iklan tunggal: iklan baru, budget awal Rp 50 rb/hari, ROAS awal 70% ROAS toko.
    - `demand` tiap unit = prediksi omzet harian produk yang tinggal di unit itu (dasar batas kenaikan omzet iklan).
    Iklan Otomatis tidak ikut rencana."""
    prod = products.set_index("product_code") if not products.empty else pd.DataFrame(columns=["nama", "omzet_harian", "stok_room"])
    pred = prod["omzet_harian"].fillna(0.0).astype(float).to_dict() if "omzet_harian" in prod.columns else {}
    room = prod["stok_room"].to_dict() if "stok_room" in prod.columns else {}
    sel = selection if not selection.empty else pd.DataFrame(columns=["Saran", "Kode produk", "Biaya iklan/hari", "Omzet iklan/hari", "_unit", "Produk"])
    claimed = set(sel["Kode produk"].astype(str))
    out: list[Unit] = []
    for u in units:
        if u.jenis not in ("Produk tunggal", "Grup"):
            continue
        rows = sel.loc[sel["_unit"] == u.key]
        moved = rows.loc[rows["Saran"].isin(MOVE_OUT)]
        kept = rows.loc[~rows["Saran"].isin(MOVE_OUT)]
        nu = Unit(u.key, u.nama, u.jenis, u.status, u.mode, u.daily_cost, u.daily_sales, u.a, u.b, u.spread, list(u.members),
                  list(u.history), u.contribution, u.stock_room)
        if rows.empty:
            codes = [c for c in u.members if c not in claimed]
        else:
            codes = kept["Kode produk"].astype(str).tolist()
        if u.jenis == "Produk tunggal":
            if not moved.empty:
                nu.locked, nu.origin = True, str(moved["Saran"].iloc[0])
        elif not moved.empty:
            tot_c, tot_s = float(rows["Biaya iklan/hari"].sum()), float(rows["Omzet iklan/hari"].sum())
            fc = float(moved["Biaya iklan/hari"].sum()) / tot_c if tot_c > 0 else len(moved) / len(rows)
            fs = float(moved["Omzet iklan/hari"].sum()) / tot_s if tot_s > 0 else len(moved) / len(rows)
            if kept.empty:
                nu.locked, nu.origin = True, "semua anggota dilepas"
            nu.daily_cost *= 1 - fc
            nu.daily_sales *= 1 - fs
            nu.a *= 1 - fs
            nu.b = max(nu.b * (1 - fc), 1.0)
            gone = set(moved["Kode produk"].astype(str))
            nu.members = [c for c in u.members if c not in gone]
            if not nu.locked:
                dup = int((moved["Saran"] == "Sudah di iklan lain").sum())
                parts = [f"{len(moved) - dup} anggota dilepas (lihat Pemilihan produk)"] if len(moved) > dup else []
                if dup:
                    parts.append(f"keluarkan {dup} produk yang sudah diiklankan di iklan lain sebelum mengaktifkan")
                nu.origin = "; ".join(parts)
        nu.demand = float(sum(pred.get(c, 0.0) for c in codes))
        rooms = [room[c] for c in codes if c in room and pd.notna(room[c])]
        if rooms:
            nu.stock_room = float(sum(rooms))
        out.append(nu)
    by_key = {u.key: u for u in units}
    split = sel.loc[sel["Saran"] == "Jadikan iklan tunggal"]
    for r in split.itertuples(index=False):
        code, parent = str(r[sel.columns.get_loc("Kode produk")]), by_key.get(str(r[sel.columns.get_loc("_unit")]))
        rows = sel.loc[sel["_unit"] == (parent.key if parent else "")]
        tot_c, tot_s = float(rows["Biaya iklan/hari"].sum()), float(rows["Omzet iklan/hari"].sum())
        mine_c, mine_s = float(r[sel.columns.get_loc("Biaya iklan/hari")]), float(r[sel.columns.get_loc("Omzet iklan/hari")])
        cost = parent.daily_cost * mine_c / tot_c if parent and tot_c > 0 else mine_c
        sales = parent.daily_sales * mine_s / tot_s if parent and tot_s > 0 else mine_s
        status = parent.status if parent else "Berjalan"
        b = max(cost, 1.0)
        a = sales / math.log(2) if cost > 0 else 0.0
        contrib = contribution_by_code.get(code)
        out.append(Unit(f"pisah:{code}", str(r[sel.columns.get_loc("Produk")]), "Produk tunggal (dari grup)", status, "GMV Max ROAS",
                        cost, sales, a, b, 0.35, [code], [], float(contrib) if contrib is not None else float("nan"),
                        float(room[code]) if code in room and pd.notna(room[code]) else float("inf"),
                        demand=pred.get(code, 0.0), origin=parent.nama if parent else ""))
    roas0 = max(_store_roas(units) * 0.7, 1.0)
    for r in sel.loc[sel["Saran"] == "Buat iklan tunggal"].itertuples(index=False):
        code = str(r[sel.columns.get_loc("Kode produk")])
        contrib = contribution_by_code.get(code)
        out.append(Unit(f"baru:{code}", str(r[sel.columns.get_loc("Produk")]), "Produk tunggal (baru)", "Usulan", "GMV Max ROAS", 0.0, 0.0,
                        roas0 * NEW_DAILY / math.log(2), NEW_DAILY, 0.5, [code], [], float(contrib) if contrib is not None else float("nan"),
                        float(room[code]) if code in room and pd.notna(room[code]) else float("inf"), demand=pred.get(code, 0.0)))
    return out


def _unit_of(selection: pd.DataFrame, plan_units: list[Unit]) -> list[str]:
    keys = {u.key for u in plan_units}
    out = []
    for saran, code, unit in zip(selection["Saran"], selection["Kode produk"].astype(str), selection["_unit"]):
        if saran == "Jadikan iklan tunggal":
            out.append(f"pisah:{code}")
        elif saran == "Buat iklan tunggal":
            out.append(f"baru:{code}")
        elif saran in MOVE_OUT or saran == "Tambahkan ke grup":
            out.append("")
        else:
            out.append(unit if unit in keys else "")
    return out


def build_plan(units: list[Unit], members: pd.DataFrame, products: pd.DataFrame, contribution_by_code: dict[str, float], *,
               gap_daily: float, target_roas: float, budget_daily: float | None, lift: float = DEMAND_LIFT,
               stock_cap: bool = False, select_roas: float | None = None) -> tuple[list[Unit], Plan, pd.DataFrame]:
    """Satu alur: pemilihan produk → susunan iklan baru → rencana budget, sehingga langkah 3 & 4 selalu sejalan.

    Iklan tunggal baru / hasil pisah yang tidak mendapat budget di rencana dikembalikan (tetap di grup / masuk grup),
    lalu rencana dihitung ulang. stock_cap: tambahan omzet tiap iklan juga dibatasi ruang stok produknya.
    select_roas: ROAS acuan pemilihan produk (bawaan = target_roas).
    Mengembalikan (unit rencana, rencana, pemilihan + kolom budget usulan)."""
    selection = product_selection(members, units, products, contribution_by_code,
                                  target_roas=target_roas if select_roas is None else select_roas)
    plan_units, plan = [], Plan("Kejar target", {}, {})
    for _ in range(3):
        plan_units = [replace(u, lift=lift) for u in restructure(units, selection, products, contribution_by_code)]
        if stock_cap:
            from src.core.ads_fixed import stock_capped

            plan_units = stock_capped(plan_units)
        plan = allocate_target(plan_units, gap_daily=gap_daily, target_roas=target_roas, budget_daily=budget_daily)
        idle = {u.members[0] for u in plan_units if u.jenis in NEW_KINDS and u.members and plan.cost.get(u.key, 0.0) <= 0}
        if selection.empty or not idle:
            break
        codes = selection["Kode produk"].astype(str)
        back = codes.isin(idle) & (selection["Saran"] == "Jadikan iklan tunggal")
        group = codes.isin(idle) & (selection["Saran"] == "Buat iklan tunggal")
        selection = selection.copy()
        selection.loc[back, "Saran"] = "Pertahankan di grup"
        selection.loc[back, "Alasan"] = "tetap di grup minggu ini: pada setelan ROAS/budget ini belum perlu budget sendiri"
        selection.loc[group, "Saran"] = "Tambahkan ke grup"
        selection.loc[group, "Alasan"] = "belum dapat budget sendiri pada setelan ini: masukkan ke grup produk sejenis"
        selection = _sort_selection(selection)
    if not selection.empty:
        by_key = {u.key: u for u in plan_units}
        keys = _unit_of(selection, plan_units)
        selection = selection.assign(
            **{"Iklan di rencana": [("Grup: " + by_key[k].nama if by_key[k].jenis == "Grup" else "Iklan tunggal") if k in by_key else "–" for k in keys],
               "Budget usulan iklan/hari": [plan.cost.get(k, np.nan) if k in by_key else np.nan for k in keys]})
    return plan_units, plan, selection


# ---------------------------------------------------------------- Rencana bertahap per minggu & rekomendasi


def week_blocks(start: date, end: date) -> list[tuple[date, date]]:
    """Blok 7 hari dari `start` s.d. `end` (blok terakhir bisa lebih pendek): budget dievaluasi & diubah tiap blok."""
    out, day = [], start
    while day <= end:
        last = min(day + timedelta(days=6), end)
        out.append((day, last))
        day = last + timedelta(days=1)
    return out


def _carry(u: Unit, cost: float) -> Unit:
    """Unit untuk minggu berikutnya: budget minggu ini menjadi titik awal (batas 2× Shopee berlaku dari sini), sisa batas
    permintaan dikurangi tambahan yang sudah dipakai."""
    if u.locked:
        return u
    sales = ad_sales(u, cost)
    used = sales - _now_sales(u)
    demand = (max(uplift_cap(u) - used, 0.0) / u.lift) if np.isfinite(u.demand) and u.lift > 0 else u.demand
    return replace(u, status="Berjalan" if cost > 0 else "Dijeda", daily_cost=cost, daily_sales=sales, demand=demand)


def ramp(units: list[Unit], *, weeks: list[int], gap_total: float, target_roas: float, budget_total: float | None,
         first: Plan | None = None) -> list[tuple[int, Plan]]:
    """Rencana per minggu: tiap minggu budget per iklan boleh naik maks. 2× (turun ke ≥ ½) dari minggu sebelumnya, sisa
    kekurangan omzet & sisa budget dibagi rata ke hari yang tersisa. Mengembalikan [(jumlah hari, rencana minggu itu)]."""
    base_now = sum(_now_sales(u) for u in units)
    current, spent, gained, days_left = list(units), 0.0, 0.0, sum(weeks)
    out: list[tuple[int, Plan]] = []
    for index, days in enumerate(weeks):
        if days <= 0:
            continue
        carried = sum(_now_sales(u) for u in current) - base_now
        gap_daily = max((gap_total - gained) / days_left - carried, 0.0)
        budget_daily = None if budget_total is None else max(budget_total - spent, 0.0) / days_left
        plan = first if index == 0 and first is not None else allocate_target(current, gap_daily=gap_daily, target_roas=target_roas, budget_daily=budget_daily)
        out.append((days, plan))
        spent += sum(plan.cost.values()) * days
        gained += (sum(ad_sales(u, plan.cost[u.key]) for u in units) - base_now) * days
        days_left -= days
        current = [_carry(u, plan.cost[u.key]) for u in units]
    return out


def ramp_effect(units: list[Unit], steps: list[tuple[int, Plan]]) -> dict:
    """Jumlah `plan_effect` semua minggu (selalu relatif terhadap kondisi iklan sekarang)."""
    keys = ("biaya_total", "biaya_tambahan", "omzet_tambahan", "omzet_iklan", "dampak_margin")
    total = {k: 0.0 for k in keys}
    lo = hi = 0.0
    known = True
    for days, plan in steps:
        e = plan_effect(units, plan, days=days)
        for k in keys:
            total[k] += e[k]
        lo, hi = lo + e["rentang"][0], hi + e["rentang"][1]
        known &= e["margin_lengkap"]
    total["rentang"] = (lo, hi)
    total["roas_rencana"] = total["omzet_iklan"] / total["biaya_total"] if total["biaya_total"] > 0 else float("nan")
    total["margin_lengkap"] = known
    return total


def weekly_table(units: list[Unit], steps: list[tuple[int, Plan]], blocks: list[tuple[date, date]]) -> pd.DataFrame:
    rows = []
    for i, ((days, plan), (a, b)) in enumerate(zip(steps, blocks), start=1):
        cost = sum(plan.cost.values())
        sales = sum(ad_sales(u, plan.cost[u.key]) for u in units)
        rows.append({"Minggu": i, "Mulai": a, "Selesai": b, "Hari": days, "Budget/hari": cost, "Omzet iklan/hari": sales,
                     "ROAS": sales / cost if cost > 0 else np.nan, "Tambahan omzet": (sales - sum(_now_sales(u) for u in units)) * days,
                     "Iklan aktif": sum(1 for v in plan.cost.values() if v > 0)})
    return pd.DataFrame(rows)


def unit_weekly_budget(units: list[Unit], steps: list[tuple[int, Plan]]) -> pd.DataFrame:
    """Budget harian per iklan per minggu (untuk unduhan & evaluasi)."""
    rows = []
    for u in units:
        values = [plan.cost.get(u.key, 0.0) for _d, plan in steps]
        if _base(u) <= 0 and not any(v > 0 for v in values):
            continue
        rows.append({"_key": u.key, "Iklan": u.nama, "Jenis": u.jenis, "Budget sekarang/hari": _base(u),
                     **{f"Minggu {i}": v for i, v in enumerate(values, start=1)}})
    return pd.DataFrame(rows)


ROAS_GRID = (30, 25, 20, 18, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1)


def recommend(units: list[Unit], members: pd.DataFrame, products: pd.DataFrame, contribution_by_code: dict[str, float], *,
              weeks: list[int], gap_total: float, grid: tuple[float, ...] = ROAS_GRID, lift: float = DEMAND_LIFT,
              stock_cap: bool = False) -> dict:
    """Target ROAS tertinggi + budget yang menutup kekurangan omzet dengan iklan saja (rencana bertahap per minggu).

    Bila tidak ada ROAS yang menutupnya, dipilih ROAS tertinggi yang memberi ≥ 99% tambahan omzet maksimal (budget di
    bawah ROAS itu tidak menambah omzet lagi). Mengembalikan roas, budget (total), tambahan, tercapai (bool), dan tabel."""
    days = max(sum(weeks), 1)
    rows, best = [], None
    for r in grid:
        plan_units, first, _sel = build_plan(units, members, products, contribution_by_code, gap_daily=gap_total / days, target_roas=r, budget_daily=None, lift=lift,
                                             stock_cap=stock_cap)
        steps = ramp(plan_units, weeks=weeks, gap_total=gap_total, target_roas=r, budget_total=None, first=first)
        eff = ramp_effect(plan_units, steps)
        rows.append({"roas": float(r), "budget": eff["biaya_total"], "tambahan": eff["omzet_tambahan"], "roas_rencana": eff["roas_rencana"]})
        if eff["omzet_tambahan"] >= gap_total - 1:
            best = rows[-1]
            break
        if len(rows) >= 4 and max(x["tambahan"] for x in rows[-3:]) <= rows[-4]["tambahan"] * 1.005:
            break
    table = pd.DataFrame(rows)
    if best is None and not table.empty:
        top = table["tambahan"].max()
        best = table.loc[table["tambahan"] >= top - abs(top) * 0.01].iloc[0].to_dict()
    best = dict(best or {"roas": float(grid[0]), "budget": 0.0, "tambahan": 0.0, "roas_rencana": float("nan")})
    best["tercapai"] = bool(best["tambahan"] >= gap_total - 1)
    best["budget"] = math.ceil(best["budget"] / 1_000_000) * 1_000_000
    return {**best, "tabel": table}


def month_totals(units: list[Unit]) -> dict[str, dict]:
    """Total biaya & omzet periode laporan terakhir per iklan (laporan bulan berjalan bersifat kumulatif s.d. tanggal laporan)."""
    out = {}
    for u in units:
        if not u.history or u.last_days <= 0:
            continue
        period, cost, sales = u.history[-1]
        out[u.key] = {"periode": period, "hari": int(u.last_days), "biaya": cost * u.last_days, "omzet": sales * u.last_days}
    return out


def evaluate(baseline: dict[str, dict], current: dict[str, dict], planned: dict[str, float], *, target_roas: float) -> tuple[pd.DataFrame, dict]:
    """Pelaksanaan campaign dari laporan iklan terbaru: biaya & omzet harian sejak campaign disimpan (selisih laporan kumulatif).

    planned: budget harian usulan per iklan (kunci unit). Dijalankan = biaya aktual 60–140% budget usulan (atau ≈ 0 bila dijeda)."""
    rows = []
    base_days = {v.get("periode"): int(v.get("hari", 0)) for v in baseline.values()}
    for key, plan_cost in planned.items():
        report_key = "produk:" + key.split(":", 1)[1] if key.startswith(("pisah:", "baru:")) else key
        cur, base = current.get(key) or current.get(report_key), baseline.get(key) or baseline.get(report_key)
        if cur is None:
            continue
        if base is None and cur["periode"] in base_days:
            base = {"periode": cur["periode"], "hari": base_days[cur["periode"]], "biaya": 0.0, "omzet": 0.0}
        if base and base.get("periode") == cur["periode"]:
            days = cur["hari"] - int(base.get("hari", 0))
            cost, sales = cur["biaya"] - float(base.get("biaya", 0)), cur["omzet"] - float(base.get("omzet", 0))
        else:
            days, cost, sales = cur["hari"], cur["biaya"], cur["omzet"]
        if days <= 0:
            continue
        cost_d, sales_d = cost / days, sales / days
        if plan_cost <= 0:
            done = cost_d <= max(5_000.0, 0.1 * float((base or {}).get("biaya", 0)) / max(int((base or {}).get("hari", 1)), 1))
        else:
            done = 0.6 <= cost_d / plan_cost <= 1.4
        rows.append({"_key": key, "Hari dievaluasi": days, "Budget usulan/hari": plan_cost, "Biaya aktual/hari": cost_d, "Omzet iklan aktual/hari": sales_d,
                     "ROAS aktual": sales_d / cost_d if cost_d > 0 else np.nan, "Rekomendasi dijalankan": "Ya" if done else "Belum"})
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame, {}
    cost, sales = frame["Biaya aktual/hari"].sum(), frame["Omzet iklan aktual/hari"].sum()
    return frame, {"hari": int(frame["Hari dievaluasi"].max()), "dijalankan": int((frame["Rekomendasi dijalankan"] == "Ya").sum()), "iklan": len(frame),
                   "biaya_harian": cost, "omzet_harian": sales, "roas": sales / cost if cost > 0 else float("nan"), "target_roas": target_roas,
                   "budget_usulan_harian": float(frame["Budget usulan/hari"].sum())}
