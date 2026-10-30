"""Geometry helpers: distances, bearings, resampling, curve (plan) and slope (prof) detection, sun position."""
import math
from datetime import datetime, timezone

R_EARTH = 6371000.0


def haversine(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R_EARTH * math.asin(math.sqrt(a))


def bearing(lat1, lon1, lat2, lon2):
    """Initial bearing in degrees [0, 360)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def angle_diff(a, b):
    """Signed difference b - a in degrees, in (-180, 180]. Positive = turning right (clockwise)."""
    d = (b - a + 180) % 360 - 180
    return 180.0 if d == -180 else d


class Polyline:
    """A lat/lon polyline with cumulative distance, supporting interpolation at any distance."""

    def __init__(self, coords):
        pts = [tuple(coords[0])]
        for c in coords[1:]:
            if haversine(*pts[-1], *c) > 0.01:
                pts.append(tuple(c))
        self.pts = pts
        self.cum = [0.0]
        for a, b in zip(pts, pts[1:]):
            self.cum.append(self.cum[-1] + haversine(*a, *b))
        self.length = self.cum[-1]

    def point_at(self, s):
        s = min(max(s, 0.0), self.length)
        lo, hi = 0, len(self.cum) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if self.cum[mid] <= s:
                lo = mid
            else:
                hi = mid
        seg = self.cum[hi] - self.cum[lo]
        t = 0.0 if seg == 0 else (s - self.cum[lo]) / seg
        (a1, o1), (a2, o2) = self.pts[lo], self.pts[hi]
        return (a1 + t * (a2 - a1), o1 + t * (o2 - o1))

    def coords_between(self, s0, s1):
        out = [self.point_at(s0)]
        out += [p for p, c in zip(self.pts, self.cum) if s0 < c < s1]
        out.append(self.point_at(s1))
        return out


def turn_at(line, s, window_m):
    """Signed bearing change (deg) between chord [s-w/2, s] and chord [s, s+w/2]."""
    h = window_m / 2
    a, b, c = line.point_at(s - h), line.point_at(s), line.point_at(s + h)
    if haversine(*a, *b) < 1 or haversine(*b, *c) < 1:
        return 0.0
    return angle_diff(bearing(*a, *b), bearing(*b, *c))


def classify_plan(turns, positions, straight_deg=15.0, sbend_window_m=300.0):
    """Map signed turns (deg, + = right) to BAAC plan codes: 1 straight, 2 left, 3 right, 4 S-bend.

    A segment is an S-bend if, within +-sbend_window_m/2, there are both a left and a right curve
    and the segment itself is curved or between them.
    """
    n = len(turns)
    half = sbend_window_m / 2
    codes = []
    for i in range(n):
        near = [turns[j] for j in range(n) if abs(positions[j] - positions[i]) <= half]
        has_left = any(t <= -straight_deg for t in near)
        has_right = any(t >= straight_deg for t in near)
        t = turns[i]
        if has_left and has_right and (abs(t) >= straight_deg or _between(i, turns, positions, half, straight_deg)):
            codes.append(4)
        elif abs(t) < straight_deg:
            codes.append(1)
        else:
            codes.append(2 if t < 0 else 3)
    return codes


def _between(i, turns, positions, half, thr):
    before = [turns[j] for j in range(len(turns)) if 0 < positions[i] - positions[j] <= half and abs(turns[j]) >= thr]
    after = [turns[j] for j in range(len(turns)) if 0 < positions[j] - positions[i] <= half and abs(turns[j]) >= thr]
    return bool(before and after and (before[-1] > 0) != (after[0] > 0))


def curve_speed_kmh(turn_deg, window_m, lateral_accel=2.5, cap=130.0):
    """Comfortable speed for a curve: v = sqrt(a_lat * R), with R ~= window / angle."""
    ang = math.radians(abs(turn_deg))
    if ang < 1e-3:
        return cap
    radius = window_m / ang
    return min(cap, math.sqrt(lateral_accel * radius) * 3.6)


def classify_prof(elev, positions, grade_pct=4.0, grade_window_m=100.0, peak_window_m=150.0, prominence_m=3.0):
    """BAAC prof codes from elevations sampled at positions: 1 flat, 2 slope, 3 hilltop, 4 bottom."""
    n = len(elev)
    codes = []
    for i in range(n):
        if elev[i] is None:
            codes.append(None)
            continue
        win = [j for j in range(n) if abs(positions[j] - positions[i]) <= peak_window_m and elev[j] is not None]
        lo_j = [j for j in win if positions[j] < positions[i]]
        hi_j = [j for j in win if positions[j] > positions[i]]
        if lo_j and hi_j:
            vals = [elev[j] for j in win]
            ends = (elev[lo_j[0]], elev[hi_j[-1]])
            if elev[i] >= max(vals) and elev[i] - max(ends) >= prominence_m:
                codes.append(3)
                continue
            if elev[i] <= min(vals) and min(ends) - elev[i] >= prominence_m:
                codes.append(4)
                continue
        gw = [j for j in range(n) if abs(positions[j] - positions[i]) <= grade_window_m / 2 and elev[j] is not None]
        a, b = gw[0], gw[-1]
        dist = positions[b] - positions[a]
        grade = abs(elev[b] - elev[a]) / dist * 100 if dist > 0 else 0.0
        codes.append(2 if grade > grade_pct else 1)
    return codes


def solar_elevation(lat, lon, dt_utc):
    """Approximate sun elevation in degrees (NOAA formulas). dt_utc: aware or naive-UTC datetime."""
    if dt_utc.tzinfo is not None:
        dt_utc = dt_utc.astimezone(timezone.utc)
    doy = dt_utc.timetuple().tm_yday
    hr = dt_utc.hour + dt_utc.minute / 60 + dt_utc.second / 3600
    g = 2 * math.pi / 365 * (doy - 1 + (hr - 12) / 24)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                       - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    tst = hr * 60 + eqtime + 4 * lon
    ha = math.radians(tst / 4 - 180)
    la = math.radians(lat)
    cosz = math.sin(la) * math.sin(decl) + math.cos(la) * math.cos(decl) * math.cos(ha)
    return 90 - math.degrees(math.acos(max(-1.0, min(1.0, cosz))))


def is_dark(lat, lon, dt, threshold_deg=0.0):
    return int(solar_elevation(lat, lon, dt) < threshold_deg)
