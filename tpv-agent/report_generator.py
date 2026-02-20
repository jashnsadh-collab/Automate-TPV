import os
from datetime import datetime
import numpy as np
import pandas as pd
from tabulate import tabulate
from config import OUTPUT_DIR


def _fmt(val: float) -> str:
    if abs(val) >= 1_000_000:
        return f"{val/1_000_000:,.2f}M"
    if abs(val) >= 1_000:
        return f"{val/1_000:,.1f}K"
    return f"{val:,.0f}"


def _pct(val: float) -> str:
    sign = "+" if val > 0 else ""
    return f"{sign}{val:.1f}%"


def generate_report(
    region_data: dict,
    predictions: dict,
    category_data: dict,
    model_stats: dict,
    backtest: dict,
    monthly: pd.DataFrame,
    alerts: list,
    today: datetime,
) -> str:
    active_regions = list(region_data.keys())
    lines = []
    lines.append("=" * 70)
    lines.append(f"  TPV DAILY PREDICTIONS REPORT — {today.strftime('%A, %B %d, %Y')}")
    lines.append("=" * 70)
    lines.append("")

    # --- Section 1: Today's Summary ---
    lines.append("## TODAY'S SUMMARY")
    lines.append("-" * 40)
    summary_rows = []
    for region in active_regions:
        hist = region_data[region]
        if hist.empty:
            continue
        latest = hist.iloc[-1]
        prev = hist.iloc[-2] if len(hist) >= 2 else latest
        week_ago = hist.iloc[-8] if len(hist) >= 8 else latest
        dod_change = ((latest["Daily_TPV"] - prev["Daily_TPV"]) / max(prev["Daily_TPV"], 1)) * 100
        wow_change = ((latest["Daily_TPV"] - week_ago["Daily_TPV"]) / max(week_ago["Daily_TPV"], 1)) * 100
        summary_rows.append([
            region,
            latest["Date"].strftime("%Y-%m-%d"),
            _fmt(latest["Daily_TPV"]),
            _pct(dod_change),
            _pct(wow_change),
            f"{int(latest['Transactions']):,}",
            f"{int(latest['Users']):,}",
        ])
    total_latest = sum(region_data[r].iloc[-1]["Daily_TPV"] for r in active_regions if not region_data[r].empty)
    lines.append(tabulate(summary_rows,
        headers=["Region", "Date", "TPV", "DoD %", "WoW %", "Txns", "Users"],
        tablefmt="simple_outline"))
    lines.append(f"\n  Combined TPV: {_fmt(total_latest)}")
    lines.append("")

    # --- Section 2: Month-to-Date ---
    lines.append("## MONTH-TO-DATE")
    lines.append("-" * 40)
    for region in active_regions:
        hist = region_data[region]
        if hist.empty:
            continue
        current_month = hist.iloc[-1]["Date"].month
        current_year = hist.iloc[-1]["Date"].year
        mtd = hist[(hist["Date"].dt.month == current_month) & (hist["Date"].dt.year == current_year)]
        mtd_total = mtd["Daily_TPV"].sum()
        days_elapsed = len(mtd)
        days_in_month = pd.Timestamp(current_year, current_month, 1).days_in_month
        projected_month = (mtd_total / max(days_elapsed, 1)) * days_in_month
        lines.append(f"  {region}: MTD {_fmt(mtd_total)} ({days_elapsed} days) → Projected month: {_fmt(projected_month)}")
    lines.append("")

    # --- Section 3: Predictions ---
    lines.append("## PREDICTIONS (Next 7 Days)")
    lines.append("-" * 40)
    for region in active_regions:
        pred = predictions[region]
        if pred.empty:
            continue
        lines.append(f"\n  {region}:")
        pred_rows = []
        for _, row in pred.head(7).iterrows():
            d = pd.Timestamp(row["Date"])
            pred_rows.append([
                d.strftime("%Y-%m-%d"),
                d.strftime("%a"),
                _fmt(row["Ensemble"]),
                _fmt(row["Low"]),
                _fmt(row["High"]),
            ])
        lines.append(tabulate(pred_rows,
            headers=["Date", "Day", "Predicted TPV", "Low", "High"],
            tablefmt="simple_outline"))
    lines.append("")

    # --- Section 4: Category Breakdown ---
    if category_data:
        lines.append("## CATEGORY BREAKDOWN (Latest Day)")
        lines.append("-" * 40)
        for region in active_regions:
            cat_df = category_data.get(region)
            if cat_df is None or cat_df.empty:
                continue
            latest_date = cat_df["Date"].max()
            day_data = cat_df[cat_df["Date"] == latest_date]
            total = day_data["Daily_TPV"].sum()
            lines.append(f"\n  {region} ({latest_date.strftime('%Y-%m-%d')}):")
            cat_rows = []
            for _, row in day_data.iterrows():
                share = (row["Daily_TPV"] / max(total, 1)) * 100
                cat_rows.append([row["Category"], _fmt(row["Daily_TPV"]), f"{share:.1f}%"])
            cat_rows.append(["TOTAL", _fmt(total), "100.0%"])
            lines.append(tabulate(cat_rows,
                headers=["Category", "TPV", "Share"],
                tablefmt="simple_outline"))

            # 7-day trend per category
            last_7 = cat_df[cat_df["Date"] >= (latest_date - pd.Timedelta(days=6))]
            if not last_7.empty:
                trend_rows = []
                for cat in last_7["Category"].unique():
                    cat_vals = last_7[last_7["Category"] == cat]["Daily_TPV"]
                    trend_rows.append([cat, _fmt(cat_vals.mean()), _fmt(cat_vals.min()), _fmt(cat_vals.max())])
                lines.append(f"\n  {region} 7-Day Category Trend:")
                lines.append(tabulate(trend_rows,
                    headers=["Category", "Avg", "Min", "Max"],
                    tablefmt="simple_outline"))
        lines.append("")

    # --- Section 5: Monthly History ---
    lines.append("## MONTHLY TPV HISTORY (Last 6 Months)")
    lines.append("-" * 40)
    recent = monthly.tail(8)
    month_rows = []
    for _, row in recent.iterrows():
        month_rows.append([
            row["Month"],
            row["Type"],
            _fmt(row["UAE_TPV"]),
            _fmt(row["UK_TPV"]),
            _fmt(row["Total_TPV"]),
        ])
    lines.append(tabulate(month_rows,
        headers=["Month", "Type", "UAE TPV", "UK TPV", "Total"],
        tablefmt="simple_outline"))
    lines.append("")

    # --- Section 6: Model Performance ---
    lines.append("## MODEL PERFORMANCE")
    lines.append("-" * 40)
    for region in active_regions:
        stats = model_stats.get(region, {})
        bt = backtest.get(region, {})
        lines.append(f"\n  {region}:")
        lines.append(f"    Linear R²: {stats.get('linear_r2', 'N/A')}  |  Slope: {_fmt(stats.get('linear_slope', 0))}/day")
        if bt:
            bt_rows = []
            for model_name, metrics in bt.items():
                bt_rows.append([model_name, f"{metrics['MAPE']}%", _fmt(metrics['RMSE'])])
            lines.append(tabulate(bt_rows,
                headers=["Model", "MAPE", "RMSE"],
                tablefmt="simple_outline"))
    lines.append("")

    # --- Section 7: Alerts ---
    if alerts:
        lines.append("## ALERTS & INSIGHTS")
        lines.append("-" * 40)
        for alert in alerts:
            lines.append(f"  ⚠  {alert}")
        lines.append("")

    lines.append("=" * 70)
    lines.append(f"  Report generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 70)
    return "\n".join(lines)


def save_report(content: str, today: datetime):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filename = f"daily_{today.strftime('%Y-%m-%d')}.md"
    filepath = os.path.join(OUTPUT_DIR, filename)
    with open(filepath, "w") as f:
        f.write(content)
    return filepath
