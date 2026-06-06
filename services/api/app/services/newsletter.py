"""
Newsletter service — builds and sends the daily PathogenIQ digest email.

Uses smtplib (stdlib) via asyncio.to_thread so the async event loop is never blocked.
Set SMTP_HOST='' in the environment to disable delivery while still saving subscribers.
"""

import asyncio
import smtplib
import ssl
import uuid
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import structlog

from app.config import get_settings
from app.db.models.newsletter import NewsletterSubscriber

logger = structlog.get_logger(__name__)


def _build_html(
    subscriber_name: str,
    pathogens: list[dict],
    unsubscribe_url: str,
) -> str:
    today = date.today().strftime("%B %d, %Y")

    rows = ""
    for p in pathogens:
        name = p.get("species_name", "Unknown")
        common = p.get("common_name") or ""
        category = (p.get("category") or "unknown").capitalize()
        routes = ", ".join(p.get("transmission_routes") or []) or "—"
        hosts = ", ".join(p.get("reservoir_hosts") or []) or "—"
        who = "Yes" if p.get("who_priority") else "No"
        desc = (p.get("description") or "")[:200]
        if len(p.get("description") or "") > 200:
            desc += "…"

        rows += f"""
        <tr>
          <td style="padding:16px 0;border-bottom:1px solid #1e293b;">
            <p style="margin:0 0 4px;font-size:15px;font-weight:600;color:#f1f5f9;">{name}</p>
            {f'<p style="margin:0 0 8px;font-size:12px;color:#64748b;">{common} &nbsp;·&nbsp; {category}</p>' if common else f'<p style="margin:0 0 8px;font-size:12px;color:#64748b;">{category}</p>'}
            <p style="margin:0 0 4px;font-size:12px;color:#94a3b8;">
              <span style="color:#64748b;">Transmission:</span> {routes}
            </p>
            <p style="margin:0 0 4px;font-size:12px;color:#94a3b8;">
              <span style="color:#64748b;">Reservoir:</span> {hosts}
            </p>
            <p style="margin:0 0 4px;font-size:12px;color:#94a3b8;">
              <span style="color:#64748b;">WHO Priority:</span> {who}
            </p>
            {f'<p style="margin:8px 0 0;font-size:12px;color:#64748b;line-height:1.5;">{desc}</p>' if desc else ''}
          </td>
        </tr>"""

    pathogen_count = len(pathogens)

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0b0f1a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0b0f1a;">
    <tr><td align="center" style="padding:40px 16px;">
      <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">

        <!-- Header -->
        <tr>
          <td style="padding:0 0 32px;">
            <p style="margin:0 0 4px;font-size:22px;font-weight:700;color:#f1f5f9;">PathogenIQ</p>
            <p style="margin:0;font-size:13px;color:#64748b;">Daily Digest &nbsp;·&nbsp; {today}</p>
          </td>
        </tr>

        <!-- Greeting -->
        <tr>
          <td style="padding:0 0 24px;">
            <p style="margin:0;font-size:14px;color:#94a3b8;line-height:1.6;">
              Hi {subscriber_name}, here is your daily update on infectious disease intelligence.
              PathogenIQ is currently tracking <strong style="color:#f1f5f9;">{pathogen_count} pathogen{"s" if pathogen_count != 1 else ""}</strong>.
            </p>
          </td>
        </tr>

        <!-- Pathogens -->
        <tr>
          <td>
            <table width="100%" cellpadding="0" cellspacing="0">
              {rows if rows else '<tr><td style="padding:16px 0;color:#64748b;font-size:13px;">No pathogens are currently being tracked.</td></tr>'}
            </table>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="padding:32px 0 0;">
            <p style="margin:0 0 8px;font-size:11px;color:#334155;">
              You are receiving this because you subscribed at PathogenIQ.
            </p>
            <p style="margin:0;font-size:11px;color:#334155;">
              <a href="{unsubscribe_url}" style="color:#64748b;text-decoration:underline;">Unsubscribe</a>
              &nbsp;·&nbsp; PathogenIQ is a research tool, not a clinical or diagnostic platform.
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _build_plain(subscriber_name: str, pathogens: list[dict], unsubscribe_url: str) -> str:
    today = date.today().strftime("%B %d, %Y")
    lines = [
        f"PathogenIQ Daily Digest — {today}",
        f"Hi {subscriber_name},",
        "",
        f"PathogenIQ is tracking {len(pathogens)} pathogen(s).",
        "",
    ]
    for p in pathogens:
        name = p.get("species_name", "Unknown")
        routes = ", ".join(p.get("transmission_routes") or []) or "—"
        hosts = ", ".join(p.get("reservoir_hosts") or []) or "—"
        who = "Yes" if p.get("who_priority") else "No"
        lines += [
            f"• {name}",
            f"  Transmission: {routes}",
            f"  Reservoir: {hosts}",
            f"  WHO Priority: {who}",
            "",
        ]
    lines += [
        "—",
        f"Unsubscribe: {unsubscribe_url}",
        "PathogenIQ is a research tool, not a clinical or diagnostic platform.",
    ]
    return "\n".join(lines)


def _send_smtp(
    to_email: str,
    subject: str,
    html: str,
    plain: str,
) -> None:
    settings = get_settings()
    if not settings.smtp_host:
        logger.info("newsletter_smtp_disabled", to=to_email)
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = to_email
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    ctx = ssl.create_default_context()
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        server.ehlo()
        server.starttls(context=ctx)
        server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(settings.smtp_from, to_email, msg.as_string())


async def send_digest_to(
    subscriber: NewsletterSubscriber,
    pathogens: list[dict],
) -> None:
    settings = get_settings()
    unsubscribe_url = (
        f"{settings.frontend_base_url}/contact"
        f"?unsubscribe={subscriber.unsubscribe_token}"
    )
    today = date.today().strftime("%B %d, %Y")
    subject = f"PathogenIQ Daily Digest — {today}"

    html = _build_html(subscriber.name, pathogens, unsubscribe_url)
    plain = _build_plain(subscriber.name, pathogens, unsubscribe_url)

    try:
        await asyncio.to_thread(_send_smtp, subscriber.email, subject, html, plain)
        logger.info("newsletter_sent", to=subscriber.email)
    except Exception as exc:
        logger.warning("newsletter_send_failed", to=subscriber.email, error=str(exc))
