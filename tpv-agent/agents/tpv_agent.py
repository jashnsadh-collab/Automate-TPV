"""
agents/tpv_agent.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TPV Forecast Agent — UAE / UK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Responsibilities:
  1. Produce daily TPV forecast per region (WMA + multiplier stack)
  2. Split forecast by user category (Non-Referred, Referred, Whale)
  3. Run anomaly detection on latest actuals vs forecast
  4. Re-forecast when external triggers arrive (market moves, data refresh)
  5. Handle edge cases: holidays, double-holiday, month-end, weekends, data gaps

Publishes to : tpv.forecasts
Subscribes to: tpv.alerts (listens for re-forecast triggers)
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import settings
from shared.calendar_service import calendar
from shared.message_bus import (
    STREAM_ALERTS,
    STREAM_STATUS,
    STREAM_TPV,
    MessageBus,
)
from shared.schemas import (
    AlertSeverity,
    AnomalyAlert,
    AgentStatus,
    Category,
    CategoryBreakdown,
    CategorySplit,
    ConfidenceInterval,
    ConfidenceLevel,
    DailyReport,
    DailyTPVForecast,
    DeviationAlert,
    ForecastRow,
    FXRegionPrediction,
    GrowthAlert,
    ModelPerformance,
    MultiplierDetail,
    Region,
    RegionSummary,
    ReforecastTrigger,
)
from agents.fx_prediction_engine import FXScenarioEngine
from data_loader import (
    get_historical_region,
    load_category_data,
    load_monthly_summary,
    load_regression_stats,
)

logger = logging.getLogger(__name__)
cfg = settings.tpv


# ── Data access layer ──────────────────────────────────────────────────────

def fetch_historical_volumes(
    region: str, target_date: date, weeks: int
) -> List[Optional[float]]:
    """
    Pull same-weekday TPV volumes over trailing N weeks from Excel data.
    Returns list of floats; None for data gaps.
    """
    hist = get_historical_region(region)
    if hist.empty:
        return [None] * weeks

    target_weekday = target_date.weekday()
    same_dow = hist[hist["Date"].dt.weekday == target_weekday].sort_values("Date", ascending=False)

    volumes: List[Optional[float]] = []
    for i in range(weeks):
        if i < len(same_dow):
            volumes.append(float(same_dow.iloc[i]["Daily_TPV"]))
        else:
            volumes.append(None)

    return list(reversed(volumes))


def fetch_recent_volumes(region: str, days: int = 30) -> pd.DataFrame:
    """Last N days of historical data."""
    hist = get_historical_region(region)
    return hist.tail(days) if not hist.empty else pd.DataFrame()


def fetch_category_latest(region: str) -> Dict[str, float]:
    """Latest day's category breakdown."""
    try:
        cat_df = load_category_data(region)
        cat_df = cat_df[cat_df["Daily_TPV"] > 0]
        if cat_df.empty:
            return {}
        latest_date = cat_df["Date"].max()
        day_data = cat_df[cat_df["Date"] == latest_date]
        return {row["Category"]: float(row["Daily_TPV"]) for _, row in day_data.iterrows()}
    except Exception:
        return {}


def fetch_category_trend(region: str, days: int = 14) -> pd.DataFrame:
    """Category data for last N days."""
    try:
        cat_df = load_category_data(region)
        cat_df = cat_df[cat_df["Daily_TPV"] > 0].sort_values("Date")
        if cat_df.empty:
            return pd.DataFrame()
        latest_date = cat_df["Date"].max()
        cutoff = latest_date - pd.Timedelta(days=days - 1)
        return cat_df[cat_df["Date"] >= cutoff]
    except Exception:
        return pd.DataFrame()


# ── Forecast Engine ────────────────────────────────────────────────────────

class TPVForecastEngine:
    """
    Weighted moving average over same-weekday TPV volumes with exponential
    decay and a stacked multiplier system.
    """

    def __init__(self):
        self.lookback = cfg.wma_lookback_weeks
        self.decay = cfg.wma_decay

    def _wma(self, volumes: List[Optional[float]]) -> float:
        """
        Exponentially-decayed weighted moving average.
        Gaps (None) filled with mean of non-null values.
        """
        filled: List[float] = []
        non_null = [v for v in volumes if v is not None]
        fallback = float(np.mean(non_null)) if non_null else 0.0

        for v in volumes:
            if v is None:
                filled.append(fallback)
                logger.warning("Data gap — using fallback volume %.2f", fallback)
            else:
                filled.append(v)

        if not filled:
            return 0.0

        n = len(filled)
        weights = np.array([self.decay ** i for i in range(n - 1, -1, -1)])
        weights /= weights.sum()
        return float(np.dot(weights, filled))

    def _confidence_interval(
        self, base: float, volumes: List[Optional[float]]
    ) -> tuple[float, float, ConfidenceLevel]:
        non_null = [v for v in volumes if v is not None]
        if not non_null:
            return base * 0.8, base * 1.2, ConfidenceLevel.LOW

        std = float(np.std(non_null))
        cv = std / base if base else 1.0
        z = cfg.ci_z_score
        lower = max(0, base - z * std)
        upper = base + z * std

        if cv < cfg.high_cv_threshold:
            confidence = ConfidenceLevel.HIGH
        elif cv < cfg.medium_cv_threshold:
            confidence = ConfidenceLevel.MEDIUM
        else:
            confidence = ConfidenceLevel.LOW

        return lower, upper, confidence

    def compute_multipliers(
        self, target_date: date, region: str
    ) -> List[MultiplierDetail]:
        """Build the multiplier stack for a given date and region."""
        mults: List[MultiplierDetail] = []
        country = settings.regions[region].holidays_country

        # 1. Payday window (25th-28th)
        if calendar.is_payday_window(target_date):
            val = (cfg.payday_multiplier_min + cfg.payday_multiplier_max) / 2
            mults.append(MultiplierDetail(
                name="payday_window", value=val,
                reason=f"Day {target_date.day} is in payday window (25-28)",
            ))

        # 2. Holiday effects
        if calendar.is_day_before_holiday(target_date, country):
            mults.append(MultiplierDetail(
                name="pre_holiday", value=cfg.holiday_pre_multiplier,
                reason=f"Day before {country} holiday — pre-holiday surge expected",
            ))
        elif calendar.is_day_after_holiday(target_date, country):
            mults.append(MultiplierDetail(
                name="post_holiday", value=cfg.holiday_post_multiplier,
                reason=f"Day after {country} holiday — post-holiday dip expected",
            ))

        # 3. Double-holiday lookahead
        lookahead = calendar.holiday_lookahead(target_date, days=3)
        holidays_ahead = lookahead["holiday_flags"].get(country, [])
        if len(holidays_ahead) >= 2:
            mults.append(MultiplierDetail(
                name="double_holiday_prefund", value=1.30,
                reason=f"Double holiday in next 3 days ({holidays_ahead}) — pre-funding boost",
            ))

        # 4. Month-end
        if calendar.is_month_end(target_date):
            mults.append(MultiplierDetail(
                name="month_end", value=cfg.month_end_multiplier,
                reason="Month-end settlement spike expected",
            ))

        # 5. Weekend decay
        if calendar.is_weekend(target_date, country):
            mults.append(MultiplierDetail(
                name="weekend", value=cfg.weekend_decay,
                reason=f"Weekend in {country} — reduced volume",
            ))

        # 6. Day-of-week seasonal factor
        dow_factors = {0: 0.95, 1: 1.00, 2: 1.00, 3: 1.05, 4: 1.08, 5: 0.82, 6: 0.72}
        dow_val = dow_factors.get(target_date.weekday(), 1.0)
        if dow_val != 1.0:
            mults.append(MultiplierDetail(
                name="day_of_week", value=dow_val,
                reason=f"{target_date.strftime('%A')} seasonal factor",
            ))

        return mults

    def forecast(
        self, target_date: date, region: str
    ) -> Dict[str, Any]:
        """Run the full forecast pipeline for one date + region."""
        volumes = fetch_historical_volumes(region, target_date, self.lookback)
        base = self._wma(volumes)
        lower_ci, upper_ci, confidence = self._confidence_interval(base, volumes)

        multipliers = self.compute_multipliers(target_date, region)

        # Stack multipliers (multiplicative)
        stacked = 1.0
        for m in multipliers:
            stacked *= m.value
        stacked = min(stacked, cfg.total_multiplier_cap)

        forecast_tpv = base * stacked

        return {
            "base_tpv": round(base, 2),
            "stacked_multiplier": round(stacked, 4),
            "forecast_tpv": round(forecast_tpv, 2),
            "lower_ci": round(lower_ci * stacked, 2),
            "upper_ci": round(upper_ci * stacked, 2),
            "confidence": confidence,
            "multipliers": multipliers,
        }

    def forecast_range(
        self, start_date: date, days: int, region: str
    ) -> List[Dict[str, Any]]:
        """Forecast a range of dates."""
        results = []
        for i in range(days):
            d = start_date + timedelta(days=i)
            result = self.forecast(d, region)
            result["date"] = d
            results.append(result)
        return results


# ── Category Splitter ──────────────────────────────────────────────────────

class CategorySplitter:
    """
    Split total TPV forecast into categories using:
      - Base: historical category mix from recent data
      - Fallback: config defaults if no category data available
    """

    def split(
        self, forecast_tpv: float, region: str
    ) -> Dict[str, Dict]:
        latest = fetch_category_latest(region)
        if latest:
            total = sum(latest.values())
            weights = {k: v / total for k, v in latest.items()} if total > 0 else {}
        else:
            weights = cfg.default_category_mix

        splits = {}
        percentages = {}
        for cat, pct in weights.items():
            splits[cat] = round(forecast_tpv * pct, 2)
            percentages[cat] = round(pct * 100, 2)

        return {"splits": splits, "percentages": percentages}


# ── Anomaly Detection ──────────────────────────────────────────────────────

class AnomalyDetector:
    """Detect deviations and growth anomalies from historical data."""

    def check_deviation(self, region: str) -> Optional[Dict]:
        """Check if latest TPV deviates >20% from 7-day avg."""
        recent = fetch_recent_volumes(region, 8)
        if len(recent) < 8:
            return None

        latest = float(recent.iloc[-1]["Daily_TPV"])
        avg_7d = float(recent.iloc[:-1]["Daily_TPV"].mean())

        if avg_7d == 0:
            return None

        deviation = ((latest - avg_7d) / avg_7d) * 100

        if abs(deviation) > 20:
            return {
                "latest": latest,
                "avg_7d": avg_7d,
                "deviation_pct": round(deviation, 2),
                "severity": AlertSeverity.CRITICAL if abs(deviation) > 40 else AlertSeverity.WARNING,
            }
        return None

    def check_growth(self, region: str) -> Optional[Dict]:
        """Check if 7d avg deviates >15% from 30d avg."""
        recent = fetch_recent_volumes(region, 30)
        if len(recent) < 14:
            return None

        avg_7d = float(recent.tail(7)["Daily_TPV"].mean())
        avg_30d = float(recent["Daily_TPV"].mean())

        if avg_30d == 0:
            return None

        growth = ((avg_7d - avg_30d) / avg_30d) * 100

        if abs(growth) > 15:
            return {
                "avg_7d": avg_7d,
                "avg_30d": avg_30d,
                "growth_pct": round(growth, 2),
                "direction": "ACCELERATING" if growth > 0 else "DECELERATING",
                "severity": AlertSeverity.WARNING,
            }
        return None


# ── Main Agent ─────────────────────────────────────────────────────────────

class TPVAgent:
    """
    Autonomous async agent for TPV prediction.
    Entry-point: await agent.run()
    """

    def __init__(self, bus: MessageBus):
        self.bus = bus
        self.engine = TPVForecastEngine()
        self.splitter = CategorySplitter()
        self.detector = AnomalyDetector()
        self.fx_engine = FXScenarioEngine()
        self._running = False
        self._last_report: Optional[DailyReport] = None
        self._custom_fx_rates: Dict[str, float] = {}  # user-provided FX rates

    # ── Publish helpers ────────────────────────────────────────────────────

    async def _publish_status(self, status: str, details: Dict = None) -> None:
        msg = AgentStatus(
            trace_id=str(uuid.uuid4()),
            status=status,
            details=details or {},
        )
        await self.bus.publish(STREAM_STATUS, msg.model_dump(mode="json"), msg.trace_id)

    async def _publish_forecast(
        self, result: Dict, region: str, target_date: date, trace_id: str
    ) -> None:
        msg = DailyTPVForecast(
            trace_id=trace_id,
            business_date=target_date,
            region=Region(region),
            base_tpv=Decimal(str(result["base_tpv"])),
            forecast_tpv=Decimal(str(result["forecast_tpv"])),
            confidence_interval=ConfidenceInterval(
                lower=Decimal(str(result["lower_ci"])),
                upper=Decimal(str(result["upper_ci"])),
            ),
            confidence_level=result["confidence"],
            stacked_multiplier=result["stacked_multiplier"],
            multipliers_applied=result["multipliers"],
        )
        await self.bus.publish(STREAM_TPV, msg.model_dump(mode="json"), trace_id)
        logger.info(
            "Published forecast  region=%s  date=%s  TPV=%.2f  confidence=%s",
            region, target_date, result["forecast_tpv"], result["confidence"].value,
        )

    async def _publish_category_split(
        self, split_data: Dict, region: str, target_date: date, trace_id: str
    ) -> None:
        msg = CategorySplit(
            trace_id=trace_id,
            business_date=target_date,
            region=Region(region),
            splits={k: Decimal(str(v)) for k, v in split_data["splits"].items()},
            percentages=split_data["percentages"],
        )
        await self.bus.publish(STREAM_TPV, msg.model_dump(mode="json"), trace_id)

    async def _publish_alerts(self, region: str, trace_id: str) -> None:
        # Deviation alert
        dev = self.detector.check_deviation(region)
        if dev:
            direction = "above" if dev["deviation_pct"] > 0 else "below"
            msg = DeviationAlert(
                trace_id=trace_id,
                region=Region(region),
                severity=dev["severity"],
                latest_tpv=Decimal(str(dev["latest"])),
                avg_7d=Decimal(str(dev["avg_7d"])),
                deviation_pct=dev["deviation_pct"],
                description=f"{region}: Latest TPV is {abs(dev['deviation_pct']):.1f}% {direction} 7-day avg",
            )
            await self.bus.publish_alert("TPV_DEVIATION", msg.model_dump(mode="json"), trace_id)

        # Growth alert
        growth = self.detector.check_growth(region)
        if growth:
            msg = GrowthAlert(
                trace_id=trace_id,
                region=Region(region),
                severity=growth["severity"],
                avg_7d=Decimal(str(growth["avg_7d"])),
                avg_30d=Decimal(str(growth["avg_30d"])),
                growth_pct=growth["growth_pct"],
                direction=growth["direction"],
                description=f"{region}: Growth {growth['direction'].lower()} — 7d avg is {abs(growth['growth_pct']):.0f}% vs 30d avg",
            )
            await self.bus.publish_alert("TPV_GROWTH", msg.model_dump(mode="json"), trace_id)

    # ── Core forecast routine ──────────────────────────────────────────────

    async def run_daily_forecast(
        self,
        target_date: Optional[date] = None,
        trace_id: Optional[str] = None,
    ) -> DailyReport:
        target_date = target_date or date.today()
        trace_id = trace_id or str(uuid.uuid4())

        await self._publish_status("FORECASTING", {"date": str(target_date)})
        logger.info("━━━ DAILY FORECAST START  date=%s  trace=%s ━━━", target_date, trace_id)

        summaries = []
        all_forecasts = {}
        category_breakdowns = []
        model_perfs = []
        all_alerts = []

        for region in settings.regions:
            logger.info("  Processing %s...", region)

            hist = get_historical_region(region)
            if hist.empty:
                logger.warning("  No data for %s — skipping", region)
                continue

            # --- Summary ---
            latest = hist.iloc[-1]
            prev = hist.iloc[-2] if len(hist) >= 2 else latest
            week_ago = hist.iloc[-8] if len(hist) >= 8 else latest
            dod = ((latest["Daily_TPV"] - prev["Daily_TPV"]) / max(prev["Daily_TPV"], 1)) * 100
            wow = ((latest["Daily_TPV"] - week_ago["Daily_TPV"]) / max(week_ago["Daily_TPV"], 1)) * 100

            cm, cy = latest["Date"].month, latest["Date"].year
            mtd_df = hist[(hist["Date"].dt.month == cm) & (hist["Date"].dt.year == cy)]
            mtd_total = mtd_df["Daily_TPV"].sum()
            days_elapsed = len(mtd_df)
            days_in_month = pd.Timestamp(cy, cm, 1).days_in_month
            proj_month = (mtd_total / max(days_elapsed, 1)) * days_in_month

            summaries.append(RegionSummary(
                region=Region(region),
                latest_date=latest["Date"].date() if hasattr(latest["Date"], "date") else latest["Date"],
                latest_tpv=Decimal(str(round(float(latest["Daily_TPV"]), 2))),
                dod_change_pct=round(dod, 2),
                wow_change_pct=round(wow, 2),
                transactions=int(latest["Transactions"]),
                users=int(latest["Users"]),
                mtd_total=Decimal(str(round(float(mtd_total), 2))),
                projected_month=Decimal(str(round(float(proj_month), 2))),
            ))

            # --- 7-day forecast ---
            last_date = latest["Date"]
            if hasattr(last_date, "date"):
                last_date = last_date.date()
            forecasts = self.engine.forecast_range(
                last_date + timedelta(days=1), 7, region
            )
            forecast_rows = []
            for f in forecasts:
                forecast_rows.append(ForecastRow(
                    date=f["date"],
                    day_of_week=f["date"].strftime("%a"),
                    ensemble=Decimal(str(f["forecast_tpv"])),
                    low=Decimal(str(f["lower_ci"])),
                    high=Decimal(str(f["upper_ci"])),
                ))
                # Publish each day's forecast
                await self._publish_forecast(f, region, f["date"], trace_id)

            all_forecasts[region] = forecast_rows

            # --- Category split (for today's forecast) ---
            today_forecast = self.engine.forecast(target_date, region)
            split = self.splitter.split(today_forecast["forecast_tpv"], region)
            await self._publish_category_split(split, region, target_date, trace_id)

            cat_latest = fetch_category_latest(region)
            cat_trend = fetch_category_trend(region, 7)
            trend_7d = []
            if not cat_trend.empty:
                for cat in cat_trend["Category"].unique():
                    vals = cat_trend[cat_trend["Category"] == cat]["Daily_TPV"]
                    trend_7d.append({
                        "name": cat,
                        "avg": round(float(vals.mean()), 2),
                        "min": round(float(vals.min()), 2),
                        "max": round(float(vals.max()), 2),
                    })

            cat_total = sum(cat_latest.values()) if cat_latest else 0
            category_breakdowns.append(CategoryBreakdown(
                region=Region(region),
                date=target_date,
                categories=[
                    {"name": k, "tpv": round(v, 2), "share": round(v / max(cat_total, 1) * 100, 1)}
                    for k, v in cat_latest.items()
                ],
                total=Decimal(str(round(cat_total, 2))),
                trend_7d=trend_7d,
            ))

            # --- Model performance ---
            from models import EnsembleForecaster
            ens = EnsembleForecaster()
            ens.fit(hist["Date"], hist["Daily_TPV"])
            stats = ens.get_model_stats()
            bt = ens.backtest(hist["Date"], hist["Daily_TPV"], holdout=30) if len(hist) > 60 else {}
            model_perfs.append(ModelPerformance(
                region=Region(region),
                linear_r2=stats["linear_r2"],
                slope_per_day=stats["linear_slope"],
                backtest={k: v for k, v in bt.items()},
            ))

            # --- Alerts ---
            await self._publish_alerts(region, trace_id)

            dev = self.detector.check_deviation(region)
            if dev:
                all_alerts.append({
                    "type": "DEVIATION",
                    "region": region,
                    "severity": dev["severity"].value,
                    "description": f"{region}: Latest TPV deviates {abs(dev['deviation_pct']):.1f}% from 7d avg",
                })

            growth = self.detector.check_growth(region)
            if growth:
                all_alerts.append({
                    "type": "GROWTH",
                    "region": region,
                    "severity": growth["severity"].value,
                    "description": f"{region}: Growth {growth['direction'].lower()} — 7d avg is {abs(growth['growth_pct']):.0f}% vs 30d avg",
                })

        # --- Monthly history ---
        monthly_df = load_monthly_summary()
        monthly_hist = []
        for _, row in monthly_df.tail(8).iterrows():
            monthly_hist.append({
                "month": row["Month"],
                "type": row["Type"],
                "uae_tpv": round(float(row["UAE_TPV"]), 2),
                "uk_tpv": round(float(row["UK_TPV"]), 2),
                "total_tpv": round(float(row["Total_TPV"]), 2),
            })

        # --- FX-Rate-Sensitive Predictions ---
        logger.info("  Generating FX-rate-sensitive predictions...")
        fx_predictions = self.fx_engine.generate_all_regions(
            custom_fx_rates=self._custom_fx_rates,
            start_date=target_date + timedelta(days=1),
        )

        # Export to Excel
        output_dir = settings.output_dir
        os.makedirs(output_dir, exist_ok=True)
        excel_path = os.path.join(
            output_dir, f"FX_Predictions_{target_date.strftime('%Y-%m-%d')}.xlsx"
        )
        self.fx_engine.export_to_excel(fx_predictions, excel_path)
        logger.info("  FX predictions exported to %s", excel_path)

        report = DailyReport(
            business_date=target_date,
            summaries=summaries,
            forecasts=all_forecasts,
            category_breakdowns=category_breakdowns,
            model_performance=model_perfs,
            alerts=all_alerts,
            monthly_history=monthly_hist,
            fx_predictions={k: v for k, v in fx_predictions.items()},
        )

        self._last_report = report
        await self._publish_status("FORECAST_COMPLETE", {
            "date": str(target_date),
            "regions": list(settings.regions.keys()),
            "alert_count": len(all_alerts),
        })

        logger.info("━━━ DAILY FORECAST COMPLETE  alerts=%d ━━━", len(all_alerts))
        return report

    # ── Inbound message handlers ───────────────────────────────────────────

    async def _handle_reforecast(self, payload: Dict) -> None:
        logger.info("Re-forecast triggered: %s", payload.get("reason", "unknown"))
        await self.run_daily_forecast(
            trace_id=payload.get("trace_id", str(uuid.uuid4()))
        )

    async def _listen_for_triggers(self) -> None:
        """Subscribe to tpv.alerts for re-forecast signals."""
        async for msg_id, payload in self.bus.subscribe(
            STREAM_ALERTS, group="tpv-agent", consumer="tpv-1"
        ):
            try:
                msg_type = payload.get("message_type") or payload.get("alert_type")
                if msg_type == "REFORECAST_TRIGGER":
                    await self._handle_reforecast(payload)
                await self.bus.ack(STREAM_ALERTS, "tpv-agent", msg_id)
            except Exception as exc:
                logger.error("Error handling trigger %s: %s", msg_id, exc)

    # ── Scheduler ─────────────────────────────────────────────────────────

    async def _daily_scheduler(self) -> None:
        """
        Fire daily forecast at 7:30 AM IST (02:00 UTC) every morning.
        On startup: run immediately if past scheduled time.
        """
        while self._running:
            now = datetime.utcnow()
            # Next run: 02:00 UTC = 7:30 AM IST
            target = now.replace(hour=2, minute=0, second=0, microsecond=0)
            if now >= target:
                target += timedelta(days=1)

            wait_s = (target - now).total_seconds()
            local_time = target + timedelta(hours=5, minutes=30)
            logger.info(
                "Next scheduled forecast at %s UTC / %s IST (in %.0f s)",
                target.strftime("%Y-%m-%d %H:%M"),
                local_time.strftime("%Y-%m-%d %H:%M"),
                wait_s,
            )
            await asyncio.sleep(wait_s)

            # Run forecast for both regions
            await self.run_daily_forecast()

    # ── Public API ─────────────────────────────────────────────────────────

    def get_last_report(self) -> Optional[DailyReport]:
        return self._last_report

    def set_fx_rates(self, rates: Dict[str, float]) -> None:
        """Set custom FX rates for next forecast (e.g. {'UAE': 24.70, 'UK': 123.8})."""
        self._custom_fx_rates = rates
        logger.info("Custom FX rates set: %s", rates)

    async def trigger_reforecast(self, reason: str = "manual") -> None:
        trigger = ReforecastTrigger(
            trace_id=str(uuid.uuid4()),
            reason=reason,
        )
        await self.bus.publish(STREAM_ALERTS, trigger.model_dump(mode="json"), trigger.trace_id)

    # ── Entry point ────────────────────────────────────────────────────────

    async def run(self) -> None:
        self._running = True
        await self._publish_status("STARTING")
        logger.info("TPV Agent starting up")

        # Run forecast immediately on startup
        await self.run_daily_forecast()
        await self._publish_status("RUNNING")

        # Run scheduler + listener concurrently
        await asyncio.gather(
            self._daily_scheduler(),
            self._listen_for_triggers(),
        )
