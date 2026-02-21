"""
shared/schemas.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TPV Agent — Pydantic schemas for all message types
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── Enums ──────────────────────────────────────────────────────────────────

class Region(str, Enum):
    UAE = "UAE"
    UK = "UK"


class Category(str, Enum):
    NON_REFERRED = "Non-Referred"
    REFERRED = "Referred"
    WHALE = "Whale"


class ConfidenceLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class AlertSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class MessageType(str, Enum):
    DAILY_FORECAST = "DAILY_FORECAST"
    CATEGORY_SPLIT = "CATEGORY_SPLIT"
    ANOMALY_ALERT = "ANOMALY_ALERT"
    REFORECAST_TRIGGER = "REFORECAST_TRIGGER"
    GROWTH_ALERT = "GROWTH_ALERT"
    DEVIATION_ALERT = "DEVIATION_ALERT"
    AGENT_STATUS = "AGENT_STATUS"


# ── Core schemas ───────────────────────────────────────────────────────────

class ConfidenceInterval(BaseModel):
    lower: Decimal
    upper: Decimal


class MultiplierDetail(BaseModel):
    name: str
    value: float
    reason: str


class DailyTPVForecast(BaseModel):
    """Published when daily forecast completes for a region."""
    message_type: MessageType = MessageType.DAILY_FORECAST
    trace_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    business_date: date
    region: Region
    base_tpv: Decimal = Field(description="Base WMA forecast before multipliers")
    forecast_tpv: Decimal = Field(description="Final forecast after multiplier stack")
    confidence_interval: ConfidenceInterval
    confidence_level: ConfidenceLevel
    stacked_multiplier: float
    multipliers_applied: List[MultiplierDetail]
    forecast_transactions: Optional[int] = None
    forecast_users: Optional[int] = None


class CategorySplit(BaseModel):
    """Published after daily forecast — breakdown by user category."""
    message_type: MessageType = MessageType.CATEGORY_SPLIT
    trace_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    business_date: date
    region: Region
    splits: Dict[str, Decimal] = Field(description="Category -> TPV amount")
    percentages: Dict[str, float] = Field(description="Category -> % share")


class AnomalyAlert(BaseModel):
    """Published when actual TPV deviates significantly from forecast."""
    message_type: MessageType = MessageType.ANOMALY_ALERT
    trace_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    business_date: date
    region: Region
    severity: AlertSeverity
    actual_tpv: Decimal
    forecast_tpv: Decimal
    deviation_pct: float
    description: str


class GrowthAlert(BaseModel):
    """Published when growth rate accelerates or decelerates significantly."""
    message_type: MessageType = MessageType.GROWTH_ALERT
    trace_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    region: Region
    severity: AlertSeverity
    avg_7d: Decimal
    avg_30d: Decimal
    growth_pct: float
    direction: str  # "ACCELERATING" or "DECELERATING"
    description: str


class DeviationAlert(BaseModel):
    """Published when latest TPV deviates >20% from 7-day average."""
    message_type: MessageType = MessageType.DEVIATION_ALERT
    trace_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    region: Region
    severity: AlertSeverity
    latest_tpv: Decimal
    avg_7d: Decimal
    deviation_pct: float
    description: str


class ReforecastTrigger(BaseModel):
    """Inbound: signals the agent to re-run forecast."""
    message_type: MessageType = MessageType.REFORECAST_TRIGGER
    trace_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    reason: str
    region: Optional[Region] = None


class AgentStatus(BaseModel):
    """Heartbeat / status update from the agent."""
    message_type: MessageType = MessageType.AGENT_STATUS
    trace_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    status: str  # "STARTING", "RUNNING", "FORECAST_COMPLETE", "ERROR"
    details: Dict[str, Any] = Field(default_factory=dict)


# ── Aggregate report (for web dashboard) ──────────────────────────────────

class RegionSummary(BaseModel):
    region: Region
    latest_date: date
    latest_tpv: Decimal
    dod_change_pct: float
    wow_change_pct: float
    transactions: int
    users: int
    mtd_total: Decimal
    projected_month: Decimal


class ForecastRow(BaseModel):
    date: date
    day_of_week: str
    ensemble: Decimal
    low: Decimal
    high: Decimal


class CategoryBreakdown(BaseModel):
    region: Region
    date: date
    categories: List[Dict[str, Any]]
    total: Decimal
    trend_7d: List[Dict[str, Any]]


class ModelPerformance(BaseModel):
    region: Region
    linear_r2: float
    slope_per_day: float
    backtest: Dict[str, Dict[str, float]]


class DailyReport(BaseModel):
    """Complete daily report aggregate — consumed by web dashboard."""
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    business_date: date
    summaries: List[RegionSummary]
    forecasts: Dict[str, List[ForecastRow]]  # region -> forecast rows
    category_breakdowns: List[CategoryBreakdown]
    model_performance: List[ModelPerformance]
    alerts: List[Dict[str, Any]]
    monthly_history: List[Dict[str, Any]]
    fx_predictions: Optional[Dict[str, "FXRegionPrediction"]] = None


# ── FX-Rate-Sensitive Prediction schemas ──────────────────────────────────

class FXScenario(BaseModel):
    """Single FX rate scenario prediction."""
    bps_change: int = Field(description="Basis point change from base rate (-20 to +20)")
    fx_rate: float = Field(description="FX rate at this scenario")
    total_tpv: Decimal = Field(description="Predicted Total TPV")
    total_tu: int = Field(description="Predicted Transaction Users")
    avg_arpu: Decimal = Field(description="Average Revenue Per User")
    tpv_change_pct: float = Field(description="% change from base (BPS=0) scenario")


class FXPredictionBlock(BaseModel):
    """All FX scenarios for a single prediction date."""
    prediction_date: date
    day_of_week: str
    scenarios: List[FXScenario]
    base_tpv: Decimal = Field(description="TPV at BPS=0")
    base_tu: int = Field(description="TU at BPS=0")
    base_arpu: Decimal = Field(description="ARPU at BPS=0")


class FXRegionPrediction(BaseModel):
    """Complete FX prediction for a region."""
    region: Region
    base_fx_rate: float = Field(description="Base FX rate used (at BPS=0)")
    currency_pair: str = Field(description="e.g. AED/USD or GBP/USD")
    prediction_blocks: List[FXPredictionBlock]
    generated_at: datetime = Field(default_factory=datetime.utcnow)
