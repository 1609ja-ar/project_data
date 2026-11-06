"""Validate uploaded files and parse them into a raw, all-text grid (no type inference).

The raw grid is a DataFrame with string columns c0..cN and one row per sheet/file row, with
None for empty cells. Cleaning (app.cleaning) works from this grid; the original file is never
modified.
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path

import pandas as pd

ALLOWED_EXTENSIONS = {".csv": "csv", ".xlsx": "xlsx", ".xls": "xls"}
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
ZIP_MAGIC = b"PK\x03\x04"
MAX_UNCOMPRESSED_BYTES = 400 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200
MAX_MERGED_RANGES = 5000


class IngestError(Exception):
    def __init__(self, message: str, code: str = "invalid_file"):
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass
class RawGrid:
    frame: pd.DataFrame                      # string columns c0..cN, None = empty cell
    sheets: list[str] | None = None          # Excel only
    sheet: str | None = None
    merged: list[tuple[int, int, int, int]] = field(default_factory=list)  # 0-based r1,c1,r2,c2 inclusive
    encoding: str | None = None
    delimiter: str | None = None


def file_type_from_name(filename: str) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise IngestError(
            "Only .csv, .xlsx and .xls files are supported. JSON, Parquet, PDF, text and database files are not accepted.",
            "unsupported_type")
    return ALLOWED_EXTENSIONS[ext]


def validate_content(data: bytes, file_type: str) -> None:
    """Check that the bytes really are the declared type, and refuse protected/macro files."""
    if not data:
        raise IngestError("The file is empty.", "empty_file")
    head = data[:8]
    if file_type == "xlsx":
        if head == OLE_MAGIC:
            if b"E\x00n\x00c\x00r\x00y\x00p\x00t\x00e\x00d\x00P\x00a\x00c\x00k\x00a\x00g\x00e" in data:
                raise IngestError("This workbook is password-protected. Remove the password in Excel and upload it again.",
                                  "password_protected")
            raise IngestError("This file is not a valid .xlsx workbook.")
        if head[:4] != ZIP_MAGIC:
            raise IngestError("This file is not a valid .xlsx workbook.")
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = set(z.namelist())
                if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
                    raise IngestError("This file is not a valid .xlsx workbook.")
                if any(n.lower().endswith("vbaproject.bin") for n in names) or \
                        b"macroEnabled" in z.read("[Content_Types].xml"):
                    raise IngestError("Macro-enabled workbooks are not accepted. Save it as a plain .xlsx without macros.",
                                      "macro_enabled")
                total = sum(i.file_size for i in z.infolist())
                compressed = max(1, sum(i.compress_size for i in z.infolist()))
                if total > MAX_UNCOMPRESSED_BYTES or total / compressed > MAX_COMPRESSION_RATIO:
                    raise IngestError("This workbook expands to an unsafe size and was rejected.", "too_large")
        except zipfile.BadZipFile:
            raise IngestError("This file is not a valid .xlsx workbook.")
    elif file_type == "xls":
        if head != OLE_MAGIC:
            raise IngestError("This file is not a valid .xls workbook.")
        if b"_\x00V\x00B\x00A\x00_\x00P\x00R\x00O\x00J\x00E\x00C\x00T" in data:
            raise IngestError("Macro-enabled workbooks are not accepted. Save it without macros.", "macro_enabled")
    elif file_type == "csv":
        if head[:4] == ZIP_MAGIC or head == OLE_MAGIC or b"\x00\x00" in data[:4096]:
            raise IngestError("This file does not look like a text CSV file.")


# ---------------------------------------------------------------- CSV

def _decode(data: bytes) -> tuple[str, str]:
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    raise IngestError("Could not read the file's text encoding.")  # latin-1 never fails; kept for safety


def _sniff_delimiter(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        lines = [ln for ln in sample.splitlines()[:50] if ln.strip()]
        best, best_score = ",", -1.0
        for d in (",", ";", "\t", "|"):
            counts = [ln.count(d) for ln in lines]
            if not counts or max(counts) == 0:
                continue
            # Prefer delimiters that appear a consistent number of times per line.
            score = sum(counts) / len(counts) - (max(counts) - min(counts)) * 0.5
            if score > best_score:
                best, best_score = d, score
        return best


def read_csv_grid(data: bytes, max_rows: int, max_cols: int) -> RawGrid:
    text, enc = _decode(data)
    delim = _sniff_delimiter(text[:65536])
    rows = []
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delim)
    try:
        for i, row in enumerate(reader):
            if i >= max_rows + 50:  # allow some title/header rows above the data
                raise IngestError(f"The file has more than {max_rows:,} rows, which is the limit.", "too_many_rows")
            if len(row) > max_cols:
                raise IngestError(f"The file has more than {max_cols} columns, which is the limit.", "too_many_columns")
            rows.append(row)
    except csv.Error as e:
        raise IngestError(f"The CSV file could not be parsed: {e}")
    if not rows:
        raise IngestError("The file has no rows.", "empty_file")
    width = max(len(r) for r in rows)
    frame = pd.DataFrame([r + [""] * (width - len(r)) for r in rows], columns=[f"c{i}" for i in range(width)], dtype=object)
    frame = frame.where(frame != "", None)
    return RawGrid(frame=_as_text(frame), encoding=enc, delimiter=delim)


# ---------------------------------------------------------------- Excel

def _cell_text(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, datetime):
        return v.isoformat(sep=" ") if (v.hour or v.minute or v.second or v.microsecond) else v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, time):
        return v.isoformat()
    if isinstance(v, float):
        if v != v:  # NaN
            return None
        return str(int(v)) if v.is_integer() and abs(v) < 1e15 else repr(v)
    s = str(v)
    return s if s != "" else None


_MERGE_RE = re.compile(rb'<mergeCell\s+ref="([A-Z]+)(\d+):([A-Z]+)(\d+)"')


def _col_index(letters: bytes) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + (ch - 64)
    return n - 1


def _xlsx_merges(data: bytes, sheet_path: str) -> list[tuple[int, int, int, int]]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read(sheet_path.lstrip("/"))
    except (KeyError, zipfile.BadZipFile):
        return []
    out = []
    for m in _MERGE_RE.finditer(xml):
        out.append((int(m.group(2)) - 1, _col_index(m.group(1)), int(m.group(4)) - 1, _col_index(m.group(3))))
        if len(out) >= MAX_MERGED_RANGES:
            break
    return out


def _rows_to_frame(rows: list[list], max_cols: int) -> pd.DataFrame:
    width = max((len(r) for r in rows), default=0)
    if width > max_cols:
        raise IngestError(f"The sheet has more than {max_cols} columns, which is the limit.", "too_many_columns")
    frame = pd.DataFrame([r + [None] * (width - len(r)) for r in rows], columns=[f"c{i}" for i in range(width)], dtype=object)
    return _as_text(frame)


def read_xlsx_grid(data: bytes, sheet: str | None, max_rows: int, max_cols: int) -> RawGrid:
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as e:  # noqa: BLE001 - any openpyxl failure means an unreadable workbook
        raise IngestError(f"The workbook could not be opened ({type(e).__name__}).")
    try:
        names = wb.sheetnames
        if sheet is not None and sheet not in names:
            raise IngestError(f"Sheet '{sheet}' was not found in the workbook.", "sheet_not_found")
        candidates = [sheet] if sheet else names
        for name in candidates:
            ws = wb[name]
            rows: list[list] = []
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i >= max_rows + 50:
                    raise IngestError(f"The sheet has more than {max_rows:,} rows, which is the limit.", "too_many_rows")
                if len(row) > max_cols:
                    raise IngestError(f"The sheet has more than {max_cols} columns, which is the limit.", "too_many_columns")
                rows.append([_cell_text(v) for v in row])
            while rows and all(v is None for v in rows[-1]):
                rows.pop()
            if rows or sheet:
                merges = _xlsx_merges(data, getattr(ws, "_worksheet_path", "") or "")
                return RawGrid(frame=_rows_to_frame(rows, max_cols), sheets=names, sheet=name, merged=merges)
        raise IngestError("Every sheet in this workbook is empty.", "empty_file")
    finally:
        wb.close()


def read_xls_grid(data: bytes, sheet: str | None, max_rows: int, max_cols: int) -> RawGrid:
    import xlrd

    try:
        book = xlrd.open_workbook(file_contents=data, formatting_info=True, on_demand=True)
    except xlrd.biffh.XLRDError as e:
        if "encrypt" in str(e).lower():
            raise IngestError("This workbook is password-protected. Remove the password and upload it again.",
                              "password_protected")
        raise IngestError("The .xls workbook could not be opened.")
    except Exception:  # noqa: BLE001
        raise IngestError("The .xls workbook could not be opened.")
    try:
        names = book.sheet_names()
        if sheet is not None and sheet not in names:
            raise IngestError(f"Sheet '{sheet}' was not found in the workbook.", "sheet_not_found")
        for name in ([sheet] if sheet else names):
            sh = book.sheet_by_name(name)
            if sh.nrows > max_rows + 50:
                raise IngestError(f"The sheet has more than {max_rows:,} rows, which is the limit.", "too_many_rows")
            if sh.ncols > max_cols:
                raise IngestError(f"The sheet has more than {max_cols} columns, which is the limit.", "too_many_columns")
            if sh.nrows == 0 and not sheet:
                continue
            rows = []
            for r in range(sh.nrows):
                out = []
                for c in range(sh.ncols):
                    cell = sh.cell(r, c)
                    if cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                        out.append(None)
                    elif cell.ctype == xlrd.XL_CELL_DATE:
                        try:
                            out.append(_cell_text(xlrd.xldate.xldate_as_datetime(cell.value, book.datemode)))
                        except Exception:  # noqa: BLE001 - keep the raw serial if conversion fails
                            out.append(_cell_text(cell.value))
                    elif cell.ctype == xlrd.XL_CELL_BOOLEAN:
                        out.append("TRUE" if cell.value else "FALSE")
                    elif cell.ctype == xlrd.XL_CELL_ERROR:
                        out.append(xlrd.error_text_from_code.get(cell.value, "#ERROR"))
                    else:
                        out.append(_cell_text(cell.value))
                rows.append(out)
            merges = [(r1, c1, r2 - 1, c2 - 1) for (r1, r2, c1, c2) in sh.merged_cells][:MAX_MERGED_RANGES]
            return RawGrid(frame=_rows_to_frame(rows, max_cols), sheets=names, sheet=name, merged=merges)
        raise IngestError("Every sheet in this workbook is empty.", "empty_file")
    finally:
        book.release_resources()


def _as_text(frame: pd.DataFrame) -> pd.DataFrame:
    # Explicit pandas string dtype; None stays missing.
    return frame.astype("str").where(frame.notna(), None) if len(frame.columns) else frame


def read_grid(data: bytes, file_type: str, sheet: str | None, max_rows: int, max_cols: int) -> RawGrid:
    if file_type == "csv":
        grid = read_csv_grid(data, max_rows, max_cols)
    elif file_type == "xlsx":
        grid = read_xlsx_grid(data, sheet, max_rows, max_cols)
    else:
        grid = read_xls_grid(data, sheet, max_rows, max_cols)
    if grid.frame.shape[1] == 0 or grid.frame.notna().sum().sum() == 0:
        raise IngestError("The file has no data.", "empty_file")
    return grid
