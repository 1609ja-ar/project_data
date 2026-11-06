"""Messy test files written by hand. Expected values in tests are computed independently of app code."""
from __future__ import annotations

import io

import openpyxl

# Sales: title rows, currency text, parenthesized negatives, percents, mixed dates, null tokens,
# case/whitespace variants, leading-zero IDs, a duplicate record with a key, a verified Total row,
# a fake "Total" row that does not add up, and a footer note.
SALES_CSV = """﻿ACME Quarterly Sales,,,,,,
Generated 2024-04-01,,,,,,
,,,,,,
Order ID, Region ,Order Date,Amount,Discount,Shipped,Notes
00101,North,2024-01-05,"$1,234.50",10%,yes,first
00102,north ,05/01/2024,(200.00),5%,no,N/A
00103,NORTH,13/02/2024,$300.25,,Y,-
00103,NORTH,13/02/2024,$300.25,,Y,-
00104,South,2024-03-01,"1,000.00",0%,n,  spaced   out
00105,South,15/03/2024,45.10-,12.5%,yes,#N/A
Total,,,"$2,589.90",,,
00106,East,20/03/2024,$99.99,,no,
Total,,,$5.00,,,
Source: internal ledger,,,,,,
"""
# Amount values of the six kept data rows (00103 duplicate removed, verified Total removed):
SALES_AMOUNTS_TEXT = ["$1,234.50", "(200.00)", "$300.25", "1,000.00", "45.10-", "$99.99"]


def plain_money_cents(text: str) -> int:
    """Independent parser for the test oracle (plain Python, no pandas)."""
    t = text.strip()
    neg = False
    if t.startswith("(") and t.endswith(")"):
        neg, t = True, t[1:-1]
    if t.endswith("-"):
        neg, t = True, t[:-1]
    t = t.replace("$", "").replace(",", "")
    whole, _, frac = t.partition(".")
    cents = int(whole) * 100 + int((frac + "00")[:2])
    return -cents if neg else cents


# Weather: semicolon delimiter, decimal commas, Latin-1 encoding, a null token and dates in DMY.
WEATHER_CSV = (
    "Station;Reading time;Temperature °C;Humidity %;Rain mm\n"
    "Zürich;01.02.2024 06:00;-3,5;81;0,0\n"
    "Zürich;01.02.2024 12:00;2,25;65;1,4\n"
    "Genève;01.02.2024 06:00;1,0;90;n/a\n"
    "Genève;01.02.2024 12:00;4,75;70;2,6\n"
    "Bern;01.02.2024 06:00;-1,5;88;0,2\n"
).encode("latin-1")


def student_marks_xlsx() -> bytes:
    """Title row, a merged two-row header ("Scores" spanning Math/Science), leading-zero roll numbers."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Term 1"
    ws["A1"] = "Class 8B - Term 1 Results"
    ws.append([])
    ws.append(["Roll No", "Student", "Scores", None, "Passed"])
    ws.append([None, None, "Math", "Science", None])
    ws.merge_cells("C3:D3")
    ws.merge_cells("A3:A4")
    ws.merge_cells("B3:B4")
    ws.merge_cells("E3:E4")
    rows = [("007", "Asha", 78, 81.5, "Yes"), ("012", "Ben", 64, 70, "No"), ("015", "Chen", 91, 88.25, "yes"),
            ("021", "Dara", None, 59, "NO")]
    for r in rows:
        ws.append(list(r))
    ws2 = wb.create_sheet("Empty")
    ws2["A1"] = None
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def xlsx_with_two_sheets() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Blank"
    ws2 = wb.create_sheet("Data")
    ws2.append(["Item", "Count"])
    ws2.append(["a", 1])
    ws2.append(["b", 2])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


AMBIGUOUS_DATES_CSV = "Event,When\nA,01/02/2024\nB,03/04/2024\nC,05/06/2024\n"
EXCEL_SERIAL_CSV = "Ref,Ship Date\nX1,45292\nX2,45323\nX3,2024-03-01\n"   # 45292 = 2024-01-01
NO_KEY_DUPES_CSV = "Product,Price\nPen,1.50\nPen,1.50\nInk,4.00\n"
EU_AMBIGUOUS_CSV = "Item,Weight\nA,\"1,234\"\nB,\"2,500\"\nC,\"3,750\"\n"
