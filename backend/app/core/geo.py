"""Geo helpers shared across services.

A 6-char geohash (the configured precision) covers roughly a ~1.2km × 0.6km
cell — a good coarse "zone" key for pre-filtering driver-matching candidates
before the precise PostGIS distance query (see step 6) and for the surge
pricing lookup (step 9).
"""
from __future__ import annotations

import math

import pygeohash

from app.core.config import settings

EARTH_RADIUS_KM = 6371.0088


def encode_geohash(lat: float, lng: float, precision: int | None = None) -> str:
    """Encode a lat/lng to a geohash at the configured zone precision."""
    return pygeohash.encode(
        lat, lng, precision=precision or settings.geohash_precision
    )


def wkt_point(lat: float, lng: float) -> str:
    """WKT for a point. Note WKT/PostGIS order is (lng lat), i.e. (x y)."""
    return f"POINT({lng} {lat})"


# Standard geohash adjacency tables (Gustavo Niemeyer's algorithm). Used to
# expand a pickup zone to its 8 neighbours so the matching pre-filter doesn't
# miss drivers just across a cell boundary.
_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"
_NEIGHBOR = {
    "n": ["p0r21436x8zb9dcf5h7kjnmqesgutwvy", "bc01fg45238967deuvhjyznpkmstqrwx"],
    "s": ["14365h7k9dcfesgujnmqp0r2twvyx8zb", "238967debc01fg45kmstqrwxuvhjyznp"],
    "e": ["bc01fg45238967deuvhjyznpkmstqrwx", "p0r21436x8zb9dcf5h7kjnmqesgutwvy"],
    "w": ["238967debc01fg45kmstqrwxuvhjyznp", "14365h7k9dcfesgujnmqp0r2twvyx8zb"],
}
_BORDER = {
    "n": ["prxz", "bcfguvyz"],
    "s": ["028b", "0145hjnp"],
    "e": ["bcfguvyz", "prxz"],
    "w": ["0145hjnp", "028b"],
}


def _adjacent(geohash: str, direction: str) -> str:
    geohash = geohash.lower()
    last, parent = geohash[-1], geohash[:-1]
    type_idx = len(geohash) % 2
    if last in _BORDER[direction][type_idx] and parent:
        parent = _adjacent(parent, direction)
    return parent + _BASE32[_NEIGHBOR[direction][type_idx].index(last)]


def geohash_neighbors(geohash: str) -> list[str]:
    """The 8 geohash cells surrounding `geohash` (N, S, E, W + diagonals)."""
    n, s = _adjacent(geohash, "n"), _adjacent(geohash, "s")
    e, w = _adjacent(geohash, "e"), _adjacent(geohash, "w")
    return [n, s, e, w, _adjacent(n, "e"), _adjacent(n, "w"),
            _adjacent(s, "e"), _adjacent(s, "w")]


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in km. Used for the fare estimate at request time
    (cheap, no DB round-trip); PostGIS handles precise distances for matching."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))
