"""Insight detectors, scoring, de-duplication and ranking."""
from __future__ import annotations

import hashlib
import math
from app.core.money import format_money, group_number
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
from scipy import stats

from app.analytics.engine import CalculationCheckFailed
from app.analytics.plan import NUMERIC, QueryPlan
from app.analytics.profile import detect_roles, numeric_values
from app.analytics.runner import run_verified

# Thresholds (documented in docs/METRICS.md)
MIN_TREND_POINTS = 8
MIN_CORR_N = 30
MIN_ABS_R = 0.5
MIN_GROUP_N = 10
MIN_DIST_N = 30
ALPHA = 0.05
MAX_TESTS = 20
MAX_CATEGORY_GROUPS = 200
CHART_ROWS = 12


@dataclass
class InsightOptions:
    focus_measure: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    max_insights: int = 10

    def key(self) -> str:
        return hashlib.sha256(f"{self.focus_measure}|{self.date_from}|{self.date_to}|{self.max_insights}".encode()).hexdigest()[:16]


@dataclass
class Ctx:
    frame: pd.DataFrame
    table: pa.Table
    schema: list[dict]
    version: dict
    by_key: dict
    measure: dict | None
    date: dict | None
    categories: list[dict]
    filters_text: list[str]
    tests_run: int = 0
    skipped: list[dict] = field(default_factory=list)

    def test_budget(self) -> bool:
        if self.tests_run >= MAX_TESTS:
            return False
        self.tests_run += 1
        return True


def fmt(v, col: dict | None = None) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "n/a"
    if col and col.get("semantic_type") == "currency":
        return format_money(v, col.get("currency"))
    if col and col.get("semantic_type") == "percent":
        return f"{v:.1%}"
    if isinstance(v, int) or (isinstance(v, float) and v.is_integer() and abs(v) < 1e15):
        return group_number(int(v))
    return f"{v:,.4g}" if abs(v) < 1e6 else group_number(v)


def pct(x: float) -> str:
    return f"{x:.1%}"


def _insight(type_, severity, score, headline, detail, numbers, columns, ctx: Ctx, rows_used, rows_skipped,
             how=None, chart=None, caveats=None, next_checks=None) -> dict:
    iid = hashlib.sha256(f"{type_}|{'|'.join(columns)}|{headline}".encode()).hexdigest()[:12]
    return {
        "id": iid, "type": type_, "severity": severity, "score": round(float(score), 6),
        "headline": headline, "detail": detail,
        "evidence": {"numbers": numbers, "columns": columns, "filters": ctx.filters_text or ["None"],
                     "rows_used": int(rows_used), "rows_skipped": int(rows_skipped)},
        "how_calculated": how, "suggested_chart_spec": chart, "caveats": caveats or [],
        "possible_next_checks": next_checks or [],
    }


def _chart(result: dict, spec: dict) -> dict:
    return {"spec": spec, "columns": result["columns"], "rows": result["rows"][:CHART_ROWS]}


def _run(ctx: Ctx, **plan) -> dict | None:
    try:
        return run_verified(ctx.frame, ctx.table, ctx.schema, QueryPlan(**plan), ctx.version)
    except CalculationCheckFailed:
        ctx.skipped.append({"detector": plan.get("operation"), "reason": "Calculation check failed"})
        return None


# ------------------------------------------------------------------ detectors

def detect_contributors(ctx: Ctx) -> list[dict]:
    out = []
    m = ctx.measure
    if not m:
        return out
    for cat in ctx.categories[:3]:
        r = _run(ctx, operation="aggregate", metric_column=m["key"], aggregation="sum", group_by=[cat["key"]], limit=1000)
        if not r or not any(c["key"] == "share" for c in r["columns"]):
            continue
        k = len(r["rows"])
        if k < 2:
            continue
        top, bottom = list(r["rows"][0]), list(r["rows"][-1])
        top[0] = "(empty)" if top[0] is None else top[0]
        bottom[0] = "(empty)" if bottom[0] is None else bottom[0]
        share_top, share_bottom = top[2], bottom[2]
        equal = 1 / k
        effect = share_top - equal
        if effect <= 0.05:
            continue
        lift = share_top / equal
        severity = "important" if share_top >= 0.5 and k >= 3 else "notable" if lift >= 1.5 else "info"
        d = r["calculation_details"]
        out.append(_insight(
            "top_contributor", severity, min(1, effect * 2) * share_top * 1.0,
            f"{top[0]} contributes {pct(share_top)} of total {m['display_name']}",
            f"{top[0]} accounts for {fmt(top[1], m)} of {fmt(r['total'], m)} across {k} {cat['display_name']} values "
            f"(an equal split would be {pct(equal)} each). The smallest is {bottom[0]} with {fmt(bottom[1], m)} ({pct(share_bottom)}).",
            {"top_value": top[1], "top_share": share_top, "total": r["total"], "groups": k, "equal_share": equal,
             "bottom_value": bottom[1], "bottom_share": share_bottom},
            [m["key"], cat["key"]], ctx, d["rows_used"], d["rows_skipped"], d,
            _chart(r, {"type": "horizontal_bar", "x": cat["key"], "y": "value"}),
            ["Share of total is descriptive; it does not explain why one group is larger."],
            [f"Compare {top[0]} over time to see whether its share is stable.",
             f"Check whether {cat['display_name']} groups have similar numbers of rows."]))
        if k >= 5:
            shares = sorted((row[2] for row in r["rows"]), reverse=True)
            n_top = max(1, math.ceil(0.2 * k))
            top_share = sum(shares[:n_top])
            cum, cutoff = 0.0, k
            for i, s in enumerate(shares, start=1):
                cum += s
                if cum >= 0.8 - 1e-12:
                    cutoff = i
                    break
            if top_share >= 0.6:
                out.append(_insight(
                    "concentration", "important" if top_share >= 0.8 else "notable", (top_share - 0.2) * top_share,
                    f"The top {n_top} of {k} {cat['display_name']} values hold {pct(top_share)} of {m['display_name']}",
                    f"{cutoff} of {k} values ({pct(cutoff / k)}) make up 80% of the total (Pareto cut-off).",
                    {"top_n": n_top, "groups": k, "top_n_share": top_share, "pareto_groups": cutoff, "pareto_share_of_groups": cutoff / k},
                    [m["key"], cat["key"]], ctx, d["rows_used"], d["rows_skipped"], d,
                    _chart(r, {"type": "bar", "x": cat["key"], "y": "value"}),
                    ["Concentration describes the current data only."],
                    ["Check how dependent results are on the top values (for example, what changes if the largest is removed)."]))
    return out


def _series(ctx: Ctx) -> tuple[dict | None, str]:
    """Verified aggregate per complete period for the measure (sum) or row count."""
    d, m = ctx.date, ctx.measure
    s = ctx.frame[d["key"]].dropna()
    # Coarsest grain that is well filled (>= 80% of periods have data) and still gives enough periods for a
    # trend test. Empty, zero-filled periods must not inflate the number of points, and daily noise should
    # not hide a monthly pattern. Falls back to the finest well-filled grain (the trend is then skipped).
    filled = []
    for g, freq in (("quarter", "Q"), ("month", "M"), ("week", "W-SUN"), ("day", "D")):
        if s.empty:
            break
        periods = s.dt.to_period(freq)
        total = (periods.max() - periods.min()).n + 1
        if periods.nunique() / total >= 0.8:
            filled.append((g, total))
    enough = [g for g, total in filled if total >= MIN_TREND_POINTS + 2]
    grain = enough[0] if enough else (filled[-1][0] if filled else "year")
    plan = {"operation": "trend", "date_column": d["key"], "time_grain": grain}
    plan.update({"metric_column": m["key"], "aggregation": "sum"} if m else {"aggregation": "count"})
    return _run(ctx, **plan), grain


def detect_trends(ctx: Ctx) -> list[dict]:
    out = []
    if not ctx.date:
        ctx.skipped.append({"detector": "trend", "reason": "No date column"})
        return out
    r, grain = _series(ctx)
    if not r or not r["rows"]:
        return out
    m = ctx.measure
    label = m["display_name"] if m else "row count"
    complete = [row for row in r["rows"] if not row[-1]]
    values = [row[2] for row in complete]
    d = r["calculation_details"]
    chart = {"spec": {"type": "line", "x": "period", "y": "value"}, "columns": r["columns"], "rows": r["rows"][-60:]}
    if len(complete) < MIN_TREND_POINTS:
        ctx.skipped.append({"detector": "trend", "reason": f"Not enough data to call a trend: {len(complete)} complete {grain}(s), "
                                                          f"need at least {MIN_TREND_POINTS}"})
    elif ctx.test_budget():
        x = np.arange(len(values), dtype=float)
        y = np.array(values, dtype=float)
        lr = stats.linregress(x, y)
        mean = float(np.mean(y))
        rel_change = (lr.slope * (len(y) - 1)) / abs(mean) if mean else 0.0
        if lr.pvalue < ALPHA and abs(rel_change) >= 0.1:
            direction = "upward" if lr.slope > 0 else "downward"
            r2 = lr.rvalue ** 2
            severity = "important" if lr.pvalue < 0.01 and abs(rel_change) >= 0.2 and r2 >= 0.5 else "notable"
            out.append(_insight(
                "trend", severity, min(1, abs(rel_change)) * 1.0 * (1 - lr.pvalue),
                f"{label[0].upper() + label[1:]} shows {'an' if direction == 'upward' else 'a'} {direction} trend over {len(values)} complete {grain}s",
                f"A straight-line fit changes by {fmt(float(lr.slope), m)} per {grain} "
                f"({pct(abs(rel_change))} of the average over the period; p = {lr.pvalue:.3g}, R² = {lr.rvalue ** 2:.2f}).",
                {"slope": float(lr.slope), "p_value": float(lr.pvalue), "r_squared": float(lr.rvalue ** 2), "periods": len(values),
                 "relative_change": rel_change, "mean": mean},
                [ctx.date["key"]] + ([m["key"]] if m else []), ctx, d["rows_used"], d["rows_skipped"], d, chart,
                ["Partial periods are excluded.", "A linear fit is a simplification; it is not a forecast.",
                 "Exploratory: several statistical tests run per dataset (multiple-comparison caution)."],
                ["Check whether a few periods drive the change (see anomalies).", "Split the trend by a category to see who drives it."]))
    # Period over period (complete periods only)
    if len(complete) >= 2:
        cur, prev = complete[-1], complete[-2]
        if prev[2] not in (None, 0) and cur[2] is not None:
            g = (cur[2] - prev[2]) / abs(prev[2])
            if abs(g) >= 0.2:
                out.append(_insight(
                    "period_change", "notable" if abs(g) >= 0.5 else "info", min(1, abs(g)) * 0.5,
                    f"{label[0].upper() + label[1:]} {'rose' if g > 0 else 'fell'} {pct(abs(g))} in {cur[0]} versus {prev[0]}",
                    f"{fmt(cur[2], m)} in {cur[0]} compared with {fmt(prev[2], m)} in {prev[0]}. "
                    "Growth = (current − previous) ÷ |previous|; partial periods are excluded.",
                    {"current": cur[2], "previous": prev[2], "growth": g},
                    [ctx.date["key"]] + ([m["key"]] if m else []), ctx, d["rows_used"], d["rows_skipped"], d, chart,
                    ["A single period-to-period change can be noise."], ["Compare with the same period last year if available."]))
        if grain == "month" and len(complete) >= 13:
            by_label = {row[0]: row for row in complete}
            last = complete[-1]
            y, mo = last[0].split("-")
            ly = by_label.get(f"{int(y) - 1}-{mo}")
            if ly and ly[2] not in (None, 0):
                g = (last[2] - ly[2]) / abs(ly[2])
                if abs(g) >= 0.1:
                    out.append(_insight(
                        "period_change", "notable" if abs(g) >= 0.25 else "info", min(1, abs(g)) * 0.6,
                        f"{label[0].upper() + label[1:]} is {pct(abs(g))} {'higher' if g > 0 else 'lower'} than a year earlier ({last[0]} vs {ly[0]})",
                        f"{fmt(last[2], m)} in {last[0]} compared with {fmt(ly[2], m)} in {ly[0]}.",
                        {"current": last[2], "previous": ly[2], "growth": g},
                        [ctx.date["key"]] + ([m["key"]] if m else []), ctx, d["rows_used"], d["rows_skipped"], d, chart,
                        ["Year-over-year compares two single months."], []))
    # Anomalies on the aggregated series (screening)
    if len(complete) >= MIN_TREND_POINTS:
        y = np.array(values, dtype=float)
        q1, q3 = np.percentile(y, [25, 75])
        iqr = q3 - q1
        med = float(np.median(y))
        mad = float(np.median(np.abs(y - med)))
        flagged = []
        for row, v in zip(complete, y):
            z = 0.6745 * (v - med) / mad if mad else 0.0
            if iqr > 0 and (v < q1 - 1.5 * iqr or v > q3 + 1.5 * iqr) and abs(z) > 3.5:
                flagged.append((row[0], float(v), float(z)))
        if flagged:
            p0 = flagged[0]
            out.append(_insight(
                "anomaly", "notable", min(1, abs(p0[2]) / 10) * (len(flagged) / len(y)) + 0.05,
                f"{len(flagged)} unusual {grain}(s) in {label} (screening)",
                f"{p0[0]} had {fmt(p0[1], m)} versus a typical {fmt(med, m)} (robust z = {p0[2]:.1f}). "
                "Flagged when outside 1.5 × IQR and |robust z| > 3.5.",
                {"period_value": p0[1], "median": med, "robust_z": p0[2], "flagged": len(flagged)},
                [ctx.date["key"]] + ([m["key"]] if m else []), ctx, d["rows_used"], d["rows_skipped"], d, chart,
                ["Screening only: unusual does not mean wrong."], [f"Look at the rows in {p0[0]} for one-off events or data errors."]))
    return out


def detect_seasonality(ctx: Ctx) -> list[dict]:
    out = []
    if not ctx.date:
        return out
    d, m = ctx.date, ctx.measure
    s = ctx.frame[d["key"]]
    present = s.dropna()
    if present.empty:
        return out
    span = (present.max() - present.min()).days
    if span < 14:
        ctx.skipped.append({"detector": "weekday", "reason": "Needs at least 2 full weeks of dates"})
        return out
    plan = {"operation": "trend", "date_column": d["key"], "time_grain": "day"}
    plan.update({"metric_column": m["key"], "aggregation": "sum"} if m else {"aggregation": "count"})
    r = _run(ctx, **plan)
    if not r:
        return out
    days = pd.DataFrame([(pd.Timestamp(row[1]), row[2]) for row in r["rows"]], columns=["day", "v"]).dropna()
    days["wd"] = days["day"].dt.day_of_week
    groups = [g["v"].to_numpy(dtype=float) for _, g in days.groupby("wd")]
    if len(groups) < 7 or min(len(g) for g in groups) < 2 or not ctx.test_budget():
        ctx.skipped.append({"detector": "weekday", "reason": "Needs at least 2 observations for every weekday"})
        return out
    h, p = stats.kruskal(*groups)
    means = days.groupby("wd")["v"].mean()
    overall = float(days["v"].mean())
    effect = float((means.max() - means.min()) / abs(overall)) if overall else 0.0
    if p < ALPHA and effect >= 0.3:
        names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        hi, lo = int(means.idxmax()), int(means.idxmin())
        dd = r["calculation_details"]
        out.append(_insight(
            "weekday_pattern", "notable", min(1, effect) * (1 - p) * 0.8,
            f"{names[hi]}s are highest and {names[lo]}s lowest for {m['display_name'] if m else 'row count'}",
            f"Average per day: {names[hi]} {fmt(float(means[hi]), m)}, {names[lo]} {fmt(float(means[lo]), m)} "
            f"(overall {fmt(overall, m)}; Kruskal-Wallis p = {p:.3g}). Days without data count as 0.",
            {"high_mean": float(means[hi]), "low_mean": float(means[lo]), "overall_mean": overall, "p_value": float(p), "effect": effect},
            [d["key"]] + ([m["key"]] if m else []), ctx, dd["rows_used"], dd["rows_skipped"], dd, None,
            ["Exploratory test (multiple-comparison caution).", "Needs at least 2 full weekly cycles."],
            ["Check whether the pattern holds in each month."]))
    return out


def detect_relationships(ctx: Ctx) -> list[dict]:
    out = []
    nums = [c for c in ctx.schema if c["dtype"] in NUMERIC and c["semantic_type"] not in ("id",)][:8]
    for i, a in enumerate(nums):
        for b in nums[i + 1:]:
            x = numeric_values(ctx.frame, a)
            y = numeric_values(ctx.frame, b)
            ok = x.notna() & y.notna()
            n = int(ok.sum())
            if n < MIN_CORR_N or x[ok].nunique() < 3 or y[ok].nunique() < 3:
                continue
            if not ctx.test_budget():
                return out
            r_p, p_p = stats.pearsonr(x[ok], y[ok])
            r_s, p_s = stats.spearmanr(x[ok], y[ok])
            if abs(r_p) >= MIN_ABS_R and p_p < ALPHA:
                out.append(_insight(
                    "relationship", "important" if abs(r_p) >= 0.8 and p_p < 0.001 else "notable", abs(r_p) * (1 - p_p) * 0.9,
                    f"{a['display_name']} and {b['display_name']} move {'together' if r_p > 0 else 'in opposite directions'} (association, not causation)",
                    f"Pearson r = {r_p:.2f} (p = {p_p:.2g}), Spearman ρ = {r_s:.2f} (p = {p_s:.2g}), n = {n} rows with both values.",
                    {"pearson_r": float(r_p), "pearson_p": float(p_p), "spearman_rho": float(r_s), "spearman_p": float(p_s), "n": n},
                    [a["key"], b["key"]], ctx, n, len(ctx.frame) - n, None, None,
                    ["Correlation is association, not causation.", "Exploratory test (multiple-comparison caution)."],
                    ["Look for a third variable that could drive both.", "Plot one against the other to check for outliers driving r."]))
    return out


def detect_segments(ctx: Ctx) -> list[dict]:
    out = []
    m = ctx.measure
    if not m:
        return out
    vals = numeric_values(ctx.frame, m)
    for cat in ctx.categories[:3]:
        counts = ctx.frame.loc[vals.notna(), cat["key"]].value_counts()
        big = counts[counts >= MIN_GROUP_N]
        if len(big) < 2:
            continue
        g1, g2 = big.index[0], big.index[1]
        a = vals[(ctx.frame[cat["key"]] == g1) & vals.notna()].to_numpy(dtype=float)
        b = vals[(ctx.frame[cat["key"]] == g2) & vals.notna()].to_numpy(dtype=float)
        if not ctx.test_budget():
            return out
        if len(a) >= 30 and len(b) >= 30:
            t, p = stats.ttest_ind(a, b, equal_var=False)
            pooled = math.sqrt((a.var(ddof=1) + b.var(ddof=1)) / 2) or 1e-12
            effect, test, eff_name = (a.mean() - b.mean()) / pooled, "Welch t-test", "Cohen's d"
            big_effect = abs(effect) >= 0.5
        else:
            u, p = stats.mannwhitneyu(a, b, alternative="two-sided")
            effect, test, eff_name = 1 - 2 * u / (len(a) * len(b)), "Mann-Whitney U", "rank-biserial r"
            effect = -effect  # positive when the first group tends to be larger
            big_effect = abs(effect) >= 0.3
        if p < ALPHA and big_effect:
            higher, lower = (g1, g2) if a.mean() > b.mean() else (g2, g1)
            effect = abs(effect)  # magnitude; the text names the higher group
            out.append(_insight(
                "segment_difference", "notable", min(1, abs(effect)) * (1 - p) * 0.8,
                f"{m['display_name']} differs between {cat['display_name']} {higher} and {lower}",
                f"Average {fmt(float(max(a.mean(), b.mean())), m)} for {higher} vs {fmt(float(min(a.mean(), b.mean())), m)} for {lower} "
                f"({test}, p = {p:.2g}; {eff_name} = {effect:.2f}; n = {len(a)} and {len(b)}).",
                {"mean_a": float(a.mean()), "mean_b": float(b.mean()), "p_value": float(p), "effect_size": float(effect),
                 "n_a": len(a), "n_b": len(b)},
                [m["key"], cat["key"]], ctx, len(a) + len(b), int(vals.isna().sum()), None, None,
                ["Compares the two largest groups only.", "Exploratory test (multiple-comparison caution).", "A difference is not a cause."],
                [f"Check whether {cat['display_name']} groups differ in other ways (time period, mix)."]))
    return out


def detect_distribution(ctx: Ctx) -> list[dict]:
    out = []
    m = ctx.measure
    if not m:
        return out
    v = numeric_values(ctx.frame, m).dropna()
    if len(v) < MIN_DIST_N:
        ctx.skipped.append({"detector": "distribution", "reason": f"Needs at least {MIN_DIST_N} values"})
        return out
    r = _run(ctx, operation="aggregate", metric_column=m["key"], aggregation="mean")
    r2 = _run(ctx, operation="aggregate", metric_column=m["key"], aggregation="median")
    if not r or not r2:
        return out
    mean, median = r["total"], r2["total"]
    skew = float(stats.skew(v))
    kurt = float(stats.kurtosis(v))
    gap = (mean - median) / abs(median) if median else None
    if abs(skew) > 1 or (gap is not None and abs(gap) >= 0.2):
        d = r["calculation_details"]
        out.append(_insight(
            "distribution", "notable" if abs(skew) > 2 else "info", min(1, abs(skew) / 4) * 0.5,
            f"{m['display_name']} is {'right' if skew > 0 else 'left'}-skewed: the mean ({fmt(mean, m)}) and median ({fmt(median, m)}) differ",
            f"Skewness {skew:.2f}, excess kurtosis {kurt:.2f}" + (f"; the mean is {pct(abs(gap))} {'above' if gap > 0 else 'below'} the median." if gap is not None else ".")
            + " Use the median as the typical value.",
            {"mean": mean, "median": median, "skewness": skew, "excess_kurtosis": kurt, "mean_median_gap": gap},
            [m["key"]], ctx, d["rows_used"], d["rows_skipped"], d, None,
            ["A few large values can pull the mean."], ["Look at the largest values (see outlier screening)."]))
    return out


def detect_quality(ctx: Ctx) -> list[dict]:
    out = []
    n = len(ctx.frame)
    for c in ctx.schema:
        if n and c["missing"] / n > 0.2:
            out.append(_insight("data_quality", "notable" if c["missing"] / n > 0.5 else "info", (c["missing"] / n) * 0.5,
                                f"{pct(c['missing'] / n)} of {c['display_name']} is empty",
                                f"{c['missing']:,} of {n:,} rows have no {c['display_name']}. Results that use this column skip those rows.",
                                {"missing": c["missing"], "rows": n, "missing_share": c["missing"] / n}, [c["key"]], ctx, n - c["missing"], c["missing"],
                                caveats=["Empty values are never treated as 0."], next_checks=["See the missing-values suggestion in Data cleaning."]))
        changed = c.get("cells_changed") or 0
        if n and changed / n > 0.1 and c["dtype"] != "string":
            out.append(_insight("data_quality", "info", (changed / n) * 0.2, f"Cleaning converted {pct(changed / n)} of {c['display_name']} values",
                                f"{changed:,} values were converted from text or normalized (for example currency symbols, separators or "
                                "date formats). The cleaning report lists every step with examples.",
                                {"cells_changed": changed, "rows": n}, [c["key"]], ctx, n, 0))
    unresolved = [s for s in (ctx.version.get("suggestions") or []) if s["type"] != "column_roles"]
    if unresolved:
        out.append(_insight("data_quality", "info", 0.05 * min(10, len(unresolved)),
                            f"{len(unresolved)} cleaning suggestion(s) not applied",
                            "These judgment calls (missing values, outliers, duplicates...) could change results if applied.",
                            {"suggestions": len(unresolved)}, [], ctx, n, 0))
    for step in (ctx.version.get("cleaning_report") or {}).get("steps", []):
        if step["step"] == "total_rows_kept":
            out.append(_insight("data_quality", "important", 0.9, f"{step['rows_affected']} 'Total' row(s) are included in the data",
                                "Rows labelled Total did not add up to the rows above, so they were kept and are counted in totals. Check them.",
                                {"rows": step["rows_affected"]}, [], ctx, n, 0))
    return out


# ------------------------------------------------------------------ orchestration

def _apply_date_range(frame: pd.DataFrame, table: pa.Table, date: dict | None, opts: InsightOptions):
    if not date or not (opts.date_from or opts.date_to):
        return frame, table, []
    lo = pd.Timestamp(opts.date_from) if opts.date_from else None
    hi = pd.Timestamp(opts.date_to) if opts.date_to else None
    mask = frame[date["key"]].notna()
    arr = table.column(date["key"]).cast(pa.timestamp("us"))
    amask = pc.is_valid(arr)
    if lo is not None:
        mask &= frame[date["key"]] >= lo
        amask = pc.and_(amask, pc.greater_equal(arr, pa.scalar(lo.to_pydatetime(), pa.timestamp("us"))))
    if hi is not None:
        mask &= frame[date["key"]] <= hi
        amask = pc.and_(amask, pc.less_equal(arr, pa.scalar(hi.to_pydatetime(), pa.timestamp("us"))))
    text = [f"{date['display_name']} between {opts.date_from or 'start'} and {opts.date_to or 'end'}"]
    return frame.loc[mask].reset_index(drop=True), table.filter(pc.fill_null(amask, False)), text


def generate_insights(frame: pd.DataFrame, table: pa.Table, version: dict, dataset: dict, opts: InsightOptions) -> dict:
    schema = version["schema"]
    by_key = {c["key"]: c for c in schema}
    roles = detect_roles(schema, dataset.get("column_roles"))
    if opts.focus_measure:
        if opts.focus_measure not in by_key or by_key[opts.focus_measure]["dtype"] not in NUMERIC:
            raise ValueError("The focus measure must be a numeric column of this dataset")
        measure = by_key[opts.focus_measure]
    else:
        measure = by_key.get(roles.get("revenue")) or next(
            (c for c in schema if c["dtype"] in NUMERIC and c["semantic_type"] not in ("id", "percent")), None)
    date = by_key.get(roles.get("date")) or next((c for c in schema if c["dtype"] in ("date", "datetime")), None)
    frame, table, ftext = _apply_date_range(frame, table, date, opts)
    cats = [c for c in schema if c["dtype"] == "string" and c["semantic_type"] == "category"
            and 2 <= c["unique"] <= MAX_CATEGORY_GROUPS]
    ctx = Ctx(frame, table, schema, version, by_key, measure, date, cats, ftext)
    found: list[dict] = []
    for det in (detect_contributors, detect_trends, detect_seasonality, detect_relationships, detect_segments,
                detect_distribution, detect_quality):
        found += det(ctx)
    # De-duplicate overlapping insights: keep the strongest per (family, columns).
    family = {"top_contributor": "share", "concentration": "share"}
    best: dict = {}
    for ins in found:
        k = (family.get(ins["type"], ins["type"] + ins["headline"]), tuple(sorted(ins["evidence"]["columns"])))
        if k not in best or ins["score"] > best[k]["score"]:
            best[k] = ins
    ranked = sorted(best.values(), key=lambda i: ({"important": 0, "notable": 1, "info": 2}[i["severity"]], -i["score"]))
    return {
        "insights": ranked[: opts.max_insights],
        "total_found": len(ranked),
        "skipped": ctx.skipped,
        "tests_run": ctx.tests_run,
        "measure": measure["key"] if measure else None,
        "date_column": date["key"] if date else None,
        "filters": ftext or ["None"],
        "dataset_version": version["version_number"],
        "note": "Exploratory analysis: several statistical tests were run, so treat individual p-values with caution.",
    }
