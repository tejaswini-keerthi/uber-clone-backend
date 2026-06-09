-- Nearest-available-driver matching query (mirror of
-- DriverRepository.find_nearest_available_driver). Run with EXPLAIN (ANALYZE,
-- BUFFERS) after seeding drivers to inspect index usage. The Python helper
-- scripts/explain_matching.py seeds data and runs this automatically.
--
-- Bind values used by the helper: pickup = (37.7749, -122.4194), radius = 5000m,
-- zones = pickup geohash6 + its 8 neighbours.

EXPLAIN (ANALYZE, BUFFERS)
SELECT drivers.id
FROM drivers
WHERE drivers.status = 'online'
  AND drivers.location IS NOT NULL
  AND ST_DWithin(
        drivers.location,
        ST_SetSRID(ST_MakePoint(-122.4194, 37.7749), 4326)::geography,
        5000)
  AND drivers.geohash_zone = ANY (ARRAY[
        '9q8yyk','9q8yym','9q8yy7','9q8yys','9q8yyh','9q8yyt','9q8yyj','9q8yye','9q8yy5'
  ])
ORDER BY ST_Distance(
        drivers.location,
        ST_SetSRID(ST_MakePoint(-122.4194, 37.7749), 4326)::geography)
LIMIT 1;
