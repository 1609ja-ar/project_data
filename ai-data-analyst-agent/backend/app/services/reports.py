"""Data reports: verified facts (dashboard KPIs, charts, insights, data quality) plus a written narrative.

The narrative is written by the configured AI provider from the facts only (no rows are sent), and every
number it writes is checked against those facts; unmatched numbers are marked "[unverified]". Without a
provider, or if the call fails, the narrative comes from fixed templates over the same facts.
"""
from __future__ import annotations

import json
import logging
import math

from app.ai.base import AIError, ChatMessage
from app.ai.provider import check_numbers, extract_numbers
from app.core.money import format_money, group_number

log = logging.getLogger("app.reports")

SECTIONS = ("summary", "kpis", "charts", "insights", "quality", "columns")


def _fmt(v, col: dict | None = None) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "n/a"
    col = col or {}
    if col.get("semantic_type") == "currency":
        return format_money(v, col.get("currency"))
    if col.get("semantic_type") == "percent":
        return f"{v:.1%}"
    if isinstance(v, int) or (isinstance(v, float) and v.is_integer() and abs(v) < 1e15):
        return group_number(int(v))
    return group_number(v, 2)


def collect_numbers(obj) -> list[float]:
    """All numbers in a JSON-like structure (the allowed set for the AI number check)."""
    out: list[float] = []
    if isinstance(obj, bool) or obj is None:
        return out
    if isinstance(obj, (int, float)):
        return [float(obj)]
    if isinstance(obj, str):
        for tok in extract_numbers(obj):
            t = tok.replace(",", "").replace("−", "-").strip("$€£₹").rstrip("%")
            try:
                out.append(float(t))
                if tok.endswith("%"):
                    out.append(float(t) / 100)
            except ValueError:
                pass
        return out
    if isinstance(obj, dict):
        for v in obj.values():
            out += collect_numbers(v)
    elif isinstance(obj, list):
        for v in obj:
            out += collect_numbers(v)
    return out


def build_facts(dataset: dict, version: dict, computed: dict) -> dict:
    """The structured, verified content of a report (what gets stored and rendered)."""
    dash, ins = computed["dashboard"], computed["insights"]
    report = version.get("cleaning_report") or {}
    summary = report.get("summary") or {}
    schema = version["schema"]
    return {
        "dataset": {"name": dataset["filename"], "version": version["version_number"], "rows": dash["row_count"],
                    "rows_in_view": dash["rows_in_view"], "columns": len(schema),
                    "date_column": (dash.get("date_column") or {}).get("label"), "view_bounds": dash.get("view_bounds"),
                    "filters": dash.get("filters_applied") or []},
        "kpis": [{"id": k["id"], "label": k["label"], "value": k["value"], "column": k["column"], "change": k["change"],
                  "how_calculated": k["how_calculated"]} for k in dash["kpis"]],
        "charts": [t for t in dash["tiles"] if t["kind"] != "table"],
        "table": next((t for t in dash["tiles"] if t["kind"] == "table"), None),
        "insights": [{"id": i["id"], "type": i["type"], "severity": i["severity"], "headline": i["headline"],
                      "detail": i["detail"], "caveats": i["caveats"], "next_checks": i["possible_next_checks"],
                      "numbers": i["evidence"]["numbers"]} for i in ins["insights"]],
        "insights_note": "Insights use the date range only; category filters apply to KPIs and charts."
                         if (dash.get("options") or {}).get("filters") else None,
        "quality": {"score_before": version.get("quality_score_before"), "score_after": version.get("quality_score_after"),
                    "rows_before": summary.get("rows_before"), "rows_after": summary.get("rows_after"),
                    "rows_removed": summary.get("rows_removed"), "cells_changed": summary.get("cells_changed"),
                    "steps": [{"step": s["step"], "column": s.get("column"), "rows_affected": s["rows_affected"],
                               "description": s["description"]} for s in report.get("steps", [])[:12]]},
        "columns": [{"name": c["display_name"], "type": c["dtype"], "meaning": c["semantic_type"],
                     "empty": c.get("missing"), "distinct": c.get("unique")} for c in schema],
    }


def template_narrative(facts: dict) -> dict:
    """Deterministic narrative from the facts (used without AI, and as the fallback)."""
    ds, kpis = facts["dataset"], facts["kpis"]
    span = ds.get("view_bounds") or {}
    parts = [f"This report covers {ds['rows_in_view']:,} records from {ds['name']} (version {ds['version']})"
             + (f", dated {span['min']} to {span['max']}" if span.get("min") else "") + "."]
    if kpis:
        k = kpis[0]
        line = f"{k['label']} is {_fmt(k['value'], k['column'])}"
        if k.get("change"):
            c = k["change"]
            line += (f"; in {c['period']} it {'rose' if c['pct'] > 0 else 'fell'} {abs(c['pct']):.1%} "
                     f"compared with {c['previous_period']}")
        parts.append(line + ".")
    important = [i for i in facts["insights"] if i["severity"] == "important"]
    if important:
        parts.append("The most important finding: " + important[0]["headline"] + ".")
    findings = [i["headline"] for i in facts["insights"][:5]]
    recs = []
    for i in facts["insights"][:4]:
        recs += i["next_checks"][:1]
    q = facts["quality"]
    if q.get("cells_changed"):
        recs.append(f"Review the cleaning report: {q['cells_changed']:,} values were standardised before analysis.")
    return {"executive_summary": " ".join(parts), "key_findings": findings, "recommendations": recs[:5], "chart_notes": {}}


def _ai_payload(facts: dict) -> dict:
    return {
        "dataset": facts["dataset"],
        "kpis": [{"id": k["id"], "label": k["label"], "value": _fmt(k["value"], k["column"]),
                  "change": ({"percent": f"{k['change']['pct']:.1%}", "period": k["change"]["period"],
                              "previous_period": k["change"]["previous_period"]} if k.get("change") else None)} for k in facts["kpis"]],
        "charts": [{"id": t["id"], "title": t["title"], "rows": [[_fmt(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v
                                                                  for v in r] for r in t["chart"]["rows"][:12]],
                    "columns": [c["label"] for c in t["chart"]["columns"]]} for t in facts["charts"]],
        "insights": [{"headline": i["headline"], "detail": i["detail"], "caveats": i["caveats"]} for i in facts["insights"]],
        "quality": facts["quality"],
    }


async def ai_narrative(provider, facts: dict) -> tuple[dict, list[str]]:
    system = ("You are a senior data analyst writing a short business report from verified results. Use only the "
              "facts given; copy numbers exactly as written; never calculate new numbers or invent causes. Plain, "
              "confident business English. Reply with JSON only: {\"executive_summary\": \"3-5 sentences\", "
              "\"key_findings\": [\"up to 5 one-sentence findings\"], \"recommendations\": [\"up to 5 practical next "
              "steps\"], \"chart_notes\": {\"<chart id>\": \"one sentence on what the chart shows\"}}")
    payload = _ai_payload(facts)
    text = await provider.chat([ChatMessage("system", system), ChatMessage("user", json.dumps(payload, default=str))],
                               temperature=0.2, max_tokens=3500)
    start, end = text.find("{"), text.rfind("}")
    data = json.loads(text[start:end + 1]) if start >= 0 and end > start else {}
    if not isinstance(data, dict) or not data.get("executive_summary"):
        raise ValueError("The AI reply was not in the expected format")
    allowed = collect_numbers(payload) + collect_numbers(facts)
    bad: list[str] = []

    def chk(s) -> str:
        checked, b = check_numbers(str(s)[:1500], allowed)
        bad.extend(b)
        return checked

    chart_ids = {t["id"] for t in facts["charts"]}
    out = {"executive_summary": chk(data["executive_summary"]),
           "key_findings": [chk(x) for x in (data.get("key_findings") or [])[:5]],
           "recommendations": [chk(x) for x in (data.get("recommendations") or [])[:5]],
           "chart_notes": {k: chk(v) for k, v in (data.get("chart_notes") or {}).items() if k in chart_ids}}
    return out, bad


async def write_narrative(user: dict, facts: dict, use_ai: bool) -> dict:
    """{narrative, source, provider, unverified, note}"""
    from app.ai.provider import get_provider

    if use_ai:
        try:
            provider = get_provider(user)
            narrative, bad = await ai_narrative(provider, facts)
            if bad:
                log.warning("AI report narrative contained unverified numbers: %s", bad)
            return {"narrative": narrative, "source": "ai", "provider": provider.name, "model": getattr(provider, "model", None),
                    "unverified": bad, "note": None}
        except (AIError, ValueError) as e:
            note = e.message if isinstance(e, AIError) else str(e)
            return {"narrative": template_narrative(facts), "source": "template", "provider": None, "model": None,
                    "unverified": [], "note": f"AI writing was not available ({note}); the summary was written from templates."}
    return {"narrative": template_narrative(facts), "source": "template", "provider": None, "model": None,
            "unverified": [], "note": None}
