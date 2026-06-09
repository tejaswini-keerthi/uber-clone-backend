"""drivers table (with PostGIS geography + GiST index)

Revision ID: 0003_drivers
Revises: 0002_users_refresh_tokens
Create Date: 2026-01-01 00:20:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import geoalchemy2 as ga
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0003_drivers"
down_revision: str | None = "0002_users_refresh_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

driver_status = postgresql.ENUM("offline", "online", "on_trip", name="driver_status")


def upgrade() -> None:
    driver_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "drivers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("vehicle_make", sa.String(length=64), nullable=False),
        sa.Column("vehicle_model", sa.String(length=64), nullable=False),
        sa.Column("vehicle_plate", sa.String(length=16), nullable=False),
        sa.Column("vehicle_color", sa.String(length=32), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "offline", "online", "on_trip", name="driver_status", create_type=False
            ),
            server_default="offline",
            nullable=False,
        ),
        sa.Column("rating", sa.Float(), server_default=sa.text("5.0"), nullable=False),
        # spatial_index=False here: the GiST index is created explicitly below so
        # it isn't double-created by geoalchemy2's create-table event listeners.
        sa.Column(
            "location",
            ga.Geography(
                geometry_type="POINT", srid=4326, spatial_index=False, nullable=True
            ),
            nullable=True,
        ),
        sa.Column("current_lat", sa.Float(), nullable=True),
        sa.Column("current_lng", sa.Float(), nullable=True),
        sa.Column("geohash_zone", sa.String(length=12), nullable=True),
        sa.Column("last_location_update", sa.DateTime(timezone=True), nullable=True),
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
            ["user_id"], ["users.id"], name="fk_drivers_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_drivers"),
    )
    op.create_index("ix_drivers_user_id", "drivers", ["user_id"], unique=True)
    op.create_index("ix_drivers_status", "drivers", ["status"], unique=False)
    op.create_index("ix_drivers_geohash_zone", "drivers", ["geohash_zone"], unique=False)
    # GiST index powers the ST_DWithin nearest-driver query in step 6.
    op.create_index(
        "idx_drivers_location", "drivers", ["location"], postgresql_using="gist"
    )


def downgrade() -> None:
    op.drop_index("idx_drivers_location", table_name="drivers")
    op.drop_index("ix_drivers_geohash_zone", table_name="drivers")
    op.drop_index("ix_drivers_status", table_name="drivers")
    op.drop_index("ix_drivers_user_id", table_name="drivers")
    op.drop_table("drivers")
    driver_status.drop(op.get_bind(), checkfirst=True)
