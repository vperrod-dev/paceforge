"""Environmental pace normalization — heat/humidity cost of a run.

Published heat-degradation data (e.g. Ely et al. 2007 marathon-weather analysis;
TrainingPeaks/RunnersConnect heat-pace tables) converges on roughly 1-3% pace
cost per 5°C above ~15°C for sustained running, worse when humidity is high.
This module turns stored per-activity weather into a multiplicative factor so a
5:30/km in 28°C can be compared honestly with a 5:20/km in 12°C.

Deliberately conservative and piecewise — a comparison aid, not physiology.
"""

from __future__ import annotations

# (threshold °C effective-temp, added fractional pace cost per °C above it)
_BANDS = ((15.0, 0.002), (22.0, 0.003), (28.0, 0.005))
_MAX_FACTOR = 1.12  # cap: beyond ~+12% the run was survival, not pacing


def pace_adjustment_factor(temp_c: float | None, humidity: float | None = None) -> float:
    """Multiplicative pace cost of the conditions (1.0 = neutral, 1.04 = 4% slower).

    Humidity above 60% raises the *effective* temperature (~+1°C per 10% RH over
    60%), approximating the wet-bulb effect on evaporative cooling.
    """
    if temp_c is None:
        return 1.0
    effective = float(temp_c)
    if humidity and humidity > 60:
        effective += (float(humidity) - 60.0) / 10.0
    cost = 0.0
    for i, (threshold, per_degree) in enumerate(_BANDS):
        upper = _BANDS[i + 1][0] if i + 1 < len(_BANDS) else float("inf")
        if effective > threshold:
            cost += (min(effective, upper) - threshold) * per_degree
    return min(1.0 + cost, _MAX_FACTOR)


def adjusted_pace(pace_sec_per_km: float | None, weather: dict | None) -> float | None:
    """The equivalent cool-conditions pace (sec/km) for a pace run in `weather`.

    Hot-day paces come back FASTER (the conditions cost you time); neutral
    weather returns the pace unchanged. Returns None when pace is missing.
    """
    if not pace_sec_per_km:
        return None
    w = weather or {}
    factor = pace_adjustment_factor(w.get("temp_c"), w.get("humidity"))
    return round(pace_sec_per_km / factor, 1)
