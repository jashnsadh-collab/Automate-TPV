#!/usr/bin/env python3
"""
TPV AI Agent — Uses Claude to analyze TPV data and generate daily predictions report.
Automates the daily Claude conversation workflow for UAE/UK TPV analysis.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import anthropic

from config import REGIONS, CATEGORIES
from data_loader import (
    get_historical_region, load_category_data,
    load_monthly_summary, load_regression_stats,
)
from models import EnsembleForecaster


def prepare_data_context() -> str:
    """Gather all TPV data into a structured text block for Claude."""
    sections = []

    # --- 1. Latest daily data per region ---
    for region in REGIONS:
        hist = get_historical_region(region)
        if hist.empty:
            continue
        last_30 = hist.tail(30)
        sections.append(f"=== {region} — Last 30 Days (Daily TPV, Transactions, Users) ===")
        for _, row in last_30.iterrows():
            sections.append(
                f"  {row['Date'].strftime('%Y-%m-%d')} ({row['Date'].strftime('%a')}): "
                f"TPV={int(row['Daily_TPV']):,}  Txns={int(row['Transactions']):,}  Users={int(row['Users']):,}"
            )
        sections.append("")

    # --- 2. Category breakdown (last 14 days) ---
    for region in REGIONS:
        try:
            cat_df = load_category_data(region)
            cat_df = cat_df[cat_df["Daily_TPV"] > 0].sort_values("Date")
            if cat_df.empty:
                continue
            latest_date = cat_df["Date"].max()
            last_14 = cat_df[cat_df["Date"] >= (latest_date - pd.Timedelta(days=13))]
            sections.append(f"=== {region} — Category Breakdown (Last 14 Days) ===")
            for date in sorted(last_14["Date"].unique()):
                day_data = last_14[last_14["Date"] == date]
                parts = []
                for _, row in day_data.iterrows():
                    parts.append(f"{row['Category']}={int(row['Daily_TPV']):,}")
                total = day_data["Daily_TPV"].sum()
                sections.append(f"  {pd.Timestamp(date).strftime('%Y-%m-%d')}: {', '.join(parts)}  (Total={int(total):,})")
            sections.append("")
        except Exception:
            pass

    # --- 3. Monthly summary ---
    monthly = load_monthly_summary()
    sections.append("=== Monthly TPV Summary ===")
    for _, row in monthly.iterrows():
        sections.append(
            f"  {row['Month']} [{row['Type']}]: "
            f"UAE={int(row['UAE_TPV']):,}  UK={int(row['UK_TPV']):,}  Total={int(row['Total_TPV']):,}"
        )
    sections.append("")

    # --- 4. Regression stats ---
    reg = load_regression_stats()
    sections.append("=== Regression Stats (from Excel) ===")
    for _, row in reg.iterrows():
        sections.append(f"  {row['Region']} {row['Metric']}: slope={row['Slope']}/day  intercept={row['Intercept']}  R²={row['R2']}")
    sections.append("")

    # --- 5. Statistical model predictions ---
    for region in REGIONS:
        hist = get_historical_region(region)
        if hist.empty:
            continue
        forecaster = EnsembleForecaster()
        forecaster.fit(hist["Date"], hist["Daily_TPV"])
        stats = forecaster.get_model_stats()
        last_date = hist["Date"].iloc[-1]
        future = pd.Series([last_date + timedelta(days=i + 1) for i in range(14)])
        preds = forecaster.predict(future)
        sections.append(f"=== {region} — Statistical Model Predictions (Next 14 Days) ===")
        sections.append(f"  Model R²: {stats['linear_r2']}  Slope: {stats['linear_slope']:,.2f}/day")
        for _, row in preds.iterrows():
            d = pd.Timestamp(row["Date"])
            sections.append(
                f"  {d.strftime('%Y-%m-%d')} ({d.strftime('%a')}): "
                f"Ensemble={int(row['Ensemble']):,}  Low={int(row['Low']):,}  High={int(row['High']):,}"
            )
        sections.append("")

    # --- 6. Today's context ---
    today = datetime.now()
    sections.insert(0, f"Today's date: {today.strftime('%A, %B %d, %Y')}\n")

    return "\n".join(sections)


SYSTEM_PROMPT = """You are a TPV (Total Payment Volume) analyst for a fintech company operating in the UAE and UK markets. You analyze daily payment volume data and produce actionable daily prediction reports.

Your role:
- Analyze the provided historical TPV data, category breakdowns, and statistical model outputs
- Identify trends, patterns, anomalies, and seasonality (weekly, monthly)
- Generate daily predictions with confidence levels
- Provide business insights and flag risks

Output your analysis as a structured daily report with these sections:

1. **Executive Summary** — 3-4 bullet points of the most important findings today
2. **UAE Analysis** — Current state, trend direction, key drivers, prediction for next 7 days
3. **UK Analysis** — Same as above for UK
4. **Category Insights** — Which categories (Non-Referred, Referred, Whale) are driving growth or decline
5. **Weekly Pattern** — Day-of-week effects observed
6. **Monthly Outlook** — Projected month-end totals vs prior months, growth trajectory
7. **Risk Flags** — Anomalies, concerning trends, or deviations from expected patterns
8. **Recommendations** — 2-3 actionable suggestions based on the data

Format numbers clearly (e.g., 22.8M, 3.7K). Be specific with percentages and comparisons. Keep it concise but data-driven."""


def run_ai_agent(api_key: str = None) -> str:
    """Run the AI agent to generate TPV analysis."""
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return "ERROR: No Anthropic API key provided. Set ANTHROPIC_API_KEY env var or pass --api-key."

    print("  Gathering TPV data...")
    data_context = prepare_data_context()

    print(f"  Data context: {len(data_context):,} chars")
    print("  Calling Claude for analysis...")

    client = anthropic.Anthropic(api_key=key)
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"Here is today's TPV data for analysis. Please generate the daily predictions report.\n\n{data_context}"
        }],
    )

    response = message.content[0].text
    return response


def save_ai_report(content: str, today: datetime) -> str:
    """Save the AI report to output directory."""
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
    os.makedirs(output_dir, exist_ok=True)
    filename = f"ai_report_{today.strftime('%Y-%m-%d')}.md"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w") as f:
        f.write(f"# TPV AI Agent Report — {today.strftime('%A, %B %d, %Y')}\n\n")
        f.write(content)
    return filepath


def main():
    import argparse
    parser = argparse.ArgumentParser(description="TPV AI Agent — Claude-powered TPV analysis")
    parser.add_argument("--api-key", help="Anthropic API key (or set ANTHROPIC_API_KEY env var)")
    parser.add_argument("--data-only", action="store_true", help="Print data context only (no AI call)")
    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("  TPV AI AGENT — Claude-Powered Analysis")
    print("=" * 70 + "\n")

    if args.data_only:
        print(prepare_data_context())
        return

    report = run_ai_agent(api_key=args.api_key)

    if report.startswith("ERROR:"):
        print(f"\n  {report}\n")
        return

    print("\n" + "=" * 70)
    print("  AI ANALYSIS REPORT")
    print("=" * 70 + "\n")
    print(report)

    filepath = save_ai_report(report, datetime.now())
    print(f"\n{'=' * 70}")
    print(f"  Report saved to: {filepath}")
    print(f"{'=' * 70}\n")


if __name__ == "__main__":
    main()
