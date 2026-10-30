"""Pure functions mapping OpenStreetMap tags to BAAC model codes."""
import re

CAR_HIGHWAYS = {
    "motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
    "secondary", "secondary_link", "tertiary", "tertiary_link", "unclassified",
    "residential", "living_street", "service", "road",
}


def base_highway(h):
    return (h or "").replace("_link", "")


def catr_from_highway(h):
    b = base_highway(h)
    if b == "motorway":
        return 1
    if b in ("trunk", "primary"):
        return 2
    if b in ("secondary", "tertiary"):
        return 3
    return 4


def parse_maxspeed(value, zones=None):
    """'50' -> 50, '30 mph' -> 48.3, 'DZ:urban' -> zones['urban']. None if unparseable."""
    if value is None:
        return None
    v = str(value).strip().lower().split(";")[0]
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(mph|km/h|kmh)?$", v)
    if m:
        n = float(m.group(1))
        return round(n * 1.609, 1) if m.group(2) == "mph" else n
    if zones and ":" in v:
        zone = v.split(":", 1)[1]
        for key, speed in zones.items():
            if key in zone:
                return float(speed)
    return None


def vma_from_tags(tags, default_maxspeed, zones=None):
    v = parse_maxspeed(tags.get("maxspeed"), zones)
    if v is not None:
        return v, False
    h = tags.get("highway", "road")
    return float(default_maxspeed.get(h, default_maxspeed.get(base_highway(h), 50))), True


def nbv_from_tags(tags, default_lanes):
    try:
        n = int(float(str(tags.get("lanes", "")).split(";")[0]))
        if n > 0:
            # OSM counts lanes per carriageway for split motorways; BAAC counts the whole road.
            if is_oneway(tags) and base_highway(tags.get("highway")) in ("motorway", "trunk") \
                    and not tags.get("highway", "").endswith("_link"):
                n *= 2
            return n
    except ValueError:
        pass
    b = base_highway(tags.get("highway"))
    n = default_lanes.get(b, default_lanes.get("default", 2))
    return n * 2 if b == "motorway" else n


def is_oneway(tags):
    return str(tags.get("oneway", "")).lower() in ("yes", "1", "true", "-1") \
        or tags.get("junction") == "roundabout" or tags.get("highway") == "motorway"


def circ_from_tags(tags):
    h = tags.get("highway", "")
    if h in ("motorway", "trunk") and (is_oneway(tags) or h == "motorway"):
        return 3  # dual carriageway mapped as two one-way ways
    if tags.get("dual_carriageway") == "yes":
        return 3
    if is_oneway(tags):
        return 1
    return 2


def agg_from_context(in_urban_area, vma):
    return 2 if in_urban_area or (vma is not None and vma <= 50) else 1


def int_from_context(tags, node_degree=0, level_crossing=False):
    """BAAC intersection code. node_degree = number of road branches meeting at the closest junction node."""
    if level_crossing:
        return 8
    if tags.get("junction") in ("roundabout", "circular"):
        return 6
    if node_degree >= 5:
        return 5
    if node_degree == 4:
        return 2
    if node_degree == 3:
        return 3
    return 1


def infra_from_tags(tags, toll=False):
    if tags.get("tunnel") in ("yes", "building_passage", "culvert"):
        return 1
    if tags.get("bridge") not in (None, "no"):
        return 2
    if toll or tags.get("barrier") == "toll_booth":
        return 7
    if tags.get("highway") == "construction" or tags.get("construction"):
        return 8
    if tags.get("highway") == "motorway_link":
        return 3
    return 0
