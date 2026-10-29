"""Sends the report to the patient by email (SMTP) or SMS (Twilio).

SLOT: both channels stay switched off until their credentials are set in
`.env`. A different SMS provider only needs `send_sms` replaced.
"""

import smtplib
from email.message import EmailMessage

import anyio
import httpx

from .models import IntakeSession
from .settings import Settings


class DeliveryError(Exception):
    pass


def email_configured(s: Settings) -> bool:
    return bool(s.smtp_host and s.smtp_from)


def sms_configured(s: Settings) -> bool:
    return bool(s.twilio_account_sid and s.twilio_auth_token and s.twilio_from)


_URGENCY_TEXT = {
    "routine": "routine",
    "soon": "see a doctor soon",
    "urgent": "urgent",
    "emergency": "emergency",
}


def _summary_line(report: dict) -> str:
    urgency = _URGENCY_TEXT.get(report["urgency"], report["urgency"])
    return f"Department: {report['department']}. Urgency: {urgency}."


async def send_email(s: Settings, session: IntakeSession, report: dict, pdf: bytes) -> None:
    message = EmailMessage()
    message["Subject"] = "Your Medora pre-consultation report"
    message["From"] = s.smtp_from
    message["To"] = session.email
    message.set_content(
        f"Hello {session.name},\n\n"
        "Your pre-consultation report is attached.\n"
        f"{_summary_line(report)}\n\n"
        f"{report['disclaimer']}\n"
    )
    message.add_attachment(
        pdf, maintype="application", subtype="pdf", filename="medora-report.pdf"
    )

    def _send() -> None:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as smtp:
            smtp.starttls()
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(message)

    try:
        await anyio.to_thread.run_sync(_send)
    except (smtplib.SMTPException, OSError) as e:
        raise DeliveryError(f"The email could not be sent: {e}") from e


def _e164(s: Settings, phone: str) -> str:
    digits = "".join(c for c in phone if c.isdigit())
    if phone.strip().startswith("+"):
        return "+" + digits
    if s.sms_default_country_code:
        return s.sms_default_country_code + digits.lstrip("0")
    raise DeliveryError(
        "The phone number has no country code and "
        "MEDORA_SMS_DEFAULT_COUNTRY_CODE is not set"
    )


async def send_sms(s: Settings, session: IntakeSession, report: dict) -> None:
    body = f"Medora report for {session.name}. {_summary_line(report)}"
    if s.public_base_url:
        body += f" Full report: {s.public_base_url.rstrip('/')}/api/sessions/{session.id}/report.pdf"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{s.twilio_account_sid}/Messages.json",
                auth=(s.twilio_account_sid, s.twilio_auth_token),
                data={"From": s.twilio_from, "To": _e164(s, session.phone), "Body": body},
            )
    except httpx.HTTPError as e:
        raise DeliveryError(f"The SMS provider could not be reached: {e}") from e
    if response.status_code >= 400:
        try:
            detail = response.json().get("message", "")
        except ValueError:
            detail = ""
        raise DeliveryError(f"The SMS was rejected: {detail or response.status_code}")
