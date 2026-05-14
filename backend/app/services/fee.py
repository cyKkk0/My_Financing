from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.services.akshare_client import AkshareFundClient


def match_rate(tiers: list[dict], holding_days: int) -> Decimal | None:
    """Find the applicable redemption fee rate for a given holding period."""
    if not tiers:
        return None
    for tier in tiers:
        min_days = tier["min_days"]
        max_days = tier["max_days"]
        if holding_days >= min_days and (max_days is None or holding_days <= max_days):
            return tier["rate"]
    return None


def fifo_calc_sell_fee(
    db: Session,
    fund_code: str,
    sell_shares: Decimal,
    sell_trade_date: date,
    nav: Decimal,
    tiers: list[dict],
    exclude_tx_id: int | None = None,
) -> tuple[Decimal | None, str | None]:
    """Calculate sell fee via FIFO matching against buy lots.

    Simulates all past confirmed sells consuming buy lots in FIFO order,
    then matches the new sell shares against remaining available lots.
    Each matched lot uses its own holding days to determine the rate tier.

    Returns (total_fee, breakdown) or (None, None) if unable to calculate.
    """
    if not tiers or sell_shares <= 0 or nav <= 0:
        return None, None

    # All confirmed buys for this fund, FIFO order
    buys = db.scalars(
        select(models.Transaction)
        .where(
            models.Transaction.fund_code == fund_code,
            models.Transaction.transaction_type == "buy",
            models.Transaction.status == "confirmed",
        )
        .order_by(models.Transaction.trade_date.asc(), models.Transaction.id.asc())
    ).all()

    if not buys:
        return None, None

    buy_lots = [
        {"id": b.id, "trade_date": b.trade_date, "shares": Decimal(b.shares)}
        for b in buys
    ]

    # All past confirmed sells for this fund, FIFO order
    sell_query = select(models.Transaction).where(
        models.Transaction.fund_code == fund_code,
        models.Transaction.transaction_type == "sell",
        models.Transaction.status == "confirmed",
    )
    if exclude_tx_id is not None:
        sell_query = sell_query.where(models.Transaction.id != exclude_tx_id)
    past_sells = db.scalars(
        sell_query.order_by(models.Transaction.trade_date.asc(), models.Transaction.id.asc())
    ).all()

    # Simulate past sells consuming buy lots
    for past_sell in past_sells:
        remaining = Decimal(past_sell.shares)
        for lot in buy_lots:
            if remaining <= 0:
                break
            if lot["shares"] <= 0:
                continue
            matched = min(remaining, lot["shares"])
            lot["shares"] -= matched
            remaining -= matched

    # Match the new sell
    remaining = sell_shares
    total_fee = Decimal("0")
    parts: list[str] = []

    for lot in buy_lots:
        if remaining <= 0:
            break
        if lot["shares"] <= 0:
            continue
        matched = min(remaining, lot["shares"])
        lot["shares"] -= matched
        remaining -= matched

        holding_days = (sell_trade_date - lot["trade_date"]).days
        rate = match_rate(tiers, holding_days)
        if rate is None:
            return None, None

        fee_part = (matched * nav * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total_fee += fee_part
        rate_pct = f"{rate:.2%}"
        matched_str = str(int(matched)) if matched % 1 == 0 else f"{matched:.4f}".rstrip("0").rstrip(".")
        parts.append(f"{matched_str}份×{rate_pct}")

    if remaining > 0:
        # Sell shares exceed available holdings
        return None, None

    breakdown = " + ".join(parts) if parts else None
    return total_fee, breakdown


def fetch_and_calc_sell_fee(
    db: Session,
    fund_code: str,
    sell_shares: Decimal,
    sell_trade_date: date,
    nav: Decimal,
    exclude_tx_id: int | None = None,
) -> tuple[Decimal | None, str | None]:
    """Fetch redemption fee tiers and calculate sell fee via FIFO.

    Returns (total_fee, breakdown) or (None, None) if unable to calculate.
    """
    try:
        tiers = AkshareFundClient().redemption_fee_tiers(fund_code)
    except Exception:
        return None, None

    if not tiers:
        return None, None

    return fifo_calc_sell_fee(db, fund_code, sell_shares, sell_trade_date, nav, tiers, exclude_tx_id)
