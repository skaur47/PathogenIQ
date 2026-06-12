"""
Newsletter service — builds and sends the daily PathogenIQ digest email.

Each pathogen block includes:
  - Name, common name, category, WHO-priority badge
  - Short biological description
  - 1-2 recent surveillance/news documents
  - 1 highlighted research article

Uses smtplib (stdlib) via asyncio.to_thread so the async event loop is never blocked.
Set SMTP_HOST='' in the environment to disable delivery while still saving subscribers.
"""

import asyncio
import html as _html
import smtplib
import ssl
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import structlog

from app.config import get_settings
from app.db.models.newsletter import NewsletterSubscriber

logger = structlog.get_logger(__name__)

_SOURCE_LABELS: dict[str, str] = {
    "cdc": "CDC",
    "who": "WHO",
    "promed": "ProMED",
    "news": "News",
    "pubmed": "PubMed",
    "biorxiv": "bioRxiv",
    "clinical_trials": "ClinicalTrials",
    "manual": "Manual",
}


def _esc(text: str) -> str:
    return _html.escape(str(text), quote=True)


def _trunc(text: str, n: int) -> str:
    t = str(text)
    return t[:n] + "…" if len(t) > n else t


def _pathogen_row(p: dict) -> str:
    name     = _esc(p.get("species_name") or "Unknown")
    common   = _esc(p.get("common_name") or "")
    category = _esc((p.get("category") or "unknown").capitalize())
    desc_raw = (p.get("description") or "").strip()
    desc     = _esc(_trunc(desc_raw, 280)) if desc_raw else ""

    # ── Header ──────────────────────────────────────────────────────────────
    common_html = (
        f'&nbsp;<span style="font-size:12px;color:#64748b;">{common}</span>'
        if common else ""
    )
    category_badge = (
        f'<span style="display:inline-block;margin-left:6px;font-size:10px;'
        f'color:#475569;padding:1px 6px;border-radius:3px;background:#1e293b;">'
        f'{category}</span>'
    )

    header = (
        f'<p style="margin:0 0 6px;">'
        f'<span style="font-size:15px;font-weight:700;color:#f1f5f9;">{name}</span>'
        f'{common_html}{category_badge}'
        f'</p>'
    )

    # ── Description ─────────────────────────────────────────────────────────
    desc_html = (
        f'<p style="margin:0 0 12px;font-size:12px;color:#64748b;line-height:1.55;">'
        f'{desc}</p>'
        if desc else ""
    )

    # ── News articles ────────────────────────────────────────────────────────
    news_items_html = ""
    for article in p.get("news_articles") or []:
        title = _esc(_trunc(article.get("title") or "", 110))
        url   = _esc(article.get("url") or "#")
        src   = _esc(_SOURCE_LABELS.get(article.get("source") or "", (article.get("source") or "").upper()))
        news_items_html += (
            f'<tr><td style="padding:2px 0;">'
            f'<span style="font-size:10px;color:#475569;text-transform:uppercase;'
            f'letter-spacing:0.4px;">{src}</span>'
            f'&nbsp;<a href="{url}" style="font-size:12px;color:#94a3b8;'
            f'text-decoration:none;">{title}</a>'
            f'</td></tr>'
        )

    news_section = ""
    if news_items_html:
        news_section = (
            f'<p style="margin:0 0 4px;font-size:10px;font-weight:600;color:#475569;'
            f'text-transform:uppercase;letter-spacing:0.5px;">Surveillance</p>'
            f'<table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:10px;">'
            f'{news_items_html}'
            f'</table>'
        )

    # ── Research article ─────────────────────────────────────────────────────
    research_section = ""
    ra = p.get("research_article")
    if ra and ra.get("title"):
        ra_title   = _esc(_trunc(ra.get("title") or "", 110))
        ra_url     = _esc(ra.get("url") or "#")
        ra_authors = _esc(_trunc(ra.get("authors") or "", 80)) if ra.get("authors") else ""
        ra_summary_raw = (ra.get("summary") or "").strip()
        ra_summary = _esc(_trunc(ra_summary_raw, 200)) if ra_summary_raw else ""

        research_section = (
            f'<p style="margin:0 0 4px;font-size:10px;font-weight:600;color:#475569;'
            f'text-transform:uppercase;letter-spacing:0.5px;">Research Highlight</p>'
            f'<a href="{ra_url}" style="font-size:12px;color:#6366f1;'
            f'text-decoration:none;display:block;margin-bottom:2px;">{ra_title}</a>'
            + (f'<p style="margin:0 0 2px;font-size:11px;color:#475569;">{ra_authors}</p>' if ra_authors else "")
            + (f'<p style="margin:0;font-size:11px;color:#64748b;line-height:1.45;">{ra_summary}</p>' if ra_summary else "")
        )

    return (
        f'<tr><td style="padding:20px 0;border-bottom:1px solid #1e293b;">'
        f'{header}{desc_html}{news_section}{research_section}'
        f'</td></tr>'
    )


def _build_html(
    subscriber_name: str,
    pathogens: list[dict],
    unsubscribe_url: str,
) -> str:
    today = date.today().strftime("%B %d, %Y")
    count = len(pathogens)
    rows = "".join(_pathogen_row(p) for p in pathogens)
    if not rows:
        rows = (
            '<tr><td style="padding:16px 0;color:#64748b;font-size:13px;">'
            'No pathogens are currently being tracked.'
            '</td></tr>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0b0f1a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0b0f1a;">
    <tr><td align="center" style="padding:40px 16px;">
      <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">

        <!-- Header -->
        <tr>
          <td style="padding:0 0 28px;border-bottom:1px solid #1e293b;">
            <p style="margin:0 0 3px;font-size:20px;font-weight:700;color:#f1f5f9;">PathogenIQ</p>
            <p style="margin:0;font-size:12px;color:#475569;">Daily Digest &nbsp;·&nbsp; {today}</p>
          </td>
        </tr>

        <!-- Greeting -->
        <tr>
          <td style="padding:20px 0 16px;">
            <p style="margin:0;font-size:13px;color:#94a3b8;line-height:1.6;">
              Hi {_esc(subscriber_name)}, here is your daily update on infectious disease intelligence.
              PathogenIQ is tracking
              <strong style="color:#f1f5f9;">{count} pathogen{"s" if count != 1 else ""}</strong>
              across all sources. Each entry includes recent surveillance reports and a research highlight.
            </p>
          </td>
        </tr>

        <!-- Pathogens -->
        <tr>
          <td>
            <table width="100%" cellpadding="0" cellspacing="0">
              {rows}
            </table>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="padding:28px 0 0;">
            <p style="margin:0 0 6px;font-size:11px;color:#1e293b;border-top:1px solid #1e293b;padding-top:20px;">
              You are receiving this because you subscribed at PathogenIQ.
              PathogenIQ is a research intelligence tool — outputs require expert review before clinical application.
            </p>
            <p style="margin:0;font-size:11px;color:#334155;">
              <a href="{_esc(unsubscribe_url)}" style="color:#475569;text-decoration:underline;">Unsubscribe</a>
              &nbsp;·&nbsp;
              <a href="https://pathogen-iq.vercel.app" style="color:#475569;text-decoration:underline;">Dashboard</a>
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
        f"PathogenIQ is tracking {len(pathogens)} pathogen(s) across all sources.",
        "",
        "=" * 60,
    ]
    for p in pathogens:
        name   = p.get("species_name", "Unknown")
        common = p.get("common_name") or ""
        cat    = (p.get("category") or "unknown").capitalize()
        who    = "YES" if p.get("who_priority") else "No"
        desc   = _trunc((p.get("description") or "").strip(), 280)

        lines += [
            f"  {name}" + (f" ({common})" if common else "") + f"  [{cat}]" + ("  [WHO PRIORITY]" if p.get("who_priority") else ""),
        ]
        if desc:
            lines.append(f"  {desc}")

        news = p.get("news_articles") or []
        if news:
            lines.append("  Surveillance:")
            for a in news:
                src = _SOURCE_LABELS.get(a.get("source") or "", (a.get("source") or "").upper())
                lines.append(f"    [{src}] {_trunc(a.get('title') or '', 100)}")
                if a.get("url"):
                    lines.append(f"           {a['url']}")

        ra = p.get("research_article")
        if ra and ra.get("title"):
            lines.append("  Research Highlight:")
            lines.append(f"    {_trunc(ra.get('title') or '', 100)}")
            if ra.get("authors"):
                lines.append(f"    {_trunc(ra['authors'], 80)}")
            if ra.get("url"):
                lines.append(f"    {ra['url']}")
            if ra.get("summary"):
                lines.append(f"    {_trunc(ra['summary'], 200)}")

        lines.append("-" * 60)

    lines += [
        "",
        f"Unsubscribe: {unsubscribe_url}",
        "PathogenIQ is a research tool, not a clinical or diagnostic platform.",
    ]
    return "\n".join(lines)


def _send_smtp(to_email: str, subject: str, html: str, plain: str) -> None:
    settings = get_settings()
    if not settings.smtp_host:
        logger.info("newsletter_smtp_disabled", to=to_email)
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = settings.smtp_from
    msg["To"]      = to_email
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
    today   = date.today().strftime("%B %d, %Y")
    subject = f"PathogenIQ Daily Digest — {today}"

    html  = _build_html(subscriber.name, pathogens, unsubscribe_url)
    plain = _build_plain(subscriber.name, pathogens, unsubscribe_url)

    try:
        await asyncio.to_thread(_send_smtp, subscriber.email, subject, html, plain)
        logger.info("newsletter_sent", to=subscriber.email)
    except Exception as exc:
        logger.warning("newsletter_send_failed", to=subscriber.email, error=str(exc))
