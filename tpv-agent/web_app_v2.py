"""
web_app_v2.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TPV Agent Web Dashboard — consumes DailyReport from the async agent.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime
from decimal import Decimal
from typing import Optional

from flask import Flask, render_template_string, jsonify, request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.settings import settings
from agents.tpv_agent import TPVAgent
from shared.schemas import DailyReport


def fmt(val) -> str:
    val = float(val) if isinstance(val, Decimal) else val
    if abs(val) >= 1_000_000:
        return f"{val / 1_000_000:,.2f}M"
    if abs(val) >= 1_000:
        return f"{val / 1_000:,.1f}K"
    return f"{val:,.0f}"


def pct_str(val: float) -> str:
    return f"{'+' if val > 0 else ''}{val:.1f}%"


TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TPV Agent — UAE / UK</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh}
.hdr{background:linear-gradient(135deg,#1e293b,#0f172a);border-bottom:1px solid #334155;padding:20px 40px;display:flex;justify-content:space-between;align-items:center}
.hdr h1{font-size:22px;font-weight:700;color:#f8fafc}
.hdr .tag{background:#6366f1;color:#fff;font-size:11px;padding:3px 10px;border-radius:9999px;margin-left:12px;font-weight:600}
.hdr p{color:#94a3b8;font-size:13px;margin-top:2px}
.hdr-r{display:flex;gap:10px;align-items:center}
.btn{padding:8px 18px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;border:none;transition:.2s}
.btn-purple{background:linear-gradient(135deg,#8b5cf6,#6366f1);color:#fff}
.btn-purple:hover{box-shadow:0 4px 12px rgba(99,102,241,.4)}
.btn-ghost{background:#334155;color:#94a3b8}
.btn-ghost:hover{background:#475569;color:#e2e8f0}
.container{max-width:1400px;margin:0 auto;padding:20px 40px}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px}
.card{background:#1e293b;border:1px solid #334155;border-radius:10px;padding:20px}
.card h2{font-size:12px;font-weight:600;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em;margin-bottom:12px}
.big{font-size:30px;font-weight:700;color:#f8fafc}
.big.g{color:#34d399}.big.r{color:#f87171}.big.b{color:#60a5fa}
.sub{font-size:12px;color:#94a3b8;margin-top:4px}
.ch{font-size:13px;font-weight:600;display:inline-block;padding:2px 7px;border-radius:4px;margin-left:6px}
.ch.up{background:#064e3b;color:#34d399}.ch.dn{background:#7f1d1d;color:#f87171}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;padding:8px 10px;color:#94a3b8;font-weight:500;border-bottom:1px solid #334155;font-size:11px;text-transform:uppercase}
td{padding:8px 10px;border-bottom:1px solid #1e293b;color:#e2e8f0}
tr:hover td{background:#334155}
.bd{display:inline-block;padding:2px 8px;border-radius:9999px;font-size:11px;font-weight:600}
.bd-g{background:#064e3b;color:#34d399}.bd-r{background:#7f1d1d;color:#f87171}
.bd-y{background:#78350f;color:#fbbf24}.bd-b{background:#1e3a5f;color:#60a5fa}
.bar{display:flex;height:28px;border-radius:6px;overflow:hidden;margin:6px 0}
.bar div{display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:600;color:#fff}
.b-nr{background:#10b981}.b-ref{background:#3b82f6}.b-wh{background:#f59e0b}
.sec{font-size:16px;font-weight:700;color:#f8fafc;margin:28px 0 12px;padding-bottom:6px;border-bottom:1px solid #334155}
.alert{background:#1c1917;border-left:4px solid #f59e0b;padding:10px 14px;border-radius:0 6px 6px 0;margin-bottom:6px;font-size:13px;color:#fbbf24}
.alert.crit{border-color:#ef4444;color:#f87171}
.mult{background:#0f172a;border:1px solid #334155;border-radius:6px;padding:4px 8px;margin:2px 0;font-size:12px;display:flex;justify-content:space-between}
.mult .val{color:#a78bfa;font-weight:600}
.bus{font-size:12px;color:#475569;padding:6px 0}
.ts{text-align:center;color:#475569;font-size:11px;padding:20px}
.fx-form{display:flex;gap:12px;align-items:center;margin-bottom:16px;flex-wrap:wrap}
.fx-form label{font-size:12px;color:#94a3b8;font-weight:500}
.fx-form input{background:#0f172a;border:1px solid #475569;color:#f8fafc;padding:6px 12px;border-radius:6px;font-size:14px;width:120px}
.fx-form input:focus{outline:none;border-color:#6366f1}
.fx-form .btn{margin-left:8px}
.fx-tab-bar{display:flex;gap:2px;margin-bottom:16px}
.fx-tab{padding:8px 20px;background:#1e293b;border:1px solid #334155;border-radius:8px 8px 0 0;font-size:13px;font-weight:600;color:#94a3b8;cursor:pointer;border-bottom:none}
.fx-tab.active{background:#334155;color:#f8fafc;border-color:#6366f1}
.fx-table{width:100%;border-collapse:collapse;font-size:12px}
.fx-table th{text-align:center;padding:6px 8px;color:#94a3b8;font-weight:500;border-bottom:1px solid #334155;font-size:10px;text-transform:uppercase;position:sticky;top:0;background:#1e293b}
.fx-table td{text-align:center;padding:6px 8px;border-bottom:1px solid rgba(51,65,85,.4);color:#e2e8f0;font-variant-numeric:tabular-nums}
.fx-table tr:hover td{background:rgba(99,102,241,.08)}
.fx-hi{color:#34d399;font-weight:600}.fx-lo{color:#f87171;font-weight:600}.fx-base{color:#fbbf24;font-weight:700;background:rgba(251,191,36,.06)}
.fx-date-hdr{background:#0f172a;font-weight:700;color:#a78bfa;text-align:left;padding:8px 10px;border-top:2px solid #6366f1}
.fx-bps{font-weight:600;font-size:11px}
.fx-bps.pos{color:#34d399}.fx-bps.neg{color:#f87171}.fx-bps.zero{color:#fbbf24}
.fx-card{background:#1e293b;border:1px solid #334155;border-radius:0 10px 10px 10px;padding:16px;max-height:600px;overflow-y:auto}
.fx-summary{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px;margin-bottom:16px}
.fx-stat{background:#0f172a;border:1px solid #334155;border-radius:8px;padding:12px;text-align:center}
.fx-stat .label{font-size:10px;color:#94a3b8;text-transform:uppercase;margin-bottom:4px}
.fx-stat .val{font-size:20px;font-weight:700;color:#f8fafc}
.fx-stat .sub{font-size:11px;color:#64748b;margin-top:2px}
</style>
</head>
<body>
<div class="hdr">
  <div>
    <h1>TPV Predictions Agent<span class="tag">ASYNC</span></h1>
    <p>{{ today }} — UAE / UK</p>
  </div>
  <div class="hdr-r">
    <a href="/predictions" class="btn btn-ghost" style="text-decoration:none">7-Day Predictions</a>
    <span class="sub">Messages: {{ msg_count }}</span>
    <button class="btn btn-purple" onclick="location.reload()">Refresh</button>
    <form action="/api/reforecast" method="POST" style="display:inline">
      <button class="btn btn-ghost" type="submit">Re-forecast</button>
    </form>
  </div>
</div>
<div class="container">
{% if not report %}
  <div class="card" style="text-align:center;padding:60px">
    <p style="font-size:18px;color:#94a3b8">Agent is starting up... Forecast will appear shortly.</p>
    <p class="sub" style="margin-top:8px">Refresh in a few seconds.</p>
  </div>
{% else %}
  <!-- Summary -->
  <div class="g2">
  {% for s in report.summaries %}
    <div class="card">
      <h2>{{ s.region.value }} — Latest TPV</h2>
      <div class="big {{ 'g' if s.dod_change_pct > 0 else 'r' }}">{{ fmt(s.latest_tpv) }}</div>
      <div class="sub">
        {{ s.latest_date }}
        <span class="ch {{ 'up' if s.dod_change_pct > 0 else 'dn' }}">{{ pct(s.dod_change_pct) }} DoD</span>
        <span class="ch {{ 'up' if s.wow_change_pct > 0 else 'dn' }}">{{ pct(s.wow_change_pct) }} WoW</span>
      </div>
      <div style="display:flex;gap:20px;margin-top:14px">
        <div><span class="sub">Txns</span><div style="font-size:18px;font-weight:600">{{ '{:,}'.format(s.transactions) }}</div></div>
        <div><span class="sub">Users</span><div style="font-size:18px;font-weight:600">{{ '{:,}'.format(s.users) }}</div></div>
        <div><span class="sub">MTD</span><div style="font-size:18px;font-weight:600">{{ fmt(s.mtd_total) }}</div></div>
        <div><span class="sub">Proj. Month</span><div style="font-size:18px;font-weight:600">{{ fmt(s.projected_month) }}</div></div>
      </div>
    </div>
  {% endfor %}
  </div>

  <!-- Combined -->
  <div class="card" style="text-align:center;margin-bottom:16px">
    <h2>Combined Daily TPV</h2>
    <div class="big b">{{ combined }}</div>
  </div>

  <!-- FX-Rate-Sensitive Predictions (moved to top) -->
  {% if report.fx_predictions %}
  <div class="sec">FX-Rate-Sensitive Predictions (BPS Scenarios) — 7-Day from Today</div>

  <!-- FX Rate Input Form -->
  <form class="fx-form" action="/api/reforecast-fx" method="POST">
    {% for region, pred in report.fx_predictions.items() %}
    <div>
      <label>{{ region }} FX Rate ({{ pred.currency_pair }})</label><br>
      <input type="number" step="0.01" name="fx_{{ region }}" value="{{ pred.base_fx_rate }}" placeholder="{{ pred.base_fx_rate }}">
    </div>
    {% endfor %}
    <div>
      <label>USD/INR Rate</label><br>
      <input type="number" step="0.01" name="fx_USDINR" value="{{ report.fx_predictions.values()|first|attr('base_usdinr') }}" placeholder="86.50">
    </div>
    <button class="btn btn-purple" type="submit">Update FX & Re-forecast</button>
  </form>

  <!-- Region tabs -->
  {% for region, pred in report.fx_predictions.items() %}
  <div style="margin-bottom:24px">
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px">
      <h3 style="font-size:16px;font-weight:700;color:#f8fafc">{{ region }}</h3>
      <span class="bd bd-b">{{ pred.currency_pair }}</span>
      <span style="font-size:12px;color:#94a3b8">Base Rate: <strong style="color:#fbbf24">{{ pred.base_fx_rate }}</strong></span>
      <span class="bd bd-y">USD/INR: {{ pred.base_usdinr }}</span>
    </div>

    <!-- Summary stats -->
    <div class="fx-summary">
      {% if pred.prediction_blocks %}
      {% set first_block = pred.prediction_blocks[0] %}
      <div class="fx-stat">
        <div class="label">Base TPV (BPS=0)</div>
        <div class="val">{{ fmt(first_block.base_tpv) }}</div>
        <div class="sub">{{ first_block.prediction_date }}</div>
      </div>
      <div class="fx-stat">
        <div class="label">Base TU</div>
        <div class="val">{{ '{:,}'.format(first_block.base_tu) }}</div>
        <div class="sub">Transaction Users</div>
      </div>
      <div class="fx-stat">
        <div class="label">Base ARPU</div>
        <div class="val">{{ fmt(first_block.base_arpu) }}</div>
        <div class="sub">Avg Revenue/User</div>
      </div>
      {% set worst = pred.prediction_blocks[0].scenarios[0] %}
      {% set best = pred.prediction_blocks[0].scenarios[-1] %}
      <div class="fx-stat">
        <div class="label">TPV Range (Day 1)</div>
        <div class="val" style="font-size:14px"><span style="color:#f87171">{{ fmt(worst.total_tpv) }}</span> — <span style="color:#34d399">{{ fmt(best.total_tpv) }}</span></div>
        <div class="sub">BPS -20 to +20</div>
      </div>
      {% endif %}
    </div>

    <!-- Predictions table -->
    <div class="fx-card">
      <table class="fx-table">
        <thead>
          <tr>
            <th>Date</th>
            <th>Day</th>
            <th>BPS</th>
            <th>FX Rate</th>
            <th>USD/INR</th>
            <th>Total TPV</th>
            <th>Total TU</th>
            <th>Avg ARPU</th>
            <th>vs Base</th>
          </tr>
        </thead>
        <tbody>
        {% for block in pred.prediction_blocks %}
          <tr><td colspan="9" class="fx-date-hdr">{{ block.prediction_date }} — {{ block.day_of_week }}</td></tr>
          {% for s in block.scenarios %}
          <tr{% if s.bps_change == 0 %} class="fx-base"{% endif %}>
            <td>{{ block.prediction_date }}</td>
            <td>{{ block.day_of_week[:3] }}</td>
            <td><span class="fx-bps {{ 'pos' if s.bps_change > 0 else 'neg' if s.bps_change < 0 else 'zero' }}">{{ '+' if s.bps_change > 0 else '' }}{{ s.bps_change }}</span></td>
            <td>{{ '%.4f' % s.fx_rate }}</td>
            <td style="color:#f59e0b">{{ '%.2f' % s.usdinr_rate }}</td>
            <td class="{{ 'fx-hi' if s.tpv_change_pct > 5 else 'fx-lo' if s.tpv_change_pct < -5 else '' }}">{{ fmt(s.total_tpv) }}</td>
            <td>{{ '{:,}'.format(s.total_tu) }}</td>
            <td>{{ fmt(s.avg_arpu) }}</td>
            <td class="{{ 'fx-hi' if s.tpv_change_pct > 0 else 'fx-lo' if s.tpv_change_pct < 0 else '' }}">{{ '+' if s.tpv_change_pct > 0 else '' }}{{ '%.1f' % s.tpv_change_pct }}%</td>
          </tr>
          {% endfor %}
        {% endfor %}
        </tbody>
      </table>
    </div>
  </div>
  {% endfor %}
  {% endif %}

  <!-- FX Currency Conversion (Actual TPV from CSV) -->
  {% if report.fx_conversion %}
  <div class="sec">Currency Conversion — Last 7 Days Actual TPV to INR (BPS Scenarios)</div>
  <div style="margin-bottom:8px;font-size:12px;color:#94a3b8">
    Source: {{ report.fx_conversion.csv_file | basename }} &nbsp;|&nbsp;
    Base rates — AED/INR: <strong style="color:#fbbf24">{{ '%.4f' % report.fx_conversion.rates_at_base.AED }}</strong> &nbsp;
    GBP/INR: <strong style="color:#fbbf24">{{ '%.4f' % report.fx_conversion.rates_at_base.GBP }}</strong> &nbsp;
    EUR/INR: <strong style="color:#fbbf24">{{ '%.4f' % report.fx_conversion.rates_at_base.EUR }}</strong> &nbsp;
    USD/INR: <strong style="color:#fbbf24">{{ '%.4f' % report.fx_conversion.rates_at_base.USD }}</strong>
  </div>
  <div class="fx-card" style="max-height:700px;margin-bottom:16px">
    <table class="fx-table">
      <thead>
        <tr>
          <th>Date</th>
          <th>BPS</th>
          <th>AED</th>
          <th>AED/INR</th>
          <th>GBP</th>
          <th>GBP/INR</th>
          <th>EUR</th>
          <th>EUR/INR</th>
          <th>USD</th>
          <th>USD/INR</th>
          <th>Total INR</th>
          <th>Total USD</th>
          <th>vs Base</th>
        </tr>
      </thead>
      <tbody>
      {% for day in report.fx_conversion.days %}
        <tr><td colspan="13" class="fx-date-hdr">{{ day.date }} — {{ day.day_of_week }} &nbsp; <span style="font-weight:400;color:#94a3b8">Base Total INR: {{ fmt(day.base_total_inr) }}</span></td></tr>
        {% for s in day.scenarios %}
        <tr{% if s.bps_change == 0 %} class="fx-base"{% endif %}>
          <td>{{ day.date }}</td>
          <td><span class="fx-bps {{ 'pos' if s.bps_change > 0 else 'neg' if s.bps_change < 0 else 'zero' }}">{{ '+' if s.bps_change > 0 else '' }}{{ s.bps_change }}</span></td>
          {% set aed = s.currencies | selectattr('currency', 'equalto', 'AED') | first %}
          {% set gbp = s.currencies | selectattr('currency', 'equalto', 'GBP') | first %}
          {% set eur = s.currencies | selectattr('currency', 'equalto', 'EUR') | first %}
          {% set usd = s.currencies | selectattr('currency', 'equalto', 'USD') | first %}
          <td>{% if aed %}{{ fmt(aed.local_amount) }}{% else %}-{% endif %}</td>
          <td style="color:#94a3b8">{{ '%.4f' % s.aedinr }}</td>
          <td>{% if gbp %}{{ fmt(gbp.local_amount) }}{% else %}-{% endif %}</td>
          <td style="color:#94a3b8">{{ '%.4f' % s.gbpinr }}</td>
          <td>{% if eur %}{{ fmt(eur.local_amount) }}{% else %}-{% endif %}</td>
          <td style="color:#94a3b8">{{ '%.4f' % s.eurinr }}</td>
          <td>{% if usd %}{{ fmt(usd.local_amount) }}{% else %}-{% endif %}</td>
          <td style="color:#f59e0b">{{ '%.2f' % s.usdinr }}</td>
          <td style="font-weight:700;color:#f8fafc">{{ fmt(s.total_inr) }}</td>
          <td style="font-weight:600;color:#60a5fa">{{ fmt(s.total_usd) }}</td>
          <td class="{{ 'fx-hi' if s.change_pct > 0 else 'fx-lo' if s.change_pct < 0 else '' }}">{{ '+' if s.change_pct > 0 else '' }}{{ '%.2f' % s.change_pct }}%</td>
        </tr>
        {% endfor %}
      {% endfor %}
      </tbody>
    </table>
  </div>
  {% endif %}

  <!-- Forecasts -->
  <div class="sec">7-Day Forecasts</div>
  <div class="g2">
  {% for region, rows in report.forecasts.items() %}
    <div class="card">
      <h2>{{ region }} Forecast</h2>
      <table>
        <thead><tr><th>Date</th><th>Day</th><th>Predicted</th><th>Low</th><th>High</th></tr></thead>
        <tbody>
        {% for r in rows %}
        <tr><td>{{ r.date }}</td><td>{{ r.day_of_week }}</td>
        <td style="font-weight:600">{{ fmt(r.ensemble) }}</td>
        <td style="color:#94a3b8">{{ fmt(r.low) }}</td>
        <td style="color:#94a3b8">{{ fmt(r.high) }}</td></tr>
        {% endfor %}
        </tbody>
      </table>
    </div>
  {% endfor %}
  </div>

  <!-- Categories -->
  <div class="sec">Category Breakdown</div>
  <div class="g2">
  {% for cb in report.category_breakdowns %}
    <div class="card">
      <h2>{{ cb.region.value }} ({{ cb.date }})</h2>
      {% set nr = namespace(pct=0) %}{% set ref = namespace(pct=0) %}{% set wh = namespace(pct=0) %}
      {% for c in cb.categories %}
        {% if c.name == 'Non-Referred' %}{% set nr.pct = c.share %}
        {% elif c.name == 'Referred' %}{% set ref.pct = c.share %}
        {% elif c.name == 'Whale' %}{% set wh.pct = c.share %}{% endif %}
      {% endfor %}
      <div class="bar">
        <div class="b-nr" style="width:{{ nr.pct }}%">NR {{ nr.pct }}%</div>
        <div class="b-ref" style="width:{{ ref.pct }}%">Ref {{ ref.pct }}%</div>
        <div class="b-wh" style="width:{{ wh.pct }}%">Wh {{ wh.pct }}%</div>
      </div>
      <table>
        <thead><tr><th>Category</th><th>TPV</th><th>Share</th></tr></thead>
        <tbody>
        {% for c in cb.categories %}
        <tr><td>{{ c.name }}</td><td>{{ fmt(c.tpv) }}</td><td>{{ c.share }}%</td></tr>
        {% endfor %}
        <tr style="font-weight:700;border-top:2px solid #334155"><td>TOTAL</td><td>{{ fmt(cb.total) }}</td><td>100%</td></tr>
        </tbody>
      </table>
      {% if cb.trend_7d %}
      <h2 style="margin-top:12px">7-Day Trend</h2>
      <table>
        <thead><tr><th>Category</th><th>Avg</th><th>Min</th><th>Max</th></tr></thead>
        <tbody>
        {% for t in cb.trend_7d %}
        <tr><td>{{ t.name }}</td><td>{{ fmt(t.avg) }}</td><td>{{ fmt(t.min) }}</td><td>{{ fmt(t.max) }}</td></tr>
        {% endfor %}
        </tbody>
      </table>
      {% endif %}
    </div>
  {% endfor %}
  </div>

  <!-- Monthly -->
  <div class="sec">Monthly History</div>
  <div class="card" style="margin-bottom:16px">
    <table>
      <thead><tr><th>Month</th><th>Type</th><th>UAE</th><th>UK</th><th>Total</th></tr></thead>
      <tbody>
      {% for m in report.monthly_history %}
      <tr><td>{{ m.month }}</td>
      <td><span class="bd {{ 'bd-g' if m.type == 'Historical' else 'bd-b' }}">{{ m.type }}</span></td>
      <td>{{ fmt(m.uae_tpv) }}</td><td>{{ fmt(m.uk_tpv) }}</td>
      <td style="font-weight:600">{{ fmt(m.total_tpv) }}</td></tr>
      {% endfor %}
      </tbody>
    </table>
  </div>

  <!-- Model Perf -->
  <div class="sec">Model Performance</div>
  <div class="g2">
  {% for mp in report.model_performance %}
    <div class="card">
      <h2>{{ mp.region.value }}</h2>
      <div style="display:flex;gap:20px;margin-bottom:12px">
        <div><span class="sub">Linear R²</span><div style="font-size:18px;font-weight:600">{{ '%.4f' % mp.linear_r2 }}</div></div>
        <div><span class="sub">Slope/Day</span><div style="font-size:18px;font-weight:600">{{ fmt(mp.slope_per_day) }}</div></div>
      </div>
      {% if mp.backtest %}
      <table>
        <thead><tr><th>Model</th><th>MAPE</th><th>RMSE</th></tr></thead>
        <tbody>
        {% for name, metrics in mp.backtest.items() %}
        <tr><td>{{ name }}</td>
        <td><span class="bd {{ 'bd-g' if metrics.MAPE < 30 else 'bd-y' if metrics.MAPE < 50 else 'bd-r' }}">{{ '%.1f' % metrics.MAPE }}%</span></td>
        <td>{{ fmt(metrics.RMSE) }}</td></tr>
        {% endfor %}
        </tbody>
      </table>
      {% endif %}
    </div>
  {% endfor %}
  </div>

  <!-- Alerts -->
  {% if report.alerts %}
  <div class="sec">Alerts</div>
  {% for a in report.alerts %}
  <div class="alert {{ 'crit' if a.severity == 'CRITICAL' else '' }}">
    [{{ a.severity }}] {{ a.description }}
  </div>
  {% endfor %}
  {% endif %}

  <!-- Bus history -->
  <div class="sec">Message Bus Activity</div>
  <div class="card">
    {% for stream, count in bus_streams.items() %}
    <div class="bus">{{ stream }}: <strong>{{ count }}</strong> messages</div>
    {% endfor %}
  </div>

  <div class="ts">Generated: {{ report.generated_at.strftime('%Y-%m-%d %H:%M:%S UTC') }}</div>
{% endif %}
</div>
</body>
</html>
"""


PREDICTIONS_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>7-Day Predictions — UAE / UK</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh}
.hdr{background:linear-gradient(135deg,#1e293b,#0f172a);border-bottom:1px solid #334155;padding:20px 40px;display:flex;justify-content:space-between;align-items:center}
.hdr h1{font-size:22px;font-weight:700;color:#f8fafc}
.hdr .tag{background:#10b981;color:#fff;font-size:11px;padding:3px 10px;border-radius:9999px;margin-left:12px;font-weight:600}
.hdr p{color:#94a3b8;font-size:13px;margin-top:2px}
.hdr-r{display:flex;gap:10px;align-items:center}
.btn{padding:8px 18px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;border:none;transition:.2s;text-decoration:none}
.btn-purple{background:linear-gradient(135deg,#8b5cf6,#6366f1);color:#fff}
.btn-purple:hover{box-shadow:0 4px 12px rgba(99,102,241,.4)}
.btn-ghost{background:#334155;color:#94a3b8}
.btn-ghost:hover{background:#475569;color:#e2e8f0}
.container{max-width:1400px;margin:0 auto;padding:20px 40px}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px}
.card{background:#1e293b;border:1px solid #334155;border-radius:10px;padding:20px}
.card h2{font-size:12px;font-weight:600;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em;margin-bottom:12px}
.big{font-size:28px;font-weight:700;color:#f8fafc}
.sub{font-size:12px;color:#94a3b8;margin-top:4px}
.sec{font-size:16px;font-weight:700;color:#f8fafc;margin:28px 0 12px;padding-bottom:6px;border-bottom:1px solid #334155}
.bd{display:inline-block;padding:2px 8px;border-radius:9999px;font-size:11px;font-weight:600}
.bd-g{background:#064e3b;color:#34d399}.bd-b{background:#1e3a5f;color:#60a5fa}.bd-y{background:#78350f;color:#fbbf24}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;padding:8px 10px;color:#94a3b8;font-weight:500;border-bottom:1px solid #334155;font-size:11px;text-transform:uppercase}
td{padding:8px 10px;border-bottom:1px solid #1e293b;color:#e2e8f0}
tr:hover td{background:#334155}
.day-card{background:#1e293b;border:1px solid #334155;border-radius:10px;padding:20px;margin-bottom:20px}
.day-hdr{display:flex;align-items:center;gap:14px;margin-bottom:16px;padding-bottom:12px;border-bottom:2px solid #6366f1}
.day-hdr h2{font-size:20px;font-weight:700;color:#f8fafc;margin:0}
.day-hdr .day-label{font-size:14px;color:#a78bfa;font-weight:600}
.region-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.region-block{background:#0f172a;border:1px solid #334155;border-radius:8px;padding:16px}
.region-block h3{font-size:14px;font-weight:700;color:#f8fafc;margin-bottom:12px;display:flex;align-items:center;gap:8px}
.fx-table{width:100%;border-collapse:collapse;font-size:12px}
.fx-table th{text-align:center;padding:6px 8px;color:#94a3b8;font-weight:500;border-bottom:1px solid #334155;font-size:10px;text-transform:uppercase}
.fx-table td{text-align:center;padding:6px 8px;border-bottom:1px solid rgba(51,65,85,.4);color:#e2e8f0;font-variant-numeric:tabular-nums}
.fx-table tr:hover td{background:rgba(99,102,241,.08)}
.fx-hi{color:#34d399;font-weight:600}.fx-lo{color:#f87171;font-weight:600}
.fx-base{color:#fbbf24;font-weight:700;background:rgba(251,191,36,.06)}
.fx-bps{font-weight:600;font-size:11px}
.fx-bps.pos{color:#34d399}.fx-bps.neg{color:#f87171}.fx-bps.zero{color:#fbbf24}
.summary-row{display:flex;gap:20px;margin-bottom:12px;flex-wrap:wrap}
.summary-item{background:#1e293b;border:1px solid #334155;border-radius:8px;padding:10px 16px;text-align:center;min-width:120px}
.summary-item .label{font-size:10px;color:#94a3b8;text-transform:uppercase;margin-bottom:2px}
.summary-item .val{font-size:18px;font-weight:700;color:#f8fafc}
.summary-item .sub{font-size:10px;color:#64748b}
.ts{text-align:center;color:#475569;font-size:11px;padding:20px}
.fx-form{display:flex;gap:12px;align-items:center;margin-bottom:20px;flex-wrap:wrap}
.fx-form label{font-size:12px;color:#94a3b8;font-weight:500}
.fx-form input{background:#0f172a;border:1px solid #475569;color:#f8fafc;padding:6px 12px;border-radius:6px;font-size:14px;width:120px}
.fx-form input:focus{outline:none;border-color:#6366f1}
</style>
</head>
<body>
<div class="hdr">
  <div>
    <h1>7-Day Predictions<span class="tag">FX SCENARIOS</span></h1>
    <p>{{ today }} — UAE / UK — Next 7 Days</p>
  </div>
  <div class="hdr-r">
    <a href="/" class="btn btn-ghost">Dashboard</a>
    <button class="btn btn-purple" onclick="location.reload()">Refresh</button>
  </div>
</div>
<div class="container">
{% if not report or not report.fx_predictions %}
  <div class="card" style="text-align:center;padding:60px">
    <p style="font-size:18px;color:#94a3b8">No predictions available yet. Forecast is running...</p>
    <p class="sub" style="margin-top:8px">Refresh in a few seconds.</p>
  </div>
{% else %}

  <!-- FX Rate Input Form -->
  <form class="fx-form" action="/api/reforecast-fx" method="POST">
    {% for region, pred in report.fx_predictions.items() %}
    <div>
      <label>{{ region }} ({{ pred.currency_pair }})</label><br>
      <input type="number" step="0.01" name="fx_{{ region }}" value="{{ pred.base_fx_rate }}">
    </div>
    {% endfor %}
    <div>
      <label>USD/INR</label><br>
      <input type="number" step="0.01" name="fx_USDINR" value="{{ report.fx_predictions.values()|first|attr('base_usdinr') }}">
    </div>
    <button class="btn btn-purple" type="submit">Update Rates</button>
  </form>

  <!-- Day-by-day predictions -->
  {% set regions = report.fx_predictions.keys() | list %}
  {% set first_region = regions[0] %}
  {% set num_days = report.fx_predictions[first_region].prediction_blocks | length %}

  {% for day_idx in range(num_days) %}
  {% set block0 = report.fx_predictions[first_region].prediction_blocks[day_idx] %}
  <div class="day-card">
    <div class="day-hdr">
      <h2>{{ block0.prediction_date }}</h2>
      <span class="day-label">{{ block0.day_of_week }}</span>
      <span class="bd bd-b">Day {{ day_idx + 1 }} of 7</span>
    </div>

    <div class="region-grid">
    {% for region in regions %}
      {% set pred = report.fx_predictions[region] %}
      {% set block = pred.prediction_blocks[day_idx] %}
      <div class="region-block">
        <h3>{{ region }} <span class="bd bd-y">{{ pred.currency_pair }}</span></h3>

        <!-- Summary stats for this day -->
        {% set base_sc = block.scenarios | selectattr('bps_change', 'equalto', 0) | first %}
        {% set base_usd = block.base_tpv|float * base_sc.fx_rate / base_sc.usdinr_rate %}
        <div class="summary-row">
          <div class="summary-item">
            <div class="label">Base TPV (Local)</div>
            <div class="val">{{ fmt(block.base_tpv) }}</div>
            <div class="sub">BPS = 0</div>
          </div>
          <div class="summary-item">
            <div class="label">Base TPV (USD)</div>
            <div class="val" style="color:#60a5fa">${{ fmt(base_usd) }}</div>
            <div class="sub">BPS = 0</div>
          </div>
          <div class="summary-item">
            <div class="label">Base TU</div>
            <div class="val">{{ '{:,}'.format(block.base_tu) }}</div>
            <div class="sub">Users</div>
          </div>
          <div class="summary-item">
            <div class="label">ARPU</div>
            <div class="val">{{ fmt(block.base_arpu) }}</div>
            <div class="sub">Per User</div>
          </div>
          {% set worst = block.scenarios[0] %}
          {% set best = block.scenarios[-1] %}
          {% set worst_usd = worst.total_tpv|float * worst.fx_rate / worst.usdinr_rate %}
          {% set best_usd = best.total_tpv|float * best.fx_rate / best.usdinr_rate %}
          <div class="summary-item">
            <div class="label">USD Range</div>
            <div class="val" style="font-size:13px"><span style="color:#f87171">${{ fmt(worst_usd) }}</span> – <span style="color:#34d399">${{ fmt(best_usd) }}</span></div>
            <div class="sub">-20 to +20 BPS</div>
          </div>
        </div>

        <!-- Scenarios table -->
        <table class="fx-table">
          <thead>
            <tr>
              <th>BPS</th>
              <th>FX Rate</th>
              <th>USD/INR</th>
              <th>TPV (Local)</th>
              <th>TPV (USD)</th>
              <th>Total TU</th>
              <th>ARPU</th>
              <th>vs Base</th>
            </tr>
          </thead>
          <tbody>
          {% for s in block.scenarios %}
          {% set tpv_usd = s.total_tpv|float * s.fx_rate / s.usdinr_rate %}
          <tr{% if s.bps_change == 0 %} class="fx-base"{% endif %}>
            <td><span class="fx-bps {{ 'pos' if s.bps_change > 0 else 'neg' if s.bps_change < 0 else 'zero' }}">{{ '+' if s.bps_change > 0 else '' }}{{ s.bps_change }}</span></td>
            <td>{{ '%.4f' % s.fx_rate }}</td>
            <td style="color:#f59e0b">{{ '%.2f' % s.usdinr_rate }}</td>
            <td class="{{ 'fx-hi' if s.tpv_change_pct > 5 else 'fx-lo' if s.tpv_change_pct < -5 else '' }}">{{ fmt(s.total_tpv) }}</td>
            <td style="font-weight:700;color:#60a5fa">${{ fmt(tpv_usd) }}</td>
            <td>{{ '{:,}'.format(s.total_tu) }}</td>
            <td>{{ fmt(s.avg_arpu) }}</td>
            <td class="{{ 'fx-hi' if s.tpv_change_pct > 0 else 'fx-lo' if s.tpv_change_pct < 0 else '' }}">{{ '+' if s.tpv_change_pct > 0 else '' }}{{ '%.1f' % s.tpv_change_pct }}%</td>
          </tr>
          {% endfor %}
          </tbody>
        </table>
      </div>
    {% endfor %}
    </div>
  </div>
  {% endfor %}

  <div class="ts">Generated: {{ report.generated_at.strftime('%Y-%m-%d %H:%M:%S UTC') }}</div>
{% endif %}
</div>
</body>
</html>
"""


def create_app(agent: TPVAgent) -> Flask:
    app = Flask(__name__)

    @app.template_global()
    def fmt_val(val):
        return fmt(val)

    @app.template_filter('basename')
    def basename_filter(path):
        return os.path.basename(path) if path else ''

    @app.context_processor
    def inject_helpers():
        return {"fmt": fmt, "pct": pct_str}

    @app.route("/")
    def dashboard():
        report = agent.get_last_report()
        today = datetime.now().strftime("%A, %B %d, %Y")
        bus_hist = agent.bus.get_history()
        stream_counts = {}
        for msg in bus_hist:
            stream_counts[msg["stream"]] = stream_counts.get(msg["stream"], 0) + 1

        combined = ""
        if report:
            total = sum(float(s.latest_tpv) for s in report.summaries)
            combined = fmt(total)

        return render_template_string(TEMPLATE,
            report=report,
            today=today,
            combined=combined,
            msg_count=len(bus_hist),
            bus_streams=stream_counts,
        )

    @app.route("/predictions")
    def predictions():
        report = agent.get_last_report()
        today = datetime.now().strftime("%A, %B %d, %Y")
        return render_template_string(PREDICTIONS_TEMPLATE,
            report=report,
            today=today,
            fmt=fmt,
            pct=pct_str,
        )

    @app.route("/api/reforecast", methods=["POST"])
    def reforecast():
        loop = asyncio.new_event_loop()
        loop.run_until_complete(agent.run_daily_forecast())
        loop.close()
        return jsonify({"status": "ok", "message": "Re-forecast complete"})

    @app.route("/api/reforecast-fx", methods=["POST"])
    def reforecast_fx():
        """Re-forecast with custom FX rates from the form."""
        custom_rates = {}
        for region in settings.regions:
            val = request.form.get(f"fx_{region}")
            if val:
                try:
                    custom_rates[region] = float(val)
                except ValueError:
                    pass
        usdinr = None
        usdinr_val = request.form.get("fx_USDINR")
        if usdinr_val:
            try:
                usdinr = float(usdinr_val)
            except ValueError:
                pass
        if custom_rates or usdinr:
            agent.set_fx_rates(custom_rates, usdinr=usdinr)
        loop = asyncio.new_event_loop()
        loop.run_until_complete(agent.run_daily_forecast())
        loop.close()
        from flask import redirect
        return redirect("/")

    @app.route("/api/report")
    def api_report():
        report = agent.get_last_report()
        if not report:
            return jsonify({"error": "No report available"}), 404
        return jsonify(json.loads(report.model_dump_json()))

    @app.route("/api/bus")
    def api_bus():
        stream = request.args.get("stream")
        limit = int(request.args.get("limit", 50))
        return jsonify(agent.bus.get_history(stream, limit))

    return app


if __name__ == "__main__":
    from shared.message_bus import MessageBus
    bus = MessageBus()
    a = TPVAgent(bus)
    app = create_app(a)
    asyncio.run(a.run_daily_forecast())
    app.run(host="0.0.0.0", port=5050, debug=False)
