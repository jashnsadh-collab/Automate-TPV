#!/usr/bin/env python3
"""
run.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TPV Agent — Entry Point
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Starts the async TPV agent with message bus and web dashboard.

Usage:
  python3 run.py                    # Agent + Web dashboard (port 5050)
  python3 run.py --agent-only       # Agent only (no web server)
  python3 run.py --web-only         # Web dashboard only (no agent scheduler)
  python3 run.py --forecast-once    # Single forecast run, print report, exit
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import threading
from datetime import datetime
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.settings import settings
from shared.message_bus import MessageBus
from agents.tpv_agent import TPVAgent

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s  %(levelname)-8s  %(name)-24s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("tpv.main")


def _fmt(val) -> str:
    val = float(val) if isinstance(val, Decimal) else val
    if abs(val) >= 1_000_000:
        return f"{val / 1_000_000:,.2f}M"
    if abs(val) >= 1_000:
        return f"{val / 1_000:,.1f}K"
    return f"{val:,.0f}"


def print_report(report) -> None:
    """Pretty-print the DailyReport to terminal."""
    print("\n" + "━" * 72)
    print("  TPV AGENT — DAILY FORECAST REPORT")
    print(f"  {report.business_date.strftime('%A, %B %d, %Y')}")
    print("━" * 72)

    # Summaries
    print("\n  REGION SUMMARY")
    print("  " + "─" * 50)
    for s in report.summaries:
        pct_dod = f"+{s.dod_change_pct:.1f}%" if s.dod_change_pct > 0 else f"{s.dod_change_pct:.1f}%"
        pct_wow = f"+{s.wow_change_pct:.1f}%" if s.wow_change_pct > 0 else f"{s.wow_change_pct:.1f}%"
        print(f"\n  {s.region.value}  ({s.latest_date})")
        print(f"    TPV: {_fmt(s.latest_tpv)}   DoD: {pct_dod}   WoW: {pct_wow}")
        print(f"    Txns: {s.transactions:,}   Users: {s.users:,}")
        print(f"    MTD: {_fmt(s.mtd_total)}   Projected Month: {_fmt(s.projected_month)}")

    # Forecasts
    print("\n  7-DAY FORECASTS")
    print("  " + "─" * 50)
    for region, rows in report.forecasts.items():
        print(f"\n  {region}:")
        print(f"    {'Date':<12} {'Day':<5} {'Predicted':>12} {'Low':>12} {'High':>12}")
        for r in rows:
            print(f"    {r.date}  {r.day_of_week:<5} {_fmt(r.ensemble):>12} {_fmt(r.low):>12} {_fmt(r.high):>12}")

    # Categories
    print("\n  CATEGORY BREAKDOWN")
    print("  " + "─" * 50)
    for cb in report.category_breakdowns:
        print(f"\n  {cb.region.value} ({cb.date}):")
        for c in cb.categories:
            print(f"    {c['name']:<16} {_fmt(c['tpv']):>12}  ({c['share']:.1f}%)")
        print(f"    {'TOTAL':<16} {_fmt(cb.total):>12}")
        if cb.trend_7d:
            print(f"\n  {cb.region.value} 7-Day Trend:")
            print(f"    {'Category':<16} {'Avg':>12} {'Min':>12} {'Max':>12}")
            for t in cb.trend_7d:
                print(f"    {t['name']:<16} {_fmt(t['avg']):>12} {_fmt(t['min']):>12} {_fmt(t['max']):>12}")

    # Model perf
    print("\n  MODEL PERFORMANCE")
    print("  " + "─" * 50)
    for mp in report.model_performance:
        print(f"\n  {mp.region.value}:  R²={mp.linear_r2:.4f}  Slope={_fmt(mp.slope_per_day)}/day")
        if mp.backtest:
            print(f"    {'Model':<12} {'MAPE':>8} {'RMSE':>14}")
            for name, metrics in mp.backtest.items():
                print(f"    {name:<12} {metrics['MAPE']:>7.2f}% {_fmt(metrics['RMSE']):>14}")

    # Alerts
    if report.alerts:
        print("\n  ALERTS")
        print("  " + "─" * 50)
        for a in report.alerts:
            icon = "🔴" if a["severity"] == "CRITICAL" else "🟡"
            print(f"  {icon}  [{a['severity']}] {a['description']}")

    # Monthly
    print("\n  MONTHLY HISTORY")
    print("  " + "─" * 50)
    print(f"    {'Month':<12} {'Type':<12} {'UAE':>14} {'UK':>14} {'Total':>14}")
    for m in report.monthly_history:
        print(f"    {m['month']:<12} {m['type']:<12} {_fmt(m['uae_tpv']):>14} {_fmt(m['uk_tpv']):>14} {_fmt(m['total_tpv']):>14}")

    # Message bus stats
    print("\n  MESSAGE BUS")
    print("  " + "─" * 50)
    bus_hist = agent.bus.get_history()
    stream_counts = {}
    for msg in bus_hist:
        stream_counts[msg["stream"]] = stream_counts.get(msg["stream"], 0) + 1
    for stream, count in stream_counts.items():
        print(f"    {stream}: {count} messages")

    print("\n" + "━" * 72)
    print(f"  Generated: {report.generated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("━" * 72 + "\n")


def start_web_dashboard(agent_instance: TPVAgent):
    """Start Flask web dashboard in a separate thread."""
    from web_app_v2 import create_app
    app = create_app(agent_instance)
    logger.info("Web dashboard starting on http://localhost:%d", settings.web_port)
    app.run(host="0.0.0.0", port=settings.web_port, debug=False, use_reloader=False)


# ── Global agent reference ─────────────────────────────────────────────────
bus = MessageBus()
agent = TPVAgent(bus)


async def run_forecast_once():
    report = await agent.run_daily_forecast()
    print_report(report)


async def run_agent_with_web():
    # Start web in background thread
    web_thread = threading.Thread(target=start_web_dashboard, args=(agent,), daemon=True)
    web_thread.start()
    # Run async agent
    await agent.run()


async def run_agent_only():
    await agent.run()


def main():
    parser = argparse.ArgumentParser(description="TPV Predictions Agent")
    parser.add_argument("--agent-only", action="store_true", help="Run agent without web dashboard")
    parser.add_argument("--web-only", action="store_true", help="Run web dashboard without agent scheduler")
    parser.add_argument("--forecast-once", action="store_true", help="Run single forecast and exit")
    args = parser.parse_args()

    print("\n" + "━" * 72)
    print("  TPV PREDICTIONS AGENT — UAE / UK")
    print("  Async Architecture with Message Bus")
    print("━" * 72 + "\n")

    if args.forecast_once:
        asyncio.run(run_forecast_once())
    elif args.agent_only:
        asyncio.run(run_agent_only())
    elif args.web_only:
        start_web_dashboard(agent)
    else:
        asyncio.run(run_agent_with_web())


if __name__ == "__main__":
    main()
