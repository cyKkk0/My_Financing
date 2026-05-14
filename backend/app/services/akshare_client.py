from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from typing import Any

import pandas as pd


@lru_cache(maxsize=1)
def load_trading_calendar() -> set[date]:
    """Return a set of Chinese stock market trading dates, cached.

    The AKShare data typically covers the current calendar year.
    When the exchange publishes next year's calendar (usually late
    Q4), a cache refresh will pick it up.
    """
    import akshare as ak

    df = ak.tool_trade_date_hist_sina()
    if df.empty or "trade_date" not in df.columns:
        return set()
    return {pd.to_datetime(d).date() for d in df["trade_date"]}


def trading_calendar_coverage_end() -> date | None:
    """Return the last date covered by the cached trading calendar."""
    cal = load_trading_calendar()
    return max(cal) if cal else None


def refresh_trading_calendar() -> set[date]:
    """Clear cached trading calendar and reload from AKShare.

    Returns the freshly loaded calendar.
    """
    load_trading_calendar.cache_clear()
    return load_trading_calendar()


def next_trading_day(d: date, trading_days: set[date]) -> date:
    """Return d if it is a trading day, else the next trading day."""
    while d not in trading_days:
        d += timedelta(days=1)
    return d


def add_trading_days(d: date, days: int, trading_days: set[date] | None = None) -> date:
    """Advance by N trading days, excluding the start date."""
    if days <= 0:
        return d
    trading_days = trading_days or load_trading_calendar()
    current = d
    remaining = days
    while remaining > 0:
        current += timedelta(days=1)
        if trading_days:
            if current in trading_days:
                remaining -= 1
        elif current.weekday() < 5:
            remaining -= 1
    return current


class AkshareFundClient:
    """Thin adapter around AKShare so API code stays testable."""

    def __init__(self) -> None:
        import akshare as ak

        self.ak = ak

    def list_open_funds(self) -> pd.DataFrame:
        return self.ak.fund_name_em()

    def daily_open_fund_navs(self) -> pd.DataFrame:
        return self.ak.fund_open_fund_daily_em()

    def fund_name_for(self, fund_code: str) -> str | None:
        df = self.list_open_funds()
        return fund_name_from_frame(df, fund_code)

    def trade_confirm_days(self, fund_code: str, transaction_type: str) -> int | None:
        df = self.ak.fund_fee_em(symbol=fund_code.zfill(6), indicator="交易确认日")
        if df.empty:
            return None
        return trade_confirm_days_from_frame(df, transaction_type)

    def redemption_fee_tiers(self, fund_code: str) -> list[dict[str, object]]:
        """Return redemption fee tiers for a fund from AKShare.

        Each tier is {"min_days": int, "max_days": int | None, "rate": Decimal}.
        max_days=None means no upper bound.
        Returns empty list if data is unavailable.
        """
        try:
            df = self.ak.fund_fee_em(symbol=fund_code.zfill(6), indicator="赎回费率")
        except Exception:
            return []
        if df.empty:
            return []
        return _parse_redemption_tiers(df)

    def confirm_date_from_trade(
        self,
        fund_code: str,
        transaction_type: str,
        trade_date: date,
    ) -> dict[str, Any]:
        confirm_days = self.trade_confirm_days(fund_code, transaction_type)
        if confirm_days is None:
            confirm_days = 1
            source = "fallback_trade_plus_1"
        else:
            source = "akshare_fund_fee_em"
        return {
            "confirm_date": add_trading_days(trade_date, confirm_days),
            "confirm_days": confirm_days,
            "source": source,
        }

    def trade_date_from_confirm(
        self,
        fund_code: str,
        transaction_type: str,
        confirm_date: date,
    ) -> dict[str, Any]:
        confirm_days = self.trade_confirm_days(fund_code, transaction_type)
        if confirm_days is None:
            confirm_days = 1
            source = "fallback_confirm_minus_1"
        else:
            source = "akshare_fund_fee_em"

        if confirm_days <= 0:
            return {
                "trade_date": confirm_date,
                "confirm_days": confirm_days,
                "source": source,
            }

        rows = sorted(
            {row["nav_date"] for row in self.history_navs(fund_code) if row["nav_date"] < confirm_date},
            reverse=True,
        )
        if len(rows) >= confirm_days:
            return {
                "trade_date": rows[confirm_days - 1],
                "confirm_days": confirm_days,
                "source": f"{source}_nav_calendar",
            }

        from datetime import timedelta

        return {
            "trade_date": confirm_date - timedelta(days=confirm_days),
            "confirm_days": confirm_days,
            "source": f"{source}_calendar_fallback",
        }

    def fund_name_map(self) -> dict[str, str]:
        df = self.list_open_funds()
        if df.empty:
            return {}

        code_column = _first_present_column(df, ["基金代码", "代码"])
        name_column = _first_present_column(df, ["基金简称", "基金名称", "基金全称", "名称"])
        if code_column is None or name_column is None:
            return {}

        result: dict[str, str] = {}
        for record in df[[code_column, name_column]].to_dict(orient="records"):
            code = str(record[code_column]).strip().zfill(6)
            name = record[name_column]
            if name is not None and not pd.isna(name):
                result[code] = str(name).strip()
        return result

    def history_navs(self, fund_code: str) -> list[dict[str, Any]]:
        df = self.ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
        if df.empty:
            return []

        date_column = "净值日期" if "净值日期" in df.columns else "日期"
        nav_column = _first_present_column(df, ["单位净值", "净值"])
        if nav_column is None:
            return []

        growth_column = _first_present_column(df, ["日增长率", "日涨幅", "日增长"])
        rows: list[dict[str, Any]] = []
        for record in df.to_dict(orient="records"):
            unit_nav = _decimal_or_none(record.get(nav_column))
            if unit_nav is None:
                continue
            nav_date = pd.to_datetime(record[date_column]).date()
            rows.append(
                {
                    "nav_date": nav_date,
                    "unit_nav": unit_nav,
                    "accumulated_nav": None,
                    "daily_growth_rate": _decimal_or_none(record.get(growth_column)) if growth_column else None,
                }
            )
        return rows

    def recent_navs_for(self, fund_code: str, limit: int = 3) -> list[dict[str, Any]]:
        rows = sorted(self.history_navs(fund_code), key=lambda item: item["nav_date"], reverse=True)
        return [
            {
                "nav_date": row["nav_date"],
                "unit_nav": row["unit_nav"],
                "accumulated_nav": row.get("accumulated_nav"),
                "daily_growth_rate": row.get("daily_growth_rate"),
                "name": fund_code,
                "source": "akshare_history",
            }
            for row in rows[:limit]
        ]

    def latest_nav_for(self, fund_code: str) -> dict[str, Any] | None:
        history_latest = self._latest_nav_from_history(fund_code)
        if history_latest is not None:
            return history_latest

        df = self.daily_open_fund_navs()
        code_column = "基金代码"
        matched = df[df[code_column].astype(str).str.zfill(6) == fund_code.zfill(6)]
        if matched.empty:
            return None

        record = matched.iloc[0].to_dict()
        date_value = record.get("净值日期") or record.get("日期") or date.today()
        nav_date = pd.to_datetime(date_value).date()
        unit_nav = _decimal_or_none(_pick_value(record, ["单位净值", "最新净值", "净值"]))
        if unit_nav is None:
            return None

        return {
            "nav_date": nav_date,
            "unit_nav": unit_nav,
            "accumulated_nav": _decimal_or_none(_pick_value(record, ["累计净值"])),
            "daily_growth_rate": _decimal_or_none(_pick_value(record, ["日增长率", "日涨幅"])),
            "name": str(record.get("基金简称") or record.get("基金名称") or fund_code),
            "source": "akshare_daily",
        }

    def nav_on_or_before(self, fund_code: str, target_date: date) -> dict[str, Any] | None:
        rows = [row for row in self.history_navs(fund_code) if row["nav_date"] <= target_date]
        if not rows:
            return None

        latest = max(rows, key=lambda item: item["nav_date"])
        return {
            "nav_date": latest["nav_date"],
            "unit_nav": latest["unit_nav"],
            "accumulated_nav": latest.get("accumulated_nav"),
            "daily_growth_rate": latest.get("daily_growth_rate"),
            "name": self.fund_name_for(fund_code) or fund_code,
            "source": "akshare_history",
        }

    def nav_on_or_after(self, fund_code: str, start_date: date, end_date: date) -> dict[str, Any] | None:
        rows = [
            row
            for row in self.history_navs(fund_code)
            if start_date <= row["nav_date"] <= end_date
        ]
        if not rows:
            return None

        earliest = min(rows, key=lambda item: item["nav_date"])
        return {
            "nav_date": earliest["nav_date"],
            "unit_nav": earliest["unit_nav"],
            "accumulated_nav": earliest.get("accumulated_nav"),
            "daily_growth_rate": earliest.get("daily_growth_rate"),
            "name": self.fund_name_for(fund_code) or fund_code,
            "source": "akshare_history",
        }

    def daily_nav_snapshot_index(self) -> dict[str, dict[str, Any]]:
        """Query fund_open_fund_daily_em once and index by fund code.

        This API often carries today's NAV before the history-series endpoint
        (fund_open_fund_info_em) is updated, so it can supplement stale history.

        Column format: YYYY-MM-DD-单位净值, YYYY-MM-DD-累计净值 (dates embedded in names).
        """
        import re

        try:
            df = self.daily_open_fund_navs()
        except Exception:
            return {}
        if df.empty:
            return {}
        code_col = _first_present_column(df, ["基金代码", "代码"])
        if code_col is None:
            return {}

        # Collect date-NV columns: find the latest date per row
        date_nav_pat = re.compile(r"^(\d{4}-\d{2}-\d{2})-单位净值$")
        date_nav_cols: list[tuple[date, str]] = []
        for col in df.columns:
            m = date_nav_pat.match(col)
            if m:
                date_nav_cols.append((pd.to_datetime(m.group(1)).date(), col))

        if not date_nav_cols:
            return {}

        # Keep only the latest date per fund
        date_nav_cols.sort(reverse=True, key=lambda x: x[0])
        latest_date = date_nav_cols[0][0]
        latest_unit_col = date_nav_cols[0][1]
        latest_accum_col = _first_present_column(df, [f"{latest_date.isoformat()}-累计净值"])
        growth_col = _first_present_column(df, ["日增长率", "日涨幅", "日增长"])

        result: dict[str, dict[str, Any]] = {}
        for _, row in df.iterrows():
            code = str(row[code_col]).strip().zfill(6)
            unit_nav = _decimal_or_none(row.get(latest_unit_col))
            if unit_nav is None:
                continue
            result[code] = {
                "nav_date": latest_date,
                "unit_nav": unit_nav,
                "accumulated_nav": _decimal_or_none(row.get(latest_accum_col)) if latest_accum_col else None,
                "daily_growth_rate": _decimal_or_none(row.get(growth_col)) if growth_col else None,
                "name": code,
                "source": "akshare_daily_snapshot",
            }
        return result

    def _latest_nav_from_history(self, fund_code: str) -> dict[str, Any] | None:
        rows = self.history_navs(fund_code)
        if not rows:
            return None

        latest = max(rows, key=lambda item: item["nav_date"])
        return {
            "nav_date": latest["nav_date"],
            "unit_nav": latest["unit_nav"],
            "accumulated_nav": latest.get("accumulated_nav"),
            "daily_growth_rate": latest.get("daily_growth_rate"),
            "name": self.fund_name_for(fund_code) or fund_code,
            "source": "akshare_history",
        }


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip().replace("%", "").replace(",", "")
    if text in {"", "-", "--", "nan", "None", "暂无数据"}:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def fund_name_from_frame(df: pd.DataFrame, fund_code: str) -> str | None:
    code_column = _first_present_column(df, ["基金代码", "代码"])
    name_column = _first_present_column(df, ["基金简称", "基金名称", "基金全称", "名称"])
    if df.empty or code_column is None or name_column is None:
        return None

    matched = df[df[code_column].astype(str).str.zfill(6) == fund_code.zfill(6)]
    if matched.empty:
        return None

    name = matched.iloc[0].to_dict().get(name_column)
    if name is None or pd.isna(name):
        return None
    return str(name).strip()


def trade_confirm_days_from_frame(df: pd.DataFrame, transaction_type: str) -> int | None:
    label = "卖出确认日" if transaction_type == "sell" else "买入确认日"
    rows = df.astype(str).to_dict(orient="records")
    for record in rows:
        values = [value.strip() for value in record.values()]
        for index, value in enumerate(values[:-1]):
            if value == label:
                return _parse_t_plus_days(values[index + 1])

    for record in rows:
        for value in record.values():
            parsed = _parse_t_plus_days(str(value))
            if parsed is not None:
                return parsed
    return None


def _parse_t_plus_days(value: str) -> int | None:
    import re

    match = re.search(r"T\s*\+\s*(\d+)", value.strip(), flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _pick_value(record: dict[str, Any], candidates: list[str]) -> Any:
    for column in candidates:
        if column in record:
            return record[column]
    return None


def _first_present_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for column in candidates:
        if column in df.columns:
            return column
    return None


def _parse_redemption_tiers(df: pd.DataFrame) -> list[dict[str, object]]:
    """Parse AKShare fund_fee_em redemption fee DataFrame into tier list.

    Handles common holding-period formats:
    - "小于7天" -> min=0, max=6
    - "7天-30天" -> min=7, max=29
    - "大于730天" -> min=731, max=None
    - "7天≤持有时间<30天" -> min=7, max=29
    """
    import re
    from decimal import Decimal, InvalidOperation

    tiers: list[dict[str, object]] = []
    for _, row in df.iterrows():
        values = [str(v).strip() for v in row.values]
        holding_text = ""
        rate_value = None
        for v in values:
            if v in ("", "nan", "None", "暂无数据"):
                continue
            if rate_value is not None:
                break
            pct = _parse_percentage(v)
            if pct is not None:
                rate_value = pct
            else:
                holding_text = v

        if rate_value is None:
            continue

        min_days, max_days = _parse_holding_range(holding_text)
        tiers.append({"min_days": min_days, "max_days": max_days, "rate": rate_value})

    return tiers


def _parse_percentage(text: str) -> Decimal | None:
    """Parse a percentage string like '1.50%' or '0.75%' to Decimal."""
    import re
    from decimal import Decimal, InvalidOperation

    match = re.search(r"(\d+\.?\d*)\s*%", text.strip())
    if not match:
        return None
    try:
        return Decimal(match.group(1)) / Decimal("100")
    except (InvalidOperation, ValueError):
        return None


def _parse_holding_range(text: str) -> tuple[int, int | None]:
    """Parse holding period description into (min_days, max_days).

    Handles AKShare formats from fund_fee_em:
    - "小于等于6天" -> (0, 6)
    - "大于等于7天，小于等于29天" -> (7, 29)
    - "大于等于730天" -> (730, None)
    - "小于7天" -> (0, 6)
    - "大于730天" -> (731, None)

    max_days=None means no upper bound.
    """
    import re

    numbers = [int(m) for m in re.findall(r"\d+", text)]
    if not numbers:
        return 0, None

    # Detect inclusive/exclusive qualifiers
    has_dengyu = "等于" in text or "≤" in text or "≥" in text

    # Compound range: two conditions separated by comma or Chinese comma
    if len(numbers) >= 2 and re.search(r"[，,]", text):
        lo, hi = numbers[0], numbers[1]
        return lo, hi if has_dengyu else hi - 1

    # Simple range with dash: "7天-30天"
    if len(numbers) >= 2:
        return numbers[0], numbers[1] - 1

    # Single condition
    n = numbers[0]
    if "小于" in text:
        return 0, n if has_dengyu else n - 1
    if "大于" in text:
        return n if has_dengyu else n + 1, None
    if "以上" in text:
        return n, None

    return 0, None
