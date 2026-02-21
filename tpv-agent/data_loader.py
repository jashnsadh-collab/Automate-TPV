import os
import pandas as pd
import numpy as np
from config.settings import settings

DATA_FILE = settings.data_file


def load_daily_summary() -> pd.DataFrame:
    df = pd.read_excel(DATA_FILE, sheet_name="Daily Summary", engine="openpyxl")
    df.columns = ["Date", "Type", "UAE_TPV", "UK_TPV", "Total_TPV"]
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").reset_index(drop=True)
    for col in ["UAE_TPV", "UK_TPV", "Total_TPV"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df


def load_region_detail(region: str) -> pd.DataFrame:
    sheet = f"{region} Projection"
    df = pd.read_excel(DATA_FILE, sheet_name=sheet, engine="openpyxl")
    df.columns = ["Date", "Type", "Daily_TPV", "Transactions", "Users"]
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").reset_index(drop=True)
    for col in ["Daily_TPV", "Transactions", "Users"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df


def load_category_data(region: str) -> pd.DataFrame:
    sheet = f"{region} by Category"
    df = pd.read_excel(DATA_FILE, sheet_name=sheet, engine="openpyxl")
    df.columns = ["Date", "Category", "Daily_TPV"]
    df["Date"] = pd.to_datetime(df["Date"])
    df["Daily_TPV"] = pd.to_numeric(df["Daily_TPV"], errors="coerce").fillna(0)
    df = df.sort_values("Date").reset_index(drop=True)
    return df


def load_monthly_summary() -> pd.DataFrame:
    df = pd.read_excel(DATA_FILE, sheet_name="Monthly Summary", engine="openpyxl")
    df.columns = ["Month", "Type", "UAE_TPV", "UK_TPV", "Total_TPV"]
    for col in ["UAE_TPV", "UK_TPV", "Total_TPV"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df


def load_regression_stats() -> pd.DataFrame:
    df = pd.read_excel(DATA_FILE, sheet_name="Regression Stats", engine="openpyxl")
    df.columns = ["Region", "Metric", "Slope", "Intercept", "R2"]
    for col in ["Slope", "Intercept", "R2"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df


def get_historical_daily() -> pd.DataFrame:
    df = load_daily_summary()
    return df[df["Type"] == "Historical"].copy()


def get_historical_region(region: str) -> pd.DataFrame:
    df = load_region_detail(region)
    return df[df["Type"] == "Historical"].copy()


def load_daily_tpv_csv() -> pd.DataFrame:
    """
    Load the daily TPV CSV from Downloads.
    Returns DataFrame with columns: Date, Currency, Amount
    """
    csv_path = settings.daily_tpv_csv
    if not csv_path or not os.path.exists(csv_path):
        return pd.DataFrame()

    df = pd.read_csv(csv_path)
    df.columns = ["Date", "Amount", "Currency"]
    df["Date"] = pd.to_datetime(df["Date"])
    df["Amount"] = df["Amount"].astype(str).str.replace(",", "").astype(float)
    df = df.sort_values("Date").reset_index(drop=True)
    return df


def get_daily_tpv_by_date() -> dict:
    """
    Returns dict: {date_str: {currency: amount}} from the daily TPV CSV.
    """
    df = load_daily_tpv_csv()
    if df.empty:
        return {}

    result = {}
    for d, grp in df.groupby("Date"):
        date_str = d.strftime("%Y-%m-%d")
        result[date_str] = {row["Currency"]: row["Amount"] for _, row in grp.iterrows()}
    return result
