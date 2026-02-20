#!/usr/bin/env python3
"""TPV Predictions Agent — Daily forecasting for UAE/UK markets."""

import argparse
import sys
import os
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import REGIONS, CATEGORIES, FORECAST_DAYS
from data_loader import (
    get_historical_region,
    load_category_data,
    load_monthly_summary,
    load_regression_stats,
)
from models import EnsembleForecaster
from report_generator import generate_report, save_report


def run_predictions(regions=None, forecast_days=FORECAST_DAYS, include_categories=True, backtest_days=30):
    regions = regions or REGIONS
    today = datetime.now()

    region_data = {}
    predictions = {}
    model_stats = {}
    backtest_results = {}
    category_data = {}
    alerts = []

    for region in regions:
        print(f"  Loading {region} data...")
        hist = get_historical_region(region)
        region_data[region] = hist

        if hist.empty:
            print(f"  WARNING: No historical data for {region}")
            predictions[region] = pd.DataFrame()
            continue

        dates = hist["Date"]
        values = hist["Daily_TPV"]

        # Fit ensemble model
        forecaster = EnsembleForecaster()
        forecaster.fit(dates, values)
        model_stats[region] = forecaster.get_model_stats()

        # Generate future dates
        last_date = dates.iloc[-1]
        future_dates = pd.Series([last_date + timedelta(days=i + 1) for i in range(forecast_days)])
        preds = forecaster.predict(future_dates)
        predictions[region] = preds

        # Backtest
        if len(hist) > backtest_days + 30:
            bt = forecaster.backtest(dates, values, holdout=backtest_days)
            backtest_results[region] = bt
            # Re-fit on full data after backtest
            forecaster.fit(dates, values)

        # Alerts
        latest_val = values.iloc[-1]
        avg_7 = values.tail(7).mean()
        avg_30 = values.tail(30).mean()

        if latest_val > avg_7 * 1.2:
            alerts.append(f"{region}: Latest TPV ({_quick_fmt(latest_val)}) is >20% above 7-day avg ({_quick_fmt(avg_7)})")
        elif latest_val < avg_7 * 0.8:
            alerts.append(f"{region}: Latest TPV ({_quick_fmt(latest_val)}) is >20% below 7-day avg ({_quick_fmt(avg_7)})")

        growth_recent = (avg_7 - avg_30) / max(avg_30, 1) * 100
        if growth_recent > 15:
            alerts.append(f"{region}: Strong growth acceleration — 7d avg is {growth_recent:.0f}% above 30d avg")
        elif growth_recent < -15:
            alerts.append(f"{region}: Growth deceleration — 7d avg is {abs(growth_recent):.0f}% below 30d avg")

    # Category data
    if include_categories:
        for region in regions:
            try:
                cat_df = load_category_data(region)
                cat_df = cat_df[cat_df["Daily_TPV"] > 0]
                category_data[region] = cat_df
            except Exception:
                pass

    # Monthly summary
    monthly = load_monthly_summary()

    # Generate report
    report = generate_report(
        region_data=region_data,
        predictions=predictions,
        category_data=category_data,
        model_stats=model_stats,
        backtest=backtest_results,
        monthly=monthly,
        alerts=alerts,
        today=today,
    )

    print(report)

    filepath = save_report(report, today)
    print(f"\nReport saved to: {filepath}")
    return report


def run_backtest_only(regions=None, holdout=30):
    regions = regions or REGIONS
    print(f"\nBacktesting models (holdout={holdout} days)...\n")

    for region in regions:
        hist = get_historical_region(region)
        if hist.empty or len(hist) < holdout + 30:
            print(f"  {region}: Not enough data for backtest")
            continue

        forecaster = EnsembleForecaster()
        results = forecaster.backtest(hist["Date"], hist["Daily_TPV"], holdout=holdout)

        print(f"  {region} — Backtest Results (last {holdout} days):")
        for model_name, metrics in results.items():
            print(f"    {model_name:12s}  MAPE: {metrics['MAPE']:6.2f}%  RMSE: {metrics['RMSE']:>12,.0f}")
        print()


def show_regression_comparison():
    from data_loader import load_regression_stats
    print("\nExcel Regression Stats vs Agent Model:\n")
    stats = load_regression_stats()
    print(stats.to_string(index=False))
    print()

    for region in REGIONS:
        hist = get_historical_region(region)
        if hist.empty:
            continue
        forecaster = EnsembleForecaster()
        forecaster.fit(hist["Date"], hist["Daily_TPV"])
        ms = forecaster.get_model_stats()
        print(f"  {region} Agent: slope={ms['linear_slope']:,.2f}/day  R²={ms['linear_r2']:.4f}")
    print()


def _quick_fmt(val):
    if abs(val) >= 1_000_000:
        return f"{val/1_000_000:,.2f}M"
    return f"{val/1_000:,.1f}K"


def main():
    parser = argparse.ArgumentParser(description="TPV Predictions Agent for UAE/UK")
    parser.add_argument("--predict", type=int, default=FORECAST_DAYS, help=f"Forecast horizon in days (default: {FORECAST_DAYS})")
    parser.add_argument("--region", choices=["UAE", "UK"], help="Single region only")
    parser.add_argument("--no-category", action="store_true", help="Skip category breakdown")
    parser.add_argument("--backtest", type=int, metavar="DAYS", help="Run backtest only with N holdout days")
    parser.add_argument("--compare", action="store_true", help="Compare agent regression with Excel stats")
    args = parser.parse_args()

    regions = [args.region] if args.region else None

    print("\n" + "=" * 70)
    print("  TPV PREDICTIONS AGENT — UAE / UK")
    print("=" * 70 + "\n")

    if args.compare:
        show_regression_comparison()
        return

    if args.backtest:
        run_backtest_only(regions=regions, holdout=args.backtest)
        return

    run_predictions(
        regions=regions,
        forecast_days=args.predict,
        include_categories=not args.no_category,
    )


if __name__ == "__main__":
    main()
