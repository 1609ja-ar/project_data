"""Tier 2 cleaning suggestions: judgment calls shown with their impact, applied only on request.

Applying suggestions creates a new `user_cleaned` version; earlier versions are never modified.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal
from difflib import SequenceMatcher

import numpy as np
import pandas as pd

from app.cleaning.parsing import MONEY_NAME_RE
from app.cleaning.profile import money_from_minor
from app.cleaning.structure import snake_key

NUMERIC = ("integer", "float", "decimal")
PERIOD_RE = re.compile(
    r"^(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?(?:[ _-]?\d{2,4})?"
    r"|(?:19|20)\d{2}(?:[-_/ ]?(?:0?[1-9]|1[0-2]|q[1-4]))?|q[1-4](?:[ _-]?(?:19|20)?\d{2})?)$", re.I)
NONNEG_NAME_RE = re.compile(r"(^|_)(qty|quantity|units|count|price|age|amount|stock|weight|height|distance)($|_)")
UNIT_RE = r"^-?\d+(?:\.\d+)?\s*(k|m|b|bn|kg|g|lb|lbs|km|cm|mm|ml|l)$"
MAGNITUDE = {"k": 1e3, "m": 1e6, "b": 1e9, "bn": 1e9}
ROLE_PATTERNS = {
    "revenue": r"(^|_)(revenue|sales|amount|total_amount|turnover|income)($|_)",
    "quantity": r"(^|_)(qty|quantity|units)($|_)",
    "price": r"(^|_)(price|unit_price)($|_)",
    "product": r"(^|_)(product|item|sku_name|product_name)($|_)",
    "category": r"(^|_)(category|segment|type|department)($|_)",
    "region": r"(^|_)(region|country|state|city|territory|market)($|_)",
    "customer": r"(^|_)(customer|client|buyer|account_name)($|_)",
    "order_id": r"(^|_)(order_id|invoice|invoice_id|transaction_id|order_no|order_number)($|_)",
}
MAX_SIMILARITY_VALUES = 300


def _money(minor_total, scale):
    return str(money_from_minor(int(minor_total), scale))


def _stats_text(s: pd.Series, col: dict) -> dict:
    present = s.dropna()
    if col["dtype"] == "decimal":
        scale = col.get("scale", 2)
        tot = int(present.astype("int64").sum()) if len(present) else 0
        mean = (money_from_minor(tot, scale) / len(present)) if len(present) else None
        return {"rows": int(len(present)), "total": _money(tot, scale),
                "mean": str(mean.quantize(Decimal(1).scaleb(-(scale + 2)))) if mean is not None else None}
    vals = present.astype("float64")
    out = {"rows": int(len(vals)), "mean": float(vals.mean()) if len(vals) else None}
    if col["semantic_type"] != "percent":  # a total of percentages has no meaning
        out["total"] = float(vals.sum()) if len(vals) else 0.0
    return out


def _fill_value(s: pd.Series, col: dict, option: str, constant=None):
    present = s.dropna()
    if option == "fill_median":
        if col["dtype"] == "decimal" or col["dtype"] == "integer":
            return int(present.astype("int64").quantile(0.5, interpolation="lower"))
        return float(present.median())
    if option == "fill_mean":
        if col["dtype"] in ("decimal", "integer"):
            return int(round(present.astype("int64").mean()))
        return float(present.mean())
    if option == "fill_mode":
        return present.mode().iloc[0] if len(present) else None
    if option == "fill_constant":
        return constant
    return None


def _date_cols(schema):
    return [c["key"] for c in schema if c["dtype"] in ("date", "datetime")]


def compute_suggestions(frame: pd.DataFrame, schema: list[dict], roles: dict | None = None) -> list[dict]:
    out: list[dict] = []
    n = len(frame)
    has_date = bool(_date_cols(schema))
    id_keys = [c["key"] for c in schema if c["semantic_type"] == "id"]
    for col in schema:
        key, s = col["key"], frame[col["key"]]
        missing = int(s.isna().sum())
        name = col["display_name"]

        # Fully null or near-constant columns
        if n and missing == n:
            out.append({"id": f"sparse:{key}", "type": "sparse_column", "columns": [key], "severity": "warning",
                        "title": f"'{name}' is completely empty",
                        "description": "This column has no values. Dropping it simplifies the dataset; keeping it changes nothing.",
                        "options": [{"value": "keep", "label": "Keep"}, {"value": "drop", "label": "Drop column"}], "default": "keep"})
            continue
        top_share = s.value_counts(normalize=True, dropna=False).iloc[0] if n else 0
        if n >= 20 and top_share >= 0.99:
            out.append({"id": f"sparse:{key}", "type": "sparse_column", "columns": [key], "severity": "info",
                        "title": f"'{name}' is nearly constant",
                        "description": f"{top_share:.1%} of rows have the same value, so it carries little information.",
                        "options": [{"value": "keep", "label": "Keep"}, {"value": "drop", "label": "Drop column"}], "default": "keep"})

        # Missing values
        if missing and col["semantic_type"] != "id":
            opts = [{"value": "leave", "label": "Leave empty (recommended)"}]
            impact = {"leave": _stats_text(s, col)} if col["dtype"] in NUMERIC else {}
            if col["dtype"] in NUMERIC:
                opts += [{"value": "fill_median", "label": "Fill with median"}, {"value": "fill_mean", "label": "Fill with mean"}]
                for o in ("fill_median", "fill_mean"):
                    impact[o] = _stats_text(s.fillna(_fill_value(s, col, o)), col)
            if col["dtype"] in ("string", "boolean"):
                opts.append({"value": "fill_mode", "label": "Fill with most common value"})
            opts.append({"value": "fill_constant", "label": "Fill with a constant", "needs": "constant"})
            if has_date:
                opts.append({"value": "ffill", "label": "Carry previous value forward (time series)"})
            opts.append({"value": "drop_rows", "label": "Drop rows with empty values"})
            if col["dtype"] in NUMERIC:
                impact["drop_rows"] = {"rows_dropped": missing}
            out.append({
                "id": f"missing:{key}", "type": "missing_values", "columns": [key], "severity": "warning" if missing / n > 0.2 else "info",
                "title": f"{missing:,} empty value(s) in '{name}' ({missing / n:.1%})",
                "description": "Empty values are skipped in calculations. Filling them changes averages and totals and can bias results "
                               "(for example, mean-filling shrinks variation); dropping rows removes their other values too.",
                "options": opts, "default": "leave", "impact": impact})

        # Outliers (IQR screening)
        if col["dtype"] in NUMERIC and col["semantic_type"] != "percent" and s.notna().sum() >= 8:
            vals = s.dropna().astype("float64") / (10 ** col.get("scale", 0) if col["dtype"] == "decimal" else 1)
            q1, q3 = vals.quantile(0.25), vals.quantile(0.75)
            iqr = q3 - q1
            lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            outl = (vals < lo) | (vals > hi)
            if iqr > 0 and outl.any():
                capped = vals.clip(lo, hi)
                out.append({
                    "id": f"outliers:{key}", "type": "outliers", "columns": [key], "severity": "info",
                    "title": f"{int(outl.sum())} possible outlier(s) in '{name}' (screening)",
                    "description": f"Values outside {lo:,.4g} to {hi:,.4g} (1.5 x IQR). This is a screening rule, not proof of an error.",
                    "options": [{"value": "flag", "label": "Keep and flag (no change)"}, {"value": "cap", "label": "Cap to the bounds (winsorize)"},
                                {"value": "exclude", "label": "Exclude these rows"}],
                    "default": "flag", "params": {"lower": float(lo), "upper": float(hi)},
                    "impact": {"flag": {"mean": float(vals.mean())}, "cap": {"mean": float(capped.mean())},
                               "exclude": {"mean": float(vals[~outl].mean()), "rows_dropped": int(outl.sum())}},
                    "examples": [f"{v:,.6g}" for v in vals[outl].head(5)]})

        # Impossible values
        if col["dtype"] in NUMERIC:
            vals = s.dropna()
            bad = pd.Series(False, index=vals.index)
            reason = []
            if NONNEG_NAME_RE.search(key) or col["semantic_type"] == "currency" and MONEY_NAME_RE.search(key) and "price" in key:
                neg = vals < 0
                if neg.any():
                    bad |= neg
                    reason.append("negative values")
            if re.search(r"(^|_)age($|_)", key):
                old = vals > 120
                if old.any():
                    bad |= old
                    reason.append("ages above 120")
            if col["semantic_type"] == "percent":
                over = vals > 1
                if over.any():
                    bad |= over
                    reason.append("percentages above 100%")
            if re.search(r"(^|_)(rating|ratings|stars|score_out_of_5)($|_)", key) and len(vals) >= 5:
                # Ratings on a 5-point scale (nearly all values 0-5) with a few values above 5.
                if (vals.between(0, 5)).mean() >= 0.85:
                    off = ~vals.between(0, 5)
                    if off.any():
                        bad |= off
                        reason.append("ratings outside 0-5")
            if bad.any():
                out.append({"id": f"impossible:{key}", "type": "impossible_values", "columns": [key], "severity": "warning",
                            "title": f"{int(bad.sum())} unlikely value(s) in '{name}': {', '.join(reason)}",
                            "description": "These values are unusual for this kind of column. Check whether they are errors (returns may be legitimately negative).",
                            "options": [{"value": "keep", "label": "Keep"}, {"value": "set_null", "label": "Set to empty"},
                                        {"value": "exclude", "label": "Exclude rows"}],
                            "default": "keep", "params": {"reason": reason}})
        if col["dtype"] in ("date", "datetime"):
            today = pd.Timestamp(datetime.now(timezone.utc).date())
            future = s > today + pd.Timedelta(days=1)
            if future.any():
                out.append({"id": f"impossible:{key}", "type": "impossible_values", "columns": [key], "severity": "warning",
                            "title": f"{int(future.sum())} future date(s) in '{name}'",
                            "description": "Historical data should not contain dates after today. Planned or scheduled dates can be valid.",
                            "options": [{"value": "keep", "label": "Keep"}, {"value": "set_null", "label": "Set to empty"},
                                        {"value": "exclude", "label": "Exclude rows"}],
                            "default": "keep", "params": {"reason": ["future dates"]}})
            # 1900-01-01, 1899-12-30/31 and earlier are what spreadsheets and databases store for "no date".
            placeholder = s < pd.Timestamp("1900-01-02")
            if placeholder.any():
                out.append({"id": f"placeholder_dates:{key}", "type": "impossible_values", "columns": [key], "severity": "warning",
                            "title": f"{int(placeholder.sum())} placeholder date(s) in '{name}' (1900 or earlier)",
                            "description": "Dates like 1900-01-01 are usually a stand-in for 'unknown'. Setting them to empty keeps them out of trends and averages.",
                            "options": [{"value": "keep", "label": "Keep"}, {"value": "set_null", "label": "Set to empty"},
                                        {"value": "exclude", "label": "Exclude rows"}],
                            "default": "set_null", "params": {"reason": ["placeholder dates"], "before": "1900-01-02"}})

        # Near-duplicate category spellings (OpenRefine-style clustering, edit-distance similarity)
        if col["dtype"] == "string" and col["semantic_type"] not in ("id", "email"):
            vc = s.value_counts()
            if 2 <= len(vc) <= 5000:
                top = vc.head(MAX_SIMILARITY_VALUES)
                values = list(top.index)
                mapping = {}
                for i, a in enumerate(values):
                    for b in values[i + 1:]:
                        if b in mapping or a in mapping:
                            continue
                        if SequenceMatcher(None, a.lower(), b.lower()).ratio() >= 0.9:
                            mapping[b] = a  # b is less frequent (value_counts is sorted)
                if mapping:
                    affected = int(s.isin(list(mapping)).sum())
                    out.append({"id": f"near_duplicates:{key}", "type": "near_duplicates", "columns": [key], "severity": "info",
                                "title": f"Similar spellings in '{name}'",
                                "description": "These values look like spelling variants. Edit the mapping and apply it to merge them.",
                                "options": [{"value": "keep", "label": "Keep as is"}, {"value": "merge", "label": "Merge using mapping"}],
                                "default": "keep", "params": {"mapping": mapping}, "impact": {"merge": {"rows_changed": affected}}})

        # Combined columns ("City, State")
        if col["dtype"] == "string" and s.notna().sum() >= 5:
            present = s.dropna()
            if present.str.fullmatch(r"[^,]+,\s*[^,]+").mean() >= 0.9:
                parts = present.head(5).str.split(r",\s*", n=1, regex=True, expand=True)
                out.append({"id": f"split:{key}", "type": "split_column", "columns": [key], "severity": "info",
                            "title": f"'{name}' combines two values",
                            "description": "Most values look like 'A, B'. Splitting gives one variable per column.",
                            "options": [{"value": "keep", "label": "Keep"}, {"value": "split", "label": "Split at the first comma"}],
                            "default": "keep",
                            "preview": {"columns": [f"{name} 1", f"{name} 2"], "rows": parts.fillna("").values.tolist()}})

        # Unit or magnitude suffixes
        if col["dtype"] == "string" and s.notna().sum() >= 3:
            low = s.dropna().str.lower().str.replace(" ", "", regex=False)
            m = low.str.extract(UNIT_RE)[0]
            if m.notna().mean() >= 0.9:
                units = sorted(set(m.dropna()))
                magnitude = set(units) <= set(MAGNITUDE)
                desc = ("Values use magnitude suffixes (" + ", ".join(units) + "); converting multiplies them out (1.2K = 1200)."
                        if magnitude else f"Values carry the unit '{units[0]}'; converting stores the number and adds the unit to the column name."
                        if len(units) == 1 else None)
                if desc:
                    out.append({"id": f"units:{key}", "type": "unit_suffix", "columns": [key], "severity": "info",
                                "title": f"'{name}' has unit suffixes", "description": desc,
                                "options": [{"value": "keep", "label": "Keep as text"}, {"value": "convert", "label": "Convert to numbers"}],
                                "default": "keep", "params": {"units": units, "magnitude": magnitude}})

    # Duplicate rows without an ID column
    data_cols = [c["key"] for c in schema]
    dup = frame[data_cols].duplicated(keep="first")
    if dup.any() and not id_keys:
        out.append({"id": "duplicates", "type": "duplicate_rows", "columns": [], "severity": "warning",
                    "title": f"{int(dup.sum())} identical row(s)",
                    "description": "Without an ID column these may be separate, genuine records (for example two identical purchases). "
                                   "Remove them only if you know they are duplicates.",
                    "options": [{"value": "keep", "label": "Keep"}, {"value": "remove", "label": "Remove duplicates (keep first)"}],
                    "default": "keep", "examples": [f"row {int(r)}" for r in frame.loc[dup, "_source_row"].head(5)]})

    # Wide format (one column per period)
    period_cols = [c for c in schema if PERIOD_RE.match(c["display_name"].strip()) and c["dtype"] in NUMERIC]
    if len(period_cols) >= 3:
        id_vars = [c["key"] for c in schema if c not in period_cols]
        sample = frame.head(2)
        rows = []
        for _, r in sample.iterrows():
            for pc_ in period_cols[:3]:
                v = r[pc_["key"]]
                rows.append([*(str(r[k]) for k in id_vars[:3]), pc_["display_name"], None if pd.isna(v) else str(v)])
        out.append({"id": "unpivot", "type": "wide_format", "columns": [c["key"] for c in period_cols], "severity": "info",
                    "title": f"{len(period_cols)} columns look like periods (wide format)",
                    "description": "Analysis is easier with one row per period. Unpivoting turns these columns into 'Period' and 'Value' columns.",
                    "options": [{"value": "keep", "label": "Keep wide"}, {"value": "unpivot", "label": "Unpivot to long format"}],
                    "default": "keep",
                    "preview": {"columns": [*(c["display_name"] for c in schema if c["key"] in id_vars[:3]), "Period", "Value"], "rows": rows}})

    # Column roles (used by business-metric helpers)
    suggested = {}
    for role, pat in ROLE_PATTERNS.items():
        for c in schema:
            if re.search(pat, c["key"]) and c["key"] not in suggested.values():
                if role in ("revenue", "price") and c["dtype"] not in NUMERIC:
                    continue
                if role == "quantity" and c["dtype"] not in ("integer", "float"):
                    continue
                suggested[role] = c["key"]
                break
    dates = _date_cols(schema)
    if dates:
        suggested["date"] = dates[0]
    if suggested and suggested != (roles or {}):
        out.append({"id": "roles", "type": "column_roles", "columns": list(suggested.values()), "severity": "info",
                    "title": "Confirm column roles",
                    "description": "Roles tell the business-metric helpers which column is revenue, date, product and so on. "
                                   "They are guesses from column names; edit them before applying.",
                    "options": [{"value": "keep", "label": "Not now"}, {"value": "apply", "label": "Use these roles"}],
                    "default": "keep", "params": {"mapping": suggested}})
    return out


# ------------------------------------------------------------------ applying

class SuggestionError(ValueError):
    pass


def apply_suggestions(frame: pd.DataFrame, schema: list[dict], suggestions: list[dict], selections: list[dict]):
    """Return (new_frame, new_column_meta, steps, roles_or_None). Never mutates the inputs."""
    by_id = {s["id"]: s for s in suggestions}
    df = frame.copy()
    cols = [dict(c) for c in schema]
    steps: list[dict] = []
    roles = None

    def col(key):
        for c in cols:
            if c["key"] == key:
                return c
        raise SuggestionError(f"Column {key} no longer exists")

    def step(name, desc, rows, column=None, examples=None):
        steps.append({"step": name, "column": column, "rows_affected": int(rows), "description": desc,
                      "examples": examples or [], "severity": "info"})

    for sel in selections:
        sug = by_id.get(sel.get("id"))
        if not sug:
            raise SuggestionError(f"Unknown suggestion '{sel.get('id')}'. Refresh the suggestions and try again.")
        option = sel.get("option")
        if option not in {o["value"] for o in sug["options"]}:
            raise SuggestionError(f"Option '{option}' is not valid for '{sug['title']}'.")
        params = {**sug.get("params", {}), **(sel.get("params") or {})}
        t = sug["type"]
        if option in ("keep", "leave", "flag"):
            continue
        if t == "column_roles":
            mapping = params.get("mapping") or {}
            known = {c["key"] for c in cols}
            roles = {r: k for r, k in mapping.items() if k in known and r in {*ROLE_PATTERNS, "date"}}
            continue
        if t == "duplicate_rows":
            dup = df[[c["key"] for c in cols]].duplicated(keep="first")
            df = df.loc[~dup]
            step("remove_duplicates", "Removed identical rows (kept the first).", dup.sum())
            continue
        if t == "wide_format":
            period_keys = [k for k in sug["columns"] if k in df.columns]
            id_vars = [c["key"] for c in cols if c["key"] not in period_keys] + ["_source_row"]
            labels = {c["key"]: c["display_name"] for c in cols}
            value_meta = col(period_keys[0])
            long = df.melt(id_vars=id_vars, value_vars=period_keys, var_name="period", value_name="value")
            long["period"] = long["period"].map(labels).astype("str")
            df = long
            cols = [c for c in cols if c["key"] not in period_keys]
            cols.append({"key": "period", "original_name": "", "display_name": "Period", "dtype": "string",
                         "semantic_type": "category", "source_col": None})
            vm = {k: value_meta.get(k) for k in ("dtype", "semantic_type", "scale", "currency")}
            cols.append({"key": "value", "original_name": "", "display_name": "Value", "source_col": None, **vm})
            step("unpivot", f"Unpivoted {len(period_keys)} period columns into Period and Value.", len(df))
            continue

        key = sug["columns"][0]
        c = col(key)
        s = df[key]
        if t == "sparse_column" and option == "drop":
            df = df.drop(columns=[key])
            cols = [x for x in cols if x["key"] != key]
            step("drop_column", f"Dropped column '{c['display_name']}'.", 0, c["display_name"])
        elif t == "missing_values":
            n_missing = int(s.isna().sum())
            if option == "drop_rows":
                df = df.loc[s.notna()]
                step("drop_missing", f"Dropped rows with empty '{c['display_name']}'.", n_missing, c["display_name"])
            elif option == "ffill":
                order = df.sort_values([_date_cols(cols)[0], "_source_row"]).index
                df.loc[order, key] = s.loc[order].ffill()
                step("fill_missing", "Carried the previous value forward (ordered by date).", n_missing, c["display_name"])
            else:
                value = _fill_value(s, c, option, params.get("constant"))
                if value is None or value == "":
                    raise SuggestionError("Enter a value to fill with.")
                value = _coerce_constant(value, c) if option == "fill_constant" else value
                df[key] = s.fillna(value)
                shown = _money(value, c.get("scale", 2)) if c["dtype"] == "decimal" and option != "fill_constant" else value
                step("fill_missing", f"Filled empty values using {option.replace('fill_', '')} ({shown}).", n_missing, c["display_name"])
        elif t == "outliers":
            scale = 10 ** c.get("scale", 0) if c["dtype"] == "decimal" else 1
            lo, hi = params["lower"] * scale, params["upper"] * scale
            mask = s.notna() & ((s < lo) | (s > hi))
            if option == "cap":
                if c["dtype"] in ("decimal", "integer"):
                    df[key] = s.clip(int(np.ceil(lo)), int(np.floor(hi)))
                else:
                    df[key] = s.clip(lo, hi)
                step("cap_outliers", "Capped values to the 1.5 x IQR bounds (winsorized).", mask.sum(), c["display_name"])
            elif option == "exclude":
                df = df.loc[~mask]
                step("exclude_outliers", "Excluded rows outside the 1.5 x IQR bounds.", mask.sum(), c["display_name"])
        elif t == "impossible_values":
            reason = params.get("reason", [])
            if c["dtype"] in ("date", "datetime"):
                if "placeholder dates" in reason:
                    mask = (s < pd.Timestamp(params.get("before", "1900-01-02"))).fillna(False)
                else:
                    mask = s > pd.Timestamp(datetime.now(timezone.utc).date()) + pd.Timedelta(days=1)
            else:
                mask = pd.Series(False, index=s.index)
                if "negative values" in reason:
                    mask |= s < 0
                if "ages above 120" in reason:
                    mask |= s > 120
                if "percentages above 100%" in reason:
                    mask |= s > 1
                if "ratings outside 0-5" in reason:
                    mask |= (s < 0) | (s > 5)
                mask = mask.fillna(False)
            if option == "set_null":
                df[key] = s.mask(mask)
                step("impossible_values", f"Set {', '.join(reason)} to empty.", mask.sum(), c["display_name"])
            elif option == "exclude":
                df = df.loc[~mask]
                step("impossible_values", f"Excluded rows with {', '.join(reason)}.", mask.sum(), c["display_name"])
        elif t == "near_duplicates" and option == "merge":
            mapping = {str(k): str(v) for k, v in (params.get("mapping") or {}).items() if str(k) != str(v)}
            hit = s.isin(list(mapping))
            df[key] = s.where(~hit, s.map(mapping))
            step("merge_spellings", "Merged similar spellings using the confirmed mapping.", hit.sum(), c["display_name"],
                 [f"'{a}' -> '{b}'" for a, b in list(mapping.items())[:5]])
        elif t == "split_column" and option == "split":
            parts = s.str.split(r",\s*", n=1, regex=True, expand=True)
            k1, k2 = _free_key(cols, f"{key}_1"), _free_key(cols, f"{key}_2")
            pos = df.columns.get_loc(key)
            df.insert(pos + 1, k1, parts[0].str.strip().astype("str"))
            df.insert(pos + 2, k2, (parts[1] if parts.shape[1] > 1 else pd.Series(None, index=df.index)).astype("str"))
            df = df.drop(columns=[key])
            i = cols.index(c)
            new = [{"key": k1, "original_name": "", "display_name": f"{c['display_name']} 1", "dtype": "string", "semantic_type": "category", "source_col": None},
                   {"key": k2, "original_name": "", "display_name": f"{c['display_name']} 2", "dtype": "string", "semantic_type": "category", "source_col": None}]
            cols = cols[:i] + new + cols[i + 1:]
            step("split_column", f"Split '{c['display_name']}' at the first comma.", s.notna().sum(), c["display_name"])
        elif t == "unit_suffix" and option == "convert":
            low = s.str.lower().str.replace(" ", "", regex=False)
            parts = low.str.extract(r"^(-?\d+(?:\.\d+)?)(k|m|b|bn|kg|g|lb|lbs|km|cm|mm|ml|l)$")
            num = pd.to_numeric(parts[0], errors="coerce")
            if params.get("magnitude"):
                num = num * parts[1].map(MAGNITUDE).astype("float64")
                c.update({"dtype": "float", "semantic_type": "numeric"})
                desc = "Multiplied out magnitude suffixes (K = thousand, M = million, B = billion)."
            else:
                unit = params["units"][0]
                c.update({"dtype": "float", "semantic_type": "numeric", "display_name": f"{c['display_name']} ({unit})"})
                desc = f"Removed the unit '{unit}' from values and added it to the column name."
            failed = int((s.notna() & num.isna()).sum())
            df[key] = num.astype("float64")
            c["invalid"] = failed
            step("convert_units", desc + (f" {failed} value(s) could not be converted and were set to empty." if failed else ""),
                 s.notna().sum(), c["display_name"])
    return df.reset_index(drop=True), cols, steps, roles


def _free_key(cols, key):
    keys = {c["key"] for c in cols}
    base, k, out = snake_key(key) or key, 2, snake_key(key) or key
    while out in keys:
        out = f"{base}_{k}"
        k += 1
    return out


def _coerce_constant(value, c):
    try:
        if c["dtype"] == "decimal":
            return int((Decimal(str(value)) * (10 ** c.get("scale", 2))).to_integral_exact())
        if c["dtype"] == "integer":
            return int(value)
        if c["dtype"] == "float":
            return float(value)
        if c["dtype"] == "boolean":
            return str(value).lower() in ("true", "yes", "1")
        if c["dtype"] in ("date", "datetime"):
            return pd.Timestamp(value)
    except Exception:  # noqa: BLE001 - user input
        raise SuggestionError(f"'{value}' is not a valid {c['dtype']} value for '{c['display_name']}'.")
    return str(value)
