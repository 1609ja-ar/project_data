"""Excel workbook for a pivot result: one sheet with the pivot (real numbers, subtotals bold) and one "About" sheet."""
from __future__ import annotations

import io
import re
from datetime import datetime

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from app.services.exports import money_format

HEAD_FILL = PatternFill("solid", fgColor="EEF2FF")
TOTAL_FILL = PatternFill("solid", fgColor="F3F4F6")


def safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name.rsplit(".", 1)[0])[:100] or "pivot"


def _fmt(col: dict) -> str:
    if col["dtype"] == "decimal":
        return money_format(col, "#,##0." + "0" * int(col.get("scale") or 2))
    if col["dtype"] == "integer":
        return "#,##0"
    return "#,##0.00"


def _cell(ws, value, *, text=False, fmt=None, bold=False, fill=None):
    c = WriteOnlyCell(ws, value=value)
    if text and isinstance(value, str):
        c.data_type = "s"  # never a formula, even if a label starts with = + - @
    if fmt:
        c.number_format = fmt
    if bold:
        c.font = Font(bold=True)
    if fill:
        c.fill = fill
    return c


def pivot_workbook(result: dict, filename: str, version: dict) -> bytes:
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("Pivot")
    rf, cf, ms = result["row_fields"], result["column_field"], result["measures"]
    cols, nm = result["columns"], len(result["measures"])
    nr = len(rf)

    header = [f["label"] for f in rf] + [""]  # last label column says what a subtotal row is
    if cf:
        for c in cols:
            for m in ms:
                header.append(f"{c} | {m['label']}" if nm > 1 else str(c))
        for m in ms:
            header.append(f"Total | {m['label']}" if nm > 1 else "Total")
    else:
        header += [m["label"] for m in ms]
    ws.freeze_panes = f"{get_column_letter(nr + 2)}2"  # header row and the label columns stay in view
    ws.append([_cell(ws, h, text=True, bold=True, fill=HEAD_FILL) for h in header])

    fmts = [_fmt(m["column"]) for m in ms]

    def numbers(values, bold=False, fill=None):
        return [None if v is None else _cell(ws, v, fmt=fmts[i % nm], bold=bold, fill=fill) for i, v in enumerate(values)]

    for r in result["rows"]:
        path = r["path"]
        labels = path + [""] * (nr - len(path))
        tail = "Total" if r["subtotal"] else ""
        label_cells = [_cell(ws, x + (" (partial)" if r["partial"] and i == len(path) - 1 else ""), text=True, bold=r["subtotal"],
                             fill=TOTAL_FILL if r["subtotal"] else None) for i, x in enumerate(labels)]
        label_cells.append(_cell(ws, tail, text=True, bold=True, fill=TOTAL_FILL if r["subtotal"] else None))
        ws.append(label_cells + numbers(r["cells"] + r["totals"] if cf else r["totals"], bold=r["subtotal"],
                                        fill=TOTAL_FILL if r["subtotal"] else None))
    foot = [_cell(ws, "Grand total", text=True, bold=True, fill=TOTAL_FILL)] + [_cell(ws, "", text=True, fill=TOTAL_FILL)] * nr
    ws.append(foot + numbers(result["column_totals"] + result["grand_total"] if cf else result["grand_total"], bold=True, fill=TOTAL_FILL))

    about = wb.create_sheet("About")
    about.column_dimensions["A"].width = 22
    about.column_dimensions["B"].width = 90
    v = result["verification"]
    lines = [
        ("Dataset", filename), ("Version", str(version.get("version_number"))),
        ("Exported", datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("Rows", " › ".join(f["label"] for f in rf)), ("Columns", cf["label"] if cf else "None"),
        ("Values", "; ".join(m["label"] for m in ms)),
        ("Filters", "; ".join(result["filters"]) or "None"),
        ("Rows used", f"{result['rows_used']:,} of {result['rows_in']:,} rows after filters"),
        ("Checks", f"{v['passed']} of {v['checks']} passed (Pandas, each group recomputed with DuckDB)"),
        ("Note", "Subtotals and totals are calculated from the underlying rows, not by adding the cells shown."),
    ]
    if result.get("top_n"):
        lines.append(("Top N", f"Only the top {result['top_n']} of {result['rows_total_count']:,} first-level rows are listed; the grand total includes all."))
    for k, val in lines:
        about.append([_cell(about, k, text=True, bold=True), _cell(about, val, text=True)])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
