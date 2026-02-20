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
