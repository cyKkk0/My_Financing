from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.core.config import Settings, get_settings
from app.db.database import get_db
from app.jobs.update_daily import run_dca_check, update_daily_navs_and_snapshot
from app.schemas import (
    AdviceOut,
    AlipayPdfImportOut,
    ChatRequest,
    DcaExecutionOut,
    DcaPlanCreate,
    DcaPlanOut,
    DcaPlanUpdate,
    FundPerformancePoint,
    PortfolioSummaryOut,
    TransactionCreate,
    TransactionOut,
)
from app.services.ai_advisor import generate_advice, stream_chat_advice
from app.services.akshare_client import (
    AkshareFundClient,
    add_trading_days,
    load_trading_calendar,
)
from app.services.alipay_pdf import ParsedAlipayTransaction, apply_resolved_trade_date, parse_alipay_pdf, parse_alipay_pdf_bytes
from app.services.portfolio import calculate_portfolio_summary, save_snapshot
from app.services.trading_calendar import ensure_trading_calendar_coverage

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/transactions", response_model=TransactionOut)
def create_transaction(payload: TransactionCreate, db: Session = Depends(get_db)) -> models.Transaction:
    fund_name = payload.fund_name or _resolve_fund_name(payload.fund_code)
    if not fund_name:
        raise HTTPException(status_code=400, detail=f"无法识别基金代码 {payload.fund_code}，未找到对应的基金名称")
    initiated_at = payload.initiated_at or datetime.now()
    if payload.initiated_at is not None:
        trade_date = _resolve_trade_date(initiated_at)
    else:
        trade_date = payload.trade_date or datetime.now().date()

    resolved_nav = payload.nav
    resolved_nav_date = trade_date
    resolved_nav_source = "manual"
    status = "confirmed"
    confirm_date: date | None = None
    if payload.transaction_type in ("buy", "sell"):
        try:
            confirm_info = AkshareFundClient().confirm_date_from_trade(
                payload.fund_code,
                payload.transaction_type,
                trade_date,
            )
            confirm_date = confirm_info["confirm_date"]
        except Exception:
            confirm_date = add_trading_days(trade_date, 1)

    if resolved_nav is None:
        nav_info = _resolve_nav_exact(payload.fund_code, trade_date, db)
        if nav_info is not None:
            resolved_nav = Decimal(nav_info["unit_nav"])
            resolved_nav_date = nav_info["nav_date"]
            resolved_nav_source = str(nav_info["source"])
    if payload.transaction_type in ("buy", "sell"):
        if resolved_nav is None or confirm_date is None or date.today() < confirm_date:
            status = "pending"

    effective_nav = resolved_nav if status == "confirmed" else None

    amount, shares = _resolve_transaction_numbers(
        payload.transaction_type,
        payload.amount,
        payload.shares,
        effective_nav,
        payload.fee,
    )
    if status == "pending" and payload.transaction_type == "buy":
        shares = Decimal("0")
    fund = db.get(models.Fund, payload.fund_code)
    if fund is None:
        fund = models.Fund(code=payload.fund_code, name=fund_name or payload.fund_code)
        db.add(fund)
    elif fund_name and fund.name == fund.code:
        fund.name = fund_name

    tx = models.Transaction(
        fund_code=payload.fund_code,
        trade_date=trade_date,
        transaction_type=payload.transaction_type,
        amount=amount,
        shares=shares,
        nav=effective_nav,
        fee=payload.fee,
        note=payload.note,
        initiated_at=initiated_at,
        confirmed_at=datetime.combine(confirm_date, datetime.min.time())
        if status == "confirmed" and confirm_date is not None
        else None,
        status=status,
    )
    db.add(tx)
    if effective_nav is not None:
        nav = db.scalar(
            select(models.FundNav).where(
                models.FundNav.fund_code == payload.fund_code,
                models.FundNav.nav_date == resolved_nav_date,
            )
        )
        if nav is None:
            nav = models.FundNav(
                fund_code=payload.fund_code,
                nav_date=resolved_nav_date,
                source=resolved_nav_source,
            )
            db.add(nav)
        nav.unit_nav = effective_nav
    db.commit()
    db.refresh(tx)
    return tx


@router.get("/transactions", response_model=list[TransactionOut])
def list_transactions(
    fund_code: str | None = None,
    transaction_type: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int | None = None,
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    base_query = _transaction_query(fund_code, transaction_type, start_date, end_date)
    query = base_query.order_by(models.Transaction.trade_date.desc(), models.Transaction.id.desc())
    if limit is not None and limit > 0:
        query = query.limit(limit)

    transactions = list(db.scalars(query).all())
    return _serialize_transactions(db, transactions)


@router.get("/transactions/page")
def list_transactions_page(
    fund_code: str | None = None,
    transaction_type: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    page: int = 1,
    page_size: int = 10,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    page = max(page, 1)
    page_size = min(max(page_size, 1), 50)
    items = _combined_transaction_items(
        db,
        fund_code=fund_code,
        transaction_type=transaction_type,
        start_date=start_date,
        end_date=end_date,
    )
    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "items": items[start:end],
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": (total + page_size - 1) // page_size,
    }


def _transaction_query(
    fund_code: str | None = None,
    transaction_type: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
):
    query = select(models.Transaction)
    if fund_code:
        query = query.where(models.Transaction.fund_code == fund_code.zfill(6))
    if transaction_type:
        query = query.where(models.Transaction.transaction_type == transaction_type)
    if start_date:
        query = query.where(models.Transaction.trade_date >= start_date)
    if end_date:
        query = query.where(models.Transaction.trade_date <= end_date)
    return query


def _serialize_transactions(db: Session, transactions: list[models.Transaction]) -> list[dict[str, object]]:
    if not transactions:
        return []
    fund_names = {
        fund.code: fund.name
        for fund in db.scalars(select(models.Fund).where(models.Fund.code.in_({tx.fund_code for tx in transactions}))).all()
    }
    return [
        {
            "id": tx.id,
            "sort_id": tx.id,
            "fund_code": tx.fund_code,
            "fund_name": fund_names.get(tx.fund_code, tx.fund_code),
            "trade_date": tx.trade_date.isoformat() if tx.trade_date else None,
            "transaction_type": tx.transaction_type,
            "amount": tx.amount,
            "shares": tx.shares,
            "nav": tx.nav,
            "fee": tx.fee,
            "note": tx.note,
            "initiated_at": tx.initiated_at.isoformat() if tx.initiated_at else None,
            "confirmed_at": tx.confirmed_at.isoformat() if tx.confirmed_at else None,
            "status": tx.status,
            "external_id": tx.external_id,
            "import_source": tx.import_source,
            "source_label": _transaction_source_label(tx),
            "is_virtual": False,
        }
        for tx in transactions
    ]


def _combined_transaction_items(
    db: Session,
    fund_code: str | None = None,
    transaction_type: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict[str, object]]:
    transactions = list(
        db.scalars(
            _transaction_query(fund_code, transaction_type, start_date, end_date)
        ).all()
    )
    items = _serialize_transactions(db, transactions)

    if transaction_type and transaction_type != "buy":
        executions = []
    else:
        execution_query = select(models.DcaExecution).where(models.DcaExecution.transaction_id.is_(None))
        if fund_code:
            execution_query = execution_query.where(models.DcaExecution.fund_code == fund_code.zfill(6))
        if start_date:
            execution_query = execution_query.where(models.DcaExecution.scheduled_date >= start_date)
        if end_date:
            execution_query = execution_query.where(models.DcaExecution.scheduled_date <= end_date)
        executions = list(db.scalars(execution_query).all())

    if executions:
        fund_codes = {execution.fund_code for execution in executions}
        plan_ids = {execution.plan_id for execution in executions}
        fund_names = {
            fund.code: fund.name
            for fund in db.scalars(select(models.Fund).where(models.Fund.code.in_(fund_codes))).all()
        }
        fees = {
            plan.id: plan.fee
            for plan in db.scalars(select(models.DcaPlan).where(models.DcaPlan.id.in_(plan_ids))).all()
        }
        items.extend(
            _serialize_dca_execution(execution, fund_names, fees)
            for execution in executions
        )

    return sorted(
        items,
        key=lambda item: (
            str(item.get("trade_date") or ""),
            1 if item.get("is_virtual") else 0,
            int(item.get("sort_id") or 0),
        ),
        reverse=True,
    )


def _serialize_dca_execution(
    execution: models.DcaExecution,
    fund_names: dict[str, str],
    fees: dict[int, Decimal],
) -> dict[str, object]:
    return {
        "id": f"dca-execution-{execution.id}",
        "sort_id": execution.id,
        "fund_code": execution.fund_code,
        "fund_name": fund_names.get(execution.fund_code, execution.fund_code),
        "trade_date": execution.scheduled_date.isoformat(),
        "transaction_type": "buy",
        "amount": execution.amount,
        "shares": execution.shares or Decimal("0"),
        "nav": execution.nav,
        "fee": fees.get(execution.plan_id, Decimal("0")),
        "note": execution.note,
        "initiated_at": None,
        "confirmed_at": execution.confirmed_date.isoformat() if execution.confirmed_date else None,
        "status": execution.status,
        "external_id": f"dca:execution-{execution.id}",
        "import_source": "dca_execution",
        "source_label": "定投执行",
        "is_virtual": True,
    }


def _transaction_source_label(tx: models.Transaction) -> str | None:
    if tx.external_id and tx.external_id.startswith("dca:"):
        return "定投确认"
    if tx.import_source == "alipay_pdf":
        return "支付宝"
    return None


@router.delete("/transactions/{transaction_id}")
def delete_transaction(transaction_id: int, db: Session = Depends(get_db)) -> dict[str, int | str]:
    tx = db.get(models.Transaction, transaction_id)
    if tx is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    execution = db.scalar(
        select(models.DcaExecution).where(models.DcaExecution.transaction_id == transaction_id)
    )
    if execution is not None:
        execution.status = "pending"
        execution.confirmed_date = None
        execution.nav = None
        execution.shares = None
        execution.transaction_id = None
        execution.note = "关联交易已撤销，等待重新确认"

    db.delete(tx)
    db.commit()
    return {"deleted_transaction_id": transaction_id}


@router.delete("/transactions")
def delete_transactions_batch(
    fund_code: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    db: Session = Depends(get_db),
) -> dict[str, int]:
    if not fund_code and not start_date and not end_date:
        raise HTTPException(status_code=400, detail="至少需要指定基金代码或日期范围")

    query = select(models.Transaction)
    if fund_code:
        query = query.where(models.Transaction.fund_code == fund_code.zfill(6))
    if start_date:
        query = query.where(models.Transaction.trade_date >= start_date)
    if end_date:
        query = query.where(models.Transaction.trade_date <= end_date)

    transactions = db.scalars(query.order_by(models.Transaction.id)).all()
    if not transactions:
        return {"deleted": 0}

    tx_ids = {tx.id for tx in transactions}

    # Reset linked DCA executions
    linked_executions = db.scalars(
        select(models.DcaExecution).where(models.DcaExecution.transaction_id.in_(tx_ids))
    ).all()
    for execution in linked_executions:
        execution.status = "pending"
        execution.confirmed_date = None
        execution.nav = None
        execution.shares = None
        execution.transaction_id = None
        execution.note = "关联交易已撤销，等待重新确认"

    for tx in transactions:
        db.delete(tx)

    db.commit()
    return {"deleted": len(transactions)}


@router.post("/transactions/import/alipay-pdf", response_model=AlipayPdfImportOut)
async def import_alipay_pdf(
    file: UploadFile = File(...),
    dry_run: bool = Form(True),
    db: Session = Depends(get_db),
) -> AlipayPdfImportOut:
    try:
        pdf_bytes = await file.read()
        parsed = parse_alipay_pdf_bytes(pdf_bytes)
        _resolve_alipay_trade_dates(parsed)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to parse PDF: {exc}") from exc

    created = 0
    updated = 0
    skipped = 0
    errors: list[dict[str, int | str]] = []
    existing_transactions = _existing_transactions_by_external_id(db, parsed)
    existing_funds = {fund.code: fund for fund in db.scalars(select(models.Fund)).all()}
    fund_name_map = _safe_fund_name_map() if not dry_run else {}

    for row_number, item in enumerate(parsed, start=1):
        try:
            existing = _find_existing_transaction(db, item, existing_transactions)
            if existing is not None:
                if dry_run:
                    if _imported_transaction_would_change(existing, item):
                        updated += 1
                    else:
                        skipped += 1
                    continue
                _ensure_fund(db, item.fund_code, existing_funds, fund_name_map)
                if _apply_imported_transaction(existing, item):
                    updated += 1
                else:
                    skipped += 1
                continue
            if dry_run:
                created += 1
                continue

            _ensure_fund(db, item.fund_code, existing_funds, fund_name_map)
            tx = models.Transaction(
                fund_code=item.fund_code,
                trade_date=item.trade_date,
                transaction_type=item.transaction_type,
                amount=item.amount,
                shares=item.shares,
                nav=item.nav,
                fee=item.fee,
                note=item.note,
                external_id=item.external_id,
                import_source="alipay_pdf",
                initiated_at=item.order_time,
                confirmed_at=item.confirm_time,
            )
            db.add(tx)
            created += 1
        except Exception as exc:
            errors.append({"row": row_number, "error": str(exc)})

    if not dry_run:
        _sync_imported_alipay_navs(db, {item.fund_code for item in parsed})
        db.commit()

    return AlipayPdfImportOut(
        parsed=len(parsed),
        created=created,
        updated=updated,
        skipped=skipped,
        failed=len(errors),
        errors=errors,
    )


@router.post("/dca-plans", response_model=DcaPlanOut)
def create_dca_plan(payload: DcaPlanCreate, db: Session = Depends(get_db)) -> models.DcaPlan:
    fund_name = payload.fund_name or _resolve_fund_name(payload.fund_code)
    fund = db.get(models.Fund, payload.fund_code)
    if fund is None:
        fund = models.Fund(code=payload.fund_code, name=fund_name or payload.fund_code)
        db.add(fund)
    elif fund_name and (fund.name == fund.code or fund.name.isdigit()):
        fund.name = fund_name

    if payload.day_of_month:
        day_of_month = payload.day_of_month
    elif payload.frequency == "weekly":
        day_of_month = payload.start_date.isoweekday()
    else:
        day_of_month = payload.start_date.day

    plan = models.DcaPlan(
        fund_code=payload.fund_code,
        amount=payload.amount,
        fee=payload.fee,
        start_date=payload.start_date,
        end_date=payload.end_date,
        frequency=payload.frequency,
        day_of_month=day_of_month,
        status=payload.status,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


@router.get("/dca-plans", response_model=list[DcaPlanOut])
def list_dca_plans(db: Session = Depends(get_db)) -> list[DcaPlanOut]:
    plans = list(db.scalars(select(models.DcaPlan).order_by(models.DcaPlan.created_at.desc())).all())
    if not plans:
        return []
    fund_codes = {plan.fund_code for plan in plans}
    fund_names = {
        fund.code: fund.name
        for fund in db.scalars(select(models.Fund).where(models.Fund.code.in_(fund_codes))).all()
    }
    return [
        DcaPlanOut(
            id=p.id,
            fund_code=p.fund_code,
            fund_name=fund_names.get(p.fund_code, p.fund_code),
            amount=p.amount,
            fee=p.fee,
            start_date=p.start_date,
            end_date=p.end_date,
            frequency=p.frequency,
            day_of_month=p.day_of_month,
            status=p.status,
        )
        for p in plans
    ]


@router.put("/dca-plans/{plan_id}", response_model=DcaPlanOut)
def update_dca_plan(plan_id: int, payload: DcaPlanUpdate, db: Session = Depends(get_db)) -> models.DcaPlan:
    plan = db.get(models.DcaPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="定投计划不存在")
    if payload.amount is not None:
        plan.amount = payload.amount
    if payload.fee is not None:
        plan.fee = payload.fee
    if payload.end_date is not None:
        plan.end_date = payload.end_date
    if payload.frequency is not None:
        plan.frequency = payload.frequency
    if payload.day_of_month is not None:
        plan.day_of_month = payload.day_of_month
    if payload.status is not None:
        plan.status = payload.status
    db.commit()
    db.refresh(plan)
    return plan


@router.delete("/dca-plans/{plan_id}")
def delete_dca_plan(plan_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    plan = db.get(models.DcaPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="定投计划不存在")
    from sqlalchemy import delete
    db.execute(delete(models.DcaExecution).where(models.DcaExecution.plan_id == plan_id))
    db.delete(plan)
    db.commit()
    return {"ok": "deleted"}


@router.get("/dca-executions", response_model=list[DcaExecutionOut])
def list_dca_executions(db: Session = Depends(get_db)) -> list[models.DcaExecution]:
    return list(
        db.scalars(
            select(models.DcaExecution).order_by(models.DcaExecution.scheduled_date.desc(), models.DcaExecution.id.desc())
        ).all()
    )


@router.get("/funds/{fund_code}/nav")
def get_fund_nav(fund_code: str, trade_date: date, db: Session = Depends(get_db)) -> dict[str, str]:
    nav = _resolve_nav_exact(fund_code, trade_date, db)
    if nav is None:
        raise HTTPException(status_code=404, detail="No NAV found for this fund on this exact date")
    return {
        "fund_code": fund_code.zfill(6),
        "nav_date": nav["nav_date"].isoformat(),
        "unit_nav": str(nav["unit_nav"]),
        "source": nav["source"],
    }


@router.get("/funds/{fund_code}/performance", response_model=list[FundPerformancePoint])
def fund_performance(
    fund_code: str,
    range: str = "month",
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    code = fund_code.zfill(6)
    days = _range_days(range)
    start_date = date.today() - timedelta(days=days)

    # Find the earliest buy transaction to use as cost basis
    first_buy = db.scalar(
        select(models.Transaction.trade_date)
        .where(
            models.Transaction.fund_code == code,
            models.Transaction.transaction_type == "buy",
            models.Transaction.status == "confirmed",
        )
        .order_by(models.Transaction.trade_date.asc())
        .limit(1)
    )
    cost_basis_date = max(first_buy, start_date) if first_buy else start_date

    # Merge stored NAVs and AKShare history for complete coverage
    stored = {
        nav.nav_date: nav
        for nav in db.scalars(
            select(models.FundNav)
            .where(models.FundNav.fund_code == code, models.FundNav.nav_date >= start_date)
            .order_by(models.FundNav.nav_date.asc())
        ).all()
    }
    try:
        for row in AkshareFundClient().history_navs(code):
            nav_date = row["nav_date"]
            if nav_date < start_date:
                continue
            if nav_date in stored:
                s = stored[nav_date]
                if s.daily_growth_rate is None and row.get("daily_growth_rate") is not None:
                    s.daily_growth_rate = row["daily_growth_rate"]
            else:
                stored[nav_date] = models.FundNav(
                    fund_code=code,
                    nav_date=nav_date,
                    unit_nav=row["unit_nav"],
                    daily_growth_rate=row.get("daily_growth_rate"),
                    source="akshare_history",
                )
                db.add(stored[nav_date])
        db.commit()
    except Exception:
        pass

    sorted_navs = sorted(stored.values(), key=lambda n: n.nav_date)
    if not sorted_navs:
        return []

    # Cost basis: NAV on or after cost_basis_date
    cost_basis_nav: Decimal | None = None
    for nav in sorted_navs:
        if nav.nav_date >= cost_basis_date:
            cost_basis_nav = Decimal(nav.unit_nav)
            break
    if cost_basis_nav is None:
        cost_basis_nav = Decimal(sorted_navs[-1].unit_nav)

    result: list[dict[str, object]] = []
    prev_nav: Decimal | None = None
    for nav in sorted_navs:
        growth = nav.daily_growth_rate
        if growth is None and prev_nav is not None and prev_nav != 0:
            growth = (Decimal(nav.unit_nav) - prev_nav) / prev_nav
        if nav.nav_date >= cost_basis_date:
            cumulative = (Decimal(nav.unit_nav) - cost_basis_nav) / cost_basis_nav
        else:
            cumulative = Decimal("0")
        result.append({
            "nav_date": nav.nav_date.isoformat(),
            "unit_nav": str(nav.unit_nav),
            "daily_growth_rate": str(growth.quantize(Decimal("0.000001"))) if growth is not None else None,
            "cumulative_return": str(cumulative.quantize(Decimal("0.000001"))) if cumulative is not None else None,
        })
        prev_nav = Decimal(nav.unit_nav)
    return result


def _range_days(range_key: str) -> int:
    mapping = {"week": 7, "month": 30, "3month": 90, "6month": 180, "year": 365}
    return mapping.get(range_key, 30)


@router.get("/portfolio/summary", response_model=PortfolioSummaryOut)
def portfolio_summary(db: Session = Depends(get_db)) -> PortfolioSummaryOut:
    return calculate_portfolio_summary(db)


@router.post("/portfolio/snapshot")
def create_snapshot(db: Session = Depends(get_db)) -> dict[str, str]:
    snapshot = save_snapshot(db)
    return {"snapshot_date": snapshot.snapshot_date.isoformat()}


@router.get("/portfolio/snapshots")
def list_snapshots(period: str = "month", db: Session = Depends(get_db)) -> list[dict[str, str]]:
    from datetime import date, timedelta

    cutoff_map = {
        "week": date.today() - timedelta(days=7),
        "month": date.today() - timedelta(days=30),
        "3months": date.today() - timedelta(days=90),
        "6months": date.today() - timedelta(days=180),
        "year": date.today() - timedelta(days=365),
    }
    cutoff = cutoff_map.get(period)

    stmt = select(models.PortfolioSnapshot).order_by(models.PortfolioSnapshot.snapshot_date.asc())
    if cutoff is not None:
        stmt = stmt.where(models.PortfolioSnapshot.snapshot_date >= cutoff)

    snapshots = db.scalars(stmt).all()
    return [
        {
            "date": item.snapshot_date.isoformat(),
            "market_value": str(item.market_value),
            "total_invested": str(item.total_invested),
            "profit": str(item.profit),
            "profit_rate": str(item.profit_rate),
            "cumulative_profit": str(item.cumulative_profit) if item.cumulative_profit is not None else None,
        }
        for item in snapshots
    ]


@router.post("/jobs/daily-update")
def daily_update(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, int | str]:
    _require_admin_token(settings, x_admin_token)
    return update_daily_navs_and_snapshot(db)


@router.post("/jobs/dca-check")
def dca_check(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, int]:
    _require_admin_token(settings, x_admin_token)
    return run_dca_check(db)


@router.post("/jobs/confirm-pending-transactions")
def confirm_pending(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, int]:
    _require_admin_token(settings, x_admin_token)
    from app.jobs.update_daily import confirm_pending_transactions
    return confirm_pending_transactions(db)


@router.post("/jobs/refresh-trading-calendar")
def refresh_calendar(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, object]:
    _require_admin_token(settings, x_admin_token)
    return ensure_trading_calendar_coverage(db, force=True)


@router.post("/funds/refresh-names")
def refresh_fund_names(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, int | str]:
    _require_admin_token(settings, x_admin_token)
    try:
        name_map = AkshareFundClient().fund_name_map()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch fund names: {exc}") from exc

    funds = db.scalars(select(models.Fund)).all()
    updated_codes: list[str] = []
    for fund in funds:
        resolved_name = name_map.get(fund.code.zfill(6))
        if resolved_name and (fund.name == fund.code or fund.name.isdigit()):
            fund.name = resolved_name
            updated_codes.append(fund.code)

    db.commit()
    return {"updated_funds": len(updated_codes), "updated_codes": ",".join(updated_codes)}


@router.post("/advice/daily", response_model=AdviceOut)
async def daily_advice(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    x_admin_token: str | None = Header(default=None),
) -> AdviceOut:
    _require_admin_token(settings, x_admin_token)
    summary = calculate_portfolio_summary(db)
    content = await generate_advice(settings, summary)
    report = models.AdviceReport(report_date=date.today(), content=content, model=settings.llm_model)
    db.add(report)
    db.commit()
    return AdviceOut(report_date=report.report_date, content=report.content, model=report.model)


@router.get("/advice/latest", response_model=AdviceOut | None)
def latest_advice(db: Session = Depends(get_db)) -> AdviceOut | None:
    report = db.scalar(select(models.AdviceReport).order_by(models.AdviceReport.created_at.desc()).limit(1))
    if report is None:
        return None
    return AdviceOut(report_date=report.report_date, content=report.content, model=report.model)


@router.post("/advice/chat")
async def chat_advice(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    x_admin_token: str | None = Header(default=None),
) -> StreamingResponse:
    _require_admin_token(settings, x_admin_token)
    summary = calculate_portfolio_summary(db)
    messages = [message.model_dump() for message in payload.messages]
    return StreamingResponse(
        stream_chat_advice(settings, summary, messages),
        media_type="text/plain; charset=utf-8",
    )


def _require_admin_token(settings: Settings, token: str | None) -> None:
    if not token or token != settings.admin_token:
        raise HTTPException(status_code=401, detail="Invalid admin token")


def _resolve_fund_name(fund_code: str) -> str | None:
    try:
        return AkshareFundClient().fund_name_for(fund_code)
    except Exception:
        return None


def _ensure_fund(
    db: Session,
    fund_code: str,
    existing_funds: dict[str, models.Fund] | None = None,
    fund_name_map: dict[str, str] | None = None,
) -> models.Fund:
    existing_funds = existing_funds if existing_funds is not None else {}
    fund_name_map = fund_name_map if fund_name_map is not None else {}
    fund = existing_funds.get(fund_code) or db.get(models.Fund, fund_code)
    fund_name = fund_name_map.get(fund_code.zfill(6)) or _resolve_fund_name(fund_code)
    if fund is None:
        fund = models.Fund(code=fund_code, name=fund_name or fund_code)
        db.add(fund)
        existing_funds[fund_code] = fund
    elif fund_name and (fund.name == fund.code or fund.name.isdigit()):
        fund.name = fund_name
    return fund


def _find_existing_transaction(
    db: Session,
    item: ParsedAlipayTransaction,
    existing_transactions: dict[str, models.Transaction] | None = None,
) -> models.Transaction | None:
    if item.external_id:
        if existing_transactions is not None:
            return existing_transactions.get(item.external_id)
        return db.scalar(select(models.Transaction).where(models.Transaction.external_id == item.external_id))

    match = db.scalar(
        select(models.Transaction)
        .where(
            models.Transaction.fund_code == item.fund_code,
            models.Transaction.trade_date == item.trade_date,
            models.Transaction.transaction_type == item.transaction_type,
            models.Transaction.amount == item.amount,
            models.Transaction.shares == item.shares,
            models.Transaction.fee == item.fee,
        )
        .limit(1)
    )
    if match is not None:
        return match

    return _find_existing_by_dca_execution(db, item)


def _find_existing_by_dca_execution(
    db: Session,
    item: ParsedAlipayTransaction,
) -> models.Transaction | None:
    exec = db.scalar(
        select(models.DcaExecution).where(
            models.DcaExecution.fund_code == item.fund_code,
            models.DcaExecution.amount == item.amount,
            models.DcaExecution.transaction_id.isnot(None),
            models.DcaExecution.scheduled_date >= item.trade_date - timedelta(days=3),
            models.DcaExecution.scheduled_date <= item.trade_date + timedelta(days=3),
        )
    )
    if exec is None:
        return None
    return db.get(models.Transaction, exec.transaction_id)


def _existing_transactions_by_external_id(
    db: Session,
    items: list[ParsedAlipayTransaction],
) -> dict[str, models.Transaction]:
    ids = {item.external_id for item in items if item.external_id}
    if not ids:
        return {}
    transactions = db.scalars(select(models.Transaction).where(models.Transaction.external_id.in_(ids))).all()
    return {tx.external_id: tx for tx in transactions if tx.external_id}


def _apply_imported_transaction(tx: models.Transaction, item: ParsedAlipayTransaction) -> bool:
    changed = False
    for field, value in _imported_transaction_updates(item).items():
        if getattr(tx, field) != value:
            setattr(tx, field, value)
            changed = True
    return changed


def _imported_transaction_would_change(tx: models.Transaction, item: ParsedAlipayTransaction) -> bool:
    return any(getattr(tx, field) != value for field, value in _imported_transaction_updates(item).items())


def _imported_transaction_updates(item: ParsedAlipayTransaction) -> dict[str, object]:
    return {
        "fund_code": item.fund_code,
        "trade_date": item.trade_date,
        "transaction_type": item.transaction_type,
        "amount": item.amount,
        "shares": item.shares,
        "nav": item.nav,
        "fee": item.fee,
        "note": item.note,
        "external_id": item.external_id,
        "import_source": "alipay_pdf",
        "initiated_at": item.order_time,
        "confirmed_at": item.confirm_time,
    }


def _sync_imported_alipay_navs(db: Session, fund_codes: set[str]) -> None:
    if not fund_codes:
        return

    stale_navs = db.scalars(
        select(models.FundNav).where(
            models.FundNav.fund_code.in_(fund_codes),
            models.FundNav.source == "alipay_pdf",
        )
    ).all()
    for nav in stale_navs:
        db.delete(nav)
    db.flush()

    existing_navs = {
        (nav.fund_code, nav.nav_date)
        for nav in db.scalars(select(models.FundNav).where(models.FundNav.fund_code.in_(fund_codes))).all()
    }
    imported_transactions = db.scalars(
        select(models.Transaction)
        .where(
            models.Transaction.fund_code.in_(fund_codes),
            models.Transaction.import_source == "alipay_pdf",
            models.Transaction.nav.is_not(None),
        )
        .order_by(models.Transaction.trade_date, models.Transaction.id)
    ).all()
    for tx in imported_transactions:
        nav_key = (tx.fund_code, tx.trade_date)
        if nav_key in existing_navs:
            continue
        db.add(
            models.FundNav(
                fund_code=tx.fund_code,
                nav_date=tx.trade_date,
                unit_nav=tx.nav,
                source="akshare_history",
            )
        )
        existing_navs.add(nav_key)


def _safe_fund_name_map() -> dict[str, str]:
    try:
        return AkshareFundClient().fund_name_map()
    except Exception:
        return {}


def _resolve_alipay_trade_dates(items: list[ParsedAlipayTransaction]) -> None:
    if not items:
        return

    client = AkshareFundClient()
    confirm_days_cache: dict[tuple[str, str], tuple[int, str]] = {}
    # Cache both NAV dates and unit NAV values from AKShare history_navs
    nav_cache: dict[str, dict[date, Decimal]] = {}
    for item in items:
        confirm_date = item.confirm_time.date()
        rule_key = (item.fund_code, item.transaction_type)
        try:
            confirm_days_source = confirm_days_cache.get(rule_key)
            if confirm_days_source is None:
                confirm_days = client.trade_confirm_days(item.fund_code, item.transaction_type)
                if confirm_days is None:
                    confirm_days_source = (1, "fallback_confirm_minus_1")
                else:
                    confirm_days_source = (confirm_days, "akshare_fund_fee_em")
                confirm_days_cache[rule_key] = confirm_days_source
            confirm_days, rule_source = confirm_days_source

            # Fetch historical NAVs once per fund (dates + unit NAV values)
            if item.fund_code not in nav_cache:
                nav_cache[item.fund_code] = {
                    row["nav_date"]: row["unit_nav"]
                    for row in client.history_navs(item.fund_code)
                }
            fund_navs = nav_cache[item.fund_code]
            nav_dates = sorted(fund_navs.keys(), reverse=True)

            if confirm_days <= 0:
                trade_date = confirm_date
                source = rule_source
            else:
                before_confirm = [d for d in nav_dates if d < confirm_date]
                if len(before_confirm) >= confirm_days:
                    trade_date = before_confirm[confirm_days - 1]
                    source = f"{rule_source}_nav_calendar"
                else:
                    trade_date = confirm_date - timedelta(days=confirm_days)
                    source = f"{rule_source}_calendar_fallback"

            apply_resolved_trade_date(
                item,
                trade_date,
                confirm_days,
                source,
            )

            # Look up the authoritative NAV from AKShare history for this trade date
            item.nav = fund_navs.get(trade_date)
        except Exception:
            continue


def _resolve_nav(fund_code: str, trade_date: date, db: Session) -> dict[str, Decimal | date | str] | None:
    stored = db.scalar(
        select(models.FundNav)
        .where(models.FundNav.fund_code == fund_code, models.FundNav.nav_date <= trade_date)
        .order_by(models.FundNav.nav_date.desc())
        .limit(1)
    )

    akshare_result = None
    if stored is None or stored.nav_date < trade_date:
        try:
            akshare_result = AkshareFundClient().nav_on_or_before(fund_code, trade_date)
        except Exception:
            pass

    if akshare_result is not None:
        akshare_date = akshare_result["nav_date"]
        if stored is None or akshare_date > stored.nav_date:
            _upsert_nav_from_akshare(db, fund_code, akshare_result)
            return {
                "nav_date": akshare_date,
                "unit_nav": Decimal(akshare_result["unit_nav"]),
                "source": akshare_result["source"],
            }

    if stored is not None:
        return {
            "nav_date": stored.nav_date,
            "unit_nav": Decimal(stored.unit_nav),
            "source": stored.source,
        }

    return None


def _resolve_nav_exact(fund_code: str, trade_date: date, db: Session) -> dict[str, Decimal | date | str] | None:
    """Return NAV only if it exists for the exact trade_date, otherwise None."""
    stored = db.scalar(
        select(models.FundNav)
        .where(models.FundNav.fund_code == fund_code, models.FundNav.nav_date == trade_date)
        .limit(1)
    )
    if stored is not None:
        return {
            "nav_date": stored.nav_date,
            "unit_nav": Decimal(stored.unit_nav),
            "source": stored.source,
        }

    try:
        client = AkshareFundClient()
        history = {row["nav_date"]: row for row in client.history_navs(fund_code)}
        if trade_date in history:
            row = history[trade_date]
            return {
                "nav_date": row["nav_date"],
                "unit_nav": row["unit_nav"],
                "source": "akshare_history",
            }
    except Exception:
        pass
    return None


def _upsert_nav_from_akshare(db: Session, fund_code: str, nav_data: dict) -> None:
    """Create or update a FundNav record from AKShare data."""
    from sqlalchemy.exc import IntegrityError

    nav = db.scalar(
        select(models.FundNav).where(
            models.FundNav.fund_code == fund_code,
            models.FundNav.nav_date == nav_data["nav_date"],
        )
    )
    if nav is not None:
        nav.unit_nav = nav_data["unit_nav"]
        if nav_data.get("accumulated_nav") is not None:
            nav.accumulated_nav = nav_data["accumulated_nav"]
        if nav_data.get("daily_growth_rate") is not None:
            nav.daily_growth_rate = nav_data["daily_growth_rate"]
        return

    try:
        nav = models.FundNav(
            fund_code=fund_code,
            nav_date=nav_data["nav_date"],
            unit_nav=nav_data["unit_nav"],
            accumulated_nav=nav_data.get("accumulated_nav"),
            daily_growth_rate=nav_data.get("daily_growth_rate"),
            source=nav_data.get("source", "akshare_history"),
        )
        db.add(nav)
        db.flush()
    except IntegrityError:
        db.rollback()
        # Another worker or prior call already inserted this row; update it instead
        nav = db.scalar(
            select(models.FundNav).where(
                models.FundNav.fund_code == fund_code,
                models.FundNav.nav_date == nav_data["nav_date"],
            )
        )
        if nav is not None:
            nav.unit_nav = nav_data["unit_nav"]
            if nav_data.get("accumulated_nav") is not None:
                nav.accumulated_nav = nav_data["accumulated_nav"]
            if nav_data.get("daily_growth_rate") is not None:
                nav.daily_growth_rate = nav_data["daily_growth_rate"]


def _resolve_trade_date(initiated_at: datetime) -> date:
    """Determine trade date (T day) from order initiation time.

    Rules:
    - Orders initiated before 15:00 on a trading day → T = same day
    - Orders initiated at/after 15:00 on a trading day → T = next trading day
    - Orders initiated on a non-trading day → T = next trading day
    - Trading days from AKShare (covers weekends + Chinese holidays)
    """
    trading_days = load_trading_calendar()
    if not trading_days:
        d = initiated_at.date()
        if initiated_at.hour >= 15:
            d += timedelta(days=1)
        while d.weekday() >= 5:
            d += timedelta(days=1)
        return d

    if initiated_at.hour >= 15:
        d = initiated_at.date() + timedelta(days=1)
    else:
        d = initiated_at.date()
    while d not in trading_days:
        d += timedelta(days=1)
    return d


def _resolve_transaction_numbers(
    transaction_type: str,
    amount: Decimal,
    shares: Decimal,
    nav: Decimal | None,
    fee: Decimal,
) -> tuple[Decimal, Decimal]:
    if nav is None or nav <= 0:
        return amount, shares

    if transaction_type == "buy" and shares == 0 and amount > 0:
        shares = ((amount - fee) / nav).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    elif transaction_type == "sell" and amount == 0 and shares > 0:
        amount = (shares * nav - fee).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    elif transaction_type == "buy" and amount == 0 and shares > 0:
        amount = (shares * nav + fee).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return amount, shares
