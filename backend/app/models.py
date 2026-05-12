from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class Fund(Base):
    __tablename__ = "funds"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    fund_type: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    navs: Mapped[list["FundNav"]] = relationship(back_populates="fund")


class FundNav(Base):
    __tablename__ = "fund_navs"
    __table_args__ = (UniqueConstraint("fund_code", "nav_date", name="uq_fund_nav_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    fund_code: Mapped[str] = mapped_column(ForeignKey("funds.code"), index=True)
    nav_date: Mapped[date] = mapped_column(Date, index=True)
    unit_nav: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    accumulated_nav: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    daily_growth_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    source: Mapped[str] = mapped_column(String(32), default="akshare")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    fund: Mapped[Fund] = relationship(back_populates="navs")


class TradingCalendarDay(Base):
    __tablename__ = "trading_calendar"

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    is_trading_day: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(String(32), default="akshare")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    fund_code: Mapped[str] = mapped_column(ForeignKey("funds.code"), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    transaction_type: Mapped[str] = mapped_column(String(16))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    shares: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    nav: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    fee: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    note: Mapped[str | None] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column(String(128), index=True)
    import_source: Mapped[str | None] = mapped_column(String(32))
    initiated_at: Mapped[datetime | None] = mapped_column(DateTime)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(16), default="confirmed")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class DcaPlan(Base):
    __tablename__ = "dca_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    fund_code: Mapped[str] = mapped_column(ForeignKey("funds.code"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    fee: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    frequency: Mapped[str] = mapped_column(String(16), default="monthly")
    day_of_month: Mapped[int | None]
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class DcaExecution(Base):
    __tablename__ = "dca_executions"
    __table_args__ = (UniqueConstraint("plan_id", "scheduled_date", name="uq_dca_execution_plan_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("dca_plans.id"), index=True)
    fund_code: Mapped[str] = mapped_column(ForeignKey("funds.code"), index=True)
    scheduled_date: Mapped[date] = mapped_column(Date, index=True)
    confirmed_date: Mapped[date | None] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    shares: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    nav: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"
    __table_args__ = (UniqueConstraint("snapshot_date", name="uq_snapshot_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    market_value: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    total_invested: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    realized_cash: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    profit: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    profit_rate: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    cumulative_profit: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    cumulative_profit_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AdviceReport(Base):
    __tablename__ = "advice_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_date: Mapped[date] = mapped_column(Date, index=True)
    content: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AdminUser(Base):
    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AdminSession(Base):
    __tablename__ = "admin_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("admin_users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
