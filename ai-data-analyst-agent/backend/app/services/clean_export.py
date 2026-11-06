"""Downloads of a cleaned version for sharing: CSV, Excel-friendly CSV, Excel workbook, JSON and a share pack (zip).

Every format is written from the same stored frame and schema, so the values match the app exactly.
"""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import datetime

import pandas as pd

from app.cleaning import frames
from app.services import exports as ex

FORMATS = ("csv", "csv_excel", "xlsx", "json", "zip")
MEDIA = {
    "csv": "text/csv; charset=utf-8",
    "csv_excel": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "json": "application/json",
    "zip": "application/zip",
}
EXT = {"csv": "csv", "csv_excel": "csv", "xlsx": "xlsx", "json": "json", "zip": "zip"}


def pick_columns(schema: list[dict], keys: list[str] | None) -> list[dict]:
    """Columns to export, in the dataset's order. Unknown keys raise ValueError; None or empty means all."""
    if not keys:
        return list(schema)
    known = {c["key"] for c in schema}
    unknown = [k for k in keys if k not in known]
    if unknown:
        raise ValueError(f"Unknown column: {unknown[0]}")
    wanted = set(keys)
    return [c for c in schema if c["key"] in wanted]


def csv_bytes(frame: pd.DataFrame, schema: list[dict], excel: bool = False) -> bytes:
    data = frames.to_csv_bytes(frame, schema)
    # Excel only reads UTF-8 correctly (₹, é, ü ...) when the file starts with a byte-order mark.
    return b"\xef\xbb\xbf" + data if excel else data


def json_bytes(frame: pd.DataFrame, schema: list[dict]) -> bytes:
    """Records with real types: numbers, ISO dates, true/false and null for empty cells. No formula escaping."""
    text = frames.export_text_frame(frame, schema, escape=False)
    cols = []
    for c in schema:
        s = text[c["display_name"]]
        if c["dtype"] in ("decimal", "float"):
            vals = [None if pd.isna(v) else float(v) for v in s]
        elif c["dtype"] == "integer":
            vals = [None if pd.isna(v) else int(v) for v in s]
        elif c["dtype"] == "boolean":
            vals = [None if pd.isna(v) else v == "true" for v in s]
        else:
            vals = [None if pd.isna(v) else str(v) for v in s]
        cols.append((c["display_name"], vals))
    records = [{name: vals[i] for name, vals in cols} for i in range(len(frame))]
    return json.dumps(records, ensure_ascii=False, indent=1).encode("utf-8")


def xlsx_bytes(frame: pd.DataFrame, schema: list[dict], version: dict, dataset: dict) -> bytes:
    data, _ = ex.excel_workbook(frame, schema, version, dataset, include={"dictionary", "cleaning"})
    return data


def _dictionary_csv(schema: list[dict]) -> bytes:
    rows = [{"column": c["display_name"], "type": c["dtype"], "meaning": c["semantic_type"], "empty_values": c.get("missing"),
             "distinct_values": c.get("unique"), "examples": ", ".join((c.get("profile") or {}).get("examples", []))} for c in schema]
    df = pd.DataFrame(rows, columns=["column", "type", "meaning", "empty_values", "distinct_values", "examples"])
    df["examples"] = frames.escape_formula(df["examples"])
    df["column"] = frames.escape_formula(df["column"])
    return df.to_csv(index=False, lineterminator="\n").encode("utf-8")


def _report_csv(report: dict) -> bytes:
    steps = report.get("steps") or []
    df = pd.DataFrame([{"step": s["step"], "column": s.get("column") or "", "rows_affected": s["rows_affected"], "severity": s["severity"],
                        "description": s["description"], "examples": " | ".join(s.get("examples") or [])} for s in steps],
                      columns=["step", "column", "rows_affected", "severity", "description", "examples"])
    for k in ("column", "description", "examples"):
        df[k] = frames.escape_formula(df[k])
    return df.to_csv(index=False, lineterminator="\n").encode("utf-8")


def share_pack(frame: pd.DataFrame, schema: list[dict], version: dict, dataset: dict, base: str, all_columns: bool) -> bytes:
    """Clean CSV + data dictionary + cleaning report + README with row counts and a checksum to confirm the file."""
    data = csv_bytes(frame, schema)
    summary = (version.get("cleaning_report") or {}).get("summary") or {}
    lines = [
        f"Clean data: {dataset['filename']} (version {version['version_number']})",
        f"Exported: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        f"Rows: {len(frame)}",
        f"Columns: {len(schema)}" + ("" if all_columns else " (a selection; other columns were left out on purpose)"),
    ]
    if summary:
        lines += ["", "What cleaning did:",
                  f"- {summary.get('rows_before')} rows read, {summary.get('rows_removed')} removed, {summary.get('cells_changed')} values fixed",
                  f"- Empty cells: {summary.get('nulls_before')} before, {summary.get('nulls_after')} after"]
        if summary.get("quality_score_before") is not None:
            lines.append(f"- Quality score: {summary.get('quality_score_before')} -> {summary.get('quality_score_after')} (out of 100)")
    lines += ["", "Files:",
              f"- {base}_clean.csv: the data (UTF-8, comma separated, ISO dates, plain numbers without currency symbols)",
              "- data_dictionary.csv: each column's type, meaning and examples",
              "- cleaning_report.csv: every automatic change, with examples",
              "", f"SHA-256 of {base}_clean.csv: {hashlib.sha256(data).hexdigest()}",
              "Anyone can recompute this checksum to confirm the data file was not changed."]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{base}_clean.csv", data)
        z.writestr("data_dictionary.csv", _dictionary_csv(schema))
        z.writestr("cleaning_report.csv", _report_csv(version.get("cleaning_report") or {}))
        z.writestr("README.txt", "\n".join(lines) + "\n")
    return buf.getvalue()


def build(fmt: str, frame: pd.DataFrame, schema: list[dict], version: dict, dataset: dict, base: str, all_columns: bool) -> bytes:
    if fmt in ("csv", "csv_excel"):
        return csv_bytes(frame, schema, excel=fmt == "csv_excel")
    if fmt == "json":
        return json_bytes(frame, schema)
    if fmt == "xlsx":
        return xlsx_bytes(frame, schema, version, dataset)
    return share_pack(frame, schema, version, dataset, base, all_columns)
