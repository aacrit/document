"""Write the map fixture's GeoJSON at test time (R-08: no data files in git)."""
from __future__ import annotations

import json
from pathlib import Path

LAND = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "properties": {"name": "Fixture land", "ADM0_A3": "FIX"},
     "geometry": {"type": "Polygon", "coordinates": [[[10.0, 10.0], [12.3, 10.1], [12.3, 13.6], [11.0, 14.0],
                                                      [9.6, 12.0], [10.0, 10.0]]]}},
    {"type": "Feature", "properties": {"name": "Fixture east", "ADM0_A3": "FXE"},
     "geometry": {"type": "Polygon", "coordinates": [[[12.3, 10.1], [14.0, 10.2], [14.5, 13.0], [12.3, 13.6],
                                                      [12.3, 10.1]]]}},
]}
RIVER = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "properties": {"name": "Fixture river", "featurecla": "River"},
     "geometry": {"type": "LineString", "coordinates": [[10.5, 13.5], [11.5, 12.4], [12.2, 12.0], [13.6, 10.4]]}},
    {"type": "Feature", "properties": {"name": "Fixture border"},
     "geometry": {"type": "LineString", "coordinates": [[12.0, 10.1], [12.3, 11.5], [11.8, 13.0], [12.1, 13.9]]}},
]}


def write(dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "land.geojson").write_text(json.dumps(LAND), encoding="utf-8")
    (dest / "river.geojson").write_text(json.dumps(RIVER), encoding="utf-8")
    return dest
