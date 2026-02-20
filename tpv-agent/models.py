import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from config import ENSEMBLE_WEIGHTS


def _date_to_ordinal(dates: pd.Series) -> np.ndarray:
    return np.array([d.toordinal() for d in dates]).reshape(-1, 1)


class LinearTrendModel:
    def __init__(self):
        self.model = LinearRegression()
        self.slope = 0.0
        self.intercept = 0.0
        self.r2 = 0.0

    def fit(self, dates: pd.Series, values: pd.Series):
        X = _date_to_ordinal(dates)
        y = values.values
        self.model.fit(X, y)
        self.slope = self.model.coef_[0]
        self.intercept = self.model.intercept_
        self.r2 = self.model.score(X, y)

    def predict(self, dates: pd.Series) -> np.ndarray:
        X = _date_to_ordinal(dates)
        return self.model.predict(X)


class WeightedMovingAvgModel:
    def __init__(self, window: int = 28):
        self.window = window
        self._last_values = None

    def fit(self, dates: pd.Series, values: pd.Series):
        self._last_values = values.tail(self.window).values

    def predict(self, dates: pd.Series) -> np.ndarray:
        n = len(dates)
        weights = np.exp(np.linspace(-2, 0, len(self._last_values)))
        weights /= weights.sum()
        base = np.dot(weights, self._last_values)
        # Use 7-day vs 14-day averages for trend
        recent_trend = 0.0
        if len(self._last_values) >= 14:
            avg_recent = np.mean(self._last_values[-7:])
            avg_prior = np.mean(self._last_values[-14:-7])
            recent_trend = (avg_recent - avg_prior) / 7
        return np.array([base + recent_trend * i for i in range(n)])


class SeasonalLinearModel:
    def __init__(self, seasonal_window: int = 90):
        self.linear = LinearTrendModel()
        self.dow_factors = np.ones(7)
        self.seasonal_window = seasonal_window

    def fit(self, dates: pd.Series, values: pd.Series):
        self.linear.fit(dates, values)
        # Compute DOW factors using only recent data to avoid distortion
        # from early low-volume periods
        n = len(dates)
        window = min(self.seasonal_window, n)
        recent_dates = dates.iloc[-window:]
        recent_values = values.iloc[-window:]
        recent_trend = self.linear.predict(recent_dates)
        # Avoid division by zero or negative trend values
        safe_trend = np.maximum(recent_trend, 1)
        ratios = recent_values.values / safe_trend
        df_tmp = pd.DataFrame({"dow": [d.weekday() for d in recent_dates], "ratio": ratios})
        self.dow_factors = df_tmp.groupby("dow")["ratio"].median().reindex(range(7), fill_value=1.0).values

    def predict(self, dates: pd.Series) -> np.ndarray:
        base = self.linear.predict(dates)
        dows = np.array([d.weekday() for d in dates])
        return base * self.dow_factors[dows]


class EnsembleForecaster:
    def __init__(self):
        self.linear = LinearTrendModel()
        self.wma = WeightedMovingAvgModel(window=28)
        self.seasonal = SeasonalLinearModel(seasonal_window=90)

    def fit(self, dates: pd.Series, values: pd.Series):
        self.linear.fit(dates, values)
        self.wma.fit(dates, values)
        self.seasonal.fit(dates, values)

    def predict(self, dates: pd.Series) -> pd.DataFrame:
        p_lin = self.linear.predict(dates)
        p_wma = self.wma.predict(dates)
        p_sea = self.seasonal.predict(dates)
        w = ENSEMBLE_WEIGHTS
        ensemble = (w["linear"] * p_lin + w["wma"] * p_wma + w["seasonal_linear"] * p_sea)
        stacked = np.column_stack([p_lin, p_wma, p_sea])
        std = np.std(stacked, axis=1)
        return pd.DataFrame({
            "Date": dates.values,
            "Linear": np.maximum(p_lin, 0),
            "WMA": np.maximum(p_wma, 0),
            "Seasonal": np.maximum(p_sea, 0),
            "Ensemble": np.maximum(ensemble, 0),
            "Low": np.maximum(ensemble - std, 0),
            "High": np.maximum(ensemble + std, 0),
        })

    def backtest(self, dates: pd.Series, values: pd.Series, holdout: int = 30) -> dict:
        train_dates = dates.iloc[:-holdout]
        train_vals = values.iloc[:-holdout]
        test_dates = dates.iloc[-holdout:]
        test_vals = values.iloc[-holdout:].values
        self.fit(train_dates, train_vals)
        preds = self.predict(test_dates)
        results = {}
        for col in ["Linear", "WMA", "Seasonal", "Ensemble"]:
            pred = preds[col].values
            mape = np.mean(np.abs((test_vals - pred) / np.maximum(test_vals, 1))) * 100
            rmse = np.sqrt(np.mean((test_vals - pred) ** 2))
            results[col] = {"MAPE": round(mape, 2), "RMSE": round(rmse, 0)}
        return results

    def get_model_stats(self) -> dict:
        return {
            "linear_r2": round(self.linear.r2, 4),
            "linear_slope": round(self.linear.slope, 2),
            "seasonal_r2": round(self.seasonal.linear.r2, 4),
        }
