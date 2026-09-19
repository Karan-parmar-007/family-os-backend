"""Finance event email templates (Family System V2 – Plan 01).

All functions call the existing email_service SMTP transport. Recipients:
- Entity owner (user).
- For family entities: all family members not excluded from that entity.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.email_service import email_service

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _fmt(amount: Decimal | float | str) -> str:
    """Format money amount with two decimal places."""
    return f"{Decimal(str(amount)):,.2f}"


async def _family_member_emails(
    session: AsyncSession,
    family_id: UUID,
    *,
    exclude_user_ids: set[UUID] | None = None,
) -> list[str]:
    """Return email addresses of all active family members (optionally excluding some)."""
    from app.api.routes.user.model import UserBase, UserFamilyLink

    stmt = (
        select(UserBase.email)
        .join(UserFamilyLink, UserBase.id == UserFamilyLink.user_id)
        .where(UserFamilyLink.family_id == family_id)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    excluded = exclude_user_ids or set()
    return [email for email in rows if email not in excluded]


# ---------------------------------------------------------------------------
# Email functions
# ---------------------------------------------------------------------------


async def send_debt_completed_email(
    session: AsyncSession,
    *,
    owner_email: str,
    debt_name: str,
    total_paid: Decimal,
    family_id: UUID | None = None,
    entity_id: UUID | None = None,
) -> None:
    """Notify owner (and family members) that a debt has been fully paid off."""
    subject = f"Debt Cleared: {debt_name} — Family OS"
    body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; color: #222;">
        <h2>🎉 Debt Cleared!</h2>
        <p>Great news! The debt <strong>{debt_name}</strong> has been fully paid off.</p>
        <table style="border-collapse: collapse; margin-top: 12px;">
            <tr>
                <td style="padding: 6px 12px; font-weight: bold;">Total Paid</td>
                <td style="padding: 6px 12px;">₹{_fmt(total_paid)}</td>
            </tr>
        </table>
        <p style="margin-top: 20px; color: #555;">Keep up the great financial management!</p>
    </body>
    </html>
    """
    recipients = [owner_email]
    if family_id:
        family_emails = await _family_member_emails(session, family_id)
        for email in family_emails:
            if email not in recipients:
                recipients.append(email)

    for recipient in recipients:
        try:
            from email.mime.multipart import MIMEMultipart
            msg = email_service._build_message(recipient, subject, body)
            email_service._send(msg)
        except Exception:
            logger.exception("Failed to send debt-completed email to %s", recipient)


async def send_investment_matured_email(
    session: AsyncSession,
    *,
    owner_email: str,
    investment_name: str,
    matured_amount: Decimal,
    credited_pool_label: str,
    family_id: UUID | None = None,
) -> None:
    """Notify owner (and family members) that an investment has matured."""
    subject = f"Investment Matured: {investment_name} — Family OS"
    body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; color: #222;">
        <h2>📈 Investment Matured!</h2>
        <p>Your investment <strong>{investment_name}</strong> has matured.</p>
        <table style="border-collapse: collapse; margin-top: 12px;">
            <tr>
                <td style="padding: 6px 12px; font-weight: bold;">Matured Amount</td>
                <td style="padding: 6px 12px;">₹{_fmt(matured_amount)}</td>
            </tr>
            <tr>
                <td style="padding: 6px 12px; font-weight: bold;">Credited To</td>
                <td style="padding: 6px 12px;">{credited_pool_label}</td>
            </tr>
        </table>
        <p style="margin-top: 20px; color: #555;">The amount has been credited to your savings pool.</p>
    </body>
    </html>
    """
    recipients = [owner_email]
    if family_id:
        family_emails = await _family_member_emails(session, family_id)
        for email in family_emails:
            if email not in recipients:
                recipients.append(email)

    for recipient in recipients:
        try:
            msg = email_service._build_message(recipient, subject, body)
            email_service._send(msg)
        except Exception:
            logger.exception("Failed to send investment-matured email to %s", recipient)


async def send_savings_plan_completed_email(
    session: AsyncSession,
    *,
    owner_email: str,
    plan_name: str,
    target_amount: Decimal,
    family_id: UUID | None = None,
) -> None:
    """Notify owner (and family members) that a savings plan has been completed."""
    subject = f"Savings Plan Complete: {plan_name} — Family OS"
    body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; color: #222;">
        <h2>✅ Savings Plan Complete!</h2>
        <p>Congratulations! Your savings plan <strong>{plan_name}</strong> has been completed.</p>
        <table style="border-collapse: collapse; margin-top: 12px;">
            <tr>
                <td style="padding: 6px 12px; font-weight: bold;">Target Amount</td>
                <td style="padding: 6px 12px;">₹{_fmt(target_amount)}</td>
            </tr>
        </table>
        <p style="margin-top: 20px; color: #555;">You successfully reached your savings goal!</p>
    </body>
    </html>
    """
    recipients = [owner_email]
    if family_id:
        family_emails = await _family_member_emails(session, family_id)
        for email in family_emails:
            if email not in recipients:
                recipients.append(email)

    for recipient in recipients:
        try:
            msg = email_service._build_message(recipient, subject, body)
            email_service._send(msg)
        except Exception:
            logger.exception("Failed to send savings-plan-completed email to %s", recipient)
