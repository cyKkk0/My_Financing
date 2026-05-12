import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models
from app.services.akshare_client import AkshareFundClient
from app.services.portfolio import backfill_snapshots, save_snapshot
from app.services.trading_calendar import (
    add_trading_days,
    ensure_trading_calendar_coverage,
    next_trading_day,
)


def update_daily_navs_and_snapshot(db: Session) -> dict[str, int | str]:
    calendar_result = ensure_trading_calendar_coverage(db)
    client = AkshareFundClient()
    fund_codes = _fund_codes_to_update(db)
    fund_names = client.fund_name_map()
    history_cache: dict[str, list[dict]] = {}
    confirm_days_cache: dict[tuple[str, str], tuple[int, str]] = {}
    updated = 0
    skipped: list[str] = []
    updated_details: list[str] = []

    for fund_code in fund_codes:
        nav_rows = _recent_navs_from_history(
            fund_code,
            _history_navs_cached(client, history_cache, fund_code),
            limit=3,
        )
        if not nav_rows:
            latest = client.latest_nav_for(fund_code)
            if latest is None:
                skipped.append(fund_code)
                continue
            nav_rows = [latest]
        latest = nav_rows[0]

        fund = db.get(models.Fund, fund_code)
        resolved_name = fund_names.get(fund_code.zfill(6))
        if fund is None:
            fund = models.Fund(code=fund_code, name=resolved_name or fund_code)
            db.add(fund)
        elif resolved_name and (fund.name == fund.code or fund.name == fund_code):
            fund.name = resolved_name

        for nav_info in nav_rows:
            _upsert_nav(db, fund_code, nav_info)
        updated += 1
        updated_details.append(
            f"{fund_code}:{latest['nav_date'].isoformat()}:{latest['unit_nav']}:{latest.get('source', 'akshare')}"
        )

    db.commit()
    pending_result = confirm_pending_transactions(db, client, history_cache, confirm_days_cache)
    dca_confirmed = confirm_pending_dca_executions(db, client, date.today(), history_cache, confirm_days_cache)
    db.commit()
    backfilled = backfill_snapshots(db)
    snapshot = save_snapshot(db, date.today())
    return {
        "updated_funds": updated,
        "skipped_funds": ",".join(skipped),
        "updated_navs": ";".join(updated_details),
        "snapshot_date": snapshot.snapshot_date.isoformat(),
        "backfilled_snapshots": backfilled,
        "pending_confirmed": pending_result["confirmed"],
        "pending_remaining": pending_result["pending_transactions"],
        "dca_confirmed": dca_confirmed,
        "dca_pending": _pending_dca_execution_count(db),
        "trading_calendar_extended": str(calendar_result["extended"]),
        "trading_calendar_previous_end": str(calendar_result["previous_coverage_end"] or ""),
        "trading_calendar_new_end": str(calendar_result["new_coverage_end"] or ""),
        "trading_calendar_inserted": str(calendar_result["inserted"]),
        "trading_calendar_fallback_inserted": str(calendar_result["fallback_inserted"]),
    }


def run_dca_check(db: Session, target_date: date | None = None) -> dict[str, int]:
    result = create_due_dca_executions(db, target_date or date.today())
    db.commit()
    return {"dca_created": result["created"], "dca_pending": result["pending"]}


def _upsert_nav(db: Session, fund_code: str, nav_info: dict) -> models.FundNav:
    nav = db.scalar(
        select(models.FundNav).where(
            models.FundNav.fund_code == fund_code,
            models.FundNav.nav_date == nav_info["nav_date"],
        )
    )
    if nav is None:
        nav = models.FundNav(fund_code=fund_code, nav_date=nav_info["nav_date"])
        db.add(nav)
    nav.unit_nav = nav_info["unit_nav"]
    nav.accumulated_nav = nav_info.get("accumulated_nav")
    nav.daily_growth_rate = nav_info.get("daily_growth_rate")
    nav.source = nav_info.get("source", "akshare")
    return nav


def process_due_dca_plans(
    db: Session,
    client: AkshareFundClient | None = None,
    target_date: date | None = None,
) -> dict[str, int]:
    client = client or AkshareFundClient()
    history_cache: dict[str, list[dict]] = {}
    confirm_days_cache: dict[tuple[str, str], tuple[int, str]] = {}
    result = create_due_dca_executions(db, target_date or date.today())
    confirmed = confirm_pending_dca_executions(
        db,
        client,
        target_date or date.today(),
        history_cache,
        confirm_days_cache,
    )
    return {"created": result["created"], "confirmed": confirmed, "pending": _pending_dca_execution_count(db)}


def create_due_dca_executions(db: Session, target_date: date | None = None) -> dict[str, int]:
    target_date = target_date or date.today()
    created = 0

    plans = db.scalars(
        select(models.DcaPlan).where(
            models.DcaPlan.status == "active",
            models.DcaPlan.start_date <= target_date,
        )
    ).all()
    for plan in plans:
        if plan.end_date is not None and plan.end_date < target_date:
            continue
        if not _is_plan_due(plan, target_date):
            continue

        execution = db.scalar(
            select(models.DcaExecution).where(
                models.DcaExecution.plan_id == plan.id,
                models.DcaExecution.scheduled_date == target_date,
            )
        )
        if execution is None:
            execution = models.DcaExecution(
                plan_id=plan.id,
                fund_code=plan.fund_code,
                scheduled_date=target_date,
                amount=plan.amount,
                status="pending",
            )
            db.add(execution)
            created += 1

    db.flush()
    return {"created": created, "pending": _pending_dca_execution_count(db)}


def confirm_pending_dca_executions(
    db: Session,
    client: AkshareFundClient,
    target_date: date,
    history_cache: dict[str, list[dict]] | None = None,
    confirm_days_cache: dict[tuple[str, str], tuple[int, str]] | None = None,
) -> int:
    """Confirm pending DCA executions whose trade-date NAV is now available.

    For each pending execution:
      1. Find the first trading day T >= scheduled_date
      2. Wait until the fund's T+N confirmation date
      3. If NAV data exists for T, create a confirmed transaction
    """
    executions = db.scalars(
        select(models.DcaExecution)
        .where(models.DcaExecution.status == "pending")
        .order_by(models.DcaExecution.scheduled_date.asc())
    ).all()
    if not executions:
        return 0

    nav_cache: dict[str, dict[date, Decimal]] = {}  # fund_code → {date: unit_nav}
    plans: dict[int, models.DcaPlan] = {}              # plan_id → plan

    confirmed = 0
    for execution in executions:
        fund = execution.fund_code
        try:
            # ── cache plan ──
            if execution.plan_id not in plans:
                plans[execution.plan_id] = db.get(models.DcaPlan, execution.plan_id)
            plan = plans[execution.plan_id]

            trade_date = next_trading_day(db, execution.scheduled_date)

            confirm_info = _confirm_info(db, client, fund, "buy", trade_date, confirm_days_cache)
            confirm_date = confirm_info["confirm_date"]
            if target_date < confirm_date:
                execution.note = f"预计 {confirm_date.isoformat()} 确认份额"
                continue

            # ── fetch NAV once per fund ──
            if fund not in nav_cache:
                nav_cache[fund] = {}
                # Try stored NAVs first
                stored = db.scalars(
                    select(models.FundNav).where(
                        models.FundNav.fund_code == fund,
                        models.FundNav.nav_date >= trade_date,
                    ).order_by(models.FundNav.nav_date.asc())
                ).all()
                for s in stored:
                    nav_cache[fund][s.nav_date] = Decimal(s.unit_nav)
                # Supplement with AKShare history
                try:
                    for row in _history_navs_cached(client, history_cache, fund):
                        d = row["nav_date"]
                        if d >= trade_date and d not in nav_cache[fund]:
                            nav_cache[fund][d] = row["unit_nav"]
                except Exception:
                    pass

            fund_navs = nav_cache[fund]
            if not fund_navs:
                execution.note = "暂无净值数据"
                continue

            # ── Confirm with the exact trade-date NAV ──
            unit_nav = fund_navs.get(trade_date)
            if unit_nav is None or unit_nav <= 0:
                execution.note = f"净值日{trade_date}暂无净值，等待数据更新"
                continue

            # ── create buy transaction ──
            nav_dec = Decimal(unit_nav)
            shares = (Decimal(execution.amount) / nav_dec).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )
            tx = models.Transaction(
                fund_code=fund,
                trade_date=trade_date,
                transaction_type="buy",
                amount=execution.amount,
                shares=shares,
                nav=nav_dec,
                fee=plan.fee if plan else Decimal("0"),
                external_id=f"dca:plan-{execution.plan_id}:{execution.scheduled_date.isoformat()}",
                initiated_at=datetime.combine(execution.scheduled_date, datetime.min.time()),
                confirmed_at=datetime.combine(confirm_date, datetime.min.time()),
                note=f"定投计划 #{execution.plan_id} 自动确认",
            )
            db.add(tx)
            db.flush()

            # Ensure FundNav record exists
            nav_row = db.scalar(
                select(models.FundNav).where(
                    models.FundNav.fund_code == fund,
                    models.FundNav.nav_date == trade_date,
                )
            )
            if nav_row is None:
                nav_row = models.FundNav(
                    fund_code=fund,
                    nav_date=trade_date,
                    unit_nav=nav_dec,
                    source="akshare_history",
                )
                db.add(nav_row)

            execution.status = "confirmed"
            execution.confirmed_date = confirm_date
            execution.nav = nav_dec
            execution.shares = shares
            execution.transaction_id = tx.id
            execution.note = None
            confirmed += 1
        except Exception:
            continue

    return confirmed


def confirm_pending_transactions(
    db: Session,
    client: AkshareFundClient | None = None,
    history_cache: dict[str, list[dict]] | None = None,
    confirm_days_cache: dict[tuple[str, str], tuple[int, str]] | None = None,
) -> dict[str, int]:
    """Confirm pending manual transactions whose trade_date NAV is now available.

    Unlike DCA executions, manual pending transactions already have the trade_date
    set (from the 15:00 cutoff rule). We just need to wait until the NAV for that
    exact trade_date is published, then update nav/shares and mark confirmed.
    """
    client = client or AkshareFundClient()
    pending = db.scalars(
        select(models.Transaction)
        .where(models.Transaction.status == "pending")
        .order_by(models.Transaction.trade_date.asc())
    ).all()
    if not pending:
        return {"pending_transactions": 0, "confirmed": 0}

    confirmed = 0
    for tx in pending:
        try:
            confirm_info = _confirm_info(db, client, tx.fund_code, tx.transaction_type, tx.trade_date, confirm_days_cache)
            confirm_date = confirm_info["confirm_date"]
            if date.today() < confirm_date:
                continue

            # Check if NAV exists for the exact trade_date
            unit_nav = None
            nav_source = "akshare_history"

            stored = db.scalar(
                select(models.FundNav).where(
                    models.FundNav.fund_code == tx.fund_code,
                    models.FundNav.nav_date == tx.trade_date,
                )
            )
            if stored is not None:
                unit_nav = Decimal(stored.unit_nav)
                nav_source = stored.source
            else:
                history = {
                    row["nav_date"]: row["unit_nav"]
                    for row in _history_navs_cached(client, history_cache, tx.fund_code)
                }
                unit_nav = history.get(tx.trade_date)

            if unit_nav is None or unit_nav <= 0:
                continue

            nav_dec = Decimal(unit_nav)
            tx.nav = nav_dec
            if tx.transaction_type == "buy":
                tx.shares = ((tx.amount - tx.fee) / nav_dec).quantize(
                    Decimal("0.0001"), rounding=ROUND_HALF_UP
                )
            elif tx.transaction_type == "sell":
                tx.amount = (tx.shares * nav_dec - tx.fee).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
            tx.status = "confirmed"
            tx.confirmed_at = datetime.combine(confirm_date, datetime.min.time())

            # Ensure FundNav record exists
            nav_row = db.scalar(
                select(models.FundNav).where(
                    models.FundNav.fund_code == tx.fund_code,
                    models.FundNav.nav_date == tx.trade_date,
                )
            )
            if nav_row is None:
                nav_row = models.FundNav(
                    fund_code=tx.fund_code,
                    nav_date=tx.trade_date,
                    unit_nav=nav_dec,
                    source=nav_source,
                )
                db.add(nav_row)

            confirmed += 1
        except Exception:
            continue

    if confirmed > 0:
        db.commit()

    remaining = db.scalar(
        select(func.count()).select_from(models.Transaction).where(models.Transaction.status == "pending")
    ) or 0
    return {"pending_transactions": remaining, "confirmed": confirmed}


def _confirm_info(
    db: Session,
    client: AkshareFundClient,
    fund_code: str,
    transaction_type: str,
    trade_date: date,
    confirm_days_cache: dict[tuple[str, str], tuple[int, str]] | None = None,
) -> dict[str, date | int | str]:
    key = (fund_code.zfill(6), transaction_type)
    try:
        if confirm_days_cache is not None and key in confirm_days_cache:
            confirm_days, source = confirm_days_cache[key]
        else:
            confirm_days = client.trade_confirm_days(fund_code, transaction_type)
            if confirm_days is None:
                confirm_days = 1
                source = "fallback_trade_plus_1"
            else:
                source = "akshare_fund_fee_em"
            if confirm_days_cache is not None:
                confirm_days_cache[key] = (confirm_days, source)
        return {
            "confirm_date": add_trading_days(db, trade_date, confirm_days),
            "confirm_days": confirm_days,
            "source": source,
        }
    except Exception:
        if confirm_days_cache is not None:
            confirm_days_cache[key] = (1, "fallback_trade_plus_1")
        return {
            "confirm_date": _add_weekdays(trade_date, 1),
            "confirm_days": 1,
            "source": "fallback_trade_plus_1",
        }


def _add_weekdays(start: date, days: int) -> date:
    current = start
    remaining = days
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


def _fund_codes_to_update(db: Session) -> list[str]:
    transaction_codes = {code for (code,) in db.execute(select(models.Transaction.fund_code).distinct()).all()}
    dca_codes = {code for (code,) in db.execute(select(models.DcaPlan.fund_code).distinct()).all()}
    return sorted(transaction_codes | dca_codes)


def _history_navs_cached(
    client: AkshareFundClient,
    history_cache: dict[str, list[dict]] | None,
    fund_code: str,
) -> list[dict]:
    if history_cache is None:
        try:
            return client.history_navs(fund_code)
        except Exception:
            return []

    code = fund_code.zfill(6)
    if code not in history_cache:
        try:
            history_cache[code] = client.history_navs(code)
        except Exception:
            history_cache[code] = []
    return history_cache[code]


def _recent_navs_from_history(fund_code: str, rows: list[dict], limit: int) -> list[dict]:
    sorted_rows = sorted(rows, key=lambda item: item["nav_date"], reverse=True)
    return [
        {
            "nav_date": row["nav_date"],
            "unit_nav": row["unit_nav"],
            "accumulated_nav": row.get("accumulated_nav"),
            "daily_growth_rate": row.get("daily_growth_rate"),
            "name": fund_code,
            "source": "akshare_history",
        }
        for row in sorted_rows[:limit]
    ]


def _pending_dca_execution_count(db: Session) -> int:
    return db.scalar(
        select(func.count()).select_from(models.DcaExecution).where(models.DcaExecution.status == "pending")
    ) or 0


def _is_plan_due(plan: models.DcaPlan, target_date: date) -> bool:
    if plan.start_date is None:
        return False
    if target_date < plan.start_date:
        return False
    if plan.frequency == "daily":
        return True
    if plan.frequency == "weekly":
        weekday = plan.day_of_month or plan.start_date.isoweekday()
        return target_date.isoweekday() == weekday

    day = plan.day_of_month or plan.start_date.day
    _, last_day = calendar.monthrange(target_date.year, target_date.month)
    due_day = min(day, last_day)
    return target_date.day == due_day


def _nav_on_or_after(
    db: Session,
    client: AkshareFundClient,
    fund_code: str,
    start_date: date,
    end_date: date,
) -> dict[str, Decimal | date | str] | None:
    stored = db.scalar(
        select(models.FundNav)
        .where(
            models.FundNav.fund_code == fund_code,
            models.FundNav.nav_date >= start_date,
            models.FundNav.nav_date <= end_date,
        )
        .order_by(models.FundNav.nav_date.asc())
        .limit(1)
    )
    if stored is not None:
        return {"nav_date": stored.nav_date, "unit_nav": Decimal(stored.unit_nav), "source": stored.source}

    try:
        return client.nav_on_or_after(fund_code, start_date, end_date)
    except Exception:
        return None
