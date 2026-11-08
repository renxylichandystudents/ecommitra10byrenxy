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
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

STEP_DAILY = 25_000.0     # kenaikan alokasi per langkah (Rp/hari)
MAX_MULTIPLE = 3.0        # tambahan maksimal per unit = 3× biaya harian saat ini
NEW_DAILY = 50_000.0      # budget awal iklan produk tunggal baru (Rp/hari)
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
        item = hist.setdefault(key, {"nama": nama, "jenis": jenis, "points": {}, "status": status, "mode": mode, "period": ""})
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
                          [(k, c, s) for k, (c, s) in points]))
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


def ad_sales(u: Unit, cost: float) -> float:
    """Omzet iklan harian pada biaya `cost`: omzet aktual sekarang + perubahan menurut kurva respons."""
    return max(_now_sales(u) + u.sales_at(cost) - u.sales_at(_base(u)), 0.0)


def allocate_target(units: list[Unit], *, gap_daily: float, target_roas: float, budget_daily: float | None = None,
                    max_multiple: float = MAX_MULTIPLE) -> Plan:
    """Rencana mengejar target dengan ROAS & budget yang ditetapkan pengguna (margin dan stok tidak membatasi).

    Target ROAS = ROAS rata-rata seluruh iklan di rencana (total omzet iklan / total biaya iklan), sama dengan arti
    Target ROAS di Shopee.
    1. Budget dipindah dari iklan dengan tambahan omzet per Rp terendah ke yang tertinggi selama omzet naik.
    2. Bila biaya di atas budget atau ROAS rata-rata di bawah target, iklan yang paling tidak efektif dipangkas dulu.
    3. Sisa budget ditambahkan bertahap (Rp 25 rb/hari) ke iklan paling efektif sampai kekurangan omzet harian
       tertutup, selama ROAS rata-rata tetap ≥ target dan tambahan per iklan ≤ `max_multiple` × biaya saat ini.
    """
    floor = {u.key: float(target_roas) for u in units}
    cost = {u.key: _base(u) for u in units}
    caps = {u.key: max(u.daily_cost * (1 + max_multiple) if u.daily_cost > 0 else NEW_DAILY * 2, cost[u.key]) for u in units}
    sales = {u.key: ad_sales(u, cost[u.key]) for u in units}
    total_cost, total_sales = sum(cost.values()), sum(sales.values())
    target_left = gap_daily - sum(sales[u.key] - _now_sales(u) for u in units)

    def gain(u: Unit, step: float) -> float:
        return ad_sales(u, cost[u.key] + step) - sales[u.key]

    def loss(u: Unit, step: float) -> float:
        return sales[u.key] - ad_sales(u, cost[u.key] - step)

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
        donor = min(live, key=lambda u: loss(u, min(STEP_DAILY, cost[u.key])) / min(STEP_DAILY, cost[u.key]))
        step = min(STEP_DAILY, cost[donor.key])
        lost = loss(donor, step)
        best, best_gain = None, 0.0
        for u in units:
            if u.key != donor.key and cost[u.key] + step <= caps[u.key] + 1e-6:
                g = gain(u, step)
                if g > best_gain:
                    best, best_gain = u, g
        if best is None or best_gain <= lost + 1.0:
            break
        move(donor, -step)
        move(best, step)

    for _ in range(20_000):
        over_budget = budget_daily is not None and total_cost > budget_daily + 1e-6
        under_roas = total_cost > 0 and total_sales / total_cost < target_roas
        if not (over_budget or under_roas):
            break
        live = [u for u in units if cost[u.key] > 0]
        if not live:
            break
        worst = min(live, key=lambda u: loss(u, min(STEP_DAILY, cost[u.key])) / min(STEP_DAILY, cost[u.key]))
        cut = min(STEP_DAILY, cost[worst.key])
        if over_budget and not under_roas:
            cut = min(cut, total_cost - budget_daily)
        move(worst, -cut)

    for _ in range(8000):
        if target_left <= 0:
            break
        room = None if budget_daily is None else budget_daily - total_cost
        if room is not None and room < 1:
            break
        step = STEP_DAILY if room is None else min(STEP_DAILY, room)
        best, best_gain = None, 0.0
        for u in units:
            if cost[u.key] + step <= caps[u.key] + 1e-6:
                g = gain(u, step)
                if g > best_gain:
                    best, best_gain = u, g
        if best is None or (total_sales + best_gain) < target_roas * (total_cost + step):
            break
        move(best, step)
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
        if u.jenis.endswith("(baru)"):
            if new <= 0:
                continue
            act = "Buat iklan baru"
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
        if act in {"Turunkan budget", "Jeda"}:
            notes.append(f"tiap Rp 1 terakhir hanya kembali Rp {u.marginal(new):.1f}: dananya dipindah ke iklan yang lebih efektif".replace(".", ","))
        elif act in {"Naikkan budget", "Aktifkan kembali", "Buat iklan baru"}:
            notes.append(f"tiap Rp 1 tambahan kembali ±Rp {u.marginal(new):.1f}".replace(".", ","))
        if np.isfinite(u.stock_room) and d_sales > u.stock_room + 1:
            notes.append("⚠️ stok kurang untuk tambahan omzet ini: siapkan restock/PO")
        if np.isfinite(u.contribution) and u.contribution <= 0 and d_sales > 0:
            notes.append("margin minus: tambahan omzet ikut menambah rugi")
        planned = ad_sales(u, new)
        rows.append({
            "key": u.key, "Tindakan": act, "Iklan": u.nama, "Jenis": "Produk tunggal" if u.jenis.startswith("Produk tunggal") else u.jenis,
            "Anggota": len(u.members), "Budget harian sekarang": now, "Budget harian usulan": new,
            "Perubahan/hari": new - now, "Target ROAS Shopee": round(planned / new, 1) if new > 0 else np.nan,
            "ROAS bulan terakhir": u.roas, "Tambahan omzet/hari": d_sales, "Catatan": "; ".join(notes),
        })
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    order = {"Naikkan budget": 0, "Buat iklan baru": 1, "Aktifkan kembali": 2, "Turunkan budget": 3, "Jeda": 4, "Pertahankan": 5}
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
