"""Discord transport only: bounded messages, ordered delivery, no retries."""
from __future__ import annotations

import http.client
import json
import re
from contextlib import closing
from urllib.parse import parse_qsl, urlencode, urlsplit


class DiscordDeliveryError(RuntimeError):
    """Safe diagnostic with no URL, response body, or underlying exception."""

    def __init__(
        self, reason: str, *, sent_chunks: int = 0, total_chunks: int = 0,
        status_code: int | None = None, outcome: str = "failed",
    ) -> None:
        self.reason = reason
        self.sent_chunks = sent_chunks
        self.total_chunks = total_chunks
        self.status_code = status_code
        self.outcome = outcome
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
