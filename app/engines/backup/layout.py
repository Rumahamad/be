"""Logical destinations, independent of Google file IDs."""

import calendar
from datetime import datetime
from pathlib import PurePosixPath

ROOT = PurePosixPath("BNC_BACKUP")


def month_folder(year: int, month: int) -> PurePosixPath:
    if not 2020 <= year <= 2200 or not 1 <= month <= 12:
        raise ValueError("Invalid archive month")
    return ROOT / "02_ARCHIVE" / str(year) / f"{month:02d}_{calendar.month_name[month]}"


def weekly_folder(when: datetime, run_id: str) -> PurePosixPath:
    if when.tzinfo is None:
        raise ValueError("Snapshot time must be timezone-aware")
    if not run_id or not all(c.isalnum() or c == "-" for c in run_id):
        raise ValueError("Invalid run ID")
    year, week, _ = when.isocalendar()
    return (ROOT / "99_FULL_RECOVERY" / "01_WEEKLY" / str(year)
            / f"{year}-W{week:02d}" / f"BNC_FULL_{when:%Y%m%dT%H%M%S%z}_{run_id}")
