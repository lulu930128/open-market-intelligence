from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
import smtplib
from typing import Iterable

from app.config import settings


class MailSenderConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class SmtpMailSender:
    host: str
    port: int
    from_email: str
    from_name: str
    username: str | None = None
    password: str | None = None
    use_tls: bool = True
    use_ssl: bool = False
    timeout_seconds: int = 30

    @classmethod
    def from_settings(cls) -> "SmtpMailSender":
        host = (settings.dispatch_smtp_host or "").strip()
        from_email = (settings.dispatch_smtp_from_email or "").strip()

        if not host or not from_email:
            raise MailSenderConfigurationError(
                "SMTP dispatch is not configured. Set DISPATCH_SMTP_HOST and DISPATCH_SMTP_FROM_EMAIL."
            )

        return cls(
            host=host,
            port=int(settings.dispatch_smtp_port),
            from_email=from_email,
            from_name=(settings.dispatch_smtp_from_name or "Open Market Intelligence").strip(),
            username=(settings.dispatch_smtp_username or "").strip() or None,
            password=settings.dispatch_smtp_password,
            use_tls=bool(settings.dispatch_smtp_use_tls),
            use_ssl=bool(settings.dispatch_smtp_use_ssl),
            timeout_seconds=max(int(settings.dispatch_smtp_timeout_seconds), 1),
        )

    def _message(
        self,
        *,
        recipient: str,
        subject: str,
        body_text: str,
        body_html: str,
        message_id: str | None = None,
    ) -> EmailMessage:
        message = EmailMessage()
        message["From"] = formataddr((self.from_name, self.from_email))
        message["To"] = recipient
        message["Subject"] = subject
        if message_id:
            message["Message-ID"] = message_id
        message.set_content(body_text)
        message.add_alternative(body_html, subtype="html")
        return message

    def send(
        self,
        *,
        recipients: Iterable[str],
        subject: str,
        body_text: str,
        body_html: str,
        message_id: str | None = None,
    ) -> dict[str, int | str]:
        recipient_list = [recipient.strip() for recipient in recipients if recipient.strip()]
        if not recipient_list:
            raise ValueError("No recipients configured for dispatch.")

        smtp_class = smtplib.SMTP_SSL if self.use_ssl else smtplib.SMTP
        sent_count = 0

        with smtp_class(self.host, self.port, timeout=self.timeout_seconds) as smtp:
            if self.use_tls and not self.use_ssl:
                smtp.starttls()
            if self.username:
                smtp.login(self.username, self.password or "")

            for recipient in recipient_list:
                smtp.send_message(
                    self._message(
                        recipient=recipient,
                        subject=subject,
                        body_text=body_text,
                        body_html=body_html,
                        message_id=message_id,
                    )
                )
                sent_count += 1

        result: dict[str, int | str] = {
            "sent_count": sent_count,
            "requested_count": len(recipient_list),
        }
        if message_id:
            result["message_id"] = message_id
        return result
