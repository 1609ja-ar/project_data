"""Short-range forecast for a dashboard trend: an ordinary least-squares line over complete periods,
projected a few periods ahead with an 80% prediction interval.

Inputs are the verified period values of the trend tile. The projection itself is a model estimate and is
labelled as such in the UI; it is not a verified figure.
"""
from __future__ import annotations

import math

import pandas as pd
from scipy import stats

from app.analytics.engine import next_start, period_label

MIN_POINTS = 6
HORIZON = 3
LEVEL = 0.8


def linear_forecast(rows: list[list], grain: str, horizon: int = HORIZON) -> dict | None:
    """rows: trend rows [period, period_start, value, growth, partial]. None when there is too little data."""
    complete = [r for r in rows if not r[4] and r[2] is not None]
    n = len(complete)
    if n < MIN_POINTS:
        return None
    ys = [float(r[2]) for r in complete]
    xs = list(range(n))
    x_bar, y_bar = (n - 1) / 2, sum(ys) / n
    sxx = sum((x - x_bar) ** 2 for x in xs)
    slope = sum((x - x_bar) * (y - y_bar) for x, y in zip(xs, ys)) / sxx
    intercept = y_bar - slope * x_bar
    fitted = [intercept + slope * x for x in xs]
    sse = sum((y - f) ** 2 for y, f in zip(ys, fitted))
    sst = sum((y - y_bar) ** 2 for y in ys)
    s = math.sqrt(sse / (n - 2))
    t = float(stats.t.ppf(0.5 + LEVEL / 2, n - 2))
    non_negative = min(ys) >= 0

    # Forecast periods continue from the last complete period (a trailing partial period is forecast in full).
    start = pd.Timestamp(complete[-1][1])
    points = []
    for h in range(1, horizon + 1):
        start = next_start(start, grain)
        x0 = n - 1 + h
        y = intercept + slope * x0
        half = t * s * math.sqrt(1 + 1 / n + (x0 - x_bar) ** 2 / sxx)
        low, high = y - half, y + half
        if non_negative:
            y, low = max(y, 0.0), max(low, 0.0)
        points.append({"period": period_label(start, grain), "value": y, "low": low, "high": high})
    return {"method": "Linear trend", "level": LEVEL, "basis": n, "grain": grain,
            "slope": slope, "r2": (1 - sse / sst) if sst else None, "points": points}
