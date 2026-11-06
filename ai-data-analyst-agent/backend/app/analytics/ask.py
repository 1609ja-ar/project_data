"""Ask: a plain-language question becomes a validated query plan, computed like every other figure.

Two ways in, one way out:
- `parse_question` handles common phrasings without AI ("top 5 products by revenue in 2024",
  "monthly units in North", "average order value by region", "how many orders").
- With an AI provider, the model fills a fixed plan template (see `ai_prompt`); the plan is validated
  against the schema before anything runs. The model never produces numbers.
The plan is run with `run_verified`, and the one-line answer is written from the result by `answer_text`.
"""
from __future__ import annotations

import json
import re

import pandas as pd

from app.analytics.dashboard import (
    date_column, default_aggregation, dimension_candidates, measure_candidates,
)
from app.analytics.plan import NUMERIC
from app.analytics.profile import detect_roles

GRAIN_WORDS = [(r"\b(daily|per day|by day|each day)\b", "day"), (r"\b(weekly|per week|by week|each week)\b", "week"),
               (r"\b(monthly|per month|by month|each month|month by month|months?)\b", "month"),
               (r"\b(quarterly|per quarter|by quarter|quarters?)\b", "quarter"),
               (r"\b(yearly|annual(ly)?|per year|by year|each year|years)\b", "year")]
TREND_WORDS = r"\b(trend|over time|timeline|evolution|history|growth|change over|progress)\b"
COUNT_WORDS = r"\b(how many|count|number of|no\. of)\b"
MEAN_WORDS = r"\b(average|avg|mean|typical|per (order|record|row|transaction|sale))\b"
LOW_WORDS = r"\b(lowest|least|bottom|smallest|worst|fewest|minimum)\b"
SHARE_WORDS = r"\b(share|percentage|percent|proportion|split|mix|breakdown|composition)\b"
CHARTS = ("kpi", "line", "area", "bar", "horizontal_bar", "donut", "stacked_bar", "table")


class AskError(ValueError):
    """The question could not be turned into a plan; the message says what to try instead."""


def _words(s: str) -> str:
    return re.sub(r"[_\-]+", " ", s.lower())


def _mentioned(cols: list[dict], q: str) -> list[dict]:
    """Columns named in the question (display name or key, as whole words), longest names first."""
    found = []
    for c in sorted(cols, key=lambda c: -len(c["display_name"])):
        for name in {_words(c["display_name"]), _words(c["key"])}:
            if name and re.search(rf"\b{re.escape(name)}s?\b", q):
                found.append((q.find(name), c))
                break
    return [c for _, c in sorted(found, key=lambda t: t[0])]


def parse_question(question: str, frame: pd.DataFrame, schema: list[dict], dataset: dict) -> dict:
    """{plan, chart_type, filters} from a question, or AskError."""
    q = " " + _words(question) + " "
    roles = detect_roles(schema, dataset.get("column_roles"))
    measures = measure_candidates(schema)
    dims = [c for c in schema if c["dtype"] == "string" and 2 <= (c.get("unique") or 0) <= 1000]
    date = date_column(schema, roles)

    # Filters: category values and a year that appear in the question ("in North", "for 2024").
    filters, used_values = [], set()
    for d in dimension_candidates(schema):
        values = [str(v) for v in frame[d["key"]].dropna().unique()[:500]]
        hit = [v for v in values if len(v) > 1 and re.search(rf"\b{re.escape(_words(v))}\b", q)]
        if hit:
            filters.append({"column": d["key"], "op": "in", "value": hit})
            used_values.update(_words(v) for v in hit)
    year = re.search(r"\b(?:in|for|during|of)\s+((?:19|20)\d{2})\b", q)
    if year and date:
        y = int(year.group(1))
        filters += [{"column": date["key"], "op": "gte", "value": f"{y}-01-01"},
                    {"column": date["key"], "op": "lt", "value": f"{y + 1}-01-01"}]

    measure_hits = _mentioned(measures, q)
    count = bool(re.search(COUNT_WORDS, q)) and not measure_hits
    if measure_hits:
        measure = measure_hits[0]
    elif count or not measures:
        measure = None
    else:
        preferred = roles.get("revenue") or roles.get("quantity")
        measure = next((m for m in measures if m["key"] == preferred), measures[0])
    if measure is None:
        agg = "count"
    elif re.search(MEAN_WORDS, q):
        agg = "mean"
    elif re.search(r"\bmedian\b", q):
        agg = "median"
    elif re.search(r"\b(total|sum|overall)\b", q):
        agg = "sum"
    else:
        agg = default_aggregation(measure, roles)
    metric = {"aggregation": agg, **({"metric_column": measure["key"]} if measure else {})}

    # Group-by: dimensions named in the question, excluding ones only used as a filter value.
    group = [d for d in _mentioned(dims, q) if _words(d["display_name"]) not in used_values][:2]
    grain = next((g for pat, g in GRAIN_WORDS if re.search(pat, q)), None)
    wants_time = bool(date and (grain or re.search(TREND_WORDS, q) or (date and _mentioned([date], q))))

    if wants_time:
        plan = {"operation": "trend", "date_column": date["key"], "time_grain": grain or "auto", **metric,
                "group_by": [d["key"] for d in group[:1]]}
        chart = "stacked_bar" if group and agg in ("sum", "count") else "line" if group or agg != "sum" else "area"
    elif group:
        top = re.search(r"\b(?:top|bottom|first|best|worst)\s+(\d{1,3})\b", q)
        limit = int(top.group(1)) if top else (5 if re.search(r"\b(top|bottom|best|worst)\b", q) else 15)
        order = "asc" if re.search(LOW_WORDS, q) else "desc"
        if len(group) == 2:
            plan = {"operation": "aggregate", "group_by": [d["key"] for d in group], "limit": 200, **metric}
            chart = "stacked_bar"
        else:
            plan = {"operation": "top_n", "group_by": [group[0]["key"]], "limit": limit, "order": order, **metric}
            few = (group[0].get("unique") or 99) <= 6
            chart = "donut" if re.search(SHARE_WORDS, q) and few and agg in ("sum", "count") else "horizontal_bar"
    else:
        if not (measure_hits or count or re.search(r"\b(total|sum|average|avg|mean|how much|what is|what's)\b", q)):
            raise AskError("I could not tell what to measure. Try for example: \"total revenue by region\", "
                           "\"monthly orders\" or \"top 5 products by units\".")
        plan = {"operation": "aggregate", **metric}
        chart = "kpi"
    return {"plan": plan, "chart_type": chart, "filters": filters, "ignored": _ignored(q, frame, schema)}


STOP = {"the", "each", "every", "all", "total", "my", "our", "this", "that", "last", "time", "general", "overall", "detail",
        "order", "terms", "average", "sum", "count", "per", "which", "what", "data", "dataset", "table", "number"}


def _ignored(q: str, frame: pd.DataFrame, schema: list[dict]) -> list[str]:
    """Words after in/for/from/at that are not a column, a category value, a year or a time word:
    they had no effect on the answer, so the user is told instead of the word being silently dropped."""
    known = set(STOP)
    for c in schema:
        known.update(_words(c["display_name"]).split() + _words(c["key"]).split())
        if c["dtype"] == "string" and (c.get("unique") or 0) <= 1000:
            for v in frame[c["key"]].dropna().unique()[:1000]:
                known.update(_words(str(v)).split())
    out = []
    for m in re.finditer(r"\b(?:in|for|from|at)\s+([a-z][a-z0-9]{2,})\b", q):
        w = m.group(1)
        if w in known or w.rstrip("s") in known or any(re.search(p, f" {w} ") for p, _ in GRAIN_WORDS) or re.search(TREND_WORDS, f" {w} "):
            continue
        out.append(w)
    return out


def ai_prompt(question: str, schema: list[dict], dims: list[dict]) -> str:
    cols = [{"key": c["key"], "name": c["display_name"], "type": c["dtype"], "meaning": c["semantic_type"]} for c in schema]
    return (
        "Translate the question into a JSON query plan for this table. Use only these column keys.\n"
        f"Columns: {json.dumps(cols)}\n"
        f"Category columns (for group_by and filters): {json.dumps([d['key'] for d in dims])}\n\n"
        "Plan fields: operation (aggregate | top_n | trend), metric_column (numeric key, omit for counts), "
        "aggregation (sum | mean | median | count | nunique | min | max), group_by (0-2 category keys; for trend 0-1), "
        "date_column and time_grain (day | week | month | quarter | year) for trend, order (asc | desc), limit (1-50), "
        "filters ([{\"column\": key, \"op\": \"in\" | \"between\" | \"gte\" | \"lte\", \"value\": list or value}], use exact "
        "words from the question for category values and YYYY-MM-DD for dates), chart (kpi | line | area | horizontal_bar | "
        "donut | stacked_bar | table).\n"
        f"Question: {question}\n"
        "Reply with JSON only: {\"plan\": {...}, \"chart\": \"...\"}. If the question cannot be answered from these "
        "columns, reply {\"error\": \"<short reason>\"}."
    )


def parse_ai_plan(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise AskError("The AI reply was not a plan")
    data = json.loads(m.group(0))
    if data.get("error"):
        raise AskError(str(data["error"])[:200])
    plan = data.get("plan") or {}
    if not isinstance(plan, dict) or plan.get("operation") not in ("aggregate", "top_n", "trend"):
        raise AskError("The AI reply was not a usable plan")
    allowed = {"operation", "metric_column", "aggregation", "group_by", "date_column", "time_grain", "order", "limit"}
    filters = [f for f in plan.get("filters") or [] if isinstance(f, dict) and {"column", "op"} <= set(f)]
    clean = {k: v for k, v in plan.items() if k in allowed and v not in (None, "", [])}
    if clean.get("operation") == "trend" and clean.get("time_grain") not in ("day", "week", "month", "quarter", "year"):
        clean["time_grain"] = "auto"
    chart = data.get("chart") if data.get("chart") in CHARTS else None
    return {"plan": clean, "chart_type": chart, "filters": [{"column": f["column"], "op": f["op"], "value": f.get("value")} for f in filters][:6]}


def describe(plan: dict, by_key: dict, filters_text: list[str]) -> str:
    """How the question was understood, in words (shown under the answer)."""
    m = by_key.get(plan.get("metric_column")) if plan.get("metric_column") else None
    agg = plan.get("aggregation", "sum")
    what = "Number of records" if m is None and agg == "count" else (
        {"sum": "Total", "mean": "Average", "median": "Median", "min": "Minimum", "max": "Maximum",
         "nunique": "Distinct", "count": "Count of"}.get(agg, agg) + " " + (m["display_name"] if m else "records"))
    groups = [by_key[g]["display_name"] for g in plan.get("group_by") or []]
    if plan["operation"] == "trend":
        what += f" by {plan.get('time_grain', 'month')}" + (f", split by {groups[0]}" if groups else "")
    elif groups:
        what += " by " + " and ".join(groups)
        if plan["operation"] == "top_n":
            what += f" ({'bottom' if plan.get('order') == 'asc' else 'top'} {plan.get('limit', 10)})"
    if filters_text:
        what += " · " + "; ".join(filters_text)
    return what


MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def period_words(p: str) -> str:
    """2024-03 -> Mar 2024, 2024-Q1 -> Q1 2024, 2024-W09 -> week 9 of 2024, 2024-03-05 -> 5 Mar 2024."""
    s = str(p)
    if m := re.fullmatch(r"(\d{4})-(\d{2})", s):
        return f"{MONTHS[int(m.group(2)) - 1]} {m.group(1)}"
    if m := re.fullmatch(r"(\d{4})-Q([1-4])", s):
        return f"Q{m.group(2)} {m.group(1)}"
    if m := re.fullmatch(r"(\d{4})-W(\d{2})", s):
        return f"week {int(m.group(2))} of {m.group(1)}"
    if m := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s):
        return f"{int(m.group(3))} {MONTHS[int(m.group(2)) - 1]} {m.group(1)}"
    return s


def answer_text(result: dict, plan: dict, fmt) -> str:
    """One sentence from the verified result. `fmt(value, column)` formats numbers."""
    cols = result["columns"]
    rows = result["rows"]
    if not rows:
        return "No records match this question."
    ix = {c["key"]: i for i, c in enumerate(cols)}
    vcol = cols[ix["value"]]
    raw = result.get("metric_label", vcol.get("label", "Value"))
    # Engine labels ("Sum of Revenue", "Row count") read better as "Total revenue", "Number of records".
    label = ("Number of records" if raw == "Row count" else
             re.sub(r"^(Sum|Average|Median|Minimum|Maximum|Count|Distinct count) of ",
                    lambda m: {"Sum": "Total ", "Average": "Average ", "Median": "Median ", "Minimum": "Lowest ",
                               "Maximum": "Highest ", "Count": "Count of ", "Distinct count": "Distinct "}[m.group(1)], raw))
    label = label[0].upper() + label[1:].lower() if label else label
    if plan["operation"] == "trend":
        complete = [r for r in rows if not r[ix["partial"]]] if "partial" in ix else rows
        if plan.get("group_by"):
            return f"{label}: {len({r[0] for r in rows})} periods shown, split by {cols[2]['label']}."
        if len(complete) >= 2:
            first, last = complete[0], complete[-1]
            sentence = (f"{label} went from {fmt(first[ix['value']], vcol)} in {period_words(first[0])} "
                        f"to {fmt(last[ix['value']], vcol)} in {period_words(last[0])}")
            if first[ix["value"]] not in (None, 0) and last[ix["value"]] is not None:
                pct = (last[ix["value"]] - first[ix["value"]]) / abs(first[ix["value"]])
                sentence += f" ({pct:+.1%})"
            return sentence + "."
        return f"{label}: {fmt(rows[-1][ix['value']], vcol)} in {period_words(rows[-1][0])}."
    if not plan.get("group_by"):
        return f"{label}: {fmt(rows[0][ix['value']], vcol)}."
    top = rows[0]
    name = " / ".join("(empty)" if top[i] is None else str(top[i]) for i in range(len(plan["group_by"])))
    word = "lowest" if plan.get("order") == "asc" else "highest"
    text = f"{name} has the {word} {label.lower()}: {fmt(top[ix['value']], vcol)}"
    if "share" in ix and top[ix["share"]] is not None:
        text += f" ({top[ix['share']]:.1%} of the total)"
    groups = result.get("groups_total")
    if groups and len(plan["group_by"]) == 1:
        text += f", across {groups} {cols[0]['label']} values"
    return text + "."


def check_filter_values(frame: pd.DataFrame, by_key: dict, filters: list[dict]) -> None:
    """Category filter values must exist (case-insensitive match is mapped to the stored spelling)."""
    for f in filters:
        col = by_key.get(f["column"])
        if not col:
            raise AskError(f"There is no column '{f['column']}'")
        if col["dtype"] != "string" or f["op"] not in ("in", "eq"):
            continue
        stored = {str(v).lower(): str(v) for v in frame[col["key"]].dropna().unique()}
        vals = f["value"] if isinstance(f["value"], list) else [f["value"]]
        mapped = []
        for v in vals:
            if str(v).lower() not in stored:
                raise AskError(f"'{v}' does not appear in {col['display_name']}")
            mapped.append(stored[str(v).lower()])
        f["op"], f["value"] = "in", mapped


__all__ = ["AskError", "parse_question", "ai_prompt", "parse_ai_plan", "describe", "answer_text", "check_filter_values", "NUMERIC"]
