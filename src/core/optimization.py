from __future__ import annotations

import numpy as np
import pandas as pd


def eoq(*, annual_demand: float, order_cost: float, holding_cost: float) -> float:
    demand = max(float(annual_demand), 0.0)
    setup = max(float(order_cost), 0.0)
    hold = max(float(holding_cost), 1e-9)
    return float(np.sqrt((2 * demand * setup) / hold)) if demand > 0 and setup > 0 else 0.0


def monte_carlo_stock_scenarios(
    *,
    demand_mean: float,
    demand_sigma: float,
    lead_time_mean: float,
    lead_time_sigma: float,
    current_stock: float,
    safety_stock: float,
    simulations: int = 1000,
    random_state: int = 42,
) -> pd.DataFrame:
    rng = np.random.default_rng(random_state)
    demand = rng.normal(float(demand_mean), max(float(demand_sigma), 0.0), int(simulations)).clip(min=0)
    lead = rng.normal(float(lead_time_mean), max(float(lead_time_sigma), 0.0), int(simulations)).clip(min=0)
    required = demand * lead + max(float(safety_stock), 0.0)
    stock = max(float(current_stock), 0.0)
    shortage = np.maximum(required - stock, 0.0)
    quantiles = {
        "Pesimistis": 0.90,
        "Moderat": 0.50,
        "Optimistis": 0.10,
    }
    rows = []
    for name, q in quantiles.items():
        need = float(np.quantile(required, q))
        short = float(np.quantile(shortage, q))
        rows.append(
            {
                "Skenario": name,
                "Kebutuhan": need,
                "Restock disarankan": max(short, 0.0),
                "Risiko stockout": float(np.mean(shortage > 0) * 100),
            }
        )
    return pd.DataFrame(rows)


def optimize_restock(
    items: pd.DataFrame,
    *,
    capacity: float = 1_000_000.0,
    moq: float = 1.0,
    holding_cost: float = 1.0,
    stockout_cost: float = 10.0,
    time_limit_seconds: int = 5,
) -> pd.DataFrame:
    """MILP optional; fallback heuristik EOQ/ROP bila PuLP tidak tersedia."""
    if items is None or items.empty:
        return pd.DataFrame()
    try:
        return _optimize_restock_pulp(
            items,
            capacity=capacity,
            moq=moq,
            holding_cost=holding_cost,
            stockout_cost=stockout_cost,
            time_limit_seconds=time_limit_seconds,
        )
    except Exception:
        return _optimize_restock_fallback(items, capacity=capacity, moq=moq)


def _optimize_restock_fallback(items: pd.DataFrame, *, capacity: float, moq: float) -> pd.DataFrame:
    out = items.copy()
    for column in ("kebutuhan", "current_stock", "rop"):
        if column not in out.columns:
            out[column] = 0.0
    out["shortage"] = (out["kebutuhan"].astype(float) - out["current_stock"].astype(float)).clip(lower=0.0)
    out["restock_qty"] = np.ceil(out["shortage"].clip(lower=float(moq)) * (out["shortage"] > 0))
    total = float(out["restock_qty"].sum())
    if total > float(capacity) > 0:
        out["restock_qty"] = np.floor(out["restock_qty"] * (float(capacity) / total))
    out["optimizer_status"] = "fallback EOQ/ROP"
    return out


def _optimize_restock_pulp(
    items: pd.DataFrame,
    *,
    capacity: float,
    moq: float,
    holding_cost: float,
    stockout_cost: float,
    time_limit_seconds: int,
) -> pd.DataFrame:
    import pulp

    work = items.reset_index(drop=True).copy()
    for column in ("kebutuhan", "current_stock"):
        if column not in work.columns:
            work[column] = 0.0
    model = pulp.LpProblem("restock_optimization", pulp.LpMinimize)
    qty_vars = {i: pulp.LpVariable(f"restock_{i}", lowBound=0, cat="Integer") for i in work.index}
    slack_vars = {i: pulp.LpVariable(f"slack_{i}", lowBound=0) for i in work.index}
    active_vars = {i: pulp.LpVariable(f"active_{i}", lowBound=0, upBound=1, cat="Binary") for i in work.index}
    big_m = max(float(work["kebutuhan"].max() or 0) * 2, float(capacity), 1.0)
    warm = _optimize_restock_fallback(work, capacity=capacity, moq=moq)
    for i in work.index:
        start_qty = float(warm.loc[i, "restock_qty"])
        qty_vars[i].setInitialValue(start_qty)
        active_vars[i].setInitialValue(1 if start_qty > 0 else 0)
    model += pulp.lpSum(
        holding_cost * qty_vars[i] + stockout_cost * slack_vars[i]
        for i in work.index
    )
    model += pulp.lpSum(qty_vars[i] for i in work.index) <= float(capacity)
    for i, row in work.iterrows():
        need = float(row["kebutuhan"])
        stock = float(row["current_stock"])
        model += stock + qty_vars[i] + slack_vars[i] >= need
        model += qty_vars[i] >= float(moq) * active_vars[i]
        model += qty_vars[i] <= big_m * active_vars[i]
    solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=int(time_limit_seconds), gapRel=0.01, warmStart=True)
    model.solve(solver)
    work["restock_qty"] = [float(qty_vars[i].value() or 0.0) for i in work.index]
    work["stockout_slack"] = [float(slack_vars[i].value() or 0.0) for i in work.index]
    work["optimizer_status"] = pulp.LpStatus.get(model.status, "unknown")
    return work


def price_elasticity(orders: pd.DataFrame, *, sku_col: str = "item_key", min_points: int = 6) -> pd.DataFrame:
    """Elastisitas harga per SKU dari regresi log-log harga bersih harian vs qty harian."""
    columns = [sku_col, "elastisitas", "titik_harga"]
    if orders is None or orders.empty or not {sku_col, "order_time", "qty", "sales"} <= set(orders.columns):
        return pd.DataFrame(columns=columns)
    work = orders[[sku_col, "order_time", "qty", "sales"]].copy()
    work["day"] = pd.to_datetime(work["order_time"], errors="coerce").dt.normalize()
    daily = work.groupby([sku_col, "day"], as_index=False).agg(qty=("qty", "sum"), sales=("sales", "sum"))
    daily = daily.loc[daily["qty"].gt(0) & daily["sales"].gt(0)]
    daily["price"] = daily["sales"] / daily["qty"]
    rows = []
    for key, group in daily.groupby(sku_col):
        if len(group) < min_points or group["price"].nunique() < 3:
            continue
        x = np.log(group["price"].to_numpy(dtype=float))
        y = np.log(group["qty"].to_numpy(dtype=float))
        if np.std(x) <= 1e-6:
            continue
        slope = float(np.polyfit(x, y, 1)[0])
        rows.append({sku_col: key, "elastisitas": float(np.clip(slope, -5, 1)), "titik_harga": int(len(group))})
    return pd.DataFrame(rows, columns=columns)


def markdown_schedule(
    *,
    price: float,
    unit_cost: float,
    margin_min_pct: float,
    elasticity: float | None,
    weekly_qty: float,
    steps: tuple[float, ...] = (0.05, 0.10, 0.15, 0.20),
) -> pd.DataFrame:
    """Markdown bertahap mingguan; berhenti di batas margin minimum dari config."""
    rows = []
    floor = unit_cost * (1 + margin_min_pct / 100.0)
    e = -1.2 if elasticity is None or not np.isfinite(elasticity) or elasticity >= 0 else float(elasticity)
    for week, cut in enumerate(steps, start=1):
        new_price = price * (1 - cut)
        if new_price < floor:
            break
        lift = (1 - cut) ** e
        rows.append(
            {
                "Minggu": week,
                "Diskon": cut * 100,
                "Harga": round(new_price),
                "Perkiraan QTY/minggu": weekly_qty * lift,
                "Margin (%)": (new_price - unit_cost) / new_price * 100 if new_price > 0 else 0.0,
            }
        )
    return pd.DataFrame(rows)

