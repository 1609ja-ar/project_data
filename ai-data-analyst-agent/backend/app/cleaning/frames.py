"""Reading/writing cleaned frames: Parquet (exact DECIMAL money), JSON-safe rows and CSV exports.

In memory, money columns are Int64 minor units; on disk they are DECIMAL(38, scale).
"""
from __future__ import annotations

import io
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from app.cleaning.parsing import minor_to_text

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _arrow_column(s: pd.Series, col: dict) -> pa.Array:
    dtype = col["dtype"]
    if dtype == "decimal":
        ints = pa.array(s.astype("Int64"), type=pa.int64(), from_pandas=True)
        return _decimal_from_unscaled(ints, int(col.get("scale", 2)))
    if dtype == "integer":
        return pa.array(s.astype("Int64"), type=pa.int64(), from_pandas=True)
    if dtype == "float":
        return pa.array(s.astype("float64"), type=pa.float64(), from_pandas=True)
    if dtype == "date":
        return pa.array(s, type=pa.timestamp("us"), from_pandas=True).cast(pa.date32())
    if dtype == "datetime":
        return pa.array(s, type=pa.timestamp("us"), from_pandas=True)
    if dtype == "boolean":
        return pa.array(s.astype("boolean"), type=pa.bool_(), from_pandas=True)
    return pa.array(s.astype("string"), type=pa.string(), from_pandas=True)


def _decimal_from_unscaled(ints: pa.Array, scale: int) -> pa.Array:
    """Exact: build Decimal objects from integer minor units (C-implemented Decimal, no float)."""
    vals = [None if v is None else Decimal(v).scaleb(-scale) for v in ints.to_pylist()]
    return pa.array(vals, type=pa.decimal128(38, scale))


def write_parquet(frame: pd.DataFrame, schema: list[dict], path: Path) -> None:
    arrays, fields = [], []
    for col in schema:
        arr = _arrow_column(frame[col["key"]], col)
        arrays.append(arr)
        fields.append(pa.field(col["key"], arr.type))
    arrays.append(pa.array(frame["_source_row"].astype("int64"), type=pa.int64()))
    fields.append(pa.field("_source_row", pa.int64()))
    table = pa.Table.from_arrays(arrays, schema=pa.schema(fields))
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path, compression="zstd")


def decimal_to_minor(arr: pa.ChunkedArray | pa.Array, scale: int) -> pa.Array:
    """DECIMAL(p, scale) -> int64 minor units, exactly.

    A decimal128 value is stored as its unscaled 128-bit little-endian integer, so after casting to
    the target scale the low 64 bits are the minor units (checked against the high word's sign).
    """
    chunks = arr.chunks if isinstance(arr, pa.ChunkedArray) else [arr]
    out = []
    for ch in chunks:
        ch = pc.cast(ch, pa.decimal128(38, scale))
        words = np.frombuffer(ch.buffers()[1], dtype="<i8")[2 * ch.offset: 2 * (ch.offset + len(ch))].reshape(-1, 2)
        low, high = words[:, 0], words[:, 1]
        valid = ~np.asarray(ch.is_null().to_numpy(zero_copy_only=False), dtype=bool)
        if (high[valid] != (low[valid] >> 63)).any():
            raise OverflowError("Money value exceeds the exact integer range")
        out.append(pa.array(low, type=pa.int64(), mask=~valid))
    return pa.concat_arrays(out) if out else pa.array([], type=pa.int64())


def read_parquet(path: Path, schema: list[dict], columns: list[str] | None = None) -> pd.DataFrame:
    """Load a cleaned version into the in-memory representation (money as Int64 minor units)."""
    want = columns or [c["key"] for c in schema] + ["_source_row"]
    table = pq.read_table(path, columns=want)
    by_key = {c["key"]: c for c in schema}
    data = {}
    for name in table.column_names:
        col = by_key.get(name)
        arr = table.column(name)
        if col and col["dtype"] == "decimal":
            data[name] = pd.Series(decimal_to_minor(arr, int(col.get("scale", 2))).to_pandas(types_mapper={pa.int64(): pd.Int64Dtype()}.get), dtype="Int64")
        elif col and col["dtype"] == "integer":
            data[name] = pd.Series(arr.to_pandas(types_mapper={pa.int64(): pd.Int64Dtype()}.get), dtype="Int64")
        elif col and col["dtype"] in ("date", "datetime"):
            data[name] = pd.to_datetime(pd.Series(arr.cast(pa.timestamp("us")).to_pandas())).astype("datetime64[ns]")
        elif col and col["dtype"] == "boolean":
            data[name] = pd.Series(arr.to_pandas(), dtype="boolean")
        elif col and col["dtype"] == "float":
            data[name] = pd.Series(arr.to_pandas(), dtype="float64")
        elif col:
            data[name] = pd.Series(arr.to_pandas(), dtype="str")
        else:
            data[name] = arr.to_pandas()
    return pd.DataFrame(data)


def read_arrow(path: Path, columns: list[str] | None = None) -> pa.Table:
    return pq.read_table(path, columns=columns)


# ------------------------------------------------------------------ JSON / CSV views

def json_rows(frame: pd.DataFrame, schema: list[dict]) -> list[list]:
    """Rows as JSON-safe lists in schema order. Money -> float of the exact decimal (exact to the cent)."""
    cols = []
    for c in schema:
        s = frame[c["key"]]
        if c["dtype"] == "decimal":
            scale = c.get("scale", 2)
            txt = minor_to_text(s, scale)
            cols.append([None if pd.isna(t) else float(Decimal(t)) for t in txt])
        elif c["dtype"] == "integer":
            cols.append([None if pd.isna(v) else int(v) for v in s])
        elif c["dtype"] == "float":
            cols.append([None if pd.isna(v) or not np.isfinite(v) else float(v) for v in s])
        elif c["dtype"] == "date":
            cols.append([None if pd.isna(v) else v.strftime("%Y-%m-%d") for v in s])
        elif c["dtype"] == "datetime":
            cols.append([None if pd.isna(v) else v.strftime("%Y-%m-%dT%H:%M:%S") for v in s])
        elif c["dtype"] == "boolean":
            cols.append([None if pd.isna(v) else bool(v) for v in s])
        else:
            cols.append([None if pd.isna(v) else str(v) for v in s])
    return [list(r) for r in zip(*cols)] if cols else []


def escape_formula(s: pd.Series) -> pd.Series:
    """Prefix risky text cells with ' so spreadsheet apps show them as text (text columns only)."""
    t = s.astype("string")
    risky = t.str.startswith(FORMULA_PREFIXES).fillna(False)
    return t.where(~risky, "'" + t)


def export_text_frame(frame: pd.DataFrame, schema: list[dict], escape: bool = True) -> pd.DataFrame:
    """Canonical text export: plain numbers (no symbols), ISO dates, true/false. Escaping only for text columns."""
    out = {}
    for c in schema:
        s = frame[c["key"]]
        if c["dtype"] == "decimal":
            out[c["display_name"]] = minor_to_text(s, c.get("scale", 2))
        elif c["dtype"] == "integer":
            out[c["display_name"]] = s.astype("Int64").astype("string")
        elif c["dtype"] == "float":
            out[c["display_name"]] = s.map(lambda x: None if pd.isna(x) else repr(float(x)))
        elif c["dtype"] == "date":
            out[c["display_name"]] = s.dt.strftime("%Y-%m-%d")
        elif c["dtype"] == "datetime":
            out[c["display_name"]] = s.dt.strftime("%Y-%m-%d %H:%M:%S")
        elif c["dtype"] == "boolean":
            out[c["display_name"]] = s.map({True: "true", False: "false"})
        else:
            out[c["display_name"]] = escape_formula(s) if escape else s.astype("string")
    return pd.DataFrame(out)


def to_csv_bytes(frame: pd.DataFrame, schema: list[dict]) -> bytes:
    buf = io.StringIO()
    export_text_frame(frame, schema).to_csv(buf, index=False, lineterminator="\n")
    return buf.getvalue().encode("utf-8")
