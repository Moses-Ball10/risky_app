"""Road-risk driving simulation: FastAPI backend. Run: python app.py, then open http://localhost:8000"""
import json
import os
from datetime import datetime

import uvicorn
import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from roadrisk import model as rmodel
from roadrisk import route as rroute
from roadrisk import weather as rweather

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
CFG = json.load(open(os.environ.get("ROADRISK_CONFIG", "config.json")))
if os.environ.get("ROADRISK_MODEL"):
    CFG["model_file"] = os.environ["ROADRISK_MODEL"]
REGISTRY = rmodel.Registry(CFG)

app = FastAPI(title="Road risk simulation")


class RouteReq(BaseModel):
    start: list[float] | None = None
    end: list[float] | None = None
    preset: str | None = None


class RiskReq(BaseModel):
    segments: list[dict]
    datetime: str
    weather: str = "dry"
    model: str | None = None


@app.get("/presets")
def presets():
    return CFG["presets"]


@app.get("/models")
def models():
    return {"default": CFG["model_file"], "models": REGISTRY.available()}


@app.get("/config")
def config():
    keys = ["weather_rule", "levels", "speeding_margin_kmh", "warning_distance_m", "warning_min_level", "base_rate", "timezone"]
    return {k: CFG[k] for k in keys}


@app.post("/route")
def route(req: RouteReq):
    start, end = req.start, req.end
    if req.preset:
        p = next((p for p in CFG["presets"] if p["id"] == req.preset), None)
        if not p:
            raise HTTPException(404, f"Unknown preset {req.preset}")
        start, end = p["start"], p["end"]
    if not start or not end:
        raise HTTPException(400, "Give start and end [lat, lon] or a preset id")
    try:
        return rroute.get_route(CFG, start, end)
    except rroute.ServiceError as e:
        raise HTTPException(502, str(e))


@app.post("/risk")
def risk(req: RiskReq):
    try:
        m = REGISTRY.get(req.model)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    try:
        return rmodel.compute_risk(m, CFG, req.segments, req.datetime, req.weather)
    except (KeyError, ValueError) as e:
        raise HTTPException(400, f"Bad request: {e}")


@app.get("/geocode")
def geocode(q: str):
    """Place search, limited to Algeria (Nominatim: free, no key, cached on disk)."""
    data = rroute.Http(CFG).get_json("Place search", CFG["apis"]["geocode"],
                                     params={"q": q, "format": "jsonv2", "countrycodes": "dz", "limit": 6})
    return [{"name": d["display_name"], "lat": float(d["lat"]), "lon": float(d["lon"])} for d in data]


@app.get("/weather")
def weather(lat: float, lon: float, at: str = "", manual: str = "live"):
    """Road weather status at a place and local time. manual=clear|rain|heavy|fog|snow skips the download."""
    when = datetime.fromisoformat(at) if at else datetime.now()
    try:
        rows = (rweather.manual_hourly(manual, when) if manual != "live"
                else rweather.fetch_hourly(CFG, lat, lon, when))
    except (requests.RequestException, KeyError, ValueError) as e:
        raise HTTPException(502, f"Weather service unavailable: {e}")
    st = rweather.status(rows, when, CFG["weather_rule"])
    if st is None:
        raise HTTPException(400, "No weather for that time (forecast covers about the last 3 days to tomorrow)")
    return st


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def index():
    return FileResponse("static/index.html")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", 8000)))
