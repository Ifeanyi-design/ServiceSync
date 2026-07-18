"""Email sending via SMTP (stdlib only — no external dependency).

When SMTP is not configured the functions log and return without raising, so
the app keeps working in demo mode. All links use settings.FRONTEND_URL.
"""
import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from app.core.config import settings

logger = logging.getLogger("services.email")


def _send_sync(to: str, subject: str, html: str, text: str) -> None:
    if not settings.SMTP_HOST:
        logger.warning("SMTP not configured; skipping email to %s (%s)", to, subject)
        return
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.EMAIL_FROM
    msg["To"] = to
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
            if settings.SMTP_USE_TLS:
                context = ssl.create_default_context()
                server.starttls(context=context)
            if settings.SMTP_USER:
                server.login(settings.SMTP_USER, settings.SMTP_PASS or "")
            server.sendmail(settings.EMAIL_FROM, [to], msg.as_string())
    except Exception as e:  # never let email break a request
        logger.error("Failed to send email to %s: %s", to, e)


async def send_email(to: str, subject: str, html: str, text: str) -> None:
    import asyncio
    await asyncio.to_thread(_send_sync, to, subject, html, text)


def _base(title: str, body_html: str) -> str:
    return f"""<html><body style="font-family:Arial,sans-serif;color:#222">
<h2 style="color:#1d4ed8">{title}</h2>
{body_html}
<hr><p style="font-size:12px;color:#888">ServiceSync &middot; AI contractor marketplace</p>
</body></html>"""


async def send_verification_email(email: str, token: str) -> None:
    base = settings.FRONTEND_URL or ""
    link = f"{base}/auth/verify-email?token={token}"
    html = _base("Verify your email",
                 f"<p>Welcome to ServiceSync. Confirm your address by opening:</p>"
                 f'<p><a href="{link}">{link}</a></p>')
    await send_email(email, "Verify your ServiceSync email", html, link)


async def send_password_reset_email(email: str, token: str) -> None:
    base = settings.FRONTEND_URL or ""
    link = f"{base}/auth/reset-password?token={token}"
    html = _base("Reset your password",
                 "<p>We received a request to reset your ServiceSync password.</p>"
                 f'<p><a href="{link}">{link}</a></p>'
                 "<p>If you didn't request this, you can ignore this email.</p>")
    await send_email(email, "Reset your ServiceSync password", html, link)


async def send_2fa_code_email(email: str, code: str) -> None:
    html = _base("Your admin login code",
                 f"<p>Your one-time admin login code is:</p>"
                 f'<p style="font-size:28px;letter-spacing:4px"><b>{code}</b></p>'
                 "<p>This code expires in 10 minutes.</p>")
    await send_email(email, "ServiceSync admin login code", html, f"Your code: {code}")
