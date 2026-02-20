"""
shared/calendar_service.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Holiday calendar & business-day logic for UAE/UK regions.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Set


# ── Static holiday sets (2025-2026) ────────────────────────────────────────
# In production: pull from a holidays API or database.

_UAE_HOLIDAYS: Set[date] = {
    # 2025
    date(2025, 1, 1),    # New Year
    date(2025, 3, 30),   # Eid al-Fitr (approx)
    date(2025, 3, 31),
    date(2025, 4, 1),
    date(2025, 6, 6),    # Eid al-Adha (approx)
    date(2025, 6, 7),
    date(2025, 6, 8),
    date(2025, 6, 27),   # Islamic New Year
    date(2025, 9, 5),    # Prophet's Birthday
    date(2025, 12, 1),   # Commemoration Day
    date(2025, 12, 2),   # National Day
    date(2025, 12, 3),
    # 2026
    date(2026, 1, 1),
    date(2026, 3, 20),   # Eid al-Fitr (approx)
    date(2026, 3, 21),
    date(2026, 3, 22),
    date(2026, 5, 27),   # Eid al-Adha (approx)
    date(2026, 5, 28),
    date(2026, 5, 29),
    date(2026, 6, 17),   # Islamic New Year
    date(2026, 8, 26),   # Prophet's Birthday
    date(2026, 12, 1),
    date(2026, 12, 2),
    date(2026, 12, 3),
}

_UK_HOLIDAYS: Set[date] = {
    # 2025
    date(2025, 1, 1),
    date(2025, 4, 18),   # Good Friday
    date(2025, 4, 21),   # Easter Monday
    date(2025, 5, 5),    # Early May
    date(2025, 5, 26),   # Spring
    date(2025, 8, 25),   # Summer
    date(2025, 12, 25),
    date(2025, 12, 26),
    # 2026
    date(2026, 1, 1),
    date(2026, 4, 3),    # Good Friday
    date(2026, 4, 6),    # Easter Monday
    date(2026, 5, 4),    # Early May
    date(2026, 5, 25),   # Spring
    date(2026, 8, 31),   # Summer
    date(2026, 12, 25),
    date(2026, 12, 28),  # Boxing Day substitute
}

_HOLIDAY_MAP: Dict[str, Set[date]] = {
    "UAE": _UAE_HOLIDAYS,
    "UK": _UK_HOLIDAYS,
}


class CalendarService:
    """Business day and holiday utilities."""

    def get_holidays(self, country: str) -> Set[date]:
        return _HOLIDAY_MAP.get(country, set())

    def is_holiday(self, d: date, country: str) -> bool:
        return d in self.get_holidays(country)

    def is_weekend(self, d: date, country: str) -> bool:
        if country == "UAE":
            # UAE weekend: Friday-Saturday
            return d.weekday() in (4, 5)
        # UK/default: Saturday-Sunday
        return d.weekday() in (5, 6)

    def is_business_day(self, d: date, country: str) -> bool:
        return not self.is_weekend(d, country) and not self.is_holiday(d, country)

    def is_payday_window(self, d: date) -> bool:
        """25th-28th of month is typical salary/payday window."""
        return 25 <= d.day <= 28

    def is_month_end(self, d: date) -> bool:
        next_day = d + timedelta(days=1)
        return next_day.month != d.month

    def is_day_before_holiday(self, d: date, country: str) -> bool:
        next_day = d + timedelta(days=1)
        return self.is_holiday(next_day, country) or (
            self.is_weekend(next_day, country) and self.is_holiday(
                next_day + timedelta(days=1), country
            )
        )

    def is_day_after_holiday(self, d: date, country: str) -> bool:
        prev_day = d - timedelta(days=1)
        return self.is_holiday(prev_day, country)

    def holiday_lookahead(self, d: date, days: int = 3) -> Dict:
        """Check for holidays in the next N days across all regions."""
        flags: Dict[str, List[date]] = {}
        for country, holidays in _HOLIDAY_MAP.items():
            upcoming = []
            for i in range(1, days + 1):
                check = d + timedelta(days=i)
                if check in holidays:
                    upcoming.append(check)
            if upcoming:
                flags[country] = upcoming
        return {"holiday_flags": flags}

    def next_business_day(self, d: date, country: str) -> date:
        """Find the next business day after d."""
        nxt = d + timedelta(days=1)
        while not self.is_business_day(nxt, country):
            nxt += timedelta(days=1)
        return nxt

    def business_days_remaining(self, d: date, country: str) -> int:
        """Count business days remaining in the month."""
        count = 0
        check = d + timedelta(days=1)
        while check.month == d.month:
            if self.is_business_day(check, country):
                count += 1
            check += timedelta(days=1)
        return count


calendar = CalendarService()
