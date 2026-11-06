"""Money and number text for insights and reports, in the Indian numbering system (12,34,567.50)."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥"}


def default_currency() -> str:
    from app.core.config import get_settings
    return (get_settings().default_currency or "INR").strip().upper()


def indian_group(digits: str) -> str:
    """'1234567' -> '12,34,567': the last three digits, then groups of two."""
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts) + "," + tail


def _rounded(v, decimals: int) -> Decimal:
    # Rounds the number as written (2.675, not its binary approximation) half away from zero: the same as the
    # browser's Intl.NumberFormat, so a figure in a report reads the same as on screen.
    d = v if isinstance(v, Decimal) else Decimal(str(v)) if isinstance(v, float) else Decimal(v)
    return d.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)


def group_number(v: float | int, decimals: int = 0) -> str:
    """A number with Indian digit grouping and exactly `decimals` decimals; no minus sign on a rounded zero."""
    q = _rounded(v, decimals)
    sign = "-" if q < 0 else ""
    whole, _, frac = f"{abs(q):f}".partition(".")
    return sign + indian_group(whole) + (f".{frac}" if decimals else "")


def format_money(v: float | int, currency: str | None) -> str:
    """-₹12,34,567.50. The symbol comes from the column's currency; an unknown code is written after the number.
    A column without a currency (cleaned before DEFAULT_CURRENCY existed) uses the default, like the web app."""
    code = (currency or default_currency()).upper()
    sym = SYMBOLS.get(code, "")
    q = _rounded(v, 2)
    body = group_number(abs(q), 2)
    text = f"{sym}{body}" if sym or not code else f"{body} {code}"
    return f"-{text}" if q < 0 else text
