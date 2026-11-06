"""Automated insights (Phase 4d): deterministic detectors, ranked and explained with the numbers behind them.

Headlines come from fixed templates (no AI). Aggregates come from `run_verified` (Pandas + DuckDB);
statistics (regression, correlation, group tests) use SciPy on those values. Thresholds: docs/METRICS.md.
"""
from app.analytics.insights.engine import InsightOptions, generate_insights

__all__ = ["InsightOptions", "generate_insights"]
