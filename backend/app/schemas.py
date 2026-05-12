from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class FundOut(BaseModel):
    code: str
    name: str
    fund_type: str | None = None

    model_config = {"from_attributes": True}


class TransactionCreate(BaseModel):
    fund_code: str = Field(min_length=1, max_length=16)
    fund_name: str | None = None
    trade_date: date | None = None
    transaction_type: str = Field(pattern="^(buy|sell|dividend|fee)$")
    amount: Decimal = Decimal("0")
    shares: Decimal = Decimal("0")
    nav: Decimal | None = None
    fee: Decimal = Decimal("0")
    note: str | None = None
    initiated_at: datetime | None = None


class TransactionOut(TransactionCreate):
    id: int
    fund_name: str | None = None
    external_id: str | None = None
    import_source: str | None = None
    initiated_at: datetime | None = None
    confirmed_at: datetime | None = None
    status: str = "confirmed"

    model_config = {"from_attributes": True}


class ImportErrorItem(BaseModel):
    row: int
    error: str


class AlipayPdfImportOut(BaseModel):
    parsed: int
    created: int
    updated: int = 0
    skipped: int
    failed: int
    errors: list[ImportErrorItem]


class DcaPlanCreate(BaseModel):
    fund_code: str = Field(min_length=1, max_length=16)
    fund_name: str | None = None
    amount: Decimal
    fee: Decimal = Decimal("0")
    start_date: date
    end_date: date | None = None
    frequency: str = Field(default="monthly", pattern="^(daily|weekly|monthly)$")
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    status: str = Field(default="active", pattern="^(active|paused)$")


class DcaPlanUpdate(BaseModel):
    amount: Decimal | None = None
    fee: Decimal | None = None
    end_date: date | None = None
    frequency: str | None = Field(default=None, pattern="^(daily|weekly|monthly)$")
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    status: str | None = Field(default=None, pattern="^(active|paused)$")


class DcaPlanOut(BaseModel):
    id: int
    fund_code: str
    fund_name: str | None = None
    amount: Decimal
    fee: Decimal = Decimal("0")
    start_date: date | None
    end_date: date | None = None
    frequency: str
    day_of_month: int | None = None
    status: str

    model_config = {"from_attributes": True}


class DcaExecutionOut(BaseModel):
    id: int
    plan_id: int
    fund_code: str
    scheduled_date: date
    confirmed_date: date | None = None
    amount: Decimal
    shares: Decimal | None = None
    nav: Decimal | None = None
    transaction_id: int | None = None
    status: str
    note: str | None = None

    model_config = {"from_attributes": True}


class HoldingOut(BaseModel):
    fund_code: str
    fund_name: str
    shares: Decimal
    cost: Decimal
    latest_nav: Decimal | None
    nav_date: date | None
    market_value: Decimal
    profit: Decimal
    profit_rate: Decimal
    holding_profit: Decimal
    holding_profit_rate: Decimal
    cumulative_profit: Decimal
    cumulative_profit_rate: Decimal
    confirmed_nav: Decimal | None = None
    confirmed_nav_date: date | None = None
    confirmed_market_value: Decimal
    confirmed_holding_profit: Decimal
    confirmed_holding_profit_rate: Decimal
    confirmed_cumulative_profit: Decimal
    confirmed_cumulative_profit_rate: Decimal
    realized_cash: Decimal
    unconfirmed_amount: Decimal = Decimal("0")
    previous_nav: Decimal | None = None
    daily_pnl: Decimal | None = None


class PortfolioSummaryOut(BaseModel):
    market_value: Decimal
    confirmed_market_value: Decimal
    total_invested: Decimal
    realized_cash: Decimal
    profit: Decimal
    profit_rate: Decimal
    holding_profit: Decimal
    holding_profit_rate: Decimal
    cumulative_profit: Decimal
    cumulative_profit_rate: Decimal
    confirmed_holding_profit: Decimal
    confirmed_holding_profit_rate: Decimal
    confirmed_cumulative_profit: Decimal
    confirmed_cumulative_profit_rate: Decimal
    latest_nav_date: date | None = None
    confirmed_nav_cutoff_date: date | None = None
    holdings: list[HoldingOut]


class AdviceOut(BaseModel):
    report_date: date
    content: str
    model: str


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1)


class FundPerformancePoint(BaseModel):
    nav_date: date
    unit_nav: Decimal
    daily_growth_rate: Decimal | None = None
    cumulative_return: Decimal | None = None


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=20)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class LoginResponse(BaseModel):
    token: str
    token_type: str = "bearer"
    username: str
    expires_at: datetime


class AdminMeOut(BaseModel):
    username: str
    expires_at: datetime | None = None
