"""Overdraft alerts for recurring expenses.

Family pools alert every family head; personal pools alert the owner.
In-app notifications are written in the caller's transaction; emails are sent
after commit (SMTP is blocking, so it runs in a worker thread).
"""

from __future__ import annotations

import asyncio
import html
import logging
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.family.model import Family
from app.api.routes.profile.model import FosProfile
from app.api.routes.scheduler.model import Notification
from app.api.routes.user.model import UserFamilyLink
from app.config import email_settings
from app.core.constants import NOTIF_STATUS_UNREAD
from app.utils.email_service import email_service

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OverdraftAlert:
    user_id: UUID
    email: str
    name: str
    subject: str
    body_html: str


async def _recipients(
    session: AsyncSession, *, family_id: UUID | None, owner_user_id: UUID | None
) -> list[FosProfile]:
    if family_id is not None:
        stmt = (
            select(FosProfile)
            .join(UserFamilyLink, UserFamilyLink.user_id == FosProfile.id)
            .where(
                UserFamilyLink.family_id == family_id,
                UserFamilyLink.is_family_manager.is_(True),
            )
        )
        return list((await session.execute(stmt)).scalars().all())
    if owner_user_id is None:
        return []
    profile = await session.get(FosProfile, owner_user_id)
    return [profile] if profile is not None else []


def _fmt(amount: Decimal) -> str:
    return f"{amount:,.2f}"


async def queue_overdraft_alerts(
    session: AsyncSession,
    *,
    family_id: UUID | None,
    owner_user_id: UUID | None,
    rule_name: str,
    amount: Decimal,
    balance_after: Decimal,
    event_id: UUID,
) -> list[OverdraftAlert]:
    """Add in-app notifications now; return the emails to send after commit."""
    pool_label = "Personal savings"
    currency = ""
    if family_id is not None:
        fam = await session.get(Family, family_id)
        pool_label = f"{fam.name} family savings" if fam else "Family savings"
        currency = f"{fam.currency} " if fam else ""
    elif owner_user_id is not None:
        profile = await session.get(FosProfile, owner_user_id)
        currency = f"{profile.personal_currency} " if profile else ""

    title = "Balance went negative"
    text = (
        f"Recurring expense \"{rule_name}\" ({currency}{_fmt(amount)}) was recorded. "
        f"{pool_label} is now {currency}{_fmt(balance_after)}."
    )
    alerts: list[OverdraftAlert] = []
    for profile in await _recipients(
        session, family_id=family_id, owner_user_id=owner_user_id
    ):
        session.add(
            Notification(
                user_id=profile.id,
                family_id=family_id,
                type="BALANCE_NEGATIVE",
                title=title,
                body=text,
                related_entity_type="MONEY_EVENT",
                related_entity_id=event_id,
                allowed_actions={"actions": ["DISMISS"]},
                status=NOTIF_STATUS_UNREAD,
            )
        )
        link = email_settings.FRONTEND_URL.rstrip("/")
        body = f"""
        <html><body style="font-family: Arial, sans-serif; color: #222;">
          <p>Hi {html.escape(profile.display_name)},</p>
          <p>{html.escape(text)}</p>
          <p>Add income or move money in to bring the balance back above zero.</p>
          <p><a href="{link}">Open Family OS</a></p>
        </body></html>
        """
        alerts.append(
            OverdraftAlert(
                user_id=profile.id,
                email=profile.email,
                name=profile.display_name,
                subject=f"{title}: {pool_label} — Family OS",
                body_html=body,
            )
        )
    return alerts


def _send_blocking(alert: OverdraftAlert) -> None:
    msg = email_service._build_message(alert.email, alert.subject, alert.body_html)
    email_service._send(msg)


async def send_overdraft_emails(alerts: list[OverdraftAlert]) -> None:
    if not alerts:
        return
    if not email_settings.SMTP_HOST:
        logger.info("SMTP not configured; skipped %d overdraft emails", len(alerts))
        return
    for alert in alerts:
        try:
            await asyncio.to_thread(_send_blocking, alert)
        except Exception:
            logger.exception("Overdraft email to %s failed", alert.email)
