"""Number/date formatting used in narratives, reports and exports (the UI formats on the client)."""
from datetime import date, datetime

CURRENCY_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹", "JPY": "¥", "AUD": "A$", "CAD": "C$", "SGD": "S$",
                    "AED": "AED ", "ZAR": "R"}


def fmt_number(v: float | None, decimals: int = 0, compact: bool = True) -> str:
    if v is None:
        return "—"
    a = abs(v)
    if compact and a >= 1_000_000_000:
        return f"{v / 1e9:,.2f}B"
    if compact and a >= 1_000_000:
        return f"{v / 1e6:,.2f}M"
    if compact and a >= 10_000:
        return f"{v / 1e3:,.1f}K"
    return f"{v:,.{decimals}f}"


def fmt_value(v: float | None, unit: str = "number", currency: str = "USD", decimals: int = 2, compact: bool = True) -> str:
    if v is None:
        return "—"
    if unit == "currency":
        sym = CURRENCY_SYMBOLS.get(currency, currency + " ")
        s = fmt_number(abs(v), 2 if abs(v) < 10_000 else decimals, compact)
        return f"-{sym}{s}" if v < 0 else f"{sym}{s}"
    if unit == "percent":
        return f"{v * 100:,.1f}%" if abs(v) <= 5 else f"{v:,.1f}%"
    if unit == "count":
        return fmt_number(v, 0, compact)
    return fmt_number(v, decimals if abs(v) < 1000 else 0, compact)


def fmt_pct(v: float | None, signed: bool = True) -> str:
    if v is None:
        return "—"
    return f"{v:+.1f}%" if signed else f"{v:.1f}%"


def period_label(d: date | datetime | str, grain: str) -> str:
    if isinstance(d, str):
        d = date.fromisoformat(d[:10])
    if grain == "year":
        return f"{d.year}"
    if grain == "quarter":
        return f"Q{(d.month - 1) // 3 + 1} {d.year}"
    if grain == "month":
        return d.strftime("%b %Y")
    if grain == "week":
        return "Week of " + d.strftime("%d %b %Y")
    return d.strftime("%d %b %Y")


def range_label(start, end) -> str:
    def f(x):
        return x.strftime("%d %b %Y") if hasattr(x, "strftime") else str(x)
    return f"{f(start)} – {f(end)}"
