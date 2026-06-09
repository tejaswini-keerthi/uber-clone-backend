"""rides table (PostGIS pickup/dropoff + lifecycle)

Revision ID: 0004_rides
Revises: 0003_drivers
Create Date: 2026-01-01 00:30:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import geoalchemy2 as ga
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0004_rides"
down_revision: str | None = "0003_drivers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ride_status = postgresql.ENUM(
    "requested", "matched", "on_trip", "completed", "cancelled", name="ride_status"
)


def upgrade() -> None:
    ride_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "rides",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("rider_id", sa.Uuid(), nullable=False),
        sa.Column("driver_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "requested",
                "matched",
                "on_trip",
                "completed",
                "cancelled",
                name="ride_status",
                create_type=False,
            ),
            server_default="requested",
            nullable=False,
        ),
        sa.Column("pickup_lat", sa.Float(), nullable=False),
        sa.Column("pickup_lng", sa.Float(), nullable=False),
        sa.Column("pickup_geohash", sa.String(length=12), nullable=False),
        sa.Column(
            "pickup_location",
            ga.Geography(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("dropoff_lat", sa.Float(), nullable=False),
        sa.Column("dropoff_lng", sa.Float(), nullable=False),
        sa.Column(
            "dropoff_location",
            ga.Geography(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("city", sa.String(length=128), nullable=False),
        sa.Column("distance_km", sa.Float(), nullable=True),
        sa.Column(
            "surge_multiplier", sa.Float(), server_default=sa.text("1.0"), nullable=False
        ),
        sa.Column("estimated_fare", sa.Float(), nullable=True),
        sa.Column("final_fare", sa.Float(), nullable=True),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_reason", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["rider_id"], ["users.id"], name="fk_rides_rider_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["driver_id"],
            ["drivers.id"],
            name="fk_rides_driver_id_drivers",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_rides"),
    )
    op.create_index("ix_rides_rider_id", "rides", ["rider_id"], unique=False)
    op.create_index("ix_rides_driver_id", "rides", ["driver_id"], unique=False)
    op.create_index("ix_rides_status", "rides", ["status"], unique=False)
    op.create_index("ix_rides_pickup_geohash", "rides", ["pickup_geohash"], unique=False)
    # GiST index on pickup powers spatial driver-matching reads in step 6.
    op.create_index(
        "idx_rides_pickup_location", "rides", ["pickup_location"], postgresql_using="gist"
    )


def downgrade() -> None:
    op.drop_index("idx_rides_pickup_location", table_name="rides")
    op.drop_index("ix_rides_pickup_geohash", table_name="rides")
    op.drop_index("ix_rides_status", table_name="rides")
    op.drop_index("ix_rides_driver_id", table_name="rides")
    op.drop_index("ix_rides_rider_id", table_name="rides")
    op.drop_table("rides")
    ride_status.drop(op.get_bind(), checkfirst=True)
