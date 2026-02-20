import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)

DATA_FILE = os.path.join(PROJECT_DIR, "TPV_Projections_UAE_UK.xlsx")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

REGIONS = ["UAE", "UK"]
CATEGORIES = ["Non-Referred", "Referred", "Whale"]
FORECAST_DAYS = 30

ENSEMBLE_WEIGHTS = {
    "seasonal_linear": 0.40,
    "wma": 0.35,
    "linear": 0.25,
}
