"""Seed N online drivers and EXPLAIN ANALYZE the nearest-driver matching query.

Generates evidence for the "sub-100ms driver matching" claim: it loads a realistic
number of drivers across a city, ANALYZEs, then prints the planner output for the
exact query DriverRepository.find_nearest_available_driver issues (geohash
pre-filter on a btree index + ST_DWithin/ST_Distance on the GiST index).

Usage (against any reachable Postgres+PostGIS with the schema applied):
    DATABASE_URL=postgresql+asyncpg://uber:uber@localhost:5432/uber \
        uv run python scripts/explain_matching.py [num_drivers]
"""
from __future__ import annotations

import asyncio
import os
import random
import sys
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.geo import encode_geohash, geohash_neighbors

# San Francisco-ish bounding box.
_LAT0, _LNG0 = 37.7749, -122.4194
_SPREAD = 0.15  # ~16 km box


async def main(num_drivers: int) -> None:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("Set DATABASE_URL (postgresql+asyncpg://...)")
    engine = create_async_engine(url)

    async with engine.begin() as conn:
        users, drivers = [], []
        for _ in range(num_drivers):
            uid, did = uuid.uuid4(), uuid.uuid4()
            lat = _LAT0 + random.uniform(-_SPREAD, _SPREAD)
            lng = _LNG0 + random.uniform(-_SPREAD, _SPREAD)
            users.append(
                {
                    "id": uid,
                    "email": f"seed-{uid}@example.com",
                    "hp": "x",
                    "fn": "Seed Driver",
                    "role": "driver",
                }
            )
            drivers.append(
                {
                    "id": did,
                    "user_id": uid,
                    "lat": lat,
                    "lng": lng,
                    "zone": encode_geohash(lat, lng),
                }
            )

        await conn.execute(
            text(
                "INSERT INTO users (id, email, hashed_password, full_name, role, "
                "is_active) VALUES (:id, :email, :hp, :fn, CAST(:role AS user_role), true)"
            ),
            users,
        )
        await conn.execute(
            text(
                "INSERT INTO drivers (id, user_id, vehicle_make, vehicle_model, "
                "vehicle_plate, status, rating, location, current_lat, current_lng, "
                "geohash_zone, last_location_update) VALUES (:id, :user_id, 'Toyota', "
                "'Prius', 'SEED', 'online', 5.0, "
                "ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography, :lat, :lng, "
                ":zone, now())"
            ),
            drivers,
        )
        await conn.execute(text("ANALYZE drivers"))

        zones = [encode_geohash(_LAT0, _LNG0), *geohash_neighbors(encode_geohash(_LAT0, _LNG0))]
        explain = text(
            """
            EXPLAIN (ANALYZE, BUFFERS)
            SELECT drivers.id
            FROM drivers
            WHERE drivers.status = 'online'
              AND drivers.location IS NOT NULL
              AND ST_DWithin(
                    drivers.location,
                    ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography, :radius)
              AND drivers.geohash_zone = ANY(:zones)
            ORDER BY ST_Distance(
                    drivers.location,
                    ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography)
            LIMIT 1
            """
        )
        result = await conn.execute(
            explain, {"lat": _LAT0, "lng": _LNG0, "radius": 5000, "zones": zones}
        )
        print(f"\n--- EXPLAIN ANALYZE ({num_drivers} online drivers) ---")
        for row in result:
            print(row[0])

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 5000))
