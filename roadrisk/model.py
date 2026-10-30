"""Model loading, feature table construction, risk levels and SHAP explanations."""
import glob
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from . import geo

CODES = {
    "catr": {1: "motorway", 2: "national road", 3: "departmental road", 4: "municipal road"},
    "circ": {1: "one-way road", 2: "two-way road", 3: "separated carriageways"},
    "agg": {1: "outside town", 2: "in town"},
    "plan": {1: "straight road", 2: "left curve", 3: "right curve", 4: "S-bend"},
    "int": {1: "no intersection", 2: "X intersection", 3: "T intersection", 4: "Y intersection",
            5: "intersection with 5+ branches", 6: "roundabout", 8: "railway crossing", 9: "intersection"},
    "prof": {1: "flat road", 2: "slope", 3: "hilltop", 4: "bottom of a hill"},
    "infra": {0: "no special structure", 1: "tunnel", 2: "bridge", 3: "interchange ramp", 7: "toll", 8: "road works"},
}
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def x_vs_average(p, base_rate=0.2):
    p = np.clip(np.asarray(p, dtype=float), 1e-9, 1 - 1e-9)
    return (p / (1 - p)) / (base_rate / (1 - base_rate))


def level_of(x, levels):
    """Index into the configured levels list (0 = low ... 3 = very high)."""
    for i, lv in enumerate(levels):
        if lv["max"] is None or x < lv["max"]:
            return i
    return len(levels) - 1


def describe(feature, value):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return f"{feature} unknown"
    v = int(value) if float(value).is_integer() else value
    if feature in CODES:
        return CODES[feature].get(v, f"{feature}={v}")
    return {
        "vma": f"speed limit {v} km/h",
        "nbv": f"{v} lane(s)",
        "hour": f"time of day ({v}h)",
        "weekday": f"day of week ({DAYS[v] if 0 <= v < 7 else v})",
        "month": f"month ({v})",
        "is_weekend": "weekend" if v else "weekday",
        "is_holiday": "public holiday" if v else "not a holiday",
        "is_dark": "driving in the dark" if v else "daylight",
        "is_rain": "rain" if v else "no rain",
        "rain_mm": f"rain {v} mm/h",
        "rain_3h_mm": f"rain {v} mm over 3h",
        "is_snow": "snow" if v else "no snow",
        "is_storm": "storm" if v else "no storm",
        "is_fog": "fog" if v else "no fog",
    }.get(feature, f"{feature}={v}")


class RiskModel:
    def __init__(self, txt_path):
        import lightgbm as lgb
        self.path = txt_path
        self.booster = lgb.Booster(model_file=txt_path)
        meta_path = os.path.splitext(txt_path)[0] + ".json"
        meta = json.load(open(meta_path)) if os.path.exists(meta_path) else {}
        self.meta = meta
        self.features = meta.get("features") or self.booster.feature_name()
        self.categorical = meta.get("categorical", [])

    def frame(self, rows):
        df = pd.DataFrame([{f: r.get(f, np.nan) for f in self.features} for r in rows], columns=self.features)
        df = df.apply(pd.to_numeric, errors="coerce").astype(float)
        for c in self.categorical:
            df[c] = df[c].astype("category")
        return df

    def predict(self, rows):
        return self.booster.predict(self.frame(rows))

    def contributions(self, rows):
        """SHAP contributions in log-odds; last column is the bias."""
        return np.asarray(self.booster.predict(self.frame(rows), pred_contrib=True))


class Registry:
    def __init__(self, cfg):
        self.cfg = cfg
        self._cache = {}

    def available(self):
        out = []
        for p in sorted(glob.glob(os.path.join(self.cfg["models_dir"], "*.txt"))):
            j = os.path.splitext(p)[0] + ".json"
            if os.path.exists(j):
                try:
                    meta = json.load(open(j))
                except ValueError:
                    continue
                if "features" in meta:
                    out.append({"file": os.path.basename(p), "features": meta["features"],
                                "with_weather": meta.get("with_weather", False), "test_auc": meta.get("test_auc")})
        return out

    def get(self, name=None):
        name = os.path.basename(name or self.cfg["model_file"])
        if name not in self._cache:
            path = os.path.join(self.cfg["models_dir"], name)
            if not os.path.exists(path):
                raise FileNotFoundError(f"Model file not found: {name}")
            self._cache[name] = RiskModel(path)
        return self._cache[name]


def time_features(lat, lon, local_dt, cfg):
    return {
        "hour": local_dt.hour,
        "weekday": local_dt.weekday(),
        "month": local_dt.month,
        "is_weekend": int(local_dt.weekday() >= 5),
        "is_holiday": int(local_dt.strftime("%m-%d") in cfg["holidays_mmdd"]),
        "is_dark": geo.is_dark(lat, lon, local_dt, cfg["dark_sun_elevation_deg"]),
    }


def compute_risk(model, cfg, segments, dt_str, weather="dry"):
    tz = ZoneInfo(cfg["timezone"])
    local_dt = datetime.fromisoformat(dt_str)
    local_dt = local_dt.replace(tzinfo=tz) if local_dt.tzinfo is None else local_dt.astimezone(tz)
    wx = cfg["weather_features"].get(weather, cfg["weather_features"]["dry"])
    rows = []
    for s in segments:
        r = dict(s["features"])
        r.update(time_features(s["lat"], s["lon"], local_dt, cfg))
        r.update(wx)
        rows.append(r)
    p = model.predict(rows)
    xs = x_vs_average(p, cfg["base_rate"])
    contrib = model.contributions(rows)
    out = []
    for k, r in enumerate(rows):
        c = contrib[k, :-1]
        order = np.argsort(-c)
        top = [{"feature": model.features[j], "value": r.get(model.features[j]),
                "contribution": round(float(c[j]), 3),
                "text": describe(model.features[j], r.get(model.features[j]))}
               for j in order[:3] if c[j] > 0]
        out.append({"i": s_i(segments[k], k), "p": round(float(p[k]), 4), "x": round(float(xs[k]), 2),
                    "level": level_of(xs[k], cfg["levels"]), "is_dark": r["is_dark"],
                    "model_features": {f: (None if r.get(f) is None or (isinstance(r.get(f), float) and np.isnan(r[f])) else r[f])
                                       for f in model.features},
                    "top_reasons": top})
    uses_weather = any(f in model.features for f in wx)
    return {"segments": out, "uses_weather": uses_weather, "model": os.path.basename(model.path),
            "datetime": local_dt.isoformat()}


def s_i(seg, k):
    return seg.get("i", k)
