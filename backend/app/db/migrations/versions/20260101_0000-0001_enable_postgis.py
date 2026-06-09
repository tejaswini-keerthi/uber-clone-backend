"""enable postgis extension

This is the base revision. The postgis/postgis Docker image normally enables the
extension on the target database automatically, but enabling it here (idempotently)
makes migrations self-sufficient on any Postgres instance and gives later
geometry-column migrations a guaranteed dependency to build on.

Revision ID: 0001_enable_postgis
Revises:
Create Date: 2026-01-01 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_enable_postgis"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")


def downgrade() -> None:
    # Intentionally do NOT drop the extension: other databases/objects in the
    # cluster may depend on it. Dropping postgis is an explicit ops decision.
    pass
