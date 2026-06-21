import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import auth_settings, email_settings

logger = logging.getLogger(__name__)


class EmailService:
    """Send emails via SMTP."""

    def __init__(
        self,
        host: str = email_settings.SMTP_HOST,
        port: int = email_settings.SMTP_PORT,
        username: str = email_settings.SMTP_USERNAME,
        password: str = email_settings.SMTP_PASSWORD,
        from_email: str = email_settings.SMTP_FROM_EMAIL,
        from_name: str = email_settings.SMTP_FROM_NAME,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.from_email = from_email
        self.from_name = from_name

    def _build_message(self, to_email: str, subject: str, body: str) -> MIMEMultipart:
        message = MIMEMultipart("alternative")
        message["From"] = f"{self.from_name} <{self.from_email}>"
        message["To"] = to_email
        message["Subject"] = subject
        message.attach(MIMEText(body, "html"))
        return message

    def _send(self, message: MIMEMultipart) -> None:
        with smtplib.SMTP(self.host, self.port) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(self.username, self.password)
            server.sendmail(self.from_email, message["To"], message.as_string())

    async def send_verification_email(self, to_email: str, token: str) -> None:
        """Send email verification link."""
        subject = "Verify Your Email - Family OS"
        link = f"{email_settings.FRONTEND_URL}/verify-email?token={token}"
        body = f"""
        <html>
          <body>
            <p>Please verify your email by clicking the link below:</p>
            <a href="{link}">{link}</a>
          </body>
        </html>
        """
        message = self._build_message(to_email, subject, body)
        self._send(message)
        logger.info("Verification email sent to %s", to_email)

    async def send_password_reset_email(self, to_email: str, token: str) -> None:
        """Send password reset link."""
        subject = "Reset Your Password - Family OS"
        link = f"{email_settings.FRONTEND_URL}/reset-password?token={token}"
        body = f"""
        <html>
          <body>
            <p>Please reset your password by clicking the link below:</p>
            <a href="{link}">{link}</a>
          </body>
        </html>
        """
        message = self._build_message(to_email, subject, body)
        self._send(message)
        logger.info("Password reset email sent to %s", to_email)

    async def send_email_change_otp(self, to_email: str, otp: str) -> None:
        """Send email change OTP to the new address."""
        subject = "Your Email Change Code - Family OS"
        body = f"""
        <html>
          <body>
            <p>Use this code to confirm your new email address:</p>
            <p style="font-size: 24px; font-weight: bold; letter-spacing: 4px;">{otp}</p>
            <p>This code expires in {auth_settings.EMAIL_CHANGE_OTP_EXPIRE_MINUTES} minutes. If you did not request this, ignore this email.</p>
          </body>
        </html>
        """
        message = self._build_message(to_email, subject, body)
        self._send(message)
        logger.info("Email change OTP sent to %s", to_email)

    async def send_family_added_email(self, to_email: str) -> None:
        """Notify an existing user they have been added to a family."""
        subject = "You've Been Added to a Family - Family OS"
        login_link = f"{email_settings.FRONTEND_URL}/login"
        body = f"""
        <html>
          <body>
            <p>You have been added to a family on Family OS.</p>
            <p>Log in to your account to see your family dashboard:</p>
            <p><a href="{login_link}"><button style="padding: 10px 20px; background-color: #007bff; color: white; text-decoration: none; border-radius: 5px;">Go to Login</button></a></p>
          </body>
        </html>
        """
        message = self._build_message(to_email, subject, body)
        self._send(message)
        logger.info("Family added notification sent to %s", to_email)

    async def send_account_setup_email(self, to_email: str, token: str) -> None:
        """Send account setup email to an invited user who doesn't have an account yet."""
        subject = "You've been added to a family — set up your account"
        link = f"{email_settings.FRONTEND_URL}/setup-account?token={token}&email={to_email}"
        body = f"""
        <html>
          <body>
            <p>You have been added to a family on Family OS, but you need to set up your account first.</p>
            <p><a href="{link}"><button style="padding: 10px 20px; background-color: #007bff; color: white; text-decoration: none; border-radius: 5px;">Set Up Account</button></a></p>
            <p>This link expires in {auth_settings.FAMILY_INVITE_TOKEN_EXPIRE_DAYS} days. If you did not expect this, ignore this email.</p>
          </body>
        </html>
        """
        message = self._build_message(to_email, subject, body)
        self._send(message)
        logger.info("Account setup email sent to %s", to_email)


email_service = EmailService()
