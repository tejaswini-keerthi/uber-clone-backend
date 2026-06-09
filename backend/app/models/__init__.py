"""Model registry.

Importing this package imports every model, which registers its table on
`Base.metadata`. Alembic's env.py and the test suite's `create_all` both rely on
that side effect, so every new model must be re-exported here.
"""
from app.db.base import Base
from app.models.driver import Driver, DriverStatus
from app.models.ride import Ride, RideStatus
from app.models.user import RefreshToken, User, UserRole

__all__ = [
    "Base",
    "User",
    "RefreshToken",
    "UserRole",
    "Driver",
    "DriverStatus",
    "Ride",
    "RideStatus",
]
