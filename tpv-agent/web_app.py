#!/usr/bin/env python3
"""TPV Predictions Web Dashboard — UAE/UK markets."""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timedelta
from flask import Flask, render_template_string, jsonify, request
import pandas as pd
import numpy as np

from config import REGIONS, CATEGORIES, FORECAST_DAYS
from data_loader import (
    get_historical_region, load_category_data,
    load_monthly_summary, load_regression_stats,
)
from models import EnsembleForecaster

app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TPV Predictions — UAE / UK</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; }
  .header { background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); border-bottom: 1px solid #334155; padding: 24px 40px; }
  .header h1 { font-size: 24px; font-weight: 700; color: #f8fafc; }
  .header p { color: #94a3b8; font-size: 14px; margin-top: 4px; }
  .container { max-width: 1400px; margin: 0 auto; padding: 24px 40px; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }
  .grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px; margin-bottom: 20px; }
  .card { background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 24px; }
  .card h2 { font-size: 14px; font-weight: 600; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 16px; }
  .card h3 { font-size: 13px; font-weight: 600; color: #64748b; margin: 16px 0 8px; }
  .big-number { font-size: 32px; font-weight: 700; color: #f8fafc; }
  .big-number.green { color: #34d399; }
  .big-number.red { color: #f87171; }
  .big-number.blue { color: #60a5fa; }
  .sub-text { font-size: 13px; color: #94a3b8; margin-top: 4px; }
  .change { font-size: 14px; font-weight: 600; display: inline-block; padding: 2px 8px; border-radius: 4px; margin-left: 8px; }
  .change.up { background: #064e3b; color: #34d399; }
  .change.down { background: #7f1d1d; color: #f87171; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th { text-align: left; padding: 10px 12px; color: #94a3b8; font-weight: 500; border-bottom: 1px solid #334155; font-size: 12px; text-transform: uppercase; }
  td { padding: 10px 12px; border-bottom: 1px solid #1e293b; color: #e2e8f0; }
  tr:hover td { background: #334155; }
  .badge { display: inline-block; padding: 3px 10px; border-radius: 9999px; font-size: 12px; font-weight: 600; }
  .badge-green { background: #064e3b; color: #34d399; }
  .badge-red { background: #7f1d1d; color: #f87171; }
  .badge-yellow { background: #78350f; color: #fbbf24; }
  .badge-blue { background: #1e3a5f; color: #60a5fa; }
  .progress-bar { height: 8px; background: #334155; border-radius: 4px; overflow: hidden; margin-top: 8px; }
  .progress-fill { height: 100%; border-radius: 4px; transition: width 0.5s; }
  .alert { background: #1c1917; border-left: 4px solid #f59e0b; padding: 12px 16px; border-radius: 0 8px 8px 0; margin-bottom: 8px; font-size: 14px; color: #fbbf24; }
  .section-title { font-size: 18px; font-weight: 700; color: #f8fafc; margin: 32px 0 16px; padding-bottom: 8px; border-bottom: 1px solid #334155; }
  .cat-bar { display: flex; height: 32px; border-radius: 6px; overflow: hidden; margin: 8px 0; }
  .cat-bar div { display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 600; color: #fff; }
  .cat-referred { background: #3b82f6; }
  .cat-nonreferred { background: #10b981; }
  .cat-whale { background: #f59e0b; }
  .timestamp { text-align: center; color: #475569; font-size: 12px; padding: 24px; }
</style>
</head>
<body>
<div class="header">
  <h1>TPV Predictions Dashboard</h1>
  <p>UAE / UK — {{ today }}</p>
</div>
<div class="container">

  <!-- Summary Cards -->
  <div class="grid">
    {% for r in summary %}
    <div class="card">
      <h2>{{ r.region }} — Latest TPV</h2>
      <div class="big-number {{ 'green' if r.dod > 0 else 'red' }}">{{ r.tpv }}</div>
      <div class="sub-text">
        {{ r.date }}
        <span class="change {{ 'up' if r.dod > 0 else 'down' }}">{{ r.dod_str }} DoD</span>
        <span class="change {{ 'up' if r.wow > 0 else 'down' }}">{{ r.wow_str }} WoW</span>
      </div>
      <div style="display:flex; gap:24px; margin-top:16px;">
        <div><span class="sub-text">Transactions</span><div style="font-size:20px;font-weight:600;">{{ r.txns }}</div></div>
        <div><span class="sub-text">Users</span><div style="font-size:20px;font-weight:600;">{{ r.users }}</div></div>
        <div><span class="sub-text">MTD</span><div style="font-size:20px;font-weight:600;">{{ r.mtd }}</div></div>
        <div><span class="sub-text">Proj. Month</span><div style="font-size:20px;font-weight:600;">{{ r.proj_month }}</div></div>
      </div>
    </div>
    {% endfor %}
  </div>

  <!-- Combined TPV -->
  <div class="card" style="margin-bottom:20px; text-align:center;">
    <h2>Combined Daily TPV</h2>
    <div class="big-number blue">{{ combined_tpv }}</div>
  </div>

  <!-- Predictions -->
  <div class="section-title">7-Day Predictions</div>
  <div class="grid">
    {% for r in predictions %}
    <div class="card">
      <h2>{{ r.region }} Forecast</h2>
      <table>
        <thead><tr><th>Date</th><th>Day</th><th>Predicted</th><th>Low</th><th>High</th></tr></thead>
        <tbody>
        {% for row in r.rows %}
        <tr>
          <td>{{ row.date }}</td>
          <td>{{ row.day }}</td>
          <td style="font-weight:600;">{{ row.ensemble }}</td>
          <td style="color:#94a3b8;">{{ row.low }}</td>
          <td style="color:#94a3b8;">{{ row.high }}</td>
        </tr>
        {% endfor %}
        </tbody>
      </table>
    </div>
    {% endfor %}
  </div>

  <!-- Category Breakdown -->
  <div class="section-title">Category Breakdown</div>
  <div class="grid">
    {% for r in categories %}
    <div class="card">
      <h2>{{ r.region }} ({{ r.date }})</h2>
      <div class="cat-bar">
        <div class="cat-nonreferred" style="width:{{ r.nr_pct }}%">Non-Ref {{ r.nr_pct }}%</div>
        <div class="cat-referred" style="width:{{ r.ref_pct }}%">Referred {{ r.ref_pct }}%</div>
        <div class="cat-whale" style="width:{{ r.wh_pct }}%">Whale {{ r.wh_pct }}%</div>
      </div>
      <table>
        <thead><tr><th>Category</th><th>TPV</th><th>Share</th></tr></thead>
        <tbody>
        {% for c in r.cats %}
        <tr><td>{{ c.name }}</td><td>{{ c.tpv }}</td><td>{{ c.share }}</td></tr>
        {% endfor %}
        <tr style="font-weight:700;border-top:2px solid #334155;"><td>TOTAL</td><td>{{ r.total }}</td><td>100%</td></tr>
        </tbody>
      </table>
      <h3>7-Day Trend</h3>
      <table>
        <thead><tr><th>Category</th><th>Avg</th><th>Min</th><th>Max</th></tr></thead>
        <tbody>
        {% for t in r.trend %}
        <tr><td>{{ t.name }}</td><td>{{ t.avg }}</td><td>{{ t.min }}</td><td>{{ t.max }}</td></tr>
        {% endfor %}
        </tbody>
      </table>
    </div>
    {% endfor %}
  </div>

  <!-- Monthly History -->
  <div class="section-title">Monthly TPV History</div>
  <div class="card" style="margin-bottom:20px;">
    <table>
      <thead><tr><th>Month</th><th>Type</th><th>UAE TPV</th><th>UK TPV</th><th>Total</th></tr></thead>
      <tbody>
      {% for m in monthly %}
      <tr>
        <td>{{ m.month }}</td>
        <td><span class="badge {{ 'badge-green' if m.type == 'Historical' else 'badge-blue' }}">{{ m.type }}</span></td>
        <td>{{ m.uae }}</td>
        <td>{{ m.uk }}</td>
        <td style="font-weight:600;">{{ m.total }}</td>
      </tr>
      {% endfor %}
      </tbody>
    </table>
  </div>

  <!-- Model Performance -->
  <div class="section-title">Model Performance</div>
  <div class="grid">
    {% for r in model_perf %}
    <div class="card">
      <h2>{{ r.region }}</h2>
      <div style="display:flex; gap:24px; margin-bottom:16px;">
        <div><span class="sub-text">Linear R²</span><div style="font-size:20px;font-weight:600;">{{ r.r2 }}</div></div>
        <div><span class="sub-text">Slope/Day</span><div style="font-size:20px;font-weight:600;">{{ r.slope }}</div></div>
      </div>
      <div class="progress-bar"><div class="progress-fill" style="width:{{ (r.r2_raw * 100)|int }}%;background:{{ '#34d399' if r.r2_raw > 0.5 else '#f59e0b' }};"></div></div>
      <h3>Backtest (30-day holdout)</h3>
      <table>
        <thead><tr><th>Model</th><th>MAPE</th><th>RMSE</th></tr></thead>
        <tbody>
        {% for b in r.backtest %}
        <tr>
          <td>{{ b.model }}</td>
          <td><span class="badge {{ 'badge-green' if b.mape < 30 else 'badge-yellow' if b.mape < 50 else 'badge-red' }}">{{ b.mape }}%</span></td>
          <td>{{ b.rmse }}</td>
        </tr>
        {% endfor %}
        </tbody>
      </table>
    </div>
    {% endfor %}
  </div>

  <!-- Alerts -->
  {% if alerts %}
  <div class="section-title">Alerts & Insights</div>
  {% for a in alerts %}
  <div class="alert">{{ a }}</div>
  {% endfor %}
  {% endif %}

  <div class="timestamp">Report generated: {{ timestamp }}</div>
</div>
</body>
</html>
"""

def fmt(val):
    if abs(val) >= 1_000_000:
        return f"{val/1_000_000:,.2f}M"
    if abs(val) >= 1_000:
        return f"{val/1_000:,.1f}K"
    return f"{val:,.0f}"

def pct_str(val):
    return f"{'+' if val > 0 else ''}{val:.1f}%"

@app.route("/")
def dashboard():
    today = datetime.now()
    summary = []
    predictions_data = []
    categories_data = []
    model_perf = []
    alerts = []

    for region in REGIONS:
        hist = get_historical_region(region)
        if hist.empty:
            continue

        latest = hist.iloc[-1]
        prev = hist.iloc[-2] if len(hist) >= 2 else latest
        week_ago = hist.iloc[-8] if len(hist) >= 8 else latest
        dod = ((latest["Daily_TPV"] - prev["Daily_TPV"]) / max(prev["Daily_TPV"], 1)) * 100
        wow = ((latest["Daily_TPV"] - week_ago["Daily_TPV"]) / max(week_ago["Daily_TPV"], 1)) * 100

        cm = latest["Date"].month
        cy = latest["Date"].year
        mtd_df = hist[(hist["Date"].dt.month == cm) & (hist["Date"].dt.year == cy)]
        mtd_total = mtd_df["Daily_TPV"].sum()
        days_elapsed = len(mtd_df)
        days_in_month = pd.Timestamp(cy, cm, 1).days_in_month
        proj_month = (mtd_total / max(days_elapsed, 1)) * days_in_month

        summary.append({
            "region": region,
            "date": latest["Date"].strftime("%Y-%m-%d"),
            "tpv": fmt(latest["Daily_TPV"]),
            "dod": dod, "dod_str": pct_str(dod),
            "wow": wow, "wow_str": pct_str(wow),
            "txns": f"{int(latest['Transactions']):,}",
            "users": f"{int(latest['Users']):,}",
            "mtd": fmt(mtd_total),
            "proj_month": fmt(proj_month),
        })

        # Predictions
        forecaster = EnsembleForecaster()
        forecaster.fit(hist["Date"], hist["Daily_TPV"])
        last_date = hist["Date"].iloc[-1]
        future = pd.Series([last_date + timedelta(days=i+1) for i in range(7)])
        preds = forecaster.predict(future)
        pred_rows = []
        for _, row in preds.iterrows():
            d = pd.Timestamp(row["Date"])
            pred_rows.append({
                "date": d.strftime("%Y-%m-%d"), "day": d.strftime("%a"),
                "ensemble": fmt(row["Ensemble"]), "low": fmt(row["Low"]), "high": fmt(row["High"]),
            })
        predictions_data.append({"region": region, "rows": pred_rows})

        # Backtest
        stats = forecaster.get_model_stats()
        bt = {}
        if len(hist) > 60:
            bt = forecaster.backtest(hist["Date"], hist["Daily_TPV"], holdout=30)
            forecaster.fit(hist["Date"], hist["Daily_TPV"])
        bt_rows = [{"model": k, "mape": v["MAPE"], "rmse": fmt(v["RMSE"])} for k, v in bt.items()]
        model_perf.append({
            "region": region, "r2": f"{stats['linear_r2']:.4f}", "r2_raw": stats["linear_r2"],
            "slope": fmt(stats["linear_slope"]), "backtest": bt_rows,
        })

        # Alerts
        avg7 = hist["Daily_TPV"].tail(7).mean()
        avg30 = hist["Daily_TPV"].tail(30).mean()
        if latest["Daily_TPV"] > avg7 * 1.2:
            alerts.append(f"{region}: Latest TPV ({fmt(latest['Daily_TPV'])}) is >20% above 7-day avg ({fmt(avg7)})")
        elif latest["Daily_TPV"] < avg7 * 0.8:
            alerts.append(f"{region}: Latest TPV ({fmt(latest['Daily_TPV'])}) is >20% below 7-day avg ({fmt(avg7)})")
        growth = (avg7 - avg30) / max(avg30, 1) * 100
        if growth > 15:
            alerts.append(f"{region}: Strong growth — 7d avg is {growth:.0f}% above 30d avg")
        elif growth < -15:
            alerts.append(f"{region}: Growth deceleration — 7d avg is {abs(growth):.0f}% below 30d avg")

    # Categories
    for region in REGIONS:
        try:
            cat_df = load_category_data(region)
            cat_df = cat_df[cat_df["Daily_TPV"] > 0]
            if cat_df.empty:
                continue
            latest_date = cat_df["Date"].max()
            day_data = cat_df[cat_df["Date"] == latest_date]
            total = day_data["Daily_TPV"].sum()
            cats = []
            nr_pct = ref_pct = wh_pct = 0
            for _, row in day_data.iterrows():
                share = (row["Daily_TPV"] / max(total, 1)) * 100
                cats.append({"name": row["Category"], "tpv": fmt(row["Daily_TPV"]), "share": f"{share:.1f}%"})
                if row["Category"] == "Non-Referred": nr_pct = round(share, 1)
                elif row["Category"] == "Referred": ref_pct = round(share, 1)
                elif row["Category"] == "Whale": wh_pct = round(share, 1)
            last7 = cat_df[cat_df["Date"] >= (latest_date - pd.Timedelta(days=6))]
            trend = []
            for cat in last7["Category"].unique():
                vals = last7[last7["Category"] == cat]["Daily_TPV"]
                trend.append({"name": cat, "avg": fmt(vals.mean()), "min": fmt(vals.min()), "max": fmt(vals.max())})
            categories_data.append({
                "region": region, "date": latest_date.strftime("%Y-%m-%d"),
                "cats": cats, "total": fmt(total), "trend": trend,
                "nr_pct": nr_pct, "ref_pct": ref_pct, "wh_pct": wh_pct,
            })
        except Exception:
            pass

    # Monthly
    monthly_df = load_monthly_summary()
    monthly = []
    for _, row in monthly_df.tail(8).iterrows():
        monthly.append({
            "month": row["Month"], "type": row["Type"],
            "uae": fmt(row["UAE_TPV"]), "uk": fmt(row["UK_TPV"]), "total": fmt(row["Total_TPV"]),
        })

    combined = sum(float(s["tpv"].replace("M","").replace("K","").replace(",","")) * (1e6 if "M" in s["tpv"] else 1e3 if "K" in s["tpv"] else 1) for s in summary)

    return render_template_string(HTML_TEMPLATE,
        today=today.strftime("%A, %B %d, %Y"),
        timestamp=today.strftime("%Y-%m-%d %H:%M:%S"),
        summary=summary,
        combined_tpv=fmt(combined),
        predictions=predictions_data,
        categories=categories_data,
        monthly=monthly,
        model_perf=model_perf,
        alerts=alerts,
    )

if __name__ == "__main__":
    print("\n  TPV Predictions Dashboard starting on http://localhost:5050\n")
    app.run(host="0.0.0.0", port=5050, debug=False)
