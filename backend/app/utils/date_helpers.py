"""
Date and Calendar Helper Utilities
Provides functions for payday calendar shifts, recurring interval calculations, and date parsing.
"""

from datetime import date, datetime, timedelta
from typing import List


def parse_date(date_str: str) -> date:
    """Parses ISO date string (YYYY-MM-DD) into date object."""
    if isinstance(date_str, date):
        return date_str
    return datetime.strptime(date_str[:10], "%Y-%m-%d").date()


def adjust_for_weekend(d: date, shift_type: str = "PRECEDING_FRIDAY") -> date:
    """
    Adjusts a date if it falls on a weekend.
    PRECEDING_FRIDAY: Shift Saturday/Sunday to Friday (typical for payday deposits).
    FOLLOWING_MONDAY: Shift Saturday/Sunday to Monday (typical for bill payments).
    """
    weekday = d.weekday()  # 5 = Saturday, 6 = Sunday
    if weekday == 5:
        return d - timedelta(days=1) if shift_type == "PRECEDING_FRIDAY" else d + timedelta(days=2)
    elif weekday == 6:
        return d - timedelta(days=2) if shift_type == "PRECEDING_FRIDAY" else d + timedelta(days=1)
    return d


def generate_90day_date_range(start_date: date) -> List[date]:
    """Generates an array of 90 consecutive dates starting from start_date."""
    return [start_date + timedelta(days=i) for i in range(90)]


def calculate_next_recurrence(current_date: date, pattern: str) -> date:
    """Calculates the next date for a given recurrence pattern."""
    pattern_upper = pattern.upper()
    if pattern_upper == "WEEKLY":
        return current_date + timedelta(days=7)
    elif pattern_upper == "BIWEEKLY":
        return current_date + timedelta(days=14)
    elif pattern_upper == "MONTHLY":
        # Approximate 1 month by shifting month integer
        year = current_date.year + (current_date.month // 12)
        month = (current_date.month % 12) + 1
        day = min(current_date.day, 28)  # Safe day fallback
        return date(year, month, day)
    return current_date + timedelta(days=30)
