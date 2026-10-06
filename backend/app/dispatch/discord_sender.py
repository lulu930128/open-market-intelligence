"""Discord transport only: bounded messages, ordered delivery, no retries."""
from __future__ import annotations

import http.client
import json
import re
from contextlib import closing
from dataclasses import dataclass
from uuid import uuid4
from urllib.parse import parse_qsl, urlencode, urlsplit

from app.dispatch.discord_report_events import report_event, safe_exception_fields


class DiscordDeliveryError(RuntimeError):
    """Safe diagnostic with no URL, response body, or underlying exception."""

    def __init__(
        self, reason: str, *, sent_chunks: int = 0, total_chunks: int = 0,
        status_code: int | None = None, outcome: str = "failed",
        cause_type: str | None = None, cause_errno: int | None = None,
        cause_winerror: int | None = None,
    ) -> None:
        self.reason = reason
        self.sent_chunks = sent_chunks
        self.total_chunks = total_chunks
        self.status_code = status_code
        self.outcome = outcome
        self.cause_type = cause_type
        self.cause_errno = cause_errno
        self.cause_winerror = cause_winerror
        super().__init__(
            f"Discord delivery {outcome}: {reason}; "
            f"sent_chunks={sent_chunks}/{total_chunks}; status_code={status_code}"
        )


def chunk_content(content: str, *, limit: int = 1900) -> list[str]:
    """Preserve text/order, prefer line boundaries; count UTF-16 conservatively."""
    if not 2 <= limit <= 2000:
        raise ValueError("Discord chunk limit must be between 2 and 2000.")
    if not content.strip():
        raise ValueError("Discord content must not be empty.")
    chunks: list[str] = []
    remaining = content
    while remaining:
        units = 0
        end = 0
        for character in remaining:
            width = 2 if ord(character) > 0xFFFF else 1
            if units + width > limit:
                break
            units += width
            end += 1
        if end < len(remaining):
            paragraph = remaining.rfind("\n\n", 0, end)
            newline = remaining.rfind("\n", 0, end)
            if paragraph >= 0 and remaining[:paragraph + 2].strip():
                end = paragraph + 2
            elif newline >= 0 and remaining[:newline + 1].strip():
                end = newline + 1
        chunks.append(remaining[:end])
        remaining = remaining[end:]
    # Reject whitespace-only segments before any delivery.
    if any(not chunk.strip() for chunk in chunks):
        raise ValueError("Discord content contains an empty message segment.")
    return chunks


def _webhook_target(webhook_url: str | None) -> tuple[str, str]:
    if not webhook_url or not webhook_url.strip():
        raise DiscordDeliveryError("secret not configured")
    target = None
    try:
        url = urlsplit(webhook_url.strip())
        if (
            url.scheme == "https"
            and url.hostname in {"discord.com", "discordapp.com"}
            and url.port in {None, 443}
            and url.username is None and url.password is None and not url.fragment
            and re.fullmatch(r"/api(?:/v\d+)?/webhooks/\d+/[A-Za-z0-9._-]+", url.path)
        ):
            query = dict(parse_qsl(url.query))
            # Preserve an explicitly configured forum thread; force confirmation.
            if set(query) <= {"wait", "thread_id"}:
                query["wait"] = "true"
                target = (url.hostname, url.path + "?" + urlencode(query))
    except ValueError:
        pass
    if target is None:
        raise DiscordDeliveryError("invalid webhook configuration")
    return target


def send_discord_report(webhook_url: str | None, content: str) -> dict[str, int | str]:
    host, path = _webhook_target(webhook_url)
    chunks = chunk_content(content)
    sent = 0
    for chunk in chunks:
        failure = None
        try:
            # A private stdlib connection emits no URL-bearing HTTP client logs,
            # follows no redirects, and performs no automatic retries.
            with closing(http.client.HTTPSConnection(host, timeout=30)) as connection:
                connection.request(
                    "POST", path,
                    body=json.dumps({
                        "content": chunk, "allowed_mentions": {"parse": []},
                    }, ensure_ascii=False).encode("utf-8"),
                    headers={"Content-Type": "application/json", "User-Agent": "OMI-Discord-Dispatch"},
                )
                response = connection.getresponse()
                status = response.status
                response.close()
            if not 200 <= status < 300:
                failure = DiscordDeliveryError(
                    "HTTP failure", sent_chunks=sent, total_chunks=len(chunks),
                    status_code=status,
                    outcome="unknown" if status >= 500 else "failed",
                )
        except Exception:
            # Do not retain/chain exceptions: their message may contain token
            # paths. A timeout/disconnect cannot prove the server did not send.
            failure = DiscordDeliveryError(
                "transport failure", sent_chunks=sent, total_chunks=len(chunks),
                outcome="unknown",
            )
        if failure is not None:
            raise failure
        sent += 1
    return {"status": "sent", "sent_chunks": sent, "total_chunks": len(chunks)}


@dataclass(frozen=True, repr=False)
class DiscordAttachment:
    filename: str
    data: bytes
    content_type: str


MAX_ATTACHMENT_BYTES = 2 * 1024 * 1024
MAX_TOTAL_ATTACHMENT_BYTES = 6 * 1024 * 1024
MAX_ATTACHMENTS = 5


def validate_rich_payload(*, content: str = "", embeds: list[dict] | None = None,
                          attachments: list[DiscordAttachment] | None = None) -> dict:
    """Strict local subset. Errors contain no caller values or credential URLs."""
    def reject() -> None:
        raise DiscordDeliveryError("invalid rich payload")

    def bounded(value: object, limit: int, *, empty: bool = False) -> int:
        if not isinstance(value, str) or (not empty and not value.strip()):
            reject()
        # Surrogates cannot be encoded as valid JSON UTF-8; reject before IO.
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            reject()
        units = sum(2 if ord(character) > 0xFFFF else 1 for character in value)
        if units > limit:
            reject()
        return units

    bounded(content, 2000, empty=True)
    embeds = [] if embeds is None else embeds
    attachments = [] if attachments is None else attachments
    if not isinstance(embeds, list) or len(embeds) > 10:
        reject()
    if not isinstance(attachments, list) or len(attachments) > MAX_ATTACHMENTS:
        reject()
    names = set()
    image_names = set()
    total_bytes = 0
    for attachment in attachments:
        if not isinstance(attachment, DiscordAttachment):
            reject()
        if (not isinstance(attachment.filename, str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", attachment.filename)
                or ".." in attachment.filename or attachment.filename in names):
            reject()
        if not isinstance(attachment.content_type, str) or attachment.content_type not in {"image/png", "text/plain; charset=utf-8", "application/json; charset=utf-8"}:
            reject()
        if not isinstance(attachment.data, bytes) or not 0 < len(attachment.data) <= MAX_ATTACHMENT_BYTES:
            reject()
        names.add(attachment.filename)
        if attachment.content_type == "image/png":
            image_names.add(attachment.filename)
        total_bytes += len(attachment.data)
    if total_bytes > MAX_TOTAL_ATTACHMENT_BYTES:
        reject()
    total_text = 0
    for embed in embeds:
        if not isinstance(embed, dict) or not embed or set(embed) - {
            "title", "description", "fields", "footer", "author", "color", "image", "thumbnail",
        }:
            reject()
        for key, limit in (("title", 256), ("description", 4096)):
            if key in embed:
                total_text += bounded(embed[key], limit)
        fields = embed.get("fields", [])
        if not isinstance(fields, list) or len(fields) > 25:
            reject()
        for item in fields:
            if not isinstance(item, dict) or set(item) - {"name", "value", "inline"}:
                reject()
            total_text += bounded(item.get("name"), 256)
            total_text += bounded(item.get("value"), 1024)
            if "inline" in item and not isinstance(item["inline"], bool):
                reject()
        for key, text_key, limit in (("footer", "text", 2048), ("author", "name", 256)):
            if key in embed:
                item = embed[key]
                if not isinstance(item, dict) or set(item) != {text_key}:
                    reject()
                total_text += bounded(item[text_key], limit)
        if "color" in embed and (type(embed["color"]) is not int or not 0 <= embed["color"] <= 0xFFFFFF):
            reject()
        for key in ("image", "thumbnail"):
            if key in embed:
                item = embed[key]
                if (not isinstance(item, dict) or set(item) != {"url"}
                        or not isinstance(item["url"], str)
                        or item["url"] not in {f"attachment://{name}" for name in image_names}):
                    reject()
    if total_text > 6000 or not (content.strip() or embeds or attachments):
        reject()
    return {"content": content, "embeds": embeds, "allowed_mentions": {"parse": []},
            "attachments": [{"id": index, "filename": attachment.filename}
                            for index, attachment in enumerate(attachments)]}


def encode_rich_payload(*, content: str = "", embeds: list[dict] | None = None,
                        attachments: list[DiscordAttachment] | None = None) -> tuple[bytes, str]:
    """Validate everything before opening the connection; encode one request."""
    payload = validate_rich_payload(content=content, embeds=embeds, attachments=attachments)
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if not attachments:
        return encoded, "application/json"
    boundary = "omi-" + uuid4().hex
    # Random boundary; guard even the extremely unlikely byte collision.
    while any(boundary.encode() in item.data for item in attachments) or boundary.encode() in encoded:
        boundary = "omi-" + uuid4().hex
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="payload_json"\r\n'
             'Content-Type: application/json; charset=utf-8\r\n\r\n'.encode() + encoded + b"\r\n"]
    for index, attachment in enumerate(attachments):
        parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="files[{index}]"; '
                      f'filename="{attachment.filename}"\r\nContent-Type: {attachment.content_type}\r\n\r\n').encode()
                     + attachment.data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def send_discord_rich_report(webhook_url: str | None, *, content: str = "",
                             embeds: list[dict] | None = None,
                             attachments: list[DiscordAttachment] | None = None) -> dict[str, int | str]:
    host, path = _webhook_target(webhook_url)
    body, content_type = encode_rich_payload(content=content, embeds=embeds, attachments=attachments)
    failure = None
    status = None
    report_event("transport_start")
    try:
        with closing(http.client.HTTPSConnection(host, timeout=30)) as connection:
            connection.request("POST", path, body=body,
                               headers={"Content-Type": content_type, "User-Agent": "OMI-Discord-Dispatch"})
            response = connection.getresponse()
            status = response.status
            report_event("transport_response", status_code=status)
            response.close()
        if not 200 <= status < 300:
            failure = DiscordDeliveryError("HTTP failure", total_chunks=1, status_code=status,
                                           outcome="unknown" if status >= 500 else "failed")
    except Exception as error:
        diagnostic = safe_exception_fields(error)
        failure = DiscordDeliveryError(
            "transport failure", total_chunks=1, outcome="unknown",
            cause_type=diagnostic["exception_type"], cause_errno=diagnostic["errno"],
            cause_winerror=diagnostic["winerror"])
    if failure is not None:
        report_event("transport_failed", exception_type=failure.cause_type,
                     errno=failure.cause_errno, winerror=failure.cause_winerror,
                     status_code=failure.status_code, outcome=failure.outcome)
        raise failure
    report_event("transport_sent", status_code=status, outcome="sent")
    return {"status": "sent", "sent_chunks": 1, "total_chunks": 1}
