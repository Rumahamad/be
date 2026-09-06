from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Protocol

from app.config.settings import Settings, get_settings


class EmailDeliveryError(Exception):
    pass


@dataclass(frozen=True)
class EmailAttachment:
    filename: str
    content: bytes
    mime_type: str


@dataclass(frozen=True)
class OutgoingEmail:
    recipient: str
    subject: str
    text: str
    html: str | None = None
    attachment: EmailAttachment | None = None


class EmailProvider(Protocol):
    name: str

    def send(self, email: OutgoingEmail) -> str | None: ...


class SMTPEmailProvider:
    name = "SMTP"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def send(self, email: OutgoingEmail) -> str | None:
        settings = self.settings
        self._validate_configuration()
        message = EmailMessage()
        message["From"] = formataddr((settings.smtp_from_name, settings.smtp_from_email))
        message["To"] = email.recipient
        message["Subject"] = email.subject
        message["Message-ID"] = make_msgid(domain=settings.smtp_from_email.rpartition("@")[2])
        if settings.smtp_reply_to:
            message["Reply-To"] = settings.smtp_reply_to
        message.set_content(email.text)
        if email.html:
            message.add_alternative(email.html, subtype="html")
        if email.attachment:
            main_type, sub_type = email.attachment.mime_type.split("/", 1)
            message.add_attachment(
                email.attachment.content,
                maintype=main_type,
                subtype=sub_type,
                filename=email.attachment.filename,
            )
        try:
            if settings.smtp_use_ssl:
                client = smtplib.SMTP_SSL(
                    settings.smtp_host,
                    settings.smtp_port,
                    timeout=settings.smtp_timeout_seconds,
                    context=ssl.create_default_context(),
                )
            else:
                client = smtplib.SMTP(
                    settings.smtp_host,
                    settings.smtp_port,
                    timeout=settings.smtp_timeout_seconds,
                )
            with client:
                if settings.smtp_use_tls and not settings.smtp_use_ssl:
                    client.starttls(context=ssl.create_default_context())
                if settings.smtp_username:
                    client.login(settings.smtp_username, settings.smtp_password)
                refused = client.send_message(message)
                if refused:
                    raise EmailDeliveryError("SMTP provider refused the recipient")
        except (OSError, smtplib.SMTPException) as exc:
            raise EmailDeliveryError("SMTP delivery failed") from exc
        return message.get("Message-ID")

    def _validate_configuration(self) -> None:
        settings = self.settings
        missing = [
            name
            for name, value in (
                ("SMTP_HOST", settings.smtp_host),
                ("SMTP_FROM_EMAIL", settings.smtp_from_email),
            )
            if not value
        ]
        if missing:
            raise EmailDeliveryError(f"SMTP configuration is incomplete: {', '.join(missing)}")
        if bool(settings.smtp_username) != bool(settings.smtp_password):
            raise EmailDeliveryError(
                "SMTP_USERNAME and SMTP_PASSWORD must either both be set or both be empty"
            )
        if settings.smtp_use_tls and settings.smtp_use_ssl:
            raise EmailDeliveryError("SMTP_USE_TLS and SMTP_USE_SSL cannot both be enabled")


def configured_email_provider(settings: Settings | None = None) -> EmailProvider | None:
    resolved = settings or get_settings()
    if not resolved.email_enabled:
        return None
    if resolved.email_provider == "smtp":
        return SMTPEmailProvider(resolved)
    raise EmailDeliveryError(f"Unsupported email provider: {resolved.email_provider}")
