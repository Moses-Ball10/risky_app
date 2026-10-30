import json
import math
from datetime import datetime, timezone

import pytest

from roadrisk import geo, osm_map
from roadrisk.model import level_of, x_vs_average

LEVELS = [{"max": 0.7}, {"max": 1.5}, {"max": 3.0}, {"max": None}]
DEFAULTS = {"primary": 80, "residential": 40, "motorway": 120}
ZONES = {"urban": 50, "rural": 80}


# ---------- OSM tag -> code ----------
@pytest.mark.parametrize("h,code", [("motorway", 1), ("motorway_link", 1), ("trunk", 2), ("primary", 2),
                                    ("secondary", 3), ("tertiary", 3), ("residential", 4),
                                    ("unclassified", 4), ("living_street", 4)])
def test_catr(h, code):
    assert osm_map.catr_from_highway(h) == code


def test_maxspeed_parsing_and_default():
    assert osm_map.parse_maxspeed("90") == 90
    assert osm_map.parse_maxspeed("30 mph") == pytest.approx(48.3, abs=0.1)
    assert osm_map.parse_maxspeed("DZ:urban", ZONES) == 50
    assert osm_map.parse_maxspeed("none") is None
    assert osm_map.vma_from_tags({"highway": "primary", "maxspeed": "60"}, DEFAULTS) == (60, False)
    assert osm_map.vma_from_tags({"highway": "residential"}, DEFAULTS) == (40, True)


def test_circ_lanes_agg():
    assert osm_map.circ_from_tags({"highway": "secondary", "oneway": "yes"}) == 1
    assert osm_map.circ_from_tags({"highway": "motorway", "oneway": "yes"}) == 3
    assert osm_map.circ_from_tags({"highway": "trunk", "oneway": "yes"}) == 3
    assert osm_map.circ_from_tags({"highway": "primary"}) == 2
    assert osm_map.nbv_from_tags({"highway": "primary", "lanes": "3"}, {"default": 2}) == 3
    assert osm_map.nbv_from_tags({"highway": "motorway", "oneway": "yes", "lanes": "2"}, {"default": 2}) == 4
    assert osm_map.agg_from_context(True, 80) == 2
    assert osm_map.agg_from_context(False, 50) == 2
    assert osm_map.agg_from_context(False, 90) == 1


def test_intersection_and_infra():
    assert osm_map.int_from_context({"junction": "roundabout"}, 3) == 6
    assert osm_map.int_from_context({}, 3) == 3
    assert osm_map.int_from_context({}, 4) == 2
    assert osm_map.int_from_context({}, 6) == 5
    assert osm_map.int_from_context({}, 2) == 1
    assert osm_map.int_from_context({}, 4, level_crossing=True) == 8
    assert osm_map.infra_from_tags({"tunnel": "yes"}) == 1
    assert osm_map.infra_from_tags({"bridge": "yes"}) == 2
    assert osm_map.infra_from_tags({}, toll=True) == 7
    assert osm_map.infra_from_tags({"highway": "primary"}) == 0


# ---------- curve detection ----------
def _arc(radius_m, angle_deg, right=True, n=200, lat0=36.5, lon0=3.0):
    """Straight 300 m going north, then a circular arc, then straight again."""
    kx, ky = 111320 * math.cos(math.radians(lat0)), 110540
    pts = [(0.0, y) for y in range(0, 301, 10)]
    sign = 1 if right else -1
    cx = sign * radius_m
    for k in range(1, n + 1):
        th = math.radians(angle_deg) * k / n
        pts.append((cx - sign * radius_m * math.cos(th), 300 + radius_m * math.sin(th)))
    ex, ey = pts[-1]
    h = math.radians(angle_deg) * sign
    for d in range(10, 301, 10):
        pts.append((ex + d * math.sin(h), ey + d * math.cos(h)))
    return [(lat0 + y / ky, lon0 + x / kx) for x, y in pts]


def _plans(coords, seg=50, window=150):
    line = geo.Polyline(coords)
    pos = [i * seg + seg / 2 for i in range(int(line.length // seg))]
    turns = [geo.turn_at(line, p, window) for p in pos]
    return geo.classify_plan(turns, pos), turns


def test_straight_road_is_straight():
    coords = [(36.5 + i * 0.0005, 3.0) for i in range(40)]
    plans, _ = _plans(coords)
    assert set(plans) == {1}


def test_right_and_left_curves():
    plans, turns = _plans(_arc(100, 90, right=True))
    assert 3 in plans and 2 not in plans and max(turns) > 15
    plans, turns = _plans(_arc(100, 90, right=False))
    assert 2 in plans and 3 not in plans and min(turns) < -15


def test_s_bend():
    a = _arc(80, 70, right=True)
    # mirror the second half: right curve immediately followed by a left one
    lat0, lon0 = a[-1]
    b = _arc(80, 70, right=False, lat0=lat0, lon0=lon0)
    plans, _ = _plans(a[:-25] + b[31:])
    assert 4 in plans


def test_angle_diff_and_bearing():
    assert geo.angle_diff(350, 10) == 20
    assert geo.angle_diff(10, 350) == -20
    assert geo.bearing(36, 3, 37, 3) == pytest.approx(0, abs=0.1)
    assert geo.bearing(36, 3, 36, 4) == pytest.approx(90, abs=1)


# ---------- is_dark ----------
def test_is_dark_algiers():
    lat, lon = 36.75, 3.06
    assert geo.is_dark(lat, lon, datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)) == 0
    assert geo.is_dark(lat, lon, datetime(2026, 6, 21, 1, 0, tzinfo=timezone.utc)) == 1
    assert geo.is_dark(lat, lon, datetime(2026, 12, 21, 18, 0, tzinfo=timezone.utc)) == 1  # 19h local in winter
    assert geo.is_dark(lat, lon, datetime(2026, 6, 21, 18, 0, tzinfo=timezone.utc)) == 0  # 19h local in summer
    assert geo.solar_elevation(lat, lon, datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)) > 70


# ---------- x_vs_average + levels ----------
def test_x_vs_average():
    assert x_vs_average(0.2) == pytest.approx(1.0)
    assert x_vs_average(0.5) == pytest.approx(4.0)
    assert x_vs_average(0.1) == pytest.approx((0.1 / 0.9) / 0.25)


@pytest.mark.parametrize("x,lvl", [(0.1, 0), (0.69, 0), (0.7, 1), (1.49, 1), (1.5, 2), (2.99, 2), (3, 3), (50, 3)])
def test_levels(x, lvl):
    assert level_of(x, LEVELS) == lvl


def test_prof():
    pos = [i * 50 for i in range(20)]
    flat = geo.classify_prof([100.0] * 20, pos)
    assert set(flat) == {1}
    slope = geo.classify_prof([100 + 0.08 * p for p in pos], pos)
    assert slope[10] == 2
    hill = geo.classify_prof([100 - abs(p - 500) * 0.05 for p in pos], pos)
    assert hill[10] == 3


# ---------- weather rule ----------
from datetime import datetime as _dt  # noqa: E402

from roadrisk import weather as rw  # noqa: E402

RULE = json.load(open("config.json"))["weather_rule"]
WHEN = _dt(2025, 1, 10, 18)


def _st(kind):
    return rw.status(rw.manual_hourly(kind, WHEN), WHEN, RULE)


def test_weather_clear_is_neutral():
    s = _st("clear")
    assert s["factor"] == 1 and s["factor_hard"] == 1 and s["reasons"] == []


@pytest.mark.parametrize("kind", ["rain", "heavy", "fog", "snow"])
def test_weather_raises_but_is_capped(kind):
    s = _st(kind)
    assert 1 < s["factor"] <= s["factor_hard"] <= RULE["cap"]
    assert s["reasons"]


def test_weather_duration_and_first_rain():
    s = _st("heavy")
    assert s["spell_h"] == 4
    s = _st("rain")                       # 1 h of rain after 3 dry days -> first rain
    assert s["spell_h"] == 1 and "first rain" in s["reasons"][0]["words"]


def test_weather_road_still_wet_after_rain():
    rows = rw.manual_hourly("rain", WHEN)
    for x in rows[-3:]:                    # rain stopped at WHEN (and after)
        x["rain"] = 0
    rows[-4]["rain"] = 0
    rows[-5]["rain"] = 2.0                 # rained 2 h before
    s = rw.status(rows, WHEN, RULE)
    assert s["since_rain_h"] == 2 and s["label"] == "Wet after rain" and s["factor"] > 1
