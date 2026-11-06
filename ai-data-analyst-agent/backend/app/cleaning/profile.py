"""Column profiles for the data dictionary and the profiling strip (valid / error / empty + distribution)."""
from __future__ import annotations

from decimal import Decimal

import numpy as np
import pandas as pd

from app.cleaning.parsing import canonical_text


def money_from_minor(minor: int, scale: int) -> Decimal:
    return Decimal(int(minor)).scaleb(-scale)


def _num(x) -> float | None:
    if x is None or (isinstance(x, float) and np.isnan(x)) or x is pd.NA:
        return None
    return float(x)


def column_profile(s: pd.Series, col: dict) -> dict:
    n = len(s)
    present = s.dropna()
    missing = n - len(present)
    invalid = min(int(col.get("invalid", 0)), missing)
    out: dict = {
        "count": int(len(present)), "missing": int(missing), "unique": int(present.nunique()),
        "quality": {"valid": len(present) / n if n else 0.0, "error": invalid / n if n else 0.0,
                    "empty": (missing - invalid) / n if n else 0.0},
        "examples": [str(v) for v in canonical_text(present.drop_duplicates().head(5), col["dtype"], col).tolist()],
    }
    dtype = col["dtype"]
    if dtype in ("integer", "float", "decimal") and len(present):
        if dtype == "decimal":
            scale = col.get("scale", 2)
            ints = present.astype("int64")
            total = int(ints.sum())
            out["stats"] = {
                "sum": str(money_from_minor(total, scale)),
                "mean": str((money_from_minor(total, scale) / len(ints)).quantize(Decimal(1).scaleb(-(scale + 4)))),
                "min": str(money_from_minor(int(ints.min()), scale)), "max": str(money_from_minor(int(ints.max()), scale)),
                "median": str((Decimal(int(ints.quantile(0.5, interpolation="lower"))) + Decimal(int(ints.quantile(0.5, interpolation="higher")))).scaleb(-scale) / 2),
                "std": _num(ints.astype("float64").std() / (10 ** scale)) if len(ints) > 1 else None,
            }
            values = ints.astype("float64") / (10 ** scale)
        else:
            values = present.astype("float64")
            out["stats"] = {"sum": _num(values.sum()), "mean": _num(values.mean()), "median": _num(values.median()),
                            "min": _num(values.min()), "max": _num(values.max()),
                            "std": _num(values.std()) if len(values) > 1 else None,
                            "q1": _num(values.quantile(0.25)), "q3": _num(values.quantile(0.75))}
        counts, edges = np.histogram(values, bins=min(12, max(1, int(values.nunique()))))
        out["dist"] = {"kind": "histogram", "counts": counts.tolist(), "edges": [float(e) for e in edges]}
    elif dtype in ("date", "datetime") and len(present):
        out["stats"] = {"min": present.min().isoformat(), "max": present.max().isoformat()}
        span_days = (present.max() - present.min()).days
        freq = "YS" if span_days > 3 * 365 else "MS" if span_days > 90 else "D"
        counts = present.dt.to_period({"YS": "Y", "MS": "M", "D": "D"}[freq]).value_counts().sort_index()
        out["dist"] = {"kind": "timeline", "labels": [str(p) for p in counts.index[:60]], "counts": counts.to_numpy()[:60].tolist()}
    elif dtype == "boolean" and len(present):
        vc = present.value_counts()
        out["dist"] = {"kind": "top", "labels": [str(bool(k)).lower() for k in vc.index], "counts": vc.to_numpy().tolist()}
    elif len(present):
        vc = present.value_counts().head(8)
        out["dist"] = {"kind": "top", "labels": [str(k) for k in vc.index], "counts": vc.to_numpy().tolist(),
                       "other": int(len(present) - vc.sum())}
        lengths = present.astype("string").str.len()
        out["stats"] = {"min_length": int(lengths.min()), "max_length": int(lengths.max())}
    return out


def build_schema(frame: pd.DataFrame, columns: list[dict]) -> list[dict]:
    schema = []
    for c in columns:
        prof = column_profile(frame[c["key"]], c)
        entry = {k: c.get(k) for k in ("key", "original_name", "display_name", "dtype", "semantic_type",
                                       "scale", "currency", "source_col", "flagged", "invalid", "cells_changed")}
        entry.update({"missing": prof["missing"], "unique": prof["unique"], "profile": prof})
        schema.append(entry)
    return schema
