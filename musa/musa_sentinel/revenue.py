"""Revenue forecaster over the pricing catalogue. Deterministic, assumption-driven, no magic."""
import json
import os

from . import DATA_DIR

SCENARIOS = {"conservative": 0.5, "base": 1.0, "aggressive": 1.8}


def load_pricing(path=None):
    with open(path or os.path.join(DATA_DIR, "pricing.json"), encoding="utf-8") as f:
        return json.load(f)


def _volume(p, month, mult):
    """Units sold (one_off) or new subscribers (monthly) in `month` (1-based)."""
    start = p.get("start_month", 1)
    if month < start:
        return 0.0
    if p.get("add_per_month") is not None:
        if p["type"] == "monthly":
            # New subscribers per month: start_volume in the launch month, then a steady add.
            base = p.get("start_volume", 0) if month == start else p["add_per_month"]
        else:
            # One-off sales ramp linearly.
            base = p.get("start_volume", 0) + p["add_per_month"] * (month - start)
    else:
        base = p.get("volume", 0) * (p.get("growth", 1.0) ** (month - start))
    return base * mult


def forecast(months=12, scenario="base", pricing=None):
    pricing = pricing or load_pricing()
    mult = SCENARIOS[scenario]
    fixed = sum(pricing.get("fixed_costs_monthly", {}).values())
    subs = {p["id"]: 0.0 for p in pricing["products"] if p["type"] == "monthly"}
    rows, cumulative = [], 0.0
    for m in range(1, months + 1):
        revenue, cogs, per_product = 0.0, 0.0, {}
        for p in pricing["products"]:
            v = _volume(p, m, mult)
            if p["type"] == "monthly":
                subs[p["id"]] = subs[p["id"]] * (1 - p.get("churn", 0)) + v
                units = subs[p["id"]]
            else:
                units = v
            r = units * p["price"]
            revenue += r
            cogs += units * p.get("cogs", 0)
            if r:
                per_product[p["id"]] = round(r)
        mrr = sum(subs[p["id"]] * p["price"] for p in pricing["products"] if p["type"] == "monthly")
        profit = revenue - cogs - fixed
        cumulative += profit
        rows.append({"month": m, "revenue": round(revenue), "mrr": round(mrr), "cogs": round(cogs), "fixed": round(fixed),
                     "profit": round(profit), "cumulative_profit": round(cumulative), "by_product": per_product})
    breakeven = next((r["month"] for r in rows if r["profit"] > 0), None)
    return {"scenario": scenario, "currency": pricing.get("currency", "EUR"), "rows": rows,
            "total_revenue": sum(r["revenue"] for r in rows), "total_profit": round(cumulative),
            "first_profitable_month": breakeven, "ending_mrr": rows[-1]["mrr"] if rows else 0}


def format_table(fc):
    lines = ["%-6s %10s %8s %8s %10s %12s" % ("Month", "Revenue", "MRR", "COGS", "Profit", "Cumulative")]
    for r in fc["rows"]:
        lines.append("%-6d %10d %8d %8d %10d %12d" % (r["month"], r["revenue"], r["mrr"], r["cogs"], r["profit"], r["cumulative_profit"]))
    lines.append("Scenario %s · total revenue %s %d · ending MRR %d · first profitable month: %s"
                 % (fc["scenario"], fc["currency"], fc["total_revenue"], fc["ending_mrr"], fc["first_profitable_month"]))
    return "\n".join(lines)
