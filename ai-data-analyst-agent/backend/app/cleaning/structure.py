"""Tier 1 structure and text steps: merged cells, empty rows/columns, header detection, footers,
column names and text normalization. Operates on the raw all-text grid."""
from __future__ import annotations

import math
import re
import unicodedata

import pandas as pd

from app.cleaning.parsing import DATE_LIKE_RE

DEFAULT_NULL_TOKENS = ["", "n/a", "na", "null", "none", "nan", "-", "--", "?", "#n/a", "#ref!", "#div/0!",
                       "#value!", "#null!", "#num!", "#name?"]
NONPRINT_RE = r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏‪-‮⁠-⁤﻿­]"
NUMBERISH_RE = r"^[\s$€£₹₨¥(+\-]*\d[\d.,\s]*%?\)?-?$"


def normalize_text(s: pd.Series) -> pd.Series:
    """NFKC, remove non-printing characters, collapse whitespace, trim. Empty -> null."""
    t = s.astype("str")
    t = t.str.normalize("NFKC")
    t = t.str.replace(NONPRINT_RE, "", regex=True)
    t = t.str.replace(r"\s+", " ", regex=True).str.strip()
    return t.where(t != "")


def fill_merged(grid: pd.DataFrame, merged: list) -> tuple[pd.DataFrame, int]:
    """Copy each merged range's top-left value into every cell of the range."""
    if not merged:
        return grid, 0
    g = grid.copy()
    filled = 0
    nrows, ncols = g.shape
    for r1, c1, r2, c2 in merged:
        if r1 >= nrows or c1 >= ncols:
            continue
        r2, c2 = min(r2, nrows - 1), min(c2, ncols - 1)
        value = g.iat[r1, c1]
        if value is None or (isinstance(value, float) and math.isnan(value)):
            continue
        block = g.iloc[r1:r2 + 1, c1:c2 + 1]
        filled += int(block.isna().sum().sum())
        g.iloc[r1:r2 + 1, c1:c2 + 1] = value
    return g, filled


def _row_profile(row: pd.Series, years_as_text: bool = False) -> tuple[int, float]:
    vals = row.dropna()
    if vals.empty:
        return 0, 0.0
    low = vals.str.lower()
    textual = ~(vals.str.fullmatch(NUMBERISH_RE) | low.str.fullmatch(DATE_LIKE_RE))
    if years_as_text:
        textual |= vals.str.fullmatch(r"(19|20)\d{2}")
    return len(vals), float(textual.mean())


def detect_header(grid: pd.DataFrame, merged_rows: set[int], header_row: int | None) -> tuple[int | None, int, list[str]]:
    """Return (header position or None, number of header rows, notes). Positions index `grid` rows."""
    notes: list[str] = []
    if header_row is not None:
        pos = header_row - 1
        if not 0 <= pos < len(grid):
            raise ValueError(f"Header row {header_row} is outside the sheet (1-{len(grid)}).")
        return pos, 1, [f"Header row {header_row} chosen by option."]
    sample = grid.head(30)
    profiles = [_row_profile(sample.iloc[i]) for i in range(len(sample))]
    max_nn = max((p[0] for p in profiles), default=0)
    need = max(1 if max_nn == 1 else 2, math.ceil(0.6 * max_nn))
    header = None
    for i, (nn, text_share) in enumerate(profiles):
        if nn >= need and text_share < 0.6 and i + 1 < len(sample):
            # Period headers such as "Region, 2021, 2022": years count as labels if the next row is data.
            ts_years = _row_profile(sample.iloc[i], years_as_text=True)[1]
            if ts_years >= 0.6 and profiles[i + 1][1] < ts_years - 0.3:
                text_share = ts_years
        if nn >= need and text_share >= 0.6:
            row_vals = sample.iloc[i].dropna()
            if row_vals.nunique() >= 0.8 * len(row_vals):
                header = i
                break
        if nn >= need and text_share < 0.6:
            break  # reached data before any header-like row
    if header is None:
        notes.append("No header row found; generated column names.")
        return None, 0, notes
    n_rows = 1
    if header + 2 < len(sample):
        nn1, ts1 = profiles[header + 1]
        _, ts2 = profiles[header + 2]
        nn0 = profiles[header][0]
        if nn1 >= need and ts1 >= 0.8 and ts2 < ts1 - 0.3 and (header in merged_rows or nn0 < nn1):
            n_rows = 2
            notes.append("Two header rows were combined into one.")
    return header, n_rows, notes


def build_names(grid: pd.DataFrame, header: int | None, n_rows: int) -> list[str]:
    ncols = grid.shape[1]
    if header is None:
        return [f"Column {i + 1}" for i in range(ncols)]
    top = normalize_text(grid.iloc[header])
    if n_rows == 1:
        return [v if isinstance(v, str) else "" for v in top]
    top = top.ffill()  # a group label spans the columns to its right
    sub = normalize_text(grid.iloc[header + 1])
    out = []
    for a, b in zip(top, sub):
        a = a if isinstance(a, str) else ""
        b = b if isinstance(b, str) else ""
        out.append(f"{a} {b}".strip() if a and b and a != b else (a or b))
    return out


def snake_key(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()
    if s and s[0].isdigit():
        s = f"c_{s}"
    return s


def finalize_names(raw_names: list[str]) -> list[dict]:
    """Display names (deduped as name, name_2) and stable unique snake_case keys."""
    seen_display: dict[str, int] = {}
    seen_keys: set[str] = {"_source_row"}
    out = []
    for i, n in enumerate(raw_names):
        original = n
        display = re.sub(r"\s+", " ", (n or "").replace("﻿", "")).strip() or f"Column {i + 1}"
        cnt = seen_display.get(display.lower(), 0) + 1
        seen_display[display.lower()] = cnt
        if cnt > 1:
            display = f"{display}_{cnt}"
        key = snake_key(display) or f"column_{i + 1}"
        base, k = key, 2
        while key in seen_keys:
            key = f"{base}_{k}"
            k += 1
        seen_keys.add(key)
        out.append({"key": key, "original_name": original or "", "display_name": display})
    return out


def trailing_note_rows(data: pd.DataFrame) -> list:
    """Index labels of trailing rows holding a single text cell (notes/footers) in a wide table."""
    if data.shape[1] < 3 or data.empty:
        return []
    nn = data.notna().sum(axis=1)
    drop = []
    for label in reversed(data.index.tolist()):
        if nn[label] == 1:
            drop.append(label)
        elif nn[label] == 0:
            continue
        else:
            break
    return drop[::-1]
