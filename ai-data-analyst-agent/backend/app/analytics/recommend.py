"""Chart suggestions ("auto charts").

Deterministic rules turn the dataset's column types into a menu of valid chart plans, each with a reason.
An AI provider, when configured, may only *choose and order* items from that menu (by id) and explain the
choice; it never writes a plan or a number. Without AI, the rule scores decide. Every chart that is shown
is then computed by `run_verified` like any other figure.
"""
from __future__ import annotations

import hashlib
import json
import re

from app.analytics.dashboard import (
    MAX_SHARE_GROUPS, MAX_STACK_GROUPS, date_column, default_aggregation, dimension_candidates, measure_candidates,
)
from app.analytics.profile import detect_roles

MAX_SUGGESTIONS = 6
MAX_MENU = 24


def _cid(plan: dict, chart_type: str) -> str:
    return hashlib.sha256(json.dumps([plan, chart_type], sort_keys=True).encode()).hexdigest()[:12]


def _label(col: dict | None, agg: str) -> str:
    if col is None:
        return "Records"
    return ("Total " if agg == "sum" else "Average ") + col["display_name"]


def candidates(schema: list[dict], dataset: dict) -> list[dict]:
    """Every chart that makes sense for these columns, scored by rule. Pure: needs the schema only."""
    roles = detect_roles(schema, dataset.get("column_roles"))
    measures = measure_candidates(schema)[:3]
    dims = dimension_candidates(schema)[:4]
    date = date_column(schema, roles)
    out: list[dict] = []

    def add(plan, chart_type, title, reason, family, score):
        plan = {"aggregation": "count", **plan} if "metric_column" not in plan else plan
        out.append({"id": _cid(plan, chart_type), "plan": plan, "chart_type": chart_type, "title": title,
                    "reason": reason, "family": family, "score": round(score, 3)})

    metrics = [(m, default_aggregation(m, roles)) for m in measures] or [(None, "count")]
    for rank, (m, agg) in enumerate(metrics):
        base = {"metric_column": m["key"], "aggregation": agg} if m else {"aggregation": "count"}
        label = _label(m, agg)
        w = 1.0 - 0.15 * rank  # the primary measure ranks first
        if date:
            add({"operation": "trend", "date_column": date["key"], "time_grain": "auto", **base}, "area" if agg == "sum" else "line",
                f"{label} over time", f"{date['display_name']} gives a time axis, so a line shows direction, growth and seasonality.",
                "trend", 0.95 * w)
        for i, d in enumerate(dims):
            dw = w * (1.0 - 0.1 * i)
            add({"operation": "top_n", "group_by": [d["key"]], "limit": 10, **base}, "horizontal_bar",
                f"{label} by {d['display_name']}", f"Ranks {d['display_name']} values so the largest and smallest stand out.",
                "ranking", 0.85 * dw)
            if agg == "sum" and d["unique"] <= MAX_SHARE_GROUPS:
                add({"operation": "aggregate", "group_by": [d["key"]], "limit": MAX_SHARE_GROUPS, **base}, "donut",
                    f"Share of {label.lower()} by {d['display_name']}",
                    f"Only {d['unique']} {d['display_name']} values, so a part-to-whole view reads clearly.", "share", 0.7 * dw)
            if m is not None and agg == "sum":
                add({"operation": "compare", "group_by": [d["key"]], "metric_column": m["key"], "aggregation": "mean", "limit": 10},
                    "bar", f"Average {m['display_name']} by {d['display_name']}",
                    "Totals favour large groups; the average per record compares groups fairly.", "average", 0.6 * dw)
            if date and d["unique"] <= MAX_STACK_GROUPS:
                add({"operation": "trend", "date_column": date["key"], "time_grain": "auto", "group_by": [d["key"]], **base},
                    "stacked_bar" if agg in ("sum", "count") else "line", f"{label} over time by {d['display_name']}",
                    f"Shows how each {d['display_name']} contributes to the trend.", "composition", 0.75 * dw)
        if len(dims) >= 2:
            a, b = dims[0], next((d for d in dims[1:] if d["unique"] <= MAX_STACK_GROUPS), None)
            if b is not None and a["unique"] <= 12:
                add({"operation": "aggregate", "group_by": [a["key"], b["key"]], "limit": 200, **base},
                    "stacked_100_bar" if agg == "sum" else "grouped_bar", f"{b['display_name']} mix within each {a['display_name']}",
                    f"Compares the {b['display_name']} mix across {a['display_name']} values.", "mix", 0.55 * w)
    # De-duplicate and keep the strongest ideas.
    seen, menu = set(), []
    for c in sorted(out, key=lambda c: -c["score"]):
        if c["id"] not in seen:
            seen.add(c["id"])
            menu.append(c)
    return menu[:MAX_MENU]


def rule_pick(menu: list[dict], n: int = MAX_SUGGESTIONS) -> list[dict]:
    """Top scores, at most two per family so the selection covers different questions."""
    picked, per_family = [], {}
    for c in menu:
        if per_family.get(c["family"], 0) >= 2:
            continue
        picked.append({**c, "why": c["reason"], "source": "rules"})
        per_family[c["family"]] = per_family.get(c["family"], 0) + 1
        if len(picked) == n:
            break
    return picked


def ai_prompt(schema: list[dict], menu: list[dict], filename: str) -> str:
    cols = [{"name": c["display_name"], "type": c["dtype"], "meaning": c["semantic_type"], "distinct": c.get("unique"),
             "empty": c.get("missing")} for c in schema]
    options = [{"id": c["id"], "chart": c["chart_type"], "title": c["title"], "shows": c["reason"]} for c in menu]
    return (f"Dataset file: {filename}\nColumns: {json.dumps(cols)}\n\nChart options: {json.dumps(options)}\n\n"
            f"Choose up to {MAX_SUGGESTIONS} options that together give the most useful overview for a business user of "
            "this dataset, most important first. Prefer variety (trend, ranking, composition). Reply with JSON only: "
            '{"charts": [{"id": "<option id>", "why": "<one sentence, no numbers>"}]}')


def parse_ai_pick(text: str, menu: list[dict]) -> list[dict]:
    """Keeps only ids that exist in the menu; anything else the model wrote is ignored."""
    by_id = {c["id"]: c for c in menu}
    m = re.search(r"\{.*\}", text, re.S)
    data = None
    if m:
        try:
            data = json.loads(m.group(0))
        except ValueError:
            data = None
    if not isinstance(data, dict):
        # A reply cut off by the token limit is not valid JSON; keep the complete {"id": ..., "why": ...} items.
        items = [{"id": i, "why": w} for i, w in re.findall(r'"id"\s*:\s*"([0-9a-f]{12})"\s*(?:,\s*"why"\s*:\s*"((?:[^"\\]|\\.)*)")?', text)]
        data = {"charts": items}
    picked, seen = [], set()
    for item in data.get("charts", []):
        cid = str(item.get("id", "")) if isinstance(item, dict) else ""
        if cid in by_id and cid not in seen:
            seen.add(cid)
            why = str(item.get("why") or by_id[cid]["reason"])[:240]
            picked.append({**by_id[cid], "why": why, "source": "ai"})
        if len(picked) == MAX_SUGGESTIONS:
            break
    return picked
