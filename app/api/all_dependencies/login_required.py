"""Re-export current-user dependency for route modules."""

from app.api.dependencies import CurrentUserDep as LoggedInUserDep

__all__ = ["LoggedInUserDep"]
