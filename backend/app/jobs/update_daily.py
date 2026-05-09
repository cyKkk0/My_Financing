import calendar
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models
from app.services.akshare_client import AkshareFundClient
from app.services.portfolio import save_snapshot


def update_daily_navs_and_snapshot(db: Session) -> dict[str, int | str]:
    client = AkshareFundClient()
    fund_codes = _fund_codes_to_update(db)
    fund_names = client.fund_name_map()
    updated = 0
    skipped: list[str] = []
    updated_details: list[str] = []

    for fund_code in fund_codes:
        latest = client.latest_nav_for(fund_code)
        if latest is None:
            skipped.append(fund_code)
            continue

        fund = db.get(models.Fund, fund_code)
        resolved_name = fund_names.get(fund_code.zfill(6)) or latest.get("name")
        if fund is None:
            fund = models.Fund(code=fund_code, name=resolved_name or fund_code)
            db.add(fund)
        elif resolved_name and (fund.name == fund.code or fund.name == fund_code):
            fund.name = resolved_name

        nav_rows = client.recent_navs_for(fund_code, limit=3) or [latest]
        for nav_info in nav_rows:
            _upsert_nav(db, fund_code, nav_info)
        updated += 1
        updated_details.append(
            f"{fund_code}:{latest['nav_date'].isoformat()}:{latest['unit_nav']}:{latest.get('source', 'akshare')}"
        )

    db.commit()
    snapshot = save_snapshot(db, date.today())
    return {
        "updated_funds": updated,
        "skipped_funds": ",".join(skipped),
        "updated_navs": ";".join(updated_details),
        "snapshot_date": snapshot.snapshot_date.isoformat(),
    }


def run_dca_check(db: Session, target_date: date | None = None) -> dict[str, int]:
    client = AkshareFundClient()
    result = process_due_dca_plans(db, client, target_date or date.today())
    db.commit()
    return {"dca_created": result["created"], "dca_confirmed": result["confirmed"], "dca_pending": result["pending"]}


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

    confirmed = _confirm_pending_dca_executions(db, client, target_date)
    pending_count = db.scalar(
        select(func.count()).select_from(models.DcaExecution).where(models.DcaExecution.status == "pending")
    )
    return {"created": created, "confirmed": confirmed, "pending": pending_count or 0}


def _confirm_pending_dca_executions(db: Session, client: AkshareFundClient, target_date: date) -> int:
    """Confirm pending DCA executions that have passed their T+N confirmation date.

    For each pending execution:
      1. T = first trading day >= scheduled_date (the NAV date)
      2. N = fund's buy confirmation days (T+N from AKShare, default 1)
      3. Confirm only when target_date >= T + N trading days
    """
    executions = db.scalars(
        select(models.DcaExecution)
        .where(models.DcaExecution.status == "pending")
        .order_by(models.DcaExecution.scheduled_date.asc())
    ).all()
    if not executions:
        return 0

    calendars: dict[str, list[date]] = {}        # fund_code → sorted trading dates
    nav_values: dict[str, dict[date, Decimal]] = {}  # fund_code → {date: unit_nav}
    confirm_days_map: dict[str, int] = {}         # fund_code → T+N
    plans: dict[int, models.DcaPlan] = {}          # plan_id → plan

    confirmed = 0
    for execution in executions:
        fund = execution.fund_code
        try:
            # ── cache plan ──
            if execution.plan_id not in plans:
                plans[execution.plan_id] = db.get(models.DcaPlan, execution.plan_id)
            plan = plans[execution.plan_id]
            # ── fetch trading calendar + NAV values once per fund ──
            if fund not in calendars:
                history = client.history_navs(fund)
                calendars[fund] = sorted({row["nav_date"] for row in history})
                nav_values[fund] = {row["nav_date"]: row["unit_nav"] for row in history}

            trading_days = calendars[fund]
            if not trading_days:
                execution.note = "暂无净值数据"
                continue

            # ── trade date T: first trading day >= scheduled_date ──
            trade_date: date | None = None
            for d in trading_days:
                if d >= execution.scheduled_date:
                    trade_date = d
                    break
            if trade_date is None:
                continue

            # ── confirmation days N ──
            if fund not in confirm_days_map:
                cd = client.trade_confirm_days(fund, "buy")
                confirm_days_map[fund] = cd if cd is not None else 1
            confirm_days = confirm_days_map[fund]

            # ── confirmation date = T + N trading days ──
            try:
                t_idx = trading_days.index(trade_date)
                confirm_idx = t_idx + confirm_days
                if confirm_idx >= len(trading_days):
                    execution.note = f"待T+{confirm_days}确认(净值日{trade_date})"
                    continue
                confirm_date = trading_days[confirm_idx]
            except (ValueError, IndexError):
                continue

            if target_date < confirm_date:
                execution.note = f"待T+{confirm_days}确认(净值日{trade_date} 确认日{confirm_date})"
                continue

            # ── NAV on trade date ──
            unit_nav = nav_values[fund].get(trade_date)
            if unit_nav is None:
                stored = db.scalar(
                    select(models.FundNav).where(
                        models.FundNav.fund_code == fund,
                        models.FundNav.nav_date == trade_date,
                    )
                )
                unit_nav = Decimal(stored.unit_nav) if stored else None
            if unit_nav is None or unit_nav <= 0:
                execution.note = f"净值日{trade_date}无净值"
                continue

            # ── create buy transaction ──
            nav_dec = Decimal(unit_nav)
            shares = (Decimal(execution.amount) / nav_dec).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )
            now = datetime.now()
            tx = models.Transaction(
                fund_code=fund,
                trade_date=trade_date,
                transaction_type="buy",
                amount=execution.amount,
                shares=shares,
                nav=nav_dec,
                fee=plan.fee if plan else Decimal("0"),
                external_id=f"dca:plan-{execution.plan_id}:{execution.scheduled_date.isoformat()}",
                initiated_at=now,
                confirmed_at=now,
                note=f"定投计划 #{execution.plan_id} 自动确认",
            )
            db.add(tx)
            db.flush()

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
            execution.confirmed_date = trade_date
            execution.nav = nav_dec
            execution.shares = shares
            execution.transaction_id = tx.id
            execution.note = None
            confirmed += 1
        except Exception:
            continue

    return confirmed


def _fund_codes_to_update(db: Session) -> list[str]:
    transaction_codes = {code for (code,) in db.execute(select(models.Transaction.fund_code).distinct()).all()}
    dca_codes = {code for (code,) in db.execute(select(models.DcaPlan.fund_code).distinct()).all()}
    return sorted(transaction_codes | dca_codes)


def _is_plan_due(plan: models.DcaPlan, target_date: date) -> bool:
    if plan.start_date is None:
        return False
    if target_date < plan.start_date:
        return False
    if plan.frequency == "daily":
        return True
    if plan.frequency == "weekly":
        return (target_date - plan.start_date).days % 7 == 0

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
