import re
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


@dataclass
class ParsedAlipayTransaction:
    external_id: str
    fund_code: str
    fund_name: str
    trade_date: date
    order_time: datetime
    confirm_time: datetime
    raw_type: str
    confirm_days: int | None
    confirm_rule_source: str
    transaction_type: str
    amount: Decimal
    shares: Decimal
    nav: Decimal | None
    fee: Decimal
    note: str


TYPE_MAP = {
    "定投买入": "buy",
    "用户买入": "buy",
    "用户卖出": "sell",
}

# Amount pattern: fund-code apply-amt apply-shares confirm-amt confirm-shares fee
_AMOUNT_RE = re.compile(
    r"(?P<code>\d{6})\s+"
    r"(?P<apply_amount>\d+\.\d{2})\s+"
    r"(?P<apply_shares>/|\d+\.\d{2})\s+"
    r"(?P<confirm_amount>\d+\.\d{2})\s+"
    r"(?P<confirm_shares>/|\d+\.\d{2})\s+"
    r"(?P<fee>\d+\.\d{2})"
)

_EIGHT_DIGIT = re.compile(r"\d{8}")
_DATE_PREFIX = re.compile(r"(\d{4})/(\d{2})/(\d{1,2})")
_DATE_SUFFIX = re.compile(r"(\d{1,2})\s+(\d{2}):(\d{2})")


def parse_alipay_pdf(path: str) -> list[ParsedAlipayTransaction]:
    text = _extract_text(path)
    return _parse_raw_text(text)


def parse_alipay_pdf_bytes(pdf_bytes: bytes) -> list[ParsedAlipayTransaction]:
    text = _extract_text_from_bytes(pdf_bytes)
    return _parse_raw_text(text)


def _extract_text(path: str) -> str:
    pdf_path = Path(path).expanduser()
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    result = subprocess.run(
        ["pdftotext", "-raw", str(pdf_path), "-"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _extract_text_from_bytes(pdf_bytes: bytes) -> str:
    result = subprocess.run(
        ["pdftotext", "-raw", "-", "-"],
        input=pdf_bytes,
        check=True,
        capture_output=True,
    )
    return result.stdout.decode()


def _parse_raw_text(text: str) -> list[ParsedAlipayTransaction]:
    lines = [line.strip() for line in text.splitlines() if _keep_line(line.strip())]

    # Anchor on amount lines — their pattern is unambiguous even when
    # pdftotext scrambles line order across page breaks.
    amount_hits: list[tuple[int, re.Match]] = []
    for i, line in enumerate(lines):
        m = _AMOUNT_RE.search(line)
        if m:
            amount_hits.append((i, m))

    used_order_id_positions: set[int] = set()
    records: list[ParsedAlipayTransaction] = []

    for amt_idx, amt_match in amount_hits:
        try:
            fund_code = amt_match.group("code")
            apply_amount = _decimal_or_none(amt_match.group("apply_amount"))
            apply_shares = _decimal_or_none(amt_match.group("apply_shares"))
            confirm_amount = Decimal(amt_match.group("confirm_amount"))
            shares = Decimal(amt_match.group("confirm_shares"))
            fee = Decimal(amt_match.group("fee"))

            # Text before the amount pattern on the same line is part of fund name
            amount_prefix = lines[amt_idx][: amt_match.start()].strip()

            # ── find transaction type (search backwards) ──
            type_idx: int | None = None
            for j in range(amt_idx - 1, max(amt_idx - 15, -1), -1):
                if lines[j] in ("定投买入", "用户买入", "用户卖出") or lines[j] == "用户跨":
                    type_idx = j
                    break
            if type_idx is None:
                continue

            raw_type, type_width = _resolve_type(lines, type_idx)
            transaction_type = _map_transaction_type(raw_type, apply_amount, apply_shares)
            if transaction_type is None:
                continue

            # ── fund name ──
            name_start = type_idx + type_width
            name_parts: list[str] = lines[name_start:amt_idx]
            if amount_prefix:
                name_parts.append(amount_prefix)

            # ── order datetime (2 lines before type) ──
            if type_idx < 2:
                continue
            order_time, _ = _parse_wrapped_datetime(lines, type_idx - 2)

            # ── confirm datetime (2 lines after amount line) ──
            if amt_idx + 2 >= len(lines):
                continue
            confirm_time, _ = _parse_wrapped_datetime(lines, amt_idx + 1)

            # ── order ID (4 eight-digit parts) ──
            order_id_parts: list[str] = []
            # Search backwards from the datetime position
            for j in range(type_idx - 3, max(type_idx - 10, -1), -1):
                if _EIGHT_DIGIT.fullmatch(lines[j]) and j not in used_order_id_positions:
                    order_id_parts.insert(0, lines[j])
                    used_order_id_positions.add(j)
                    if len(order_id_parts) == 4:
                        break

            # If page break displaced some parts, search forwards too.
            # Also handles the combined pattern "DDDDDDDD fund-text"
            # that pdftotext produces when concatenating order-ID with fund name.
            if len(order_id_parts) < 4:
                for j in range(amt_idx + 3, min(amt_idx + 20, len(lines))):
                    line = lines[j]
                    if _EIGHT_DIGIT.fullmatch(line) and j not in used_order_id_positions:
                        order_id_parts.append(line)
                        used_order_id_positions.add(j)
                        if len(order_id_parts) == 4:
                            break
                    m = re.match(r"^(\d{8})\s+(.+)", line)
                    if m and j not in used_order_id_positions:
                        order_id_parts.append(m.group(1))
                        used_order_id_positions.add(j)
                        suffix = m.group(2).strip()
                        if suffix and suffix not in name_parts:
                            name_parts.append(suffix)
                        if len(order_id_parts) == 4:
                            break

            if len(order_id_parts) < 4:
                continue

            # Collect displaced fund-name fragments (after confirm time, skip
            # already-consumed order-ID positions and date lines).
            for j in range(amt_idx + 3, min(amt_idx + 15, len(lines))):
                if j in used_order_id_positions:
                    continue
                line = lines[j]
                if _EIGHT_DIGIT.fullmatch(line):
                    break
                if re.match(r"^\d{8}\s+", line):
                    continue
                if line and not _DATE_PREFIX.fullmatch(line) and not _DATE_SUFFIX.fullmatch(line):
                    if line not in name_parts:
                        name_parts.append(line)

            external_order_id = "".join(order_id_parts[:4])
            amount = _accounting_amount(transaction_type, confirm_amount, fee)
            external_id = f"alipay:{external_order_id}:{fund_code}:{transaction_type}"
            fund_name = "".join(name_parts).strip() or fund_code
            fallback_trade_date = confirm_time.date() - timedelta(days=1)

            records.append(
                ParsedAlipayTransaction(
                    external_id=external_id,
                    fund_code=fund_code,
                    fund_name=fund_name,
                    trade_date=fallback_trade_date,
                    order_time=order_time,
                    confirm_time=confirm_time,
                    raw_type=raw_type,
                    confirm_days=1,
                    confirm_rule_source="fallback_confirm_minus_1",
                    transaction_type=transaction_type,
                    amount=amount,
                    shares=shares,
                    nav=None,
                    fee=fee,
                    note=_build_note(
                        external_order_id=external_order_id,
                        order_time=order_time,
                        confirm_time=confirm_time,
                        trade_date=fallback_trade_date,
                        raw_type=raw_type,
                        fund_name=fund_name,
                        confirm_days=1,
                        confirm_rule_source="fallback_confirm_minus_1",
                    ),
                )
            )
        except (IndexError, ValueError, ArithmeticError):
            continue

    return records


def apply_resolved_trade_date(
    item: ParsedAlipayTransaction,
    trade_date: date,
    confirm_days: int | None,
    confirm_rule_source: str,
) -> None:
    item.trade_date = trade_date
    item.confirm_days = confirm_days
    item.confirm_rule_source = confirm_rule_source
    item.note = _build_note(
        external_order_id=_order_id_from_external_id(item.external_id),
        order_time=item.order_time,
        confirm_time=item.confirm_time,
        trade_date=trade_date,
        raw_type=item.raw_type,
        fund_name=item.fund_name,
        confirm_days=confirm_days,
        confirm_rule_source=confirm_rule_source,
    )


def _build_note(
    external_order_id: str,
    order_time: datetime,
    confirm_time: datetime,
    trade_date: date,
    raw_type: str,
    fund_name: str,
    confirm_days: int | None,
    confirm_rule_source: str,
) -> str:
    confirm_rule = f"T+{confirm_days}" if confirm_days is not None else "未知"
    return (
        f"支付宝PDF导入；订单号 {external_order_id}；交易时间 {order_time.isoformat()}；"
        f"确认时间 {confirm_time.isoformat()}；净值日期 {trade_date.isoformat()}；"
        f"确认规则 {confirm_rule}（{confirm_rule_source}）；原交易类型 {raw_type}；"
        f"支付宝基金名称 {fund_name}"
    )


def _order_id_from_external_id(external_id: str) -> str:
    parts = external_id.split(":")
    return parts[1] if len(parts) >= 2 else external_id


def _keep_line(line: str) -> bool:
    if not line:
        return False
    if re.fullmatch(r"\d+\s*/\s*\d+", line):
        return False
    if line.startswith("编号：") or line.startswith("蚂蚁") or line.startswith("基金交易明细"):
        return False
    if line.startswith("订单号 ") or line.startswith("兹证明") or line.startswith("说明："):
        return False
    return True


def _parse_wrapped_datetime(lines: list[str], index: int) -> tuple[datetime, int]:
    first = lines[index]
    second = lines[index + 1]
    match = _DATE_PREFIX.fullmatch(first)
    if not match:
        raise ValueError("bad date prefix")
    day_time = _DATE_SUFFIX.fullmatch(second)
    if not day_time:
        raise ValueError("bad date suffix")
    day = match.group(3) + day_time.group(1)
    value = datetime(
        int(match.group(1)),
        int(match.group(2)),
        int(day),
        int(day_time.group(2)),
        int(day_time.group(3)),
    )
    return value, index + 2


def _resolve_type(lines: list[str], index: int) -> tuple[str, int]:
    """Return (raw_type, number_of_lines_consumed)."""
    value = lines[index]
    if value == "用户跨" and index + 1 < len(lines) and lines[index + 1] == "TA转换":
        return "用户跨TA转换", 2
    return value, 1


def _is_amount_line(line: str) -> bool:
    return _AMOUNT_RE.search(line) is not None


def _amount_match(line: str):
    return _AMOUNT_RE.search(line)


def _decimal_or_none(value: str) -> Decimal | None:
    if value == "/":
        return None
    return Decimal(value)


def _accounting_amount(transaction_type: str, confirm_amount: Decimal, fee: Decimal) -> Decimal:
    if transaction_type == "buy":
        return confirm_amount - fee
    if transaction_type == "sell":
        return confirm_amount + fee
    return confirm_amount


def _map_transaction_type(
    raw_type: str,
    apply_amount: Decimal | None,
    apply_shares: Decimal | None,
) -> str | None:
    if raw_type in TYPE_MAP:
        return TYPE_MAP[raw_type]
    if raw_type == "用户跨TA转换":
        if apply_amount is not None and apply_amount > 0:
            return "buy"
        if apply_shares is not None and apply_shares > 0:
            return "sell"
    return None
