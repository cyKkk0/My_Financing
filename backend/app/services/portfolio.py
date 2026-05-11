from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.schemas import HoldingOut, PortfolioSummaryOut


TWOPLACES = Decimal("0.01")
FOURPLACES = Decimal("0.0001")
EPSILON = Decimal("0.000001")


def calculate_portfolio_summary(db: Session) -> PortfolioSummaryOut:
    funds = {fund.code: fund for fund in db.scalars(select(models.Fund)).all()}
    transactions = db.scalars(
        select(models.Transaction)
        .where(models.Transaction.status == "confirmed")
        .order_by(
            models.Transaction.trade_date,
            models.Transaction.external_id,
            models.Transaction.id,
        )
    ).all()
    manual_navs: dict[str, tuple[date, Decimal]] = {}

    lots: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: {
            "shares": Decimal("0"),
            "cost": Decimal("0"),
            "invested": Decimal("0"),
            "realized_cash": Decimal("0"),
        }
    )

    for tx in transactions:
        item = lots[tx.fund_code]
        amount = Decimal(tx.amount)
        shares = Decimal(tx.shares)
        fee = Decimal(tx.fee)
        if tx.nav is not None:
            manual_navs[tx.fund_code] = (tx.trade_date, Decimal(tx.nav))
        if tx.transaction_type == "buy":
            item["shares"] += shares
            item["cost"] += amount + fee
            item["invested"] += amount + fee
        elif tx.transaction_type == "sell":
            original_shares = item["shares"]
            average_cost = item["cost"] / original_shares if original_shares > 0 else Decimal("0")
            item["shares"] -= shares
            item["cost"] -= average_cost * shares
            item["realized_cash"] += amount - fee
        elif tx.transaction_type == "dividend":
            item["realized_cash"] += amount
        elif tx.transaction_type == "fee":
            item["cost"] += fee or amount
            item["invested"] += fee or amount

    holdings: list[HoldingOut] = []
    market_value = Decimal("0")
    confirmed_market_value = Decimal("0")
    total_cost = Decimal("0")
    total_invested = Decimal("0")
    realized_cash = Decimal("0")
    active_fund_codes = {
        fund_code
        for fund_code, item in lots.items()
        if item["shares"] > EPSILON or item["cost"] > EPSILON
    }
    latest_nav_date = _latest_official_nav_date(db, active_fund_codes)
    confirmed_nav_cutoff_date = _confirmed_nav_cutoff_date(db, active_fund_codes, latest_nav_date)

    for fund_code, item in lots.items():
        if abs(item["shares"]) <= EPSILON:
            item["shares"] = Decimal("0")
        if abs(item["cost"]) <= EPSILON:
            item["cost"] = Decimal("0")

        latest_nav = _latest_official_nav(db, fund_code) or _latest_any_nav(db, fund_code)
        fallback_nav = manual_navs.get(fund_code)
        nav = Decimal(latest_nav.unit_nav) if latest_nav else fallback_nav[1] if fallback_nav else None
        nav_date = latest_nav.nav_date if latest_nav else fallback_nav[0] if fallback_nav else None
        # Previous NAV for daily P&L
        prev_nav_raw = _previous_nav(db, fund_code, nav_date) if nav_date else None
        prev_nav = Decimal(prev_nav_raw.unit_nav) if prev_nav_raw else None
        daily_pnl = (item["shares"] * (nav - prev_nav)) if nav is not None and prev_nav is not None else None
        confirmed_nav_row = _confirmed_nav(db, fund_code, confirmed_nav_cutoff_date)
        confirmed_nav = (
            Decimal(confirmed_nav_row.unit_nav)
            if confirmed_nav_row is not None
            else fallback_nav[1]
            if fallback_nav and confirmed_nav_cutoff_date is None
            else None
        )
        confirmed_nav_date = (
            confirmed_nav_row.nav_date
            if confirmed_nav_row is not None
            else fallback_nav[0]
            if fallback_nav and confirmed_nav_cutoff_date is None
            else None
        )
        fund_market_value = (item["shares"] * nav) if nav is not None else Decimal("0")
        confirmed_fund_market_value = (item["shares"] * confirmed_nav) if confirmed_nav is not None else Decimal("0")
        holding_profit = fund_market_value - item["cost"]
        holding_profit_rate = holding_profit / item["cost"] if item["cost"] > 0 else Decimal("0")
        cumulative_profit = fund_market_value + item["realized_cash"] - item["invested"]
        cumulative_profit_rate = cumulative_profit / item["invested"] if item["invested"] > 0 else Decimal("0")
        confirmed_holding_profit = confirmed_fund_market_value - item["cost"]
        confirmed_holding_profit_rate = (
            confirmed_holding_profit / item["cost"] if item["cost"] > 0 else Decimal("0")
        )
        confirmed_cumulative_profit = confirmed_fund_market_value + item["realized_cash"] - item["invested"]
        confirmed_cumulative_profit_rate = (
            confirmed_cumulative_profit / item["invested"] if item["invested"] > 0 else Decimal("0")
        )

        if item["shares"] > 0 or item["cost"] > 0:
            market_value += fund_market_value
            confirmed_market_value += confirmed_fund_market_value
            total_cost += item["cost"]
        total_invested += item["invested"]
        realized_cash += item["realized_cash"]

        if item["shares"] <= 0 and item["cost"] <= 0:
            continue

        fund = funds.get(fund_code)
        holdings.append(
            HoldingOut(
                fund_code=fund_code,
                fund_name=fund.name if fund else fund_code,
                shares=_q4(item["shares"]),
                cost=_q2(item["cost"]),
                latest_nav=nav,
                nav_date=nav_date,
                market_value=_q2(fund_market_value),
                profit=_q2(holding_profit),
                profit_rate=_q4(holding_profit_rate),
                holding_profit=_q2(holding_profit),
                holding_profit_rate=_q4(holding_profit_rate),
                cumulative_profit=_q2(cumulative_profit),
                cumulative_profit_rate=_q4(cumulative_profit_rate),
                confirmed_nav=confirmed_nav,
                confirmed_nav_date=confirmed_nav_date,
                confirmed_market_value=_q2(confirmed_fund_market_value),
                confirmed_holding_profit=_q2(confirmed_holding_profit),
                confirmed_holding_profit_rate=_q4(confirmed_holding_profit_rate),
                confirmed_cumulative_profit=_q2(confirmed_cumulative_profit),
                confirmed_cumulative_profit_rate=_q4(confirmed_cumulative_profit_rate),
                realized_cash=_q2(item["realized_cash"]),
                previous_nav=prev_nav,
                daily_pnl=_q2(daily_pnl) if daily_pnl is not None else None,
            )
        )

    holding_profit = market_value - total_cost
    holding_profit_rate = holding_profit / total_cost if total_cost > 0 else Decimal("0")
    cumulative_profit = market_value + realized_cash - total_invested
    cumulative_profit_rate = cumulative_profit / total_invested if total_invested > 0 else Decimal("0")
    confirmed_holding_profit = confirmed_market_value - total_cost
    confirmed_holding_profit_rate = confirmed_holding_profit / total_cost if total_cost > 0 else Decimal("0")
    confirmed_cumulative_profit = confirmed_market_value + realized_cash - total_invested
    confirmed_cumulative_profit_rate = (
        confirmed_cumulative_profit / total_invested if total_invested > 0 else Decimal("0")
    )
    return PortfolioSummaryOut(
        market_value=_q2(market_value),
        confirmed_market_value=_q2(confirmed_market_value),
        total_invested=_q2(total_cost),
        realized_cash=_q2(realized_cash),
        profit=_q2(holding_profit),
        profit_rate=_q4(holding_profit_rate),
        holding_profit=_q2(holding_profit),
        holding_profit_rate=_q4(holding_profit_rate),
        cumulative_profit=_q2(cumulative_profit),
        cumulative_profit_rate=_q4(cumulative_profit_rate),
        confirmed_holding_profit=_q2(confirmed_holding_profit),
        confirmed_holding_profit_rate=_q4(confirmed_holding_profit_rate),
        confirmed_cumulative_profit=_q2(confirmed_cumulative_profit),
        confirmed_cumulative_profit_rate=_q4(confirmed_cumulative_profit_rate),
        latest_nav_date=latest_nav_date,
        confirmed_nav_cutoff_date=confirmed_nav_cutoff_date,
        holdings=holdings,
    )


def save_snapshot(db: Session, snapshot_date: date | None = None) -> models.PortfolioSnapshot:
    target_date = snapshot_date or date.today()
    summary = calculate_portfolio_summary(db)
    snapshot = db.scalar(
        select(models.PortfolioSnapshot).where(models.PortfolioSnapshot.snapshot_date == target_date)
    )
    if snapshot is None:
        snapshot = models.PortfolioSnapshot(snapshot_date=target_date)
        db.add(snapshot)

    snapshot.market_value = summary.market_value
    snapshot.total_invested = summary.total_invested
    snapshot.realized_cash = summary.realized_cash
    snapshot.profit = summary.profit
    snapshot.profit_rate = summary.profit_rate
    snapshot.cumulative_profit = summary.cumulative_profit
    snapshot.cumulative_profit_rate = summary.cumulative_profit_rate
    db.commit()
    db.refresh(snapshot)
    return snapshot


def calculate_snapshot_as_of(
    db: Session, as_of_date: date
) -> dict[str, Decimal | date | None]:
    """Calculate portfolio state as of a specific date using only transactions
    and NAV data available on or before that date."""
    funds = {fund.code: fund for fund in db.scalars(select(models.Fund)).all()}
    transactions = db.scalars(
        select(models.Transaction)
        .where(
            models.Transaction.status == "confirmed",
            models.Transaction.trade_date <= as_of_date,
        )
        .order_by(
            models.Transaction.trade_date,
            models.Transaction.external_id,
            models.Transaction.id,
        )
    ).all()

    lots: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: {
            "shares": Decimal("0"),
            "cost": Decimal("0"),
            "invested": Decimal("0"),
            "realized_cash": Decimal("0"),
        }
    )

    for tx in transactions:
        item = lots[tx.fund_code]
        amount = Decimal(tx.amount)
        shares = Decimal(tx.shares)
        fee = Decimal(tx.fee)
        if tx.transaction_type == "buy":
            item["shares"] += shares
            item["cost"] += amount + fee
            item["invested"] += amount + fee
        elif tx.transaction_type == "sell":
            original_shares = item["shares"]
            average_cost = item["cost"] / original_shares if original_shares > 0 else Decimal("0")
            item["shares"] -= shares
            item["cost"] -= average_cost * shares
            item["realized_cash"] += amount - fee
        elif tx.transaction_type == "dividend":
            item["realized_cash"] += amount
        elif tx.transaction_type == "fee":
            item["cost"] += fee or amount
            item["invested"] += fee or amount

    market_value = Decimal("0")
    total_invested = Decimal("0")
    realized_cash = Decimal("0")
    total_cost = Decimal("0")

    for fund_code, item in lots.items():
        if abs(item["shares"]) <= EPSILON:
            item["shares"] = Decimal("0")
        if abs(item["cost"]) <= EPSILON:
            item["cost"] = Decimal("0")
        total_invested += item["invested"]
        realized_cash += item["realized_cash"]
        if item["shares"] <= 0 and item["cost"] <= 0:
            continue
        total_cost += item["cost"]
        nav_row = _nav_on_or_before(db, fund_code, as_of_date)
        if nav_row is not None:
            market_value += item["shares"] * Decimal(nav_row.unit_nav)

    profit = market_value - total_cost
    profit_rate = profit / total_cost if total_cost > 0 else Decimal("0")
    cumulative_profit = market_value + realized_cash - total_invested
    cumulative_profit_rate = cumulative_profit / total_invested if total_invested > 0 else Decimal("0")
    return {
        "market_value": _q2(market_value),
        "total_invested": _q2(total_cost),
        "realized_cash": _q2(realized_cash),
        "profit": _q2(profit),
        "profit_rate": _q4(profit_rate),
        "cumulative_profit": _q2(cumulative_profit),
        "cumulative_profit_rate": _q4(cumulative_profit_rate),
    }


def backfill_snapshots(db: Session) -> int:
    """Create snapshots for all dates between the first confirmed transaction
    and today where snapshots are missing. Only creates snapshots for dates
    that have NAV data for at least one held fund."""
    from sqlalchemy import func as sa_func

    first_txn = db.scalar(
        select(models.Transaction.trade_date)
        .where(models.Transaction.status == "confirmed")
        .order_by(models.Transaction.trade_date.asc())
        .limit(1)
    )
    if first_txn is None:
        return 0

    existing_dates = {
        row[0]
        for row in db.execute(
            select(models.PortfolioSnapshot.snapshot_date)
        ).all()
    }

    all_nav_dates = {
        row[0]
        for row in db.execute(
            select(models.FundNav.nav_date.distinct())
            .where(models.FundNav.nav_date >= first_txn)
            .order_by(models.FundNav.nav_date.asc())
        ).all()
    }

    missing_dates = sorted(all_nav_dates - existing_dates)

    created = 0
    for target_date in missing_dates:
        result = calculate_snapshot_as_of(db, target_date)
        if result["market_value"] == Decimal("0") and result["total_invested"] == Decimal("0"):
            continue
        snapshot = models.PortfolioSnapshot(
            snapshot_date=target_date,
            market_value=result["market_value"],
            total_invested=result["total_invested"],
            realized_cash=result["realized_cash"],
            profit=result["profit"],
            profit_rate=result["profit_rate"],
            cumulative_profit=result["cumulative_profit"],
            cumulative_profit_rate=result["cumulative_profit_rate"],
        )
        db.add(snapshot)
        created += 1

    db.commit()
    return created


def _nav_on_or_before(db: Session, fund_code: str, as_of_date: date) -> models.FundNav | None:
    return db.scalar(
        select(models.FundNav)
        .where(
            models.FundNav.fund_code == fund_code,
            models.FundNav.nav_date <= as_of_date,
        )
        .order_by(models.FundNav.nav_date.desc())
        .limit(1)
    )


def _q2(value: Decimal) -> Decimal:
    return value.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def _q4(value: Decimal) -> Decimal:
    return value.quantize(FOURPLACES, rounding=ROUND_HALF_UP)


def _latest_official_nav(db: Session, fund_code: str) -> models.FundNav | None:
    return db.scalar(
        select(models.FundNav)
        .where(
            models.FundNav.fund_code == fund_code,
            models.FundNav.source.like("akshare%"),
        )
        .order_by(models.FundNav.nav_date.desc())
        .limit(1)
    )


def _latest_any_nav(db: Session, fund_code: str) -> models.FundNav | None:
    return db.scalar(
        select(models.FundNav)
        .where(models.FundNav.fund_code == fund_code)
        .order_by(models.FundNav.nav_date.desc())
        .limit(1)
    )


def _latest_official_nav_date(db: Session, fund_codes: set[str]) -> date | None:
    if not fund_codes:
        return None
    return db.scalar(
        select(models.FundNav.nav_date)
        .where(
            models.FundNav.fund_code.in_(fund_codes),
            models.FundNav.source.like("akshare%"),
        )
        .order_by(models.FundNav.nav_date.desc())
        .limit(1)
    )


def _confirmed_nav_cutoff_date(
    db: Session,
    fund_codes: set[str],
    latest_nav_date: date | None,
) -> date | None:
    if not fund_codes or latest_nav_date is None:
        return latest_nav_date
    previous_date = db.scalar(
        select(models.FundNav.nav_date)
        .where(
            models.FundNav.fund_code.in_(fund_codes),
            models.FundNav.source.like("akshare%"),
            models.FundNav.nav_date < latest_nav_date,
        )
        .order_by(models.FundNav.nav_date.desc())
        .limit(1)
    )
    return previous_date or latest_nav_date


def _previous_nav(db: Session, fund_code: str, latest_nav_date: date) -> models.FundNav | None:
    return db.scalar(
        select(models.FundNav)
        .where(
            models.FundNav.fund_code == fund_code,
            models.FundNav.nav_date < latest_nav_date,
        )
        .order_by(models.FundNav.nav_date.desc())
        .limit(1)
    )


def _confirmed_nav(
    db: Session,
    fund_code: str,
    cutoff_date: date | None,
) -> models.FundNav | None:
    if cutoff_date is None:
        return _latest_official_nav(db, fund_code) or _latest_any_nav(db, fund_code)
    official = db.scalar(
        select(models.FundNav)
        .where(
            models.FundNav.fund_code == fund_code,
            models.FundNav.source.like("akshare%"),
            models.FundNav.nav_date <= cutoff_date,
        )
        .order_by(models.FundNav.nav_date.desc())
        .limit(1)
    )
    if official is not None:
        return official
    fallback = db.scalar(
        select(models.FundNav)
        .where(
            models.FundNav.fund_code == fund_code,
            models.FundNav.nav_date <= cutoff_date,
        )
        .order_by(models.FundNav.nav_date.desc())
        .limit(1)
    )
    if fallback is not None and fallback.nav_date >= cutoff_date - timedelta(days=3):
        return fallback
    return _latest_official_nav(db, fund_code) or fallback
