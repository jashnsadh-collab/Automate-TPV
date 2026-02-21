"""
config/settings.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TPV Agent — Configuration
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict


@dataclass
class FXConfig:
    """FX-rate-sensitive prediction parameters."""
    # BPS range: -20 to +20 in steps of 5
    bps_levels: tuple = (-20, -15, -10, -5, 0, 5, 10, 15, 20)

    # UAE: AED/USD
    uae_base_fx: float = 24.6611      # Base FX rate at BPS=0
    uae_fx_per_5bps: float = 0.05     # FX change per 5 BPS
    uae_currency_pair: str = "AED/USD"

    # UK: GBP/USD (expressed as pence per dollar)
    uk_base_fx: float = 123.5         # Base FX rate at BPS=0
    uk_fx_per_5bps: float = 0.2       # FX change per 5 BPS
    uk_currency_pair: str = "GBP/USD"

    # Forecast horizon (days ahead)
    fx_forecast_days: int = 7

    # UAE FX elasticity — TPV multipliers at each BPS level
    # Derived from sample prediction data (16th Feb UAE sheet)
    uae_tpv_multipliers: Dict[int, float] = field(default_factory=lambda: {
        -20: 0.9036, -15: 0.9385, -10: 0.9574, -5: 0.9932, 0: 1.0,
        5: 1.2417, 10: 1.5147, 15: 1.6727, 20: 1.7404,
    })
    uae_tu_multipliers: Dict[int, float] = field(default_factory=lambda: {
        -20: 0.9618, -15: 0.9923, -10: 1.0047, -5: 1.0015, 0: 1.0,
        5: 1.1287, 10: 1.1813, 15: 1.1940, 20: 1.1974,
    })

    # UK FX elasticity — TPV multipliers at each BPS level
    # Derived from sample prediction data (18th Feb UK sheet)
    uk_tpv_multipliers: Dict[int, float] = field(default_factory=lambda: {
        -20: 0.82, -15: 0.86, -10: 0.90, -5: 0.95, 0: 1.0,
        5: 1.06, 10: 1.13, 15: 1.19, 20: 1.24,
    })
    uk_tu_multipliers: Dict[int, float] = field(default_factory=lambda: {
        -20: 0.88, -15: 0.91, -10: 0.94, -5: 0.97, 0: 1.0,
        5: 1.04, 10: 1.08, 15: 1.12, 20: 1.15,
    })


@dataclass
class TPVForecastConfig:
    """Forecast engine parameters."""
    # WMA
    wma_lookback_weeks: int = 12
    wma_decay: float = 0.85

    # Multipliers
    payday_multiplier_min: float = 1.10
    payday_multiplier_max: float = 1.35
    holiday_pre_multiplier: float = 1.20
    holiday_post_multiplier: float = 0.85
    weekend_decay: float = 0.70
    month_end_multiplier: float = 1.15
    fx_elasticity_z_coeff: float = 0.08
    fx_elasticity_cap: float = 1.25
    total_multiplier_cap: float = 1.80

    # Confidence
    high_cv_threshold: float = 0.10
    medium_cv_threshold: float = 0.20
    ci_z_score: float = 1.282  # 80% CI

    # Category defaults (Non-Referred, Referred, Whale)
    default_category_mix: Dict[str, float] = field(default_factory=lambda: {
        "Non-Referred": 0.35,
        "Referred": 0.40,
        "Whale": 0.25,
    })

    # RDA / nostro
    rda_safety_buffer: float = 0.10  # 10% buffer on balances

    # Re-forecast trigger threshold (% move)
    reforecast_threshold_pct: float = 5.0


@dataclass
class RegionConfig:
    """Per-region settings."""
    name: str
    currency: str
    timezone: str
    forecast_hour: int  # hour in local TZ to run daily forecast
    holidays_country: str


@dataclass
class Settings:
    """Top-level settings."""
    project_dir: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_file: str = ""
    output_dir: str = ""
    web_port: int = 5050
    log_level: str = "INFO"

    tpv: TPVForecastConfig = field(default_factory=TPVForecastConfig)
    fx: FXConfig = field(default_factory=FXConfig)

    regions: Dict[str, RegionConfig] = field(default_factory=lambda: {
        "UAE": RegionConfig(
            name="UAE",
            currency="AED",
            timezone="Asia/Dubai",
            forecast_hour=7,
            holidays_country="UAE",
        ),
        "UK": RegionConfig(
            name="UK",
            currency="GBP",
            timezone="Europe/London",
            forecast_hour=6,
            holidays_country="UK",
        ),
    })

    def __post_init__(self):
        parent = os.path.dirname(self.project_dir)
        self.data_file = os.path.join(parent, "TPV_Projections_UAE_UK.xlsx")
        self.output_dir = os.path.join(self.project_dir, "output")


settings = Settings()
