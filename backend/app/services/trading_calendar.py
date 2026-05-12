import calendar
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models
from app.services.akshare_client import refresh_trading_calendar


def trading_calendar_coverage_end(db: Session) -> date | None:
    return db.scalar(
        select(func.max(models.TradingCalendarDay.trade_date)).where(
            models.TradingCalendarDay.is_trading_day.is_(True)
        )
    )


def load_trading_days(db: Session) -> set[date]:
    return set(
        db.scalars(
            select(models.TradingCalendarDay.trade_date).where(
                models.TradingCalendarDay.is_trading_day.is_(True)
            )
        ).all()
    )


def ensure_trading_calendar_coverage(
    db: Session,
    today: date | None = None,
    threshold_days: int = 15,
    months_ahead: int = 3,
    force: bool = False,
) -> dict[str, object]:
    today = today or date.today()
    previous_end = trading_calendar_coverage_end(db)
    target_end = _add_months(today, months_ahead)
    should_extend = force or previous_end is None or (previous_end - today).days < threshold_days
    inserted = 0
    fallback_inserted = 0

    if should_extend:
        akshare_days: set[date] = set()
        try:
            akshare_days = refresh_trading_calendar()
        except Exception:
            akshare_days = set()

        for trading_day in sorted(day for day in akshare_days if day <= target_end):
            inserted += _upsert_trading_day(db, trading_day, "akshare")

        db.flush()
        current_end = trading_calendar_coverage_end(db)
        fallback_start = today if current_end is None else current_end + timedelta(days=1)
        for trading_day in _weekday_trading_days(fallback_start, target_end):
            if db.get(models.TradingCalendarDay, trading_day) is None:
                fallback_inserted += _upsert_trading_day(db, trading_day, "weekday_fallback")

        db.commit()

    new_end = trading_calendar_coverage_end(db)
    return {
        "previous_coverage_end": previous_end.isoformat() if previous_end else None,
        "new_coverage_end": new_end.isoformat() if new_end else None,
        "target_coverage_end": target_end.isoformat(),
        "extended": should_extend,
        "inserted": inserted,
        "fallback_inserted": fallback_inserted,
    }


def next_trading_day(db: Session, start: date) -> date:
    trading_days = load_trading_days(db)
    current = start
    coverage_end = max(trading_days) if trading_days else None
    while coverage_end is not None and current <= coverage_end:
        if current in trading_days:
            return current
        current += timedelta(days=1)

    while current.weekday() >= 5:
        current += timedelta(days=1)
    return current


def add_trading_days(db: Session, start: date, days: int) -> date:
    if days <= 0:
        return start

    trading_days = load_trading_days(db)
    coverage_end = max(trading_days) if trading_days else None
    current = start
    remaining = days
    while remaining > 0:
        current += timedelta(days=1)
        if coverage_end is not None and current <= coverage_end:
            if current in trading_days:
                remaining -= 1
        elif current.weekday() < 5:
            remaining -= 1
    return current


def _upsert_trading_day(db: Session, trading_day: date, source: str) -> int:
    row = db.get(models.TradingCalendarDay, trading_day)
    if row is None:
        row = models.TradingCalendarDay(trade_date=trading_day)
        db.add(row)
        inserted = 1
    else:
        inserted = 0
    row.is_trading_day = True
    row.source = source
    return inserted


def _weekday_trading_days(start: date, end: date) -> list[date]:
    days: list[date] = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def _add_months(value: date, months: int) -> date:
    month = value.month - 1 + months
    year = value.year + month // 12
    month = month % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)
