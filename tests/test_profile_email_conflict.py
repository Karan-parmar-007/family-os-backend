"""Setup must report an email already linked to another SSO account (409),
not crash on the unique index (500). No database: the session is faked."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.routes.profile.profile_service import ProfileService


def _result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


@pytest.mark.asyncio
async def test_create_profile_rejects_email_owned_by_another_sso_account():
    session = MagicMock()
    # 1st lookup: by sso id -> none; 2nd: by email -> existing profile
    session.execute = AsyncMock(side_effect=[_result(None), _result(SimpleNamespace(id="p1"))])
    session.add = MagicMock()
    req = SimpleNamespace(display_name="K", currency_code="USD", timezone="UTC")

    with pytest.raises(ValueError, match="email_in_use"):
        await ProfileService(session).create_profile(
            sso_user_id="new-sso-id", email="k@example.com", req=req
        )
    session.add.assert_not_called()
