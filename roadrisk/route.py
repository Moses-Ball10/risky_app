"""Route fetching (OSRM), road data (Overpass), elevation (Open-Meteo) and per-segment feature building."""
import hashlib
import json
import math
import os

import numpy as np
import requests

from . import geo, osm_map


class ServiceError(Exception):
    pass


class Http:
    def __init__(self, cfg):
        self.cfg = cfg
        self.dir = os.path.join(cfg["cache_dir"], "http")
        os.makedirs(self.dir, exist_ok=True)
        self.s = requests.Session()
        self.s.headers["User-Agent"] = cfg["user_agent"]

    def _path(self, key):
        return os.path.join(self.dir, hashlib.sha1(key.encode()).hexdigest() + ".json")

    def get_json(self, name, urls, params=None, data=None):
        urls = urls if isinstance(urls, list) else [urls]
        key = json.dumps([urls[0], params, data], sort_keys=True)
        p = self._path(key)
        if os.path.exists(p):
            with open(p) as f:
                return json.load(f)
        last = None
        for url in urls:
            try:
                if data is not None:
                    r = self.s.post(url, data=data, timeout=self.cfg["apis"]["timeout_s"])
                else:
                    r = self.s.get(url, params=params, timeout=self.cfg["apis"]["timeout_s"])
                r.raise_for_status()
                out = r.json()
                with open(p, "w") as f:
                    json.dump(out, f)
                return out
            except (requests.RequestException, ValueError) as e:
                last = e
        raise ServiceError(f"{name} is unavailable ({type(last).__name__}: {str(last)[:150]}). "
                           f"Check your internet connection or try again later.")


def fetch_route(http, cfg, start, end):
    url = f"{cfg['apis']['osrm']}/{start[1]},{start[0]};{end[1]},{end[0]}"
    data = http.get_json("OSRM routing", url, params={"overview": "full", "geometries": "geojson"})
    if data.get("code") != "Ok" or not data.get("routes"):
        raise ServiceError(f"OSRM found no route: {data.get('message', data.get('code'))}")
    return [(lat, lon) for lon, lat in data["routes"][0]["geometry"]["coordinates"]]


def fetch_osm(http, cfg, line):
    n = max(2, int(line.length // 100) + 1)
    pts = [line.point_at(i * line.length / (n - 1)) for i in range(n)]
    poly = ",".join(f"{a:.5f},{o:.5f}" for a, o in pts)
    hw = "|".join(sorted(osm_map.CAR_HIGHWAYS))
    q = f"""[out:json][timeout:120];
way[highway~"^({hw})$"](around:30,{poly});
out body geom;
node[railway=level_crossing](around:20,{poly});
out;
node[barrier=toll_booth](around:30,{poly});
out;
way[landuse~"^(residential|commercial|retail)$"](around:10,{poly});
out geom;
way[place~"^(city|town|village|suburb|neighbourhood|quarter)$"](around:10,{poly});
out geom;"""
    return http.get_json("Overpass (OpenStreetMap)", cfg["apis"]["overpass"], data={"data": q})["elements"]


def fetch_elevation(http, cfg, points):
    out = []
    for i in range(0, len(points), 100):
        chunk = points[i:i + 100]
        d = http.get_json("Open-Meteo elevation", cfg["apis"]["elevation"], params={
            "latitude": ",".join(f"{a:.5f}" for a, _ in chunk),
            "longitude": ",".join(f"{o:.5f}" for _, o in chunk)})
        out += d["elevation"]
    return out


class _Proj:
    """Local equirectangular projection to metres."""

    def __init__(self, lat0):
        self.kx = math.cos(math.radians(lat0)) * 111320.0
        self.ky = 110540.0

    def __call__(self, lat, lon):
        return np.asarray(lon) * self.kx, np.asarray(lat) * self.ky


def _point_seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    t = np.where(l2 > 0, ((px - ax) * dx + (py - ay) * dy) / np.where(l2 > 0, l2, 1), 0)
    t = np.clip(t, 0, 1)
    return np.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _in_polygon(x, y, xs, ys):
    inside = False
    j = len(xs) - 1
    for i in range(len(xs)):
        if (ys[i] > y) != (ys[j] > y) and x < (xs[j] - xs[i]) * (y - ys[i]) / (ys[j] - ys[i] + 1e-12) + xs[i]:
            inside = not inside
        j = i
    return inside


def build_segments(cfg, coords, elements, elevation_fn):
    seg_len = cfg["segment_length_m"]
    line = geo.Polyline(coords)
    nseg = max(1, int(math.ceil(line.length / seg_len)))
    proj = _Proj(coords[0][0])

    ways = [e for e in elements if e["type"] == "way" and e.get("tags", {}).get("highway") in osm_map.CAR_HIGHWAYS]
    areas = [e for e in elements if e["type"] == "way" and ("landuse" in e.get("tags", {}) or "place" in e.get("tags", {}))]
    crossings = [e for e in elements if e["type"] == "node" and e.get("tags", {}).get("railway") == "level_crossing"]
    tolls = [e for e in elements if e["type"] == "node" and e.get("tags", {}).get("barrier") == "toll_booth"]

    # Edge arrays for nearest-way matching; branch degree for each node.
    ex0, ey0, ex1, ey1, ewi, ebr = [], [], [], [], [], []
    degree, node_pos = {}, {}
    for wi, w in enumerate(ways):
        g = w.get("geometry") or []
        nodes = w.get("nodes") or []
        for k, (a, b) in enumerate(zip(g, g[1:])):
            x0, y0 = proj(a["lat"], a["lon"])
            x1, y1 = proj(b["lat"], b["lon"])
            ex0.append(x0); ey0.append(y0); ex1.append(x1); ey1.append(y1); ewi.append(wi)
            ebr.append(geo.bearing(a["lat"], a["lon"], b["lat"], b["lon"]))
        closed = len(nodes) > 2 and nodes[0] == nodes[-1]
        for k, nid in enumerate(nodes):
            interior = 0 < k < len(nodes) - 1 or closed
            if closed and k == len(nodes) - 1:
                continue
            degree[nid] = degree.get(nid, 0) + (2 if interior else 1)
            if k < len(g):
                node_pos[nid] = proj(g[k]["lat"], g[k]["lon"])
    ex0, ey0, ex1, ey1 = map(np.array, (ex0, ey0, ex1, ey1))
    ebr = np.array(ebr)
    junctions = [(nid, *node_pos[nid]) for nid, d in degree.items() if d >= 3 and nid in node_pos]
    jx = np.array([j[1] for j in junctions]); jy = np.array([j[2] for j in junctions]); jd = [degree[j[0]] for j in junctions]
    cx = np.array([proj(n["lat"], n["lon"])[0] for n in crossings]); cy = np.array([proj(n["lat"], n["lon"])[1] for n in crossings])
    tx = np.array([proj(n["lat"], n["lon"])[0] for n in tolls]); ty = np.array([proj(n["lat"], n["lon"])[1] for n in tolls])
    area_polys = []
    for a in areas:
        g = a.get("geometry") or []
        if len(g) >= 4:
            xs, ys = proj([p["lat"] for p in g], [p["lon"] for p in g])
            area_polys.append((xs, ys, xs.min(), xs.max(), ys.min(), ys.max()))

    pc = cfg["plan"]
    segs = []
    for i in range(nseg):
        s0, s1 = i * seg_len, min(line.length, (i + 1) * seg_len)
        sm = (s0 + s1) / 2
        lat, lon = line.point_at(sm)
        a, b = line.point_at(s0), line.point_at(s1)
        brg = geo.bearing(*a, *b) if geo.haversine(*a, *b) > 1 else (segs[-1]["bearing"] if segs else 0.0)
        segs.append({"i": i, "s": s0, "length": s1 - s0, "lat": lat, "lon": lon, "bearing": brg,
                     "coords": line.coords_between(s0, s1), "turn": geo.turn_at(line, sm, pc["window_m"])})

    plans = geo.classify_plan([s["turn"] for s in segs], [s["s"] + s["length"] / 2 for s in segs],
                              pc["straight_deg"], pc["sbend_window_m"])
    try:
        elev = elevation_fn([(s["lat"], s["lon"]) for s in segs])
    except ServiceError:
        elev = [None] * len(segs)
    pr = cfg["prof"]
    profs = geo.classify_prof(elev, [s["s"] for s in segs], pr["grade_pct"], pr["grade_window_m"],
                              pr["peak_window_m"], pr["peak_prominence_m"])

    for k, s in enumerate(segs):
        px, py = proj(s["lat"], s["lon"])
        (ax, ay), (bx, by) = proj(*s["coords"][0]), proj(*s["coords"][-1])
        tags, way_id = {}, None
        if len(ex0):
            d = _point_seg_dist(px, py, ex0, ey0, ex1, ey1)
            mis = np.abs((ebr - s["bearing"] + 180) % 360 - 180)
            mis = np.minimum(mis, 180 - mis)  # direction-agnostic
            score = d + np.where(mis > 45, 25, 0)
            j = int(np.argmin(score))
            if d[j] < 30:
                tags = ways[ewi[j]].get("tags", {})
                way_id = ways[ewi[j]]["id"]
        if not tags:
            tags = {"highway": "unclassified"}
        vma, vma_default = osm_map.vma_from_tags(tags, cfg["default_maxspeed"], cfg["maxspeed_zones"])
        in_urban = any(x0 <= px <= x1 and y0 <= py <= y1 and _in_polygon(px, py, xs, ys)
                       for xs, ys, x0, x1, y0, y1 in area_polys)
        deg = 0
        if len(jx):
            dj = _point_seg_dist(jx, jy, ax, ay, bx, by)
            near = np.where(dj < 15)[0]
            if len(near):
                deg = max(jd[n] for n in near)
        lc = bool(len(cx)) and bool((_point_seg_dist(cx, cy, ax, ay, bx, by) < 15).any())
        toll = bool(len(tx)) and bool((_point_seg_dist(tx, ty, ax, ay, bx, by) < 25).any())
        s["features"] = {
            "catr": osm_map.catr_from_highway(tags.get("highway")),
            "vma": vma,
            "nbv": osm_map.nbv_from_tags(tags, cfg["default_lanes"]),
            "circ": osm_map.circ_from_tags(tags),
            "agg": osm_map.agg_from_context(in_urban, vma),
            "plan": plans[k],
            "int": osm_map.int_from_context(tags, deg, lc),
            "prof": profs[k],
            "infra": osm_map.infra_from_tags(tags, toll),
        }
        s["osm"] = {"way_id": way_id, "highway": tags.get("highway"), "name": tags.get("name") or tags.get("ref"),
                    "maxspeed_tag": tags.get("maxspeed"), "vma_default": vma_default, "elevation": elev[k]}
        s["curve_speed"] = round(min(vma, geo.curve_speed_kmh(s["turn"], pc["window_m"], cfg["curve_lateral_accel_ms2"])), 1)
    return {"length": line.length, "segments": segs, "coords": line.pts,
            "elevation_ok": elev[0] is not None if elev else False}


def get_route(cfg, start, end):
    """Full pipeline with an on-disk cache of the final result (offline demo once loaded)."""
    key = f"{start[0]:.5f},{start[1]:.5f}->{end[0]:.5f},{end[1]:.5f}|{cfg['segment_length_m']}"
    path = os.path.join(cfg["cache_dir"], "routes", hashlib.sha1(key.encode()).hexdigest() + ".json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    http = Http(cfg)
    coords = fetch_route(http, cfg, start, end)
    line = geo.Polyline(coords)
    elements = fetch_osm(http, cfg, line)
    out = build_segments(cfg, coords, elements, lambda pts: fetch_elevation(http, cfg, pts))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(out, f)
    return out
