"""Vectorized per-column type detection and conversion (Tier 1 steps 4-6).

All functions take a pandas string Series that has already been text-normalized (trimmed,
null tokens removed). They never drop values silently: values that fail conversion are
returned as failures so the report can count them and show examples.

Money is held in memory as Int64 *minor units* (e.g. cents) with a schema `scale`, so sums are
exact integer arithmetic. It is written to Parquet as DECIMAL(38, scale).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from fractions import Fraction

import numpy as np
import pandas as pd

ID_NAME_RE = re.compile(
    r"(^|_)(id|ids|uuid|guid|code|sku|zip|zipcode|postcode|postal|pin|pincode|phone|mobile|tel|telephone|ssn|"
    r"account|acct|iban|ean|upc|isbn|barcode)($|_)")
MONEY_NAME_RE = re.compile(
    r"(^|_)(price|prices|amount|amt|revenue|revenues|sales|cost|costs|salary|salaries|wage|wages|"
    r"fee|fees|payment|payments|spend|spending|income|profit|budget|expense|expenses|"
    r"usd|eur|inr|gbp|turnover)($|_)")
DATE_NAME_RE = re.compile(r"(^|_)(date|dates|day|dt|time|timestamp|created|updated|month|period|when|dob)($|_)|_at$|_on$")
CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "₹": "INR", "₨": "INR", "¥": "JPY"}
CURRENCY_CODE_RE = r"(?:USD|EUR|GBP|INR|JPY|Rs\.?)"
TRUE_TOKENS = {"true", "t", "yes", "y", "1"}
FALSE_TOKENS = {"false", "f", "no", "n", "0"}
TEXT_BOOL_TOKENS = {"true", "false", "t", "f", "yes", "no", "y", "n"}

MONTHS = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
DATE_LIKE_RE = (
    r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}(?:[ tT]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:[zZ]|[+-]\d{2}:?\d{2})?)?$"
    r"|^\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}(?: \d{1,2}:\d{2}(?::\d{2})?)?$"
    rf"|^\d{{1,2}}[ -]{MONTHS}[ -,]*\d{{2,4}}$"
    rf"|^{MONTHS} \d{{1,2}},? \d{{4}}$"
)
NUMERIC_DMY_RE = r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})"
EXCEL_EPOCH = pd.Timestamp("1899-12-30")
MAX_FAIL_SHARE = 0.1
ORDINAL_RE = r"(?i)\b(\d{1,2})(?:st|nd|rd|th)\b"


def too_many_failures(fails: int, n: int) -> bool:
    """A column is converted when at most 10% of its values fail (or a single value in a column of 8+).
    Failed values become empty and are listed in the cleaning report; the original file keeps them."""
    return fails > MAX_FAIL_SHARE * n and not (fails == 1 and n >= 8)

DMY_FORMATS = [f"%d{sep}%m{sep}{year}{tm}" for tm in ("", " %H:%M", " %H:%M:%S") for year in ("%Y", "%y") for sep in "/-."]
MDY_FORMATS = [f"%m{sep}%d{sep}{year}{tm}" for tm in ("", " %H:%M", " %H:%M:%S") for year in ("%Y", "%y") for sep in "/-."]
NAMED_FORMATS = ["%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%d-%b-%y", "%d-%B-%Y", "%b %d, %Y", "%B %d, %Y",
                 "%b %d %Y", "%B %d %Y", "%d %b, %Y", "%d %b %y"]
YMD_FORMATS = ["ISO8601", "%Y/%m/%d", "%Y.%m.%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"]
COMPACT_FORMATS = ["%Y%m%d"]


@dataclass
class Parsed:
    values: pd.Series
    dtype: str                     # string|integer|float|decimal|date|datetime|boolean
    semantic: str                  # id|currency|percent|numeric|date|boolean|category|text
    failures: pd.Series | None = None   # bool mask (aligned) of values that failed conversion -> null
    meta: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    description: str = ""


def _examples(s: pd.Series, n: int = 5) -> list[str]:
    return [str(v)[:60] for v in s.dropna().unique()[:n]]


# ------------------------------------------------------------------ IDs and booleans

def looks_like_id(key: str, s: pd.Series, forced: bool) -> bool:
    v = s.dropna()
    if forced:
        return True
    if v.empty:
        return False
    digits = v.str.fullmatch(r"\d+")
    if (digits & (v.str.len() > 1) & v.str.startswith("0")).any():
        return True  # leading zeros would be lost as numbers
    if ID_NAME_RE.search(key):
        return True
    n_unique = v.nunique()
    unique_ratio = n_unique / len(v)
    if len(v) >= 20 and digits.all() and unique_ratio >= 0.9 and v.str.len().nunique() == 1 and v.str.len().iloc[0] >= 5:
        return True
    if len(v) >= 20 and unique_ratio >= 0.9 and v.str.fullmatch(r"[A-Za-z]{1,6}[-_]?\d{2,}").all():
        return True
    return False


def parse_boolean(s: pd.Series) -> Parsed | None:
    v = s.dropna()
    if v.empty:
        return None
    lower = v.str.lower()
    if not lower.isin(TRUE_TOKENS | FALSE_TOKENS).all() or not lower.isin(TEXT_BOOL_TOKENS).any():
        return None
    out = pd.Series(pd.NA, index=s.index, dtype="boolean")
    low_all = s.str.lower()
    out[low_all.isin(TRUE_TOKENS)] = True
    out[low_all.isin(FALSE_TOKENS)] = False
    return Parsed(out, "boolean", "boolean", description="Mapped yes/no, y/n, true/false and 1/0 to true/false")


# ------------------------------------------------------------------ dates

def _numeric_order(v: pd.Series) -> tuple[bool, bool]:
    parts = v.str.extract(NUMERIC_DMY_RE)
    a = pd.to_numeric(parts[0], errors="coerce")
    b = pd.to_numeric(parts[1], errors="coerce")
    return bool((a > 12).any()), bool((b > 12).any())


def parse_dates(key: str, s: pd.Series, date_order: str) -> Parsed | None:
    original = s
    s = s.str.replace(ORDINAL_RE, r"\1", regex=True)  # "7th Jan 2024" -> "7 Jan 2024"
    v = s.dropna()
    if v.empty:
        return None
    lower = v.str.lower()
    date_like = lower.str.fullmatch(DATE_LIKE_RE)
    serial_like = v.str.fullmatch(r"\d{5}(?:\.\d+)?") & pd.to_numeric(v, errors="coerce").between(20000, 80000)
    compact_like = v.str.fullmatch(r"(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])")
    name_hint = bool(DATE_NAME_RE.search(key))
    share_dates = date_like.mean()
    if not (share_dates >= 0.5 or (name_hint and (date_like | serial_like | compact_like).mean() >= 0.8)):
        return None
    # Excel serial numbers and 20240110-style values are only read as dates inside a column that is clearly dates.
    allow_numeric_dates = name_hint or (date_like | serial_like | compact_like).mean() >= 0.8

    warnings: list[str] = []
    dmy_evidence, mdy_evidence = _numeric_order(v[date_like])
    has_numeric_ambiguous = v[date_like].str.match(NUMERIC_DMY_RE).any()
    if dmy_evidence and mdy_evidence:
        order = date_order
        warnings.append(f"Mixed day-first and month-first dates; used {order} (dataset option). Values that do not fit became null.")
    elif dmy_evidence:
        order = "DMY"
    elif mdy_evidence:
        order = "MDY"
    else:
        order = date_order
        if has_numeric_ambiguous:
            warnings.append(f"Day and month order is ambiguous (no part above 12); assumed {order}. "
                            "Change the date order option if this is wrong.")

    result = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    formats = YMD_FORMATS + (DMY_FORMATS if order == "DMY" else MDY_FORMATS) + NAMED_FORMATS
    if allow_numeric_dates:
        formats = formats + COMPACT_FORMATS
    for fmt in formats:
        todo = result.isna() & s.notna()
        if not todo.any():
            break
        subset = s[todo]
        if fmt == "ISO8601":
            # Values with a UTC offset ("Z", "+05:30") are converted to UTC; values without one are kept as written.
            parsed = pd.to_datetime(subset, format=fmt, errors="coerce", utc=True).dt.tz_localize(None)
            n_tz = int(subset.str.contains(r"\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?\s*(?:[zZ]|[+-]\d{2}:?\d{2})$", regex=True).sum())
            if n_tz:
                warnings.append(f"{n_tz} value(s) had a time zone and were converted to UTC.")
        else:
            subset = subset.str.replace(r"(?i)\bsept\b", "Sep", regex=True)
            parsed = pd.to_datetime(subset, format=fmt, errors="coerce")
        result.loc[todo] = parsed
    todo = result.isna() & s.notna()
    # 2024-13-01: a year-first date whose middle part cannot be a month was written year-day-month.
    ydm = todo & s.str.fullmatch(r"\d{4}[-/.](1[3-9]|2\d|3[01])[-/.](0?[1-9]|1[0-2])").fillna(False)
    if ydm.any():
        fixed = pd.to_datetime(s[ydm].str.replace(r"[/.]", "-", regex=True), format="%Y-%d-%m", errors="coerce")
        result.loc[ydm] = fixed
        if fixed.notna().any():
            warnings.append(f"Read {int(fixed.notna().sum())} value(s) such as {s[ydm].iloc[0]} as year-day-month (the middle number is above 12).")
    todo = result.isna() & s.notna()
    if todo.any() and allow_numeric_dates:
        nums = pd.to_numeric(s[todo], errors="coerce")
        ok = nums.between(20000, 80000)
        if ok.any():
            result.loc[nums[ok].index] = EXCEL_EPOCH + pd.to_timedelta(nums[ok], unit="D")
            warnings.append(f"Converted {int(ok.sum())} Excel serial date number(s) to dates.")

    failures = result.isna() & s.notna()
    if too_many_failures(int(failures.sum()), len(v)):
        return Parsed(original, "string", "text",
                      warnings=[f"{int(failures.sum())} of {len(v)} values could not be read as dates "
                                f"(examples: {', '.join(_examples(original[failures], 3))}); column kept as text."],
                      meta={"flagged": True})
    present = result.dropna()
    has_time = bool((present != present.dt.normalize()).any())
    dtype = "datetime" if has_time else "date"
    if not has_time:
        result = result.dt.normalize()
    return Parsed(result, dtype, "date", failures=failures, warnings=warnings, meta={"date_order": order},
                  description=f"Parsed dates ({order if has_numeric_ambiguous or dmy_evidence or mdy_evidence else 'ISO/named'})")


# ------------------------------------------------------------------ numbers

def _strip_number_text(v: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """Return (body, negative mask, percent mask, currency symbol per value)."""
    x = v.str.replace(" ", " ", regex=False)
    symbol = x.str.extract(r"([$€£₹₨¥])", expand=False)
    code = x.str.extract(rf"(?i)^({CURRENCY_CODE_RE})\s*|\s*({CURRENCY_CODE_RE})$")
    code = code[0].fillna(code[1]).str.upper().str.replace("RS.", "INR", regex=False).str.replace("RS", "INR", regex=False)
    symbol = symbol.map(CURRENCY_SYMBOLS).fillna(code)
    x = x.str.replace(rf"(?i)^{CURRENCY_CODE_RE}\s*|\s*{CURRENCY_CODE_RE}$", "", regex=True)
    x = x.str.replace(r"[$€£₹₨¥\s]", "", regex=True)
    pct = x.str.endswith("%")
    x = x.str.replace("%", "", regex=False)
    paren = x.str.fullmatch(r"\(.*\)")
    x = x.where(~paren, x.str.slice(1, -1))
    trail = x.str.endswith("-") & ~x.str.startswith("-")
    x = x.where(~trail, x.str.slice(0, -1))
    lead_minus = x.str.startswith("-")
    x = x.str.lstrip("+-")
    negative = paren | trail | lead_minus
    return x, negative, pct, symbol


def _separator_votes(body: pd.Series) -> tuple[int, int, bool]:
    """Count values that unambiguously use '.' (US) or ',' (EU) as decimal separator."""
    has_dot = body.str.contains(".", regex=False)
    has_comma = body.str.contains(",", regex=False)
    both = has_dot & has_comma
    last_dot = body.str.rfind(".") > body.str.rfind(",")
    us = both & last_dot
    eu = both & ~last_dot
    only_dot = has_dot & ~has_comma
    only_comma = has_comma & ~has_dot
    multi_dot = body.str.count(r"\.") > 1
    multi_comma = body.str.count(",") > 1
    after_dot = body.str.len() - body.str.rfind(".") - 1
    after_comma = body.str.len() - body.str.rfind(",") - 1
    lead_dot = body.str.find(".")
    lead_comma = body.str.find(",")
    us |= only_dot & ~multi_dot & ((after_dot != 3) | (lead_dot > 3) | body.str.startswith("0."))
    eu |= only_dot & multi_dot
    eu |= only_comma & ~multi_comma & ((after_comma != 3) | (lead_comma > 3) | body.str.startswith("0,"))
    us |= only_comma & multi_comma
    ambiguous = ((only_dot & ~multi_dot) | (only_comma & ~multi_comma)) & ~us & ~eu
    return int(us.sum()), int(eu.sum()), bool(ambiguous.any())


def number_convention(s: pd.Series) -> str | None:
    """'.' / ',' when the column settles the decimal separator, 'conflict', or None if undecided."""
    v = s.dropna()
    if v.empty:
        return None
    body, *_ = _strip_number_text(v)
    body = body[body.str.fullmatch(r"[\d.,]+")]
    us, eu, _ = _separator_votes(body)
    if us and eu:
        return "conflict"
    return "." if us else "," if eu else None



# ------------------------------------------------------------------ number pre-processing
# Units, magnitudes, scientific notation and "3/5" scores are turned into plain numbers before parsing.

MAGNITUDE_UNITS = {"k": 10**3, "thousand": 10**3, "m": 10**6, "mn": 10**6, "mio": 10**6, "million": 10**6,
                   "b": 10**9, "bn": 10**9, "billion": 10**9, "lakh": 10**5, "lakhs": 10**5, "lac": 10**5, "lacs": 10**5,
                   "cr": 10**7, "crore": 10**7, "crores": 10**7}
_LB = Fraction(45359237, 100000)
_IN = Fraction(254, 10000)
UNIT_FAMILIES = {
    "mass": {"mg": Fraction(1, 1000), "g": 1, "gm": 1, "gms": 1, "gram": 1, "grams": 1, "kg": 1000, "kgs": 1000,
             "kilo": 1000, "kilos": 1000, "kilogram": 1000, "kilograms": 1000, "lb": _LB, "lbs": _LB, "pound": _LB, "pounds": _LB,
             "oz": Fraction(28349523125, 10**9), "ton": 10**6, "tons": 10**6, "tonne": 10**6, "tonnes": 10**6},
    "length": {"mm": Fraction(1, 1000), "cm": Fraction(1, 100), "m": 1, "mtr": 1, "km": 1000, "in": _IN, "inch": _IN, "inches": _IN,
               "ft": Fraction(3048, 10000), "feet": Fraction(3048, 10000), "mi": Fraction(1609344, 1000), "miles": Fraction(1609344, 1000)},
    "volume": {"ml": Fraction(1, 1000), "l": 1, "ltr": 1, "ltrs": 1, "litre": 1, "litres": 1, "liter": 1, "liters": 1},
    "duration": {"sec": Fraction(1, 3600), "secs": Fraction(1, 3600), "min": Fraction(1, 60), "mins": Fraction(1, 60),
                 "minutes": Fraction(1, 60), "hr": 1, "hrs": 1, "hour": 1, "hours": 1, "day": 24, "days": 24},
    "count": {"pcs": 1, "pc": 1, "piece": 1, "pieces": 1, "unit": 1, "units": 1, "nos": 1, "item": 1, "items": 1,
              "star": 1, "stars": 1, "pax": 1, "people": 1},
}
LENGTH_NAME_RE = re.compile(r"(^|_)(length|height|width|depth|distance|size|dist)($|_)")
UNIT_SPLIT_RE = r"^(?P<num>[^A-Za-z]*\d[^A-Za-z]*?)\s*(?P<unit>[A-Za-z]+)\.?$"
SCI_RE = r"[-+]?\d+(?:\.\d+)?[eE][-+]?\d+"
FRACTION_RE = r"^(\d+(?:\.\d+)?)\s*/\s*(\d+)$"
NAME_CURRENCY = {"usd": "USD", "dollar": "USD", "dollars": "USD", "eur": "EUR", "euro": "EUR", "euros": "EUR",
                 "gbp": "GBP", "inr": "INR", "rs": "INR", "rupee": "INR", "rupees": "INR", "jpy": "JPY", "yen": "JPY"}


@dataclass
class _Pre:
    text: pd.Series                       # cleaned text, same index as the input
    factor: pd.Series | None = None       # Fraction per value (multiply after parsing), None when all 1
    unit: str | None = None               # unit label for the column name ("kg"); None for counts/magnitudes
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _preprocess_numbers(key: str, s: pd.Series) -> _Pre:
    out = _Pre(s.copy())
    v = s.dropna()
    if v.empty:
        return out
    # 1.2E+05 -> 120000 (Excel shows large numbers this way)
    sci = v.str.fullmatch(SCI_RE)
    if sci.any():
        def plain(x):
            try:
                return format(Decimal(x), "f")
            except InvalidOperation:
                return x
        out.text.loc[v.index[sci]] = v[sci].map(plain)
        out.notes.append("scientific notation")
        v = out.text.dropna()
    # "3/5" scores: one shared denominator (5, 10 or 100) -> the score itself
    fr = v.str.extract(FRACTION_RE)
    is_fr = fr[0].notna()
    if is_fr.any():
        dens = set(fr.loc[is_fr, 1])
        if len(dens) == 1 and int(next(iter(dens))) in (5, 10, 100):
            out.text.loc[v.index[is_fr]] = fr.loc[is_fr, 0]
            out.warnings.append(f"Read scores like '{v[is_fr].iloc[0]}' as {fr.loc[is_fr, 0].iloc[0]} (out of {next(iter(dens))}).")
            v = out.text.dropna()
    # Units and magnitudes: 2 kg, 500 g, 3 pcs, 12k, 1.5 lakh
    m = v.str.extract(UNIT_SPLIT_RE)
    unit = m["unit"].str.lower()
    has = unit.notna()
    if not has.any():
        return out
    units = set(unit[has])
    as_length = bool(LENGTH_NAME_RE.search(key)) or bool(units & (set(UNIT_FAMILIES["length"]) - {"m"}))
    if units <= set(MAGNITUDE_UNITS) and not (as_length and units <= set(UNIT_FAMILIES["length"])):
        table, label, note = MAGNITUDE_UNITS, None, "magnitude suffixes (12k = 12000)"
        base = 1
    else:
        fam = next((f for f, t in UNIT_FAMILIES.items() if units <= set(t)), None)
        if fam is None:
            return out  # unknown or mixed kinds of units (e.g. kg and cm): leave for the text checks
        table = UNIT_FAMILIES[fam]
        counts = unit[has].value_counts()
        dominant = counts.index[0]
        base = Fraction(table[dominant])
        label = None if fam == "count" else dominant
        note = ("removed the word" + ("s " if len(units) > 1 else " ") + ", ".join(f"'{u}'" for u in sorted(units)) if fam == "count"
                else f"units converted to {dominant}" if len(units) > 1 else f"unit '{dominant}' moved to the column name")
    out.text.loc[v.index[has]] = m.loc[has, "num"].str.strip()
    factor = pd.Series(Fraction(1), index=s.index, dtype=object)
    factor.loc[v.index[has]] = [Fraction(table[u]) / base for u in unit[has]]
    out.factor = factor if any(f != 1 for f in factor) else None
    out.unit = label
    out.notes.append(note)
    return out


def _apply_factor(parsed: "Parsed", factor: pd.Series) -> "Parsed":
    vals = parsed.values
    idx = vals.index
    f = factor.reindex(idx)
    whole = all(x.denominator == 1 for x in f)
    if parsed.dtype == "decimal" and whole:
        parsed.values = (vals.astype("Int64") * pd.array([int(x) for x in f], dtype="Int64")).astype("Int64")
        return parsed
    if parsed.dtype == "integer" and whole:
        parsed.values = (vals.astype("Int64") * pd.array([int(x) for x in f], dtype="Int64")).astype("Int64")
        return parsed
    if parsed.dtype == "decimal":
        scale = parsed.meta.get("scale", 2)
        parsed.values = pd.Series(vals.astype("Float64").to_numpy(dtype="float64", na_value=np.nan) / 10**scale, index=idx)
        parsed.dtype, parsed.semantic = "float", "numeric"
        parsed.meta.pop("scale", None)
    out = vals.astype("float64") if parsed.dtype != "integer" else vals.astype("Float64").to_numpy(dtype="float64", na_value=np.nan)
    out = pd.Series(np.asarray(out, dtype="float64") * np.array([float(x) for x in f]), index=idx).round(9)
    parsed.values = out
    parsed.dtype = "float"
    return parsed


def parse_numbers(key: str, s: pd.Series, decimal_sep: str | None, dataset_sep: str | None) -> Parsed | None:
    pre = _preprocess_numbers(key, s)
    parsed = _parse_number_core(key, pre.text, decimal_sep, dataset_sep)
    if parsed is None or parsed.dtype == "string":
        if parsed is not None and parsed.values is pre.text:
            parsed.values = s  # keep the original text when the column stays text
        return parsed
    if pre.factor is not None and parsed.semantic != "percent":
        parsed = _apply_factor(parsed, pre.factor)
    if pre.unit and parsed.semantic != "percent":
        parsed.meta["unit"] = pre.unit
    parsed.warnings = pre.warnings + parsed.warnings
    if pre.notes:
        extra = ", ".join(pre.notes)
        parsed.description = f"{parsed.description} ({extra})" if "(" not in parsed.description else parsed.description[:-1] + f", {extra})"
    return parsed


def _parse_number_core(key: str, s: pd.Series, decimal_sep: str | None, dataset_sep: str | None) -> Parsed | None:
    v = s.dropna()
    if v.empty:
        return None
    body, negative, pct, symbol = _strip_number_text(v)
    shape_ok = body.str.fullmatch(r"\d[\d.,]*|\.\d+")
    if shape_ok.mean() < 0.5:
        return None

    warnings: list[str] = []
    us, eu, ambiguous = _separator_votes(body[shape_ok])
    syms = set(symbol.dropna().unique())
    if decimal_sep in (".", ","):
        sep = decimal_sep
    elif us and eu:
        return Parsed(s, "string", "text", meta={"flagged": True},
                      warnings=["Values use both 1,234.56 and 1.234,56 styles; column kept as text. "
                                "Set the decimal separator option to convert it."])
    elif us or eu:
        sep = "." if us else ","
    elif ambiguous:
        if dataset_sep in (".", ","):
            sep = dataset_sep
            warnings.append(f"Separator was ambiguous in this column; used '{sep}' as decimal separator, as in other columns.")
        elif syms and syms <= {"USD", "GBP", "INR", "JPY"}:
            sep = "."
            warnings.append("Separator was ambiguous; used '.' as decimal separator based on the currency symbol.")
        else:
            return Parsed(s, "string", "text", meta={"flagged": True},
                          warnings=["Cannot tell whether ',' or '.' is the decimal separator (for example '1,234'); "
                                    "column kept as text. Set the decimal separator option to convert it."])
    else:
        sep = "."

    if sep == ".":
        norm = body.str.replace(",", "", regex=False)
    else:
        norm = body.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    valid = norm.str.fullmatch(r"\d+(?:\.\d+)?|\.\d+") & shape_ok
    fail_count = int((~valid).sum())
    if too_many_failures(fail_count, len(v)):
        return Parsed(s, "string", "text", meta={"flagged": fail_count < 0.5 * len(v)},
                      warnings=([f"{fail_count} of {len(v)} values are not numbers (examples: "
                                 f"{', '.join(_examples(v[~valid], 3))}); column kept as text."]
                                if fail_count < 0.5 * len(v) else []))

    norm = norm.where(valid)
    norm = norm.where(~norm.str.startswith(".", na=False), "0" + norm)
    failures = pd.Series(False, index=s.index)
    failures.loc[v.index[~valid.to_numpy()]] = True

    is_percent = pct.mean() >= 0.5
    is_currency = (not is_percent) and (symbol.notna().mean() >= 0.5 or bool(MONEY_NAME_RE.search(key)))
    bare_ratio = pd.Series(False, index=v.index)
    if is_percent and not pct.all():
        nums_all = pd.to_numeric(norm, errors="coerce")
        bare = ~pct & nums_all.notna()
        if bare.any() and (nums_all[bare] <= 1).all() and nums_all[pct].median() > 1:
            bare_ratio = bare
            warnings.append("Values without a % sign were already ratios (0.15 = 15%); values with % were divided by 100.")
        else:
            warnings.append("Some values had a % sign and some did not; all were treated as percentages.")
    if is_currency and len(syms) > 1:
        return Parsed(s, "string", "text", meta={"flagged": True},
                      warnings=[f"Mixed currencies ({', '.join(sorted(syms))}) cannot be added together; column kept as text."])

    has_decimal = norm.str.contains(".", regex=False).fillna(False)
    sign = np.where(negative.reindex(norm.index).fillna(False).to_numpy(), -1, 1)
    conversions = []
    if sep == "," and (eu or decimal_sep == ","):
        conversions.append("decimal comma")
    if symbol.notna().any():
        conversions.append("currency symbols")
    if body.str.contains(",|\\.(?=\\d{3})", regex=True).any():
        conversions.append("thousands separators")
    if negative.any():
        conversions.append("negative formats")

    if is_currency:
        parts = norm.str.extract(r"^(\d+)(?:\.(\d+))?$")
        frac = parts[1].fillna("")
        scale = int(min(6, max(2, frac.str.len().max() if frac.notna().any() else 2)))
        if parts[0].str.len().max() + scale > 18:
            return Parsed(s, "string", "text", meta={"flagged": True},
                          warnings=["Money values are too large to store exactly; column kept as text."])
        minor_txt = parts[0] + frac.str.pad(scale, side="right", fillchar="0")
        minor = pd.to_numeric(minor_txt, errors="coerce", dtype_backend="numpy_nullable").astype("Int64") * sign
        out = pd.Series(pd.NA, index=s.index, dtype="Int64")
        out.loc[minor.index] = minor
        code = next(iter(syms)) if syms else next((NAME_CURRENCY[t] for t in key.split("_") if t in NAME_CURRENCY), None)
        return Parsed(out, "decimal", "currency", failures=failures, warnings=warnings,
                      meta={"scale": scale, "currency": code},
                      description="Converted money text to exact decimal" + (f" ({', '.join(conversions)})" if conversions else ""))

    nums = pd.to_numeric(norm, errors="coerce", dtype_backend="numpy_nullable")
    if is_percent:
        out = pd.Series(np.nan, index=s.index, dtype="float64")
        ratio = (nums.astype("float64") * sign) / 100.0
        ratio[bare_ratio.reindex(nums.index).fillna(False).to_numpy()] *= 100.0
        out.loc[nums.index] = ratio
        return Parsed(out, "float", "percent", failures=failures, warnings=warnings,
                      description="Converted percentages to ratios (45% -> 0.45)")
    if not has_decimal.any():
        out = pd.Series(pd.NA, index=s.index, dtype="Int64")
        out.loc[nums.index] = nums.astype("Int64") * sign
        return Parsed(out, "integer", "numeric", failures=failures, warnings=warnings,
                      description="Converted to integers" + (f" ({', '.join(conversions)})" if conversions else ""))
    out = pd.Series(np.nan, index=s.index, dtype="float64")
    out.loc[nums.index] = nums.astype("float64") * sign
    return Parsed(out, "float", "numeric", failures=failures, warnings=warnings,
                  description="Converted to decimal numbers" + (f" ({', '.join(conversions)})" if conversions else ""))


# ------------------------------------------------------------------ canonical text (for change tracking)

def minor_to_text(minor: pd.Series, scale: int) -> pd.Series:
    """Exact decimal text from Int64 minor units, e.g. -123450 (scale 2) -> '-1234.50'."""
    m = minor.astype("Int64")
    neg = m < 0
    a = m.abs()
    base = 10 ** scale
    whole = (a // base).astype("string")
    frac = (a % base).astype("string").str.zfill(scale)
    txt = whole + "." + frac if scale else whole
    return txt.where(~neg.fillna(False), "-" + txt)


def canonical_text(values: pd.Series, dtype: str, meta: dict) -> pd.Series:
    """The text form a cleaned value would have; used to count changed cells and for idempotence."""
    if dtype == "decimal":
        return minor_to_text(values, meta.get("scale", 2))
    if dtype == "integer":
        return values.astype("Int64").astype("string")
    if dtype == "float":
        return values.astype("float64").map(lambda x: None if x != x else repr(float(x))).astype("string")
    if dtype == "date":
        return values.dt.strftime("%Y-%m-%d").astype("string")
    if dtype == "datetime":
        return values.dt.strftime("%Y-%m-%d %H:%M:%S").astype("string")
    if dtype == "boolean":
        return values.map({True: "true", False: "false"}).astype("string")
    return values.astype("string")
