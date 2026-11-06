"""Automatic Tier 1 cleaning pipeline: raw all-text grid -> tidy typed frame + cleaning report.

Deterministic Pandas/NumPy only. The raw grid is never modified; every change is counted against
the raw cell text, and a row-count reconciliation runs before the result is returned.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Literal

import numpy as np
import pandas as pd

from app.core.money import default_currency
from app.cleaning import parsing, standardize
from app.cleaning.structure import (DEFAULT_NULL_TOKENS, NUMBERISH_RE, build_names, detect_header, fill_merged, finalize_names,
                                    normalize_text, trailing_note_rows)

TOTAL_RE = r"(?i)(?:grand\s*)?(?:sub\s*-?\s*)?totals?\b.*"
MAX_EXAMPLES = 5


@dataclass
class CleaningOptions:
    sheet: str | None = None
    header_row: int | None = None
    date_order: Literal["DMY", "MDY"] = "DMY"
    decimal_separator: Literal[".", ","] | None = None
    null_tokens: list[str] | None = None
    id_columns: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CleanResult:
    frame: pd.DataFrame          # columns: schema keys + "_source_row"
    columns: list[dict]          # key, original_name, display_name, dtype, semantic_type, scale, currency, source_col, ...
    report: dict


class CleaningCheckFailed(Exception):
    pass


class _Report:
    def __init__(self):
        self.steps: list[dict] = []

    def add(self, step: str, description: str, rows_affected: int = 0, column: str | None = None,
            examples: list | None = None, severity: str = "info") -> None:
        self.steps.append({
            "step": step, "column": column, "rows_affected": int(rows_affected), "description": description,
            "examples": [str(e)[:80] for e in (examples or [])[:MAX_EXAMPLES]], "severity": severity,
        })


def _ex(s: pd.Series) -> list[str]:
    return [str(v) for v in s.dropna().unique()[:MAX_EXAMPLES]]


def _pairs(before: pd.Series, after: pd.Series) -> list[str]:
    """Distinct 'old' -> 'new' examples for the report."""
    seen = dict.fromkeys(f"'{a}' -> '{b}'" for a, b in zip(before, after))
    return list(seen)[:MAX_EXAMPLES]


def _score(completeness: float, validity: float, uniqueness: float) -> float:
    return round(100 * (0.4 * completeness + 0.4 * validity + 0.2 * uniqueness), 1)


def run_cleaning(grid: pd.DataFrame, merged: list | None = None, opts: CleaningOptions | None = None) -> CleanResult:
    opts = opts or CleaningOptions()
    t0 = time.perf_counter()
    rep = _Report()
    raw = grid.reset_index(drop=True)
    rows_before, cols_before = raw.shape
    removed = 0  # running total of removed rows, reconciled at the end

    # ---- 1. structure ------------------------------------------------------------------
    g, filled = fill_merged(raw, merged or [])
    if filled:
        rep.add("merged_cells", f"Filled {filled} cells covered by merged ranges with the merged value.", filled)
    mojibake = 0
    mojibake_examples: list[str] = []
    if g.shape[1]:
        g = g.copy()
        for col in g.columns:
            fixed, hit = standardize.fix_mojibake(g[col])
            if hit.any():
                mojibake += int(hit.sum())
                mojibake_examples += [f"'{a}' -> '{b}'" for a, b in zip(g[col][hit].head(3), fixed[hit].head(3))]
                g[col] = fixed
    if mojibake:
        rep.add("encoding", "Repaired characters garbled by a wrong text encoding (for example 'CafÃ©' -> 'Café', 'â‚¹' -> '₹').",
                mojibake, examples=mojibake_examples)
    norm = g.apply(normalize_text) if g.shape[1] else g
    empty_rows = norm.isna().all(axis=1)
    empty_cols = norm.isna().all(axis=0)
    if empty_rows.any():
        rep.add("empty_rows", "Dropped fully empty rows.", int(empty_rows.sum()),
                examples=[f"row {i + 1}" for i in np.flatnonzero(empty_rows)[:MAX_EXAMPLES]])
        removed += int(empty_rows.sum())
    if empty_cols.any():
        rep.add("empty_columns", f"Dropped {int(empty_cols.sum())} fully empty column(s).", 0)
    work = norm.loc[~empty_rows, ~empty_cols]
    if work.empty:
        raise ValueError("The file has no data after removing empty rows and columns.")

    merged_rows = {r1 for (r1, c1, r2, c2) in (merged or []) if c2 > c1}
    pos_of_raw = {label: i for i, label in enumerate(work.index)}
    merged_positions = {pos_of_raw[r] for r in merged_rows if r in pos_of_raw}
    header_row_pos = None
    if opts.header_row is not None:
        target = opts.header_row - 1
        if target not in pos_of_raw:
            raise ValueError(f"Header row {opts.header_row} is empty or outside the sheet.")
        header_row_pos = pos_of_raw[target] + 1
    header, n_hdr, notes = detect_header(work, merged_positions, header_row_pos)
    names = build_names(work, header, n_hdr)
    if header is not None:
        title_rows = header
        if title_rows:
            rep.add("title_rows", "Skipped title/blank rows above the header.", title_rows,
                    examples=_ex(work.iloc[:title_rows].bfill(axis=1).iloc[:, 0]))
        rep.add("header", " ".join(notes) or f"Detected the header in row {work.index[header] + 1}.", title_rows + n_hdr)
        removed += title_rows + n_hdr
        data = work.iloc[header + n_hdr:]
    else:
        rep.add("header", " ".join(notes), 0, severity="warning")
        data = work
    notes_rows = trailing_note_rows(data)
    if notes_rows:
        rep.add("footer_notes", "Dropped trailing note/footer rows.", len(notes_rows),
                examples=_ex(data.loc[notes_rows].bfill(axis=1).iloc[:, 0]))
        removed += len(notes_rows)
        data = data.drop(index=notes_rows)

    # ---- 2. column names ----------------------------------------------------------------
    cols = finalize_names(names)
    source_cols = [int(c[1:]) for c in data.columns]
    renamed = [c for c in cols if c["display_name"] != (c["original_name"] or "")]
    if renamed:
        rep.add("column_names", "Cleaned column names (trimmed, deduplicated, generated where missing) and created snake_case keys.",
                0, examples=[f"'{c['original_name']}' -> '{c['display_name']}'" for c in renamed])
    data = data.copy()
    data.columns = [c["key"] for c in cols]
    for c, sc in zip(cols, source_cols):
        c["source_col"] = sc
    table_region = data.copy()  # normalized text before null tokens; used for quality-before

    # ---- 3. text + null tokens ----------------------------------------------------------
    tokens = {t.strip().lower() for t in (opts.null_tokens if opts.null_tokens is not None else DEFAULT_NULL_TOKENS)}
    null_token_cells = 0
    for c in cols:
        s = data[c["key"]]
        hit = s.str.lower().isin(tokens) & s.notna()
        if hit.any():
            n = int(hit.sum())
            null_token_cells += n
            rep.add("null_tokens", "Converted null markers to empty values.", n, c["display_name"], _ex(s[hit]))
            data[c["key"]] = s.where(~hit)
    all_null = data.isna().all(axis=1)
    if all_null.any():
        rep.add("empty_rows", "Dropped rows that only contained null markers.", int(all_null.sum()))
        removed += int(all_null.sum())
        data = data.loc[~all_null]

    # ---- 4-6. types ---------------------------------------------------------------------
    conventions = {parsing.number_convention(data[c["key"]]) for c in cols}
    decided = conventions & {".", ","}
    dataset_sep = next(iter(decided)) if len(decided) == 1 and "conflict" not in conventions else None
    id_forced = {x.strip().lower() for x in opts.id_columns}
    typed: dict[str, pd.Series] = {}
    conversions = []
    for c in cols:
        key, s = c["key"], data[c["key"]]
        forced = key in id_forced or c["display_name"].lower() in id_forced
        parsed: parsing.Parsed | None
        if parsing.looks_like_id(key, s, forced):
            parsed = parsing.Parsed(s, "string", "id", description="Kept as text identifier (leading zeros preserved)")
        else:
            parsed = (parsing.parse_boolean(s) or parsing.parse_dates(key, s, opts.date_order)
                      or parsing.parse_numbers(key, s, opts.decimal_separator, dataset_sep))
            if parsed is None:
                n = int(s.notna().sum())
                uniq = s.nunique()
                semantic = "category" if n and uniq <= max(20, 0.5 * n) else "text"
                parsed = parsing.Parsed(s, "string", semantic)
        for w in parsed.warnings:
            rep.add("type_warning", w, 0, c["display_name"], severity="warning")
        if parsed.failures is not None and parsed.failures.any():
            n = int(parsed.failures.sum())
            rep.add("conversion_failures", f"{n} value(s) could not be converted to {parsed.dtype} and were set to empty.",
                    n, c["display_name"], _ex(s[parsed.failures]), severity="warning")
        c.update({"dtype": parsed.dtype, "semantic_type": parsed.semantic, "invalid": int(parsed.failures.sum()) if parsed.failures is not None else 0,
                  "flagged": bool(parsed.meta.get("flagged", False))})
        if parsed.dtype == "decimal":
            c["scale"] = parsed.meta["scale"]
            if parsed.semantic == "currency":
                # No symbol in the values and none in the column name: use the configured default (INR).
                c["currency"] = parsed.meta.get("currency") or default_currency()
            else:
                c["currency"] = parsed.meta.get("currency")
        if parsed.meta.get("unit"):
            c["unit"] = parsed.meta["unit"]
            if f"({c['unit']})" not in c["display_name"].lower():
                c["display_name"] = f"{c['display_name']} ({c['unit']})"
        if parsed.dtype != "string":
            conversions.append({"column": c["display_name"], "to": parsed.dtype, "semantic_type": parsed.semantic})
            rep.add("type_conversion", parsed.description or f"Converted to {parsed.dtype}.", int(s.notna().sum()), c["display_name"])
        typed[key] = parsed.values
    frame = pd.DataFrame(typed, index=data.index)
    col_by_key = {c["key"]: c for c in cols}

    # ---- text standardisation: emails, phone numbers, person names -------------------------
    handled: set[str] = set()
    for c in cols:
        if c["dtype"] != "string":
            continue
        key, s = c["key"], frame[c["key"]]
        if standardize.is_email_column(key, s):
            new, changed, invalid = standardize.standardize_emails(s)
            c["semantic_type"] = "email"
            handled.add(key)
            if changed.any():
                rep.add("emails", "Lower-cased and trimmed email addresses so the same address always matches.",
                        int(changed.sum()), c["display_name"], _ex(s[changed]))
            if invalid.any():
                c["invalid"] = int(invalid.sum())
                rep.add("invalid_emails", "These do not look like valid email addresses. They were kept; check them before sending anything.",
                        int(invalid.sum()), c["display_name"], _ex(new[invalid]), severity="warning")
            frame[key] = new
        elif standardize.is_phone_column(key, s):
            new, changed, invalid = standardize.standardize_phones(s)
            handled.add(key)
            if changed.any():
                rep.add("phones", "Removed spaces, brackets and dashes from phone numbers (a leading + is kept; no country code is guessed).",
                        int(changed.sum()), c["display_name"], _pairs(s[changed], new[changed]))
            if invalid.any():
                c["invalid"] = int(invalid.sum())
                rep.add("invalid_phones", "These do not look like phone numbers (fewer than 7 or more than 15 digits). They were kept.",
                        int(invalid.sum()), c["display_name"], _ex(new[invalid]), severity="warning")
            frame[key] = new
        elif c["semantic_type"] != "id" and standardize.is_person_name_column(key, s):
            new, changed = standardize.standardize_person_names(s)
            handled.add(key)
            if changed.any():
                rep.add("name_case", "Fixed the capitalisation of names written in all lower or ALL CAPS ('john SMITH' -> 'John Smith').",
                        int(changed.sum()), c["display_name"], _pairs(s[changed], new[changed]))
            frame[key] = new

    # ---- total / subtotal rows ------------------------------------------------------------
    # The label sits in the first text column (which may be an ID column, e.g. "Total" under Order ID).
    label_key = next((c["key"] for c in cols if c["dtype"] == "string"), None)
    num_keys = [c["key"] for c in cols if c["dtype"] in ("integer", "float", "decimal")]
    if label_key and num_keys:
        is_total = frame[label_key].str.fullmatch(TOTAL_RE).fillna(False).to_numpy(dtype=bool)
        if is_total.any():
            drop_labels, kept_flags = [], []
            positions = np.flatnonzero(is_total)
            prev = 0
            for p in positions:
                seg = [i for i in range(prev, p) if not is_total[i]]
                above = [i for i in range(0, p) if not is_total[i]]
                row = frame.iloc[p]
                if _total_matches(frame, row, seg, num_keys, col_by_key) or _total_matches(frame, row, above, num_keys, col_by_key):
                    drop_labels.append(frame.index[p])
                else:
                    kept_flags.append(frame.index[p])
                prev = p + 1
            if drop_labels:
                rep.add("total_rows", "Removed total/subtotal rows whose values equal the sum of the rows above (prevents double counting).",
                        len(drop_labels), label_key and col_by_key[label_key]["display_name"],
                        examples=[f"row {i + 1}: {frame.at[i, label_key]}" for i in drop_labels])
                removed += len(drop_labels)
                frame = frame.drop(index=drop_labels)
            if kept_flags:
                rep.add("total_rows_kept", "Rows labelled 'Total' did not match the sum of the rows above, so they were kept. Check them.",
                        len(kept_flags), col_by_key[label_key]["display_name"],
                        examples=[f"row {i + 1}: {frame.at[i, label_key]}" for i in kept_flags], severity="warning")

    # ---- 7. category variants -------------------------------------------------------------
    for c in cols:
        if c["dtype"] != "string" or c["semantic_type"] == "id":
            continue
        if c["semantic_type"] == "email":
            continue
        s = frame[c["key"]]
        k = s.str.lower().str.replace(r"[^\w\s]", "", regex=True).str.replace(r"\s+", " ", regex=True).str.strip()
        k = k.where(~s.str.fullmatch(NUMBERISH_RE).fillna(False))  # numbers that differ only by sign or symbol are different values
        pairs = pd.DataFrame({"k": k, "v": s}).dropna()
        pairs = pairs[pairs["k"] != ""]
        if pairs.empty:
            continue
        counts = pairs.groupby(["k", "v"], sort=False).size().reset_index(name="n")
        multi = counts.groupby("k")["v"].transform("size") > 1
        if not multi.any():
            continue
        counts = counts[multi]
        # Most frequent spelling wins; ties go to the spelling seen first (groupby keeps first-seen order).
        counts["cased"] = ~((counts["v"].str.lower() == counts["v"]) | (counts["v"].str.upper() == counts["v"]))
        best = (counts.sort_values(["n", "cased"], ascending=False, kind="stable")
                .drop_duplicates("k").set_index("k")["v"])
        mapping = {v: best[kk] for kk, v in zip(counts["k"], counts["v"]) if v != best[kk]}
        hit = s.isin(list(mapping))
        frame[c["key"]] = s.where(~hit, s.map(mapping))
        rep.add("category_variants", "Merged case, spacing and punctuation variants into the most frequent spelling.",
                int(hit.sum()), c["display_name"], [f"'{a}' -> '{b}'" for a, b in mapping.items()])

    # ---- 7b. capitalisation of category labels (after spelling variants are merged) --------
    for c in cols:
        if c["dtype"] != "string" or c["semantic_type"] != "category" or c["key"] in handled:
            continue
        s = frame[c["key"]]
        new, changed = standardize.standardize_category_case(s)
        if changed.any():
            rep.add("category_case", "Gave labels in all lower or ALL CAPS the same capitalisation as the rest of the column.",
                    int(changed.sum()), c["display_name"], _pairs(s[changed], new[changed]))
            frame[c["key"]] = new

    # ---- 8. exact duplicate rows ------------------------------------------------------------
    id_keys = [c["key"] for c in cols if c["semantic_type"] == "id"]
    dup = frame.duplicated(keep="first")
    if dup.any():
        if id_keys:
            key = next((k for k in id_keys if "id" in k.split("_")), id_keys[0])
            rep.add("duplicate_rows", f"Removed exact duplicate records that share the same {col_by_key[key]['display_name']}.",
                    int(dup.sum()), col_by_key[key]["display_name"],
                    examples=[f"row {i + 1}" for i in frame.index[dup][:MAX_EXAMPLES]])
            removed += int(dup.sum())
            frame = frame.loc[~dup]
        else:
            rep.add("duplicate_rows_kept", "Identical rows were found but kept, because without an ID column they may be separate records. "
                    "See the suggestions to remove them.", int(dup.sum()), severity="warning",
                    examples=[f"row {i + 1}" for i in frame.index[dup][:MAX_EXAMPLES]])

    # ---- the same ID on different records --------------------------------------------------
    for k in id_keys:
        if "id" not in k.split("_") and not k.endswith("_no"):
            continue
        ids = frame[k].dropna()
        if len(ids) < 2 or ids.nunique() / len(ids) < 0.8:
            continue  # IDs that repeat by design (e.g. a customer ID on an orders table)
        repeated = ids[ids.duplicated(keep=False)]
        if not repeated.empty:
            rep.add("duplicate_ids", f"{repeated.nunique()} {col_by_key[k]['display_name']} value(s) appear on more than one record with different details. "
                    "They were kept; check whether they are the same record entered twice.",
                    len(repeated), col_by_key[k]["display_name"], _ex(repeated), severity="warning")

    # ---- changes against the raw text, quality scores, reconciliation ---------------------
    raw_aligned = raw.loc[frame.index, [f"c{c['source_col']}" for c in cols]].astype("string")
    raw_aligned.columns = [c["key"] for c in cols]
    cells_changed = 0
    for c in cols:
        canon = parsing.canonical_text(frame[c["key"]], c["dtype"], c)
        r = raw_aligned[c["key"]]
        same = (r.isna() & canon.isna()) | (r == canon).fillna(False)
        changed = int((~same).sum())
        c["cells_changed"] = changed
        cells_changed += changed

    n_cells_before = max(1, table_region.size)
    nulls_before = int(table_region.isna().sum().sum()) + null_token_cells
    raw_nonnull = raw_aligned.notna()
    changed_nonnull = sum(int(((raw_aligned[c["key"]] != parsing.canonical_text(frame[c["key"]], c["dtype"], c)).fillna(True)
                               & raw_nonnull[c["key"]]).sum()) for c in cols)
    q_before = _score(1 - nulls_before / n_cells_before,
                      1 - changed_nonnull / max(1, int(raw_nonnull.sum().sum())),
                      1 - float(table_region.duplicated().mean()) if len(table_region) else 1.0)
    n_cells_after = max(1, frame.size)
    nulls_after = int(frame.isna().sum().sum())
    flagged_cells = sum(int(frame[c["key"]].notna().sum()) for c in cols if c.get("flagged"))
    q_after = _score(1 - nulls_after / n_cells_after, 1 - flagged_cells / n_cells_after,
                     1 - float(frame.duplicated().mean()) if len(frame) else 1.0)

    rows_after = len(frame)
    if rows_before - removed != rows_after:
        raise CleaningCheckFailed(f"Row reconciliation failed: {rows_before} - {removed} != {rows_after}")

    frame = frame.copy()
    frame["_source_row"] = (frame.index.to_numpy() + 1).astype("int64")
    frame = frame.reset_index(drop=True)
    report = {
        "summary": {
            "rows_before": int(rows_before), "rows_after": int(rows_after), "rows_removed": int(removed),
            "columns_before": int(cols_before), "columns_after": len(cols),
            "cells_changed": int(cells_changed), "nulls_before": nulls_before, "nulls_after": nulls_after,
            "conversions": conversions, "quality_score_before": q_before, "quality_score_after": q_after,
            "warnings": sum(1 for s in rep.steps if s["severity"] == "warning"),
            "duration_ms": round((time.perf_counter() - t0) * 1000),
        },
        "steps": rep.steps,
    }
    return CleanResult(frame=frame, columns=cols, report=report)


def _total_matches(frame: pd.DataFrame, row: pd.Series, idx: list[int], num_keys: list[str], meta: dict) -> bool:
    if not idx:
        return False
    compared = 0
    for k in num_keys:
        v = row[k]
        if pd.isna(v):
            continue
        part = frame[k].iloc[idx].dropna()
        if part.empty:
            return False
        total = part.sum()
        if meta[k]["dtype"] in ("integer", "decimal"):
            ok = abs(int(total) - int(v)) <= (1 if meta[k]["dtype"] == "decimal" else 0)
        else:
            ok = abs(float(total) - float(v)) <= max(1e-9 * abs(float(total)), 0.005)
        if not ok:
            return False
        compared += 1
    return compared > 0
