"""Cleaning pipeline (Phase 3b). Expected values are hand-computed or computed in plain Python."""
import io
import time
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

from app.cleaning import frames
from app.cleaning.pipeline import CleaningOptions, run_cleaning
from app.cleaning.profile import build_schema
from app.cleaning.suggestions import apply_suggestions, compute_suggestions
from app.services.ingest import read_csv_grid, read_xlsx_grid
from tests import fixtures as fx


def clean_csv(text, **opts):
    data = text.encode("utf-8") if isinstance(text, str) else text
    return run_cleaning(read_csv_grid(data, 100_000, 100).frame, [], CleaningOptions(**opts))


def col(result, display):
    return next(c for c in result.columns if c["display_name"] == display)


@pytest.fixture(scope="module")
def sales():
    return clean_csv(fx.SALES_CSV)


def test_structure_title_rows_footer_and_header(sales):
    assert [c["display_name"] for c in sales.columns] == ["Order ID", "Region", "Order Date", "Amount", "Discount", "Shipped", "Notes"]
    assert [c["key"] for c in sales.columns] == ["order_id", "region", "order_date", "amount", "discount", "shipped", "notes"]
    steps = {s["step"] for s in sales.report["steps"]}
    assert {"title_rows", "footer_notes", "header"} <= steps
    assert "Source: internal ledger" not in sales.frame["order_id"].tolist()


def test_currency_negatives_exact(sales):
    amount = col(sales, "Amount")
    assert amount["dtype"] == "decimal" and amount["semantic_type"] == "currency" and amount["scale"] == 2
    assert amount["currency"] == "USD"
    rows = sales.frame[sales.frame["order_id"] != "Total"]
    assert rows["amount"].tolist() == [123450, -20000, 30025, 100000, -4510, 9999]  # cents


def test_cleaned_sum_matches_independent_plain_python_sum(sales):
    expected = sum(fx.plain_money_cents(t) for t in fx.SALES_AMOUNTS_TEXT)
    rows = sales.frame[sales.frame["order_id"] != "Total"]
    assert int(rows["amount"].sum()) == expected == 238964


def test_percent_values(sales):
    d = sales.frame.set_index("order_id")["discount"]
    assert d["00101"] == pytest.approx(0.10, abs=1e-15)
    assert d["00105"] == pytest.approx(0.125, abs=1e-15)
    assert np.isnan(d["00103"])


def test_mixed_dates_dayfirst_from_evidence(sales):
    d = sales.frame.set_index("order_id")["order_date"]
    assert col(sales, "Order Date")["dtype"] == "date"
    assert d["00102"] == pd.Timestamp("2024-01-05")  # 05/01/2024 read day-first because 13/02 settles it
    assert d["00103"] == pd.Timestamp("2024-02-13")
    assert d["00105"] == pd.Timestamp("2024-03-15")


def test_booleans_nulls_and_text(sales):
    f = sales.frame.set_index("order_id")
    assert f.loc["00101", "shipped"] is True or bool(f.loc["00101", "shipped"]) is True
    assert bool(f.loc["00104", "shipped"]) is False
    assert pd.isna(f.loc["00102", "notes"]) and pd.isna(f.loc["00105", "notes"]) and pd.isna(f.loc["00103", "notes"])
    assert f.loc["00104", "notes"] == "spaced out"


def test_category_case_variants_merged(sales):
    # North, north and NORTH become one label, written the way the rest of the column is (Title case).
    assert set(sales.frame["region"].dropna()) == {"North", "South", "East"}


def test_leading_zero_ids_preserved(sales):
    c = col(sales, "Order ID")
    assert c["dtype"] == "string" and c["semantic_type"] == "id"
    assert "00101" in sales.frame["order_id"].tolist()


def test_duplicate_with_key_removed_and_totals(sales):
    assert sales.frame["order_id"].tolist().count("00103") == 1
    steps = {s["step"]: s for s in sales.report["steps"]}
    assert steps["duplicate_rows"]["rows_affected"] == 1
    assert steps["total_rows"]["rows_affected"] == 1                       # verified total removed
    assert steps["total_rows_kept"]["severity"] == "warning"                # fake total kept and flagged
    assert sales.frame["order_id"].tolist().count("Total") == 1


def test_row_reconciliation(sales):
    s = sales.report["summary"]
    assert s["rows_before"] == 14  # every line of the file, including title, header and footer
    assert s["rows_before"] - s["rows_removed"] == s["rows_after"] == len(sales.frame) == 7
    removed_by_steps = sum(st["rows_affected"] for st in sales.report["steps"]
                           if st["step"] in ("empty_rows", "header", "footer_notes", "total_rows", "duplicate_rows"))
    assert removed_by_steps == s["rows_removed"]
    assert s["quality_score_after"] > s["quality_score_before"]


def test_source_row_maps_back_to_file_lines(sales):
    f = sales.frame.set_index("order_id")
    lines = fx.SALES_CSV.splitlines()
    assert lines[f.loc["00104", "_source_row"] - 1].startswith("00104")


def test_ambiguous_dates_warn_and_option_changes_order():
    dmy = clean_csv(fx.AMBIGUOUS_DATES_CSV)
    assert dmy.frame["when"].tolist()[0] == pd.Timestamp("2024-02-01")
    assert any("ambiguous" in s["description"] for s in dmy.report["steps"] if s["severity"] == "warning")
    mdy = clean_csv(fx.AMBIGUOUS_DATES_CSV, date_order="MDY")
    assert mdy.frame["when"].tolist()[0] == pd.Timestamp("2024-01-02")


def test_excel_serial_dates():
    r = clean_csv(fx.EXCEL_SERIAL_CSV)
    assert r.frame["ship_date"].tolist() == [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-02-01"), pd.Timestamp("2024-03-01")]


def test_date_failures_over_5_percent_keep_text():
    r = clean_csv("Shipped On,X\n2024-01-01,1\nsoon,2\nlater,3\n2024-01-04,4\n")
    assert col(r, "Shipped On")["dtype"] == "string"
    assert any(s["severity"] == "warning" for s in r.report["steps"])


def test_conversion_failures_counted_not_dropped():
    rows = "\n".join(f"{i},{i * 10}" for i in range(1, 40))
    r = clean_csv(f"N,Score\n{rows}\n40,oops\n")
    c = col(r, "Score")
    assert c["dtype"] == "integer" and c["invalid"] == 1
    fail = next(s for s in r.report["steps"] if s["step"] == "conversion_failures")
    assert fail["rows_affected"] == 1 and fail["examples"] == ["oops"]
    assert len(r.frame) == 40


def test_european_decimals_latin1_semicolon():
    r = run_cleaning(read_csv_grid(fx.WEATHER_CSV, 1000, 50).frame)
    assert r.frame["station"].tolist()[0] == "Zürich"
    assert r.frame["temperature_c"].tolist() == [-3.5, 2.25, 1.0, 4.75, -1.5]
    assert col(r, "Reading time")["dtype"] == "datetime"
    assert r.frame["reading_time"].iloc[1] == pd.Timestamp("2024-02-01 12:00")


def test_ambiguous_thousands_kept_as_text_then_option():
    r = clean_csv(fx.EU_AMBIGUOUS_CSV)
    assert col(r, "Weight")["dtype"] == "string"
    assert any("decimal separator" in s["description"] for s in r.report["steps"])
    us = clean_csv(fx.EU_AMBIGUOUS_CSV, decimal_separator=".")
    assert us.frame["weight"].tolist() == [1234, 2500, 3750]
    eu = clean_csv(fx.EU_AMBIGUOUS_CSV, decimal_separator=",")
    assert eu.frame["weight"].tolist() == [1.234, 2.5, 3.75]


def test_duplicates_without_key_are_kept_with_suggestion():
    r = clean_csv(fx.NO_KEY_DUPES_CSV)
    assert len(r.frame) == 3
    schema = build_schema(r.frame, r.columns)
    sugs = compute_suggestions(r.frame, schema)
    dup = next(s for s in sugs if s["type"] == "duplicate_rows")
    new, cols, steps, _ = apply_suggestions(r.frame, schema, sugs, [{"id": dup["id"], "option": "remove"}])
    assert len(new) == 2 and steps[0]["rows_affected"] == 1
    assert len(r.frame) == 3  # input untouched


def test_merged_multirow_header_xlsx():
    g = read_xlsx_grid(fx.student_marks_xlsx(), None, 1000, 50)
    assert g.sheet == "Term 1" and g.sheets == ["Term 1", "Empty"]
    r = run_cleaning(g.frame, g.merged)
    assert [c["display_name"] for c in r.columns] == ["Roll No", "Student", "Scores Math", "Scores Science", "Passed"]
    assert r.frame["roll_no"].tolist() == ["007", "012", "015", "021"]
    assert r.frame["scores_science"].tolist() == [81.5, 70.0, 88.25, 59.0]
    assert pd.isna(r.frame["scores_math"].iloc[3])


def test_idempotent_on_cleaned_export(sales):
    schema = build_schema(sales.frame, sales.columns)
    exported = frames.to_csv_bytes(sales.frame, schema)
    again = run_cleaning(read_csv_grid(exported, 1000, 50).frame)
    s = again.report["summary"]
    assert s["cells_changed"] == 0
    assert s["rows_removed"] == 1  # only the header line
    tier1_changes = [st for st in again.report["steps"]
                     if st["step"] in ("null_tokens", "category_variants", "duplicate_rows", "total_rows", "merged_cells", "footer_notes")]
    assert tier1_changes == []
    for c in sales.columns:
        a = sales.frame[c["key"]].reset_index(drop=True)
        b = again.frame[c["key"]].reset_index(drop=True)
        if c["semantic_type"] == "percent":
            assert np.allclose(a.astype(float), b.astype(float), equal_nan=True)
        else:
            assert a.astype("string").fillna("<NA>").tolist() == b.astype("string").fillna("<NA>").tolist(), c["key"]


def test_parquet_roundtrip_is_exact(sales, tmp_path):
    schema = build_schema(sales.frame, sales.columns)
    p = tmp_path / "v.parquet"
    frames.write_parquet(sales.frame, schema, p)
    import pyarrow.parquet as pq
    assert str(pq.read_schema(p).field("amount").type) == "decimal128(38, 2)"
    back = frames.read_parquet(p, schema)
    assert back.equals(sales.frame)


def test_csv_export_escapes_text_only(sales):
    df = sales.frame.copy()
    df.loc[0, "notes"] = "=HYPERLINK(1)"
    schema = build_schema(df, sales.columns)
    out = frames.to_csv_bytes(df, schema).decode()
    assert "'=HYPERLINK(1)" in out
    assert ",-200.00," in out and ",-45.10," in out  # negative numbers are not escaped


def test_performance_100k_rows():
    rng = np.random.default_rng(1)
    n = 100_000
    buf = io.StringIO()
    buf.write("Order ID,Region,Date,Amount,Qty\n")
    regions = np.array(["North", "south", "EAST ", "West"])
    for i in range(n):
        buf.write(f"{i:07d},{regions[i % 4]},2024-{(i % 12) + 1:02d}-{(i % 28) + 1:02d},\"${rng.integers(1, 99999) / 100:,.2f}\",{i % 9}\n")
    data = buf.getvalue().encode()
    t = time.perf_counter()
    r = run_cleaning(read_csv_grid(data, 1_000_000, 100).frame)
    elapsed = time.perf_counter() - t
    assert len(r.frame) == n
    assert elapsed < 10, f"cleaning took {elapsed:.1f}s"


# ---------------------------------------------------------------- messy real-world file (tests/messy_customers.csv)

@pytest.fixture(scope="module")
def messy():
    from pathlib import Path
    return clean_csv((Path(__file__).parent / "messy_customers.csv").read_bytes())


def by_id(result):
    return result.frame.set_index("customer_id")


def test_garbled_encoding_repaired_before_numbers(messy):
    # 'â‚¹2000' is ₹2000 saved with the wrong encoding; it must not become 12000.
    c = col(messy, "Amount (INR)")
    assert c["dtype"] == "decimal" and c["currency"] == "INR"
    assert by_id(messy).loc["C009", "amount_inr"] == 2000_00
    assert by_id(messy).loc["C009", "customer_name"] == "Café Owner"


def test_money_formats_scientific_magnitude_and_indian_grouping(messy):
    f = by_id(messy)
    assert f.loc["C001", "amount_inr"] == 120000_50      # ₹1,20,000.50
    assert f.loc["C003", "amount_inr"] == 120000_00      # 1.2E+05
    assert f.loc["C005", "amount_inr"] == 12000_00       # 12k
    assert f.loc["C008", "amount_inr"] == 10000000_00    # ₹1,00,00,000
    assert f.loc["C007", "amount_inr"] == -500_00


def test_mixed_percent_and_ratio(messy):
    f = by_id(messy)
    assert f.loc["C001", "discount"] == pytest.approx(0.10)
    assert f.loc["C004", "discount"] == pytest.approx(0.15)  # written 0.15 next to values like 10%


def test_units_and_counts(messy):
    f = by_id(messy)
    assert col(messy, "Weight (kg)")["unit"] == "kg"
    assert f.loc["C003", "weight"] == pytest.approx(0.5)     # 500 g
    assert f.loc["C002", "weight"] == pytest.approx(1.5)     # 1.5kg
    assert col(messy, "Qty")["dtype"] == "integer"
    assert f.loc["C002", "qty"] == 3                        # 3 pcs
    assert f.loc["C007", "qty"] == -2                       # sign kept, never merged with 2
    assert f.loc["C003", "rating"] == 5 and f.loc["C004", "rating"] == 3  # 5 stars, 3/5


def test_dates_ordinal_timezone_serial_compact_and_swapped(messy):
    f = by_id(messy)
    assert col(messy, "Signup Date")["semantic_type"] == "date"
    assert f.loc["C003", "signup_date"] == pd.Timestamp("2024-01-07")           # 7th Jan 2024
    assert f.loc["C002", "signup_date"] == pd.Timestamp("2024-01-07 09:15:00")  # ...Z
    assert f.loc["C007", "signup_date"] == pd.Timestamp("2024-01-13")           # 2024-13-01
    assert f.loc["C004", "last_order"] == pd.Timestamp("2024-01-10")            # 20240110
    assert f.loc["C005", "last_order"] == pd.Timestamp("2024-01-09")            # Excel serial 45300


def test_emails_phones_names_and_casing(messy):
    f = by_id(messy)
    assert col(messy, "Email")["semantic_type"] == "email"
    assert f.loc["C001", "email"] == "john.smith@gmail.com"
    assert f.loc["C003", "email"] == "kate@example"      # invalid addresses are kept and reported
    steps = {s["step"]: s for s in messy.report["steps"]}
    assert steps["invalid_emails"]["rows_affected"] == 2 and steps["invalid_emails"]["severity"] == "warning"
    assert f.loc["C001", "phone"] == "+919876543210" and f.loc["C003", "phone"] == "02223456789"
    assert f.loc["C001", "customer_name"] == "John Smith"
    assert f.loc["C003", "customer_name"] == "O'Brien, Kate"
    assert set(f["city"]) >= {"Mumbai", "Bombay", "New Delhi"} and "mumbai" not in set(f["city"])
    assert set(f["status"].dropna()) == {"Active", "Inactive", "Actve"}


def test_messy_suggestions_flag_what_cannot_be_fixed_automatically(messy):
    sug = {s["id"]: s for s in compute_suggestions(messy.frame, messy.columns)}
    assert sug["placeholder_dates:signup_date"]["default"] == "set_null"
    assert "near_duplicates:status" in sug and sug["near_duplicates:status"]["params"]["mapping"] == {"Actve": "Active"}
    assert "near_duplicates:email" not in sug
    frame, cols, _ = apply_suggestions(messy.frame, messy.columns, list(sug.values()),
                                       [{"id": "placeholder_dates:signup_date", "option": "set_null"}])[:3]
    assert frame["signup_date"].isna().sum() == messy.frame["signup_date"].isna().sum() + 1


def test_timezone_values_do_not_crash():
    r = clean_csv("when,value\n2024-01-01T10:00:00Z,1\n2024-01-02T10:00:00+05:30,2\n2024-01-03,3\n")
    assert r.frame["when"].tolist()[1] == pd.Timestamp("2024-01-02 04:30:00")


def test_money_without_symbol_defaults_to_rupees_and_symbols_are_kept():
    r = clean_csv("Item,Revenue,Price USD,Cost\nA,1000,5,₹10\nB,2500.50,7,₹20\n")
    cur = {c["key"]: c.get("currency") for c in r.columns if c["semantic_type"] == "currency"}
    assert cur["revenue"] == "INR"          # plain numbers in a money column: the default currency
    assert cur["price_usd"] == "USD"        # the column name says dollars: kept, never relabelled
    assert cur["cost"] == "INR"
    dollars = clean_csv("Item,Amount\nA,$10.00\nB,$20.00\n")
    assert dollars.columns[1]["currency"] == "USD"  # values written in $ stay dollars (no conversion is invented)


def test_rupee_formats_are_read():
    r = clean_csv("Item,Amount\nA,\"₹12,34,567.50\"\nB,Rs. 250\nC,INR 1000\nD,₨ 75\n")
    assert r.columns[1]["currency"] == "INR"
    assert r.frame["amount"].tolist() == [123456750, 25000, 100000, 7500]  # exact paise


def test_small_column_gets_one_capitalisation_style():
    # Only two distinct labels after merging north/NORTH and south/South: they must end up in the same style.
    r = clean_csv("Order ID,Region,Amount\n00101, north,10\n00102,NORTH,20\n00103,South ,30\n00104,south,40\n")
    assert sorted(set(r.frame["region"])) == ["North", "South"]
    assert any(s["step"] == "category_case" for s in r.report["steps"])


def test_landing_page_cleaning_demo_matches_the_real_pipeline():
    """frontend/src/components/landing/sample.js shows this exact file before and after cleaning."""
    raw = ("Order ID,Region,Order Date,Amount\n00101, north,05/01/2024,\"₹1,234.50\"\n00102,NORTH,13/02/2024,(200.00)\n"
           "00102,NORTH,13/02/2024,(200.00)\n00104,South ,2024-03-01,\"1,000.00\"\n00105,south,15/03/2024,Rs 250.00\nTotal,,,\"₹2,084.50\"\n")
    r = clean_csv(raw)
    assert next(c for c in r.columns if c["key"] == "amount")["currency"] == "INR"
    text = frames.export_text_frame(r.frame, r.columns, escape=False)
    assert text.values.tolist() == [["00101", "North", "2024-01-05", "1234.50"], ["00102", "North", "2024-02-13", "-200.00"],
                                    ["00104", "South", "2024-03-01", "1000.00"], ["00105", "South", "2024-03-15", "250.00"]]
    steps = {s["step"]: s["rows_affected"] for s in r.report["steps"]}
    assert steps["total_rows"] == 1 and steps["duplicate_rows"] == 1  # the total only goes because it adds up (duplicate included)
    assert r.report["summary"]["cells_changed"] == 11


def test_money_text_uses_indian_grouping_and_matches_the_web_app():
    from app.core.money import format_money, group_number
    assert format_money(1234567.5, "INR") == "₹12,34,567.50"
    assert format_money(-200, "INR") == "-₹200.00"
    assert format_money(1234.5, None) == "₹1,234.50"          # no currency recorded -> default (INR)
    assert format_money(10, "USD") == "$10.00"               # dollar data keeps its symbol
    assert format_money(2.675, "INR") == "₹2.68"             # rounds like the browser
    assert format_money(-0.001, "INR") == "₹0.00"            # no "-₹0.00"
    assert format_money(10, "AED") == "10.00 AED"
    assert group_number(12345678901) == "12,34,56,78,901"
    assert group_number(999) == "999" and group_number(-100000) == "-1,00,000"
