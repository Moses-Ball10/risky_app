# Road Risk Simulator (SolveX 3.0)

A simulated car drives a real Algerian road. A LightGBM model trained on accident data scores every 50 m of the route for the chosen date and hour. The weather is added through a small, capped rule. A simulated phone warns the driver before each risky spot: what it is, how far away, why it's risky, and what to do.

No paid service and no API key are used. OSRM, Overpass, Nominatim and Open-Meteo are free public services, and their answers are cached in `cache/`.

## Run
```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py                 # http://localhost:8000
python -m pytest -q tests
```

## Layout
```
app.py            API endpoints (FastAPI)
config.json       every threshold, URL, risk level and weather rule
models/           risk_model_nohist.txt + .json (the model in use)
roadrisk/
  geo.py          distances, bearings, curves, slopes, sun / darkness
  osm_map.py      OpenStreetMap tags → BAAC feature codes
  route.py        OSRM route + Overpass + elevation → 50 m segments
  model.py        load LightGBM, predict, x vs average, SHAP reasons
  weather.py      Open-Meteo status + capped weather rule
static/
  index.html      map UI: place search, car, sensors, chart, phone
  shared.js       driver words, spot names, colours, weather rule
tests/            pytest
```

## The model
`models/risk_model_nohist.txt` is a LightGBM model with no weather inputs.

| | |
|---|---|
| Inputs (14) | road: `catr plan vma int agg circ nbv prof infra` · time: `hour weekday month is_weekend is_dark` |
| Output | `p`, compared with the 0.2 base rate: `x = odds(p) / odds(0.2)` → "×2.3 vs average" |
| Levels | x < 0.7 low · < 1.5 medium · < 3 high · ≥ 3 very high |
| Reasons | SHAP (`pred_contrib=True`), top 3 positive contributions |

**To swap the model:** put `X.txt` and `X.json` (the json needs a `"features"` list) in `models/`. Then set `model_file` in `config.json`, or run `ROADRISK_MODEL=X.txt python app.py`, or pick the model in the UI.

**Known limit:** the model learned from French accidents (BAAC 2016-2024). Treat its comparisons (curve vs straight, night vs day) as useful, but not its exact × values.

## Pipeline
```
start + destination (search / preset / map click)
  → OSRM route → 50 m segments
  → OpenStreetMap: road type, speed limit, lanes, one-way, roundabout, junctions, rail crossing, bridge/tunnel, town
  → curve (bearing change over 150 m) and slope (Open-Meteo elevation)
  → time features + darkness from the sun's position
  → LightGBM p → x → level + SHAP reasons
  → weather rule → spots → phone notification
```

**Weather rule (not the model)**
- **What it looks at:**
  - rain intensity, and how long it has been raining;
  - first rain after 48 dry hours;
  - road still wet up to 2 h after the rain stops;
  - fog, snow and strong wind.
- **How it adds risk:** each condition adds a little (`config.json → weather_rule`).
  - The total is capped at **×1.5**.
  - Curves and slopes get a bit more, still under the cap.
  - Weather raises a segment by **one level at most**.

**Warnings**
- **Risk that covers the whole route** (night, weekend, weather) is shown once on the phone.
- **Notifications are only for spots:**
  - a road feature: curve, junction, roundabout, rail crossing, bridge or slope;
  - or a stretch at least 1.3× the route's middle value.

  Each one gives the distance, the reasons and advice.
- **Speeding** (limit + 10 km/h) raises the level by one step.
- **Language:** Arabic (default, right to left), French or English, from the *Language* buttons. The notification only shows the risk (spot + distance) and the action (speed + one tip, or the weather when it raises the risk); 🔊 Voice reads the same words.

## API
| Method | Path | Input | Output |
|---|---|---|---|
| GET | `/config` | – | levels, weather rule, speeding margin, warning distance |
| GET | `/models` | – | available models and their features |
| GET | `/presets` | – | demo routes |
| GET | `/geocode?q=Blida` | place text | `[{name, lat, lon}]` (Algeria) |
| POST | `/route` | `{start:[lat,lon], end:[lat,lon]}` or `{preset}` | `{coords, length, segments:[{i, s, lat, lon, coords, turn, curve_speed, features, osm}]}` |
| POST | `/risk` | `{segments:[{i, lat, lon, features}], datetime, model?}` | `{segments:[{i, p, x, level, is_dark, model_features, top_reasons}]}` |
| GET | `/weather?lat=&lon=&at=&manual=live` | `manual` = live, clear, rain, heavy, fog or snow | `{icon, label, rain_mm, spell_h, since_rain_h, rain_in_h, factor, factor_hard, reasons}` |

**Final risk of a segment:**
```
x     = model_x × (factor_hard on curves/slopes, else factor)
level = min(model_level + 1, level_of(x))
```

**Example:**
```python
import requests
B = "http://localhost:8000"
route = requests.post(f"{B}/route", json={"start": [36.47, 2.83], "end": [36.43, 2.89]}).json()
segs = [{k: s[k] for k in ("i", "lat", "lon", "features")} for s in route["segments"]]
risk = requests.post(f"{B}/risk", json={"segments": segs, "datetime": "2026-10-30T02:00"}).json()
```

## 2-minute demo
1. **Search a route:** *From* "Blida", *To* "Chréa" (press Enter and pick each place), or load the **Mountain road** preset.
2. **Day vs night:** click **14:00**, then **02:00**. The road turns orange and red, and the phone shows "Whole route ×N now: late at night".
3. **Drive:** press ▶ at 5×. Before each curve or junction, the phone slides in a short notification, for example "منعطف يساراً بعد 200 م · خفّف إلى 50 🌧 طريق مبلل". Switch Arabic / Français / English with the Language buttons.
4. **Weather:** choose **🔁 Demo: change every 5 s**. The colours and warnings update live.
5. **Behaviour:** set the driver to **Speeding +30%**. The level goes up one step.
6. **Explain:** click a red segment to see the model ×, the weather × and the top factors.
