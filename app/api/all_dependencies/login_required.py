"""
Re-exports the SSO-authenticated identity dep.
Domain routes that need a Family OS user id must use LoggedInUserDep (fos_profiles).
Setup and session routes keep AuthenticatedDep (SSO identity only).
"""
from app.auth.dependencies import AuthenticatedDep
from app.auth.fos_profile import FosProfileDep

LoggedInUserDep = FosProfileDep

__all__ = ["LoggedInUserDep", "AuthenticatedDep"]
