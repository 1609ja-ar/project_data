"""Text standardisation steps that run after type detection: broken encodings, emails, phone numbers,
person names and consistent casing of categories.

Each function returns the new values plus a mask of the cells it changed, so the pipeline can report
exactly what happened. Nothing here removes a value; invalid emails or phone numbers are only flagged.
"""
from __future__ import annotations

import re

import pandas as pd

# Typical UTF-8 text that was decoded as Windows-1252 ("CafÃ©", "â‚¹", "Ã¼").
MOJIBAKE_RE = r"Ã.|Â.|â[\u0080-⃿]"
EMAIL_RE = r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"
EMAIL_ISH_RE = r"[^\s@]*@+[^\s@]*"
EMAIL_NAME_RE = re.compile(r"(^|_)(e_?mail|email_address|mail)($|_)")
PHONE_NAME_RE = re.compile(r"(^|_)(phone|mobile|mob|tel|telephone|contact_no|contact_number|cell|whatsapp)($|_)")
PHONE_ISH_RE = r"\+?[\d\s().\-/]{7,22}"
PERSON_NAME_RE = re.compile(r"(^|_)(name|first_name|last_name|full_name|surname|customer|client|contact|owner|employee|"
                            r"manager|agent|person|student|patient|rep|salesperson)($|_)")


def _repair(text: str) -> str:
    try:
        fixed = text.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    return fixed if len(fixed) < len(text) else text


def fix_mojibake(s: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Repairs text decoded with the wrong encoding. Runs on the raw text, before any other normalisation."""
    t = s.astype("string")
    hit = t.str.contains(MOJIBAKE_RE, regex=True, na=False)
    if not hit.any():
        return s, hit
    fixed = t[hit].map(_repair)
    changed = pd.Series(False, index=s.index)
    changed.loc[fixed.index] = fixed != t[hit]
    out = s.copy()
    out.loc[changed[changed].index] = fixed[changed[changed].index]
    return out, changed


def is_email_column(key: str, s: pd.Series) -> bool:
    v = s.dropna()
    if v.empty:
        return False
    share = v.str.fullmatch(EMAIL_ISH_RE).mean()
    return share >= 0.9 or (bool(EMAIL_NAME_RE.search(key)) and share >= 0.6)


def standardize_emails(s: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Lower-case and trim; returns (values, changed mask, invalid mask). Invalid addresses are kept, not removed."""
    v = s.dropna()
    low = v.str.lower().str.replace(r"\s+", "", regex=True).str.replace(r"^mailto:", "", regex=True)
    changed = pd.Series(False, index=s.index)
    changed.loc[v.index] = low != v
    out = s.copy()
    out.loc[v.index] = low
    invalid = pd.Series(False, index=s.index)
    invalid.loc[v.index] = ~low.str.fullmatch(EMAIL_RE)
    return out, changed, invalid


def is_phone_column(key: str, s: pd.Series) -> bool:
    v = s.dropna()
    if v.empty:
        return False
    digits = v.str.count(r"\d")
    phoneish = v.str.fullmatch(PHONE_ISH_RE) & digits.between(7, 15)
    return bool(PHONE_NAME_RE.search(key)) and phoneish.mean() >= 0.6


def standardize_phones(s: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Keeps a leading + and the digits ("+91 98765-43210" -> "+919876543210"); flags numbers with fewer than 7
    or more than 15 digits. The country code is not guessed."""
    v = s.dropna()
    plus = v.str.startswith("+") | v.str.startswith("00")
    digits = v.str.replace(r"\D", "", regex=True)
    digits = digits.where(~v.str.startswith("00"), digits.str.slice(2))
    norm = digits.where(~plus, "+" + digits)
    ok = v.str.fullmatch(PHONE_ISH_RE) & digits.str.len().between(7, 15)
    norm = norm.where(ok, v)  # values that are not phone numbers stay as written
    changed = pd.Series(False, index=s.index)
    changed.loc[v.index] = norm != v
    out = s.copy()
    out.loc[v.index] = norm
    invalid = pd.Series(False, index=s.index)
    invalid.loc[v.index] = ~ok
    return out, changed, invalid


def _proper_word(w: str) -> str:
    if len(w) <= 1 or not (w.islower() or w.isupper()):
        return w
    # o'brien -> O'Brien, anne-marie -> Anne-Marie
    return re.sub(r"[A-Za-z]+", lambda m: m.group(0).capitalize(), w)


def is_person_name_column(key: str, s: pd.Series) -> bool:
    v = s.dropna()
    if v.empty or not PERSON_NAME_RE.search(key):
        return False
    return v.str.fullmatch(r"[^\d@]+").mean() >= 0.9


def standardize_person_names(s: pd.Series) -> tuple[pd.Series, pd.Series]:
    """'john SMITH' -> 'John Smith'. Words already in mixed case (McDonald, DeSouza) are left alone."""
    v = s.dropna()
    fixed = v.map(lambda x: " ".join(_proper_word(w) for w in x.split(" ")))
    changed = pd.Series(False, index=s.index)
    changed.loc[v.index] = fixed != v
    out = s.copy()
    out.loc[v.index] = fixed
    return out, changed


def standardize_category_case(s: pd.Series) -> tuple[pd.Series, pd.Series]:
    """When at least half of the distinct labels are written in Title or mixed case, all-lower or ALL-CAPS labels
    are brought in line ('BOMBAY' -> 'Bombay', 'new delhi' -> 'New Delhi'). Codes of 3 letters or fewer ('USA', 'NY') are kept."""
    v = s.dropna()
    distinct = pd.Series(v.unique())
    if len(distinct) < 2:
        return s, pd.Series(False, index=s.index)
    lettered = distinct[distinct.str.contains(r"[A-Za-z]", regex=True)]
    if lettered.empty:
        return s, pd.Series(False, index=s.index)
    mixed = ~(lettered.str.lower() == lettered) & ~(lettered.str.upper() == lettered)
    if mixed.mean() < 0.5:
        return s, pd.Series(False, index=s.index)
    off = (v.str.lower() == v) | ((v.str.upper() == v) & (v.str.replace(r"[^A-Za-z]", "", regex=True).str.len() > 3))
    off &= v.str.contains(r"[A-Za-z]", regex=True) & ~v.str.contains(r"\d", regex=True)
    fixed = v[off].map(lambda x: " ".join(_proper_word(w) for w in x.split(" ")))
    changed = pd.Series(False, index=s.index)
    changed.loc[fixed.index] = fixed != v[off]
    out = s.copy()
    out.loc[fixed.index] = fixed
    return out, changed
