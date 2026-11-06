"""Public (JSON-safe) views of stored documents. Never expose storage paths or internal fields."""
from __future__ import annotations


def _iso(v):
    return v.isoformat() if v is not None and hasattr(v, "isoformat") else v


def _sid(v):
    return str(v) if v is not None else None


def dataset_public(d: dict) -> dict:
    return {
        "id": str(d["_id"]),
        "filename": d["filename"],
        "file_type": d["file_type"],
        "size_bytes": d["size_bytes"],
        "raw_sha256": d.get("raw_sha256"),
        "active_version_id": _sid(d.get("active_version_id")),
        "cleaning_status": d.get("cleaning_status", "pending"),
        "cleaning_stage": d.get("cleaning_stage"),
        "cleaning_error": d.get("cleaning_error"),
        "row_count": d.get("row_count"),
        "column_count": d.get("column_count"),
        "raw_row_count": d.get("raw_row_count"),
        "raw_column_count": d.get("raw_column_count"),
        "sheet": d.get("sheet"),
        "sheets": d.get("sheets"),
        "created_at": _iso(d.get("created_at")),
        "source": ({"kind": d["source"].get("kind"), "url": d["source"].get("url"),
                    "fetched_at": _iso(d["source"].get("fetched_at")), "changed_at": _iso(d["source"].get("changed_at"))}
                   if d.get("source") else None),
    }


def version_public(v: dict, include_report: bool = False) -> dict:
    out = {
        "id": str(v["_id"]),
        "dataset_id": str(v["dataset_id"]),
        "version_number": v["version_number"],
        "kind": v["kind"],
        "parent_version_id": _sid(v.get("parent_version_id")),
        "row_count": v["row_count"],
        "column_count": v["column_count"],
        "schema": v["schema"],
        "cleaning_options": v.get("cleaning_options"),
        "quality_score_before": v.get("quality_score_before"),
        "quality_score_after": v.get("quality_score_after"),
        "created_at": _iso(v.get("created_at")),
    }
    if include_report:
        out["cleaning_report"] = v.get("cleaning_report")
    return out


def analysis_public(a: dict) -> dict:
    return {
        "id": str(a["_id"]),
        "dataset_id": _sid(a.get("dataset_id")),
        "version_id": _sid(a.get("version_id")),
        "analysis_type": a["analysis_type"],
        "question": a.get("question"),
        "dataset_name": a.get("dataset_name"),
        "result_summary": a.get("result_summary_brief") or None,
        "created_at": _iso(a.get("created_at")),
    }
