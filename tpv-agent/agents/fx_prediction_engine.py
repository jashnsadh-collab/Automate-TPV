"""
agents/fx_prediction_engine.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FX-Rate-Sensitive TPV Prediction Engine
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Generates daily TPV/TU/ARPU predictions at multiple FX rate scenarios
(BPS changes from -20 to +20) for UAE and UK regions.

Replicates the manual daily workflow from UAE_UK Predictions.xlsx:
  For each prediction date → For each FX rate scenario →
    Predict Total_TPV, Total_TU, Avg_ARPU
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import settings
from shared.schemas import (
    FXPredictionBlock,
    FXRegionPrediction,
    FXScenario,
    Region,
)
from data_loader import get_historical_region

logger = logging.getLogger(__name__)
fx_cfg = settings.fx


class FXScenarioEngine:
    """
    Generates FX-rate-sensitive TPV predictions.

    Workflow:
      1. Get base TPV prediction from historical WMA (at BPS=0)
      2. Get base TU from historical TPV/TU ratio
      3. For each BPS level, apply pre-fitted elasticity multipliers
      4. Calculate ARPU = TPV / TU
    """

    def __init__(self):
        self._region_params = {
            "UAE": {
                "base_fx": fx_cfg.uae_base_fx,
                "fx_per_5bps": fx_cfg.uae_fx_per_5bps,
                "currency_pair": fx_cfg.uae_currency_pair,
                "tpv_multipliers": fx_cfg.uae_tpv_multipliers,
                "tu_multipliers": fx_cfg.uae_tu_multipliers,
            },
            "UK": {
                "base_fx": fx_cfg.uk_base_fx,
                "fx_per_5bps": fx_cfg.uk_fx_per_5bps,
                "currency_pair": fx_cfg.uk_currency_pair,
                "tpv_multipliers": fx_cfg.uk_tpv_multipliers,
                "tu_multipliers": fx_cfg.uk_tu_multipliers,
            },
        }

    def _get_base_predictions(
        self, region: str, start_date: date, days: int
    ) -> List[Dict]:
        """
        Get base TPV and TU predictions for each date using
        weighted moving average of recent historical data.
        """
        hist = get_historical_region(region)
        if hist.empty:
            logger.warning("No historical data for %s", region)
            return []

        predictions = []

        for i in range(days):
            target = start_date + timedelta(days=i)
            target_dow = target.weekday()

            # Get same-weekday volumes from history
            same_dow = hist[hist["Date"].dt.weekday == target_dow].sort_values(
                "Date", ascending=False
            )

            if same_dow.empty:
                # Fallback to overall recent data
                recent = hist.tail(28)
                base_tpv = float(recent["Daily_TPV"].mean())
                base_tu = int(recent["Transactions"].mean())
            else:
                # Exponentially weighted average of same-weekday data
                n = min(len(same_dow), 12)
                recent_dow = same_dow.head(n)
                weights = np.exp(np.linspace(0, -2, n))
                weights /= weights.sum()

                tpv_vals = recent_dow["Daily_TPV"].values[:n].astype(float)
                tu_vals = recent_dow["Transactions"].values[:n].astype(float)

                base_tpv = float(np.dot(weights, tpv_vals))
                base_tu = max(1, int(np.dot(weights, tu_vals)))

            # Also factor in recent trend
            recent_7d = hist.tail(7)["Daily_TPV"].mean()
            recent_14d = hist.tail(14)["Daily_TPV"].mean()
            if recent_14d > 0:
                trend_factor = recent_7d / recent_14d
                # Dampen extreme trends
                trend_factor = max(0.9, min(1.1, trend_factor))
                base_tpv *= trend_factor

            predictions.append({
                "date": target,
                "base_tpv": round(base_tpv, 2),
                "base_tu": base_tu,
                "base_arpu": round(base_tpv / max(base_tu, 1), 2),
            })

        return predictions

    def _get_fx_rate(self, region: str, bps: int, custom_base_fx: Optional[float] = None) -> float:
        """Calculate FX rate for a given BPS offset."""
        params = self._region_params[region]
        base = custom_base_fx if custom_base_fx is not None else params["base_fx"]
        offset = (bps / 5) * params["fx_per_5bps"]
        return round(base + offset, 4)

    def _get_multiplier(
        self, region: str, metric: str, bps: int
    ) -> float:
        """
        Get the elasticity multiplier for a given BPS change.
        Uses linear interpolation between pre-fitted levels.
        """
        params = self._region_params[region]
        key = f"{metric}_multipliers"
        mult_table = params[key]

        if bps in mult_table:
            return mult_table[bps]

        # Interpolate between nearest levels
        levels = sorted(mult_table.keys())
        if bps <= levels[0]:
            return mult_table[levels[0]]
        if bps >= levels[-1]:
            return mult_table[levels[-1]]

        for j in range(len(levels) - 1):
            if levels[j] <= bps <= levels[j + 1]:
                lo, hi = levels[j], levels[j + 1]
                t = (bps - lo) / (hi - lo)
                return mult_table[lo] + t * (mult_table[hi] - mult_table[lo])

        return 1.0

    def generate_predictions(
        self,
        region: str,
        custom_base_fx: Optional[float] = None,
        start_date: Optional[date] = None,
        days: Optional[int] = None,
    ) -> FXRegionPrediction:
        """
        Generate complete FX-rate-sensitive predictions for a region.

        Args:
            region: "UAE" or "UK"
            custom_base_fx: Override base FX rate (defaults to config)
            start_date: First prediction date (defaults to tomorrow)
            days: Number of days to predict (defaults to config)

        Returns:
            FXRegionPrediction with all BPS scenarios for each date
        """
        start_date = start_date or (date.today() + timedelta(days=1))
        days = days or fx_cfg.fx_forecast_days

        params = self._region_params[region]
        base_fx = custom_base_fx if custom_base_fx is not None else params["base_fx"]

        base_predictions = self._get_base_predictions(region, start_date, days)
        if not base_predictions:
            logger.warning("No base predictions available for %s", region)
            return FXRegionPrediction(
                region=Region(region),
                base_fx_rate=base_fx,
                currency_pair=params["currency_pair"],
                prediction_blocks=[],
            )

        blocks = []
        for pred in base_predictions:
            scenarios = []

            for bps in fx_cfg.bps_levels:
                fx_rate = self._get_fx_rate(region, bps, custom_base_fx)
                tpv_mult = self._get_multiplier(region, "tpv", bps)
                tu_mult = self._get_multiplier(region, "tu", bps)

                scenario_tpv = pred["base_tpv"] * tpv_mult
                scenario_tu = max(1, int(pred["base_tu"] * tu_mult))
                scenario_arpu = scenario_tpv / scenario_tu

                # % change from base (BPS=0)
                base_tpv_at_0 = pred["base_tpv"] * self._get_multiplier(region, "tpv", 0)
                tpv_change_pct = ((scenario_tpv - base_tpv_at_0) / max(base_tpv_at_0, 1)) * 100

                scenarios.append(FXScenario(
                    bps_change=bps,
                    fx_rate=fx_rate,
                    total_tpv=Decimal(str(round(scenario_tpv, 0))),
                    total_tu=scenario_tu,
                    avg_arpu=Decimal(str(round(scenario_arpu, 2))),
                    tpv_change_pct=round(tpv_change_pct, 2),
                ))

            # Base scenario values (BPS=0)
            base_scenario = next(s for s in scenarios if s.bps_change == 0)

            blocks.append(FXPredictionBlock(
                prediction_date=pred["date"],
                day_of_week=pred["date"].strftime("%A"),
                scenarios=scenarios,
                base_tpv=base_scenario.total_tpv,
                base_tu=base_scenario.total_tu,
                base_arpu=base_scenario.avg_arpu,
            ))

        return FXRegionPrediction(
            region=Region(region),
            base_fx_rate=base_fx,
            currency_pair=params["currency_pair"],
            prediction_blocks=blocks,
        )

    def generate_all_regions(
        self,
        custom_fx_rates: Optional[Dict[str, float]] = None,
        start_date: Optional[date] = None,
    ) -> Dict[str, FXRegionPrediction]:
        """Generate FX predictions for all configured regions."""
        custom_fx_rates = custom_fx_rates or {}
        results = {}

        for region in settings.regions:
            custom_fx = custom_fx_rates.get(region)
            results[region] = self.generate_predictions(
                region, custom_base_fx=custom_fx, start_date=start_date
            )
            logger.info(
                "FX predictions generated for %s: %d dates x %d scenarios",
                region,
                len(results[region].prediction_blocks),
                len(fx_cfg.bps_levels),
            )

        return results

    def export_to_dataframe(
        self, prediction: FXRegionPrediction
    ) -> pd.DataFrame:
        """Export FX predictions to a flat DataFrame (for Excel export)."""
        rows = []
        for block in prediction.prediction_blocks:
            for s in block.scenarios:
                rows.append({
                    "Prediction_Date": block.prediction_date,
                    "Day": block.day_of_week,
                    "BPS_Change": s.bps_change,
                    "FX_Rate": s.fx_rate,
                    "Total_TPV": float(s.total_tpv),
                    "Total_TU": s.total_tu,
                    "Avg_ARPU": float(s.avg_arpu),
                    "TPV_Change_%": s.tpv_change_pct,
                })
        return pd.DataFrame(rows)

    def export_to_excel(
        self,
        predictions: Dict[str, FXRegionPrediction],
        output_path: str,
    ) -> str:
        """
        Export all region predictions to Excel workbook
        matching the manual UAE_UK Predictions.xlsx format.
        """
        from datetime import datetime
        today_str = date.today().strftime("%dth %b")

        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            for region, pred in predictions.items():
                sheet_name = f"{today_str} {region}"
                df = self.export_to_dataframe(pred)
                df.to_excel(writer, sheet_name=sheet_name, index=False)

        logger.info("FX predictions exported to %s", output_path)
        return output_path
