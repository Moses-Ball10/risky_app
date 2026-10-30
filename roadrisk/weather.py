"""Road weather status (Open-Meteo forecast, free, no key) and a fixed-rule risk factor.

The weather is a rule on top of the model, not a model input. It is kept small on purpose:
the total factor is capped (config weather_rule.cap), and the app lets it raise a segment
by one level at most, so the road and time effects from the model stay in charge.
"""
import time
from datetime import datetime, timedelta

import requests

# WMO weather codes used by Open-Meteo
FOG_CODES = {45, 48}
SNOW_CODES = {71, 73, 75, 77, 85, 86}
STORM_CODES = {95, 96, 99}

_CACHE = {}          # (lat, lon, day) -> (fetched_at, hourly)
CACHE_TTL_S = 15 * 60

# Manual conditions for demos / offline: one "now" hour plus the hours before it.
MANUAL = {
    "clear": {"rain": 0, "snow": 0, "vis": 20000, "code": 0, "hours": 0},
    "rain":  {"rain": 1.5, "snow": 0, "vis": 8000, "code": 61, "hours": 1},
    "heavy": {"rain": 6.0, "snow": 0, "vis": 3000, "code": 65, "hours": 4},
    "fog":   {"rain": 0, "snow": 0, "vis": 150, "code": 45, "hours": 0},
    "snow":  {"rain": 0, "snow": 1.2, "vis": 1500, "code": 73, "hours": 2},
}


def fetch_hourly(cfg, lat, lon, when):
    """Hourly weather around `when` (local time), cached 15 min. Returns a list of dicts or raises."""
    key = (round(lat, 2), round(lon, 2), when.date().isoformat())
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL_S:
        return hit[1]
    r = requests.get(cfg["apis"]["weather"], timeout=cfg["apis"]["timeout_s"], headers={"User-Agent": cfg["user_agent"]},
                     params={"latitude": lat, "longitude": lon, "timezone": cfg["timezone"],
                             "hourly": "rain,snowfall,visibility,weather_code,wind_gusts_10m",
                             "start_date": (when - timedelta(days=3)).date().isoformat(),
                             "end_date": (when + timedelta(days=1)).date().isoformat()})
    r.raise_for_status()
    h = r.json()["hourly"]
    rows = [{"time": datetime.fromisoformat(t), "rain": h["rain"][k] or 0,
             "snow": h["snowfall"][k] or 0, "vis": h["visibility"][k], "code": h["weather_code"][k] or 0,
             "gust": h["wind_gusts_10m"][k] or 0} for k, t in enumerate(h["time"])]
    _CACHE[key] = (time.time(), rows)
    return rows


def manual_hourly(kind, when):
    m = MANUAL.get(kind, MANUAL["clear"])
    when = when.replace(minute=0, second=0, microsecond=0)
    rows = []
    for k in range(-72, 3):
        on = -m["hours"] < k <= 0
        rows.append({"time": when + timedelta(hours=k), "rain": m["rain"] if on else 0, "snow": m["snow"] if on else 0,
                     "vis": m["vis"] if k == 0 else 20000, "code": m["code"] if on or k == 0 else 0, "gust": 0})
    return rows


def status(rows, when, rule):
    """Weather status at `when` and the capped risk factor. `rule` = config weather_rule."""
    when = when.replace(minute=0, second=0, microsecond=0, tzinfo=None)
    idx = next((k for k, x in enumerate(rows) if x["time"] == when), None)
    if idx is None:
        return None
    now = rows[idx]
    wet = lambda x: x["rain"] >= 0.1 or x["snow"] > 0          # noqa: E731
    # how long it has been raining (or snowing) without a break, and how long since it stopped
    spell = 0
    while idx - spell >= 0 and wet(rows[idx - spell]):
        spell += 1
    since = None
    if spell == 0:
        k = idx - 1
        while k >= 0 and not wet(rows[k]):
            k -= 1
        since = idx - k if k >= 0 else None
    dry_before = 0                                              # dry hours before the current spell
    k = idx - spell
    while k >= 0 and not wet(rows[k]):
        dry_before += 1
        k -= 1
    next_rain = next((k - idx for k in range(idx + 1, min(len(rows), idx + 3)) if wet(rows[k])), None)

    parts = []                                                  # (words, advice, added risk)
    vis = now["vis"] if now["vis"] is not None else 20000
    if now["snow"] > 0 or now["code"] in SNOW_CODES:
        parts.append(("snow", "snow", "Brake gently, no sudden moves", rule["snow_heavy"] if now["snow"] >= 1 else rule["snow"]))
    elif now["rain"] >= 0.1:
        add = rule["rain_heavy"] if now["rain"] >= 4 else rule["rain"] if now["rain"] >= 1 else rule["rain_light"]
        if spell >= 3:
            add += rule["long_spell"]
        key, words = ("heavy", "heavy rain") if now["rain"] >= 4 else ("rain", "wet road")
        if spell <= 2 and dry_before >= 48:
            add += rule["first_rain"]
            key, words = "first_rain", "first rain, slippery road"
        parts.append((key, words, "Keep double distance", add))
    elif since is not None and since <= 2:
        parts.append(("still_wet", "road still wet", "Keep double distance", rule["still_wet"]))
    if vis < 1000 or now["code"] in FOG_CODES:
        parts.append(("fog", "fog", "Low beams on, slow down", rule["fog_dense"] if vis < 200 else rule["fog"]))
    if now["gust"] >= 60 or now["code"] in STORM_CODES:
        parts.append(("wind", "strong wind", "Hold the wheel firmly", rule["wind"]))

    add = min(rule["cap"] - 1, sum(p[3] for p in parts))
    if now["snow"] > 0 or now["code"] in SNOW_CODES:
        icon, label = "❄️", "Snow"
    elif now["rain"] >= 4:
        icon, label = "⛈", "Heavy rain"
    elif now["rain"] >= 0.1:
        icon, label = "🌧", "Rain"
    elif vis < 1000 or now["code"] in FOG_CODES:
        icon, label = "🌫", "Fog"
    elif since is not None and since <= 2:
        icon, label = "🌦", "Wet after rain"
    else:
        icon, label = "☀️", "Clear"
    return {
        "time": when.isoformat(), "icon": icon, "label": label,
        "rain_mm": round(now["rain"], 1), "snow_cm": round(now["snow"], 1), "visibility_m": vis,
        "spell_h": spell, "since_rain_h": since, "rain_in_h": next_rain,
        "factor": round(1 + add, 2),
        "factor_hard": round(min(rule["cap"], 1 + add * rule["hard_mult"]), 2),   # curves and slopes
        "reasons": [{"key": k, "words": w, "todo": t} for k, w, t, _ in parts],   # key -> translations in shared.js
    }
