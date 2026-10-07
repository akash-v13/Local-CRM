"""Turning a raw email (RFC 5322 bytes from IMAP) into what a case needs.

Pure functions, no I/O:

- `parse_email`: sender, subject, plain-text body (HTML converted if there's no
  text part), threading headers (Message-ID, In-Reply-To, References),
  attachment names/sizes, and whether it's an automatic message.
- `strip_quoted`: drop the quoted history under a reply ("On … wrote:", "> …",
  Outlook's "-----Original Message-----"), so a case shows what the customer
  actually wrote this time.
- `case_number_in`: the "[Case 1791…]" token our replies put in the subject,
  a fallback for threading when a mail client drops the In-Reply-To header.
"""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from html.parser import HTMLParser

CASE_TOKEN = re.compile(r"\[Case (\d{13,19})\]")
MSGID = re.compile(r"<[^<>\s]+>")


@dataclass
class Attachment:
    filename: str
    content_type: str
    size: int


@dataclass
class ParsedEmail:
    message_id: str
    subject: str
    from_address: str
    from_name: str | None
    to: list[str]
    cc: list[str]
    date: datetime | None
    in_reply_to: str | None
    references: list[str]
    text: str
    attachments: list[Attachment] = field(default_factory=list)
    automatic: str | None = None  # why it's automatic (auto-reply, bounce, list…), else None

    def thread_ids(self) -> list[str]:
        """Message-IDs this email replies to, most direct first."""
        ids = [self.in_reply_to] if self.in_reply_to else []
        return ids + [r for r in reversed(self.references) if r not in ids]


class _HtmlToText(HTMLParser):
    """Minimal HTML → text: keeps line breaks for block elements, drops scripts/styles."""

    BLOCKS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "blockquote", "table"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "head"):
            self.skip += 1
        elif tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "head"):
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _HtmlToText()
    parser.feed(html)
    text = "".join(parser.parts)
    lines = [re.sub(r"[ \t ]+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _automatic_reason(msg: EmailMessage, from_address: str) -> str | None:
    """Messages that must never open a case or get a reply (prevents mail loops)."""
    auto = str(msg.get("Auto-Submitted", "")).lower()
    if auto and auto != "no":
        return f"Auto-Submitted: {auto}"
    if msg.get("X-Autoreply") or msg.get("X-Autorespond"):
        return "auto-reply"
    precedence = str(msg.get("Precedence", "")).lower()
    if precedence in ("bulk", "junk", "list", "auto_reply"):
        return f"Precedence: {precedence}"
    if msg.get("List-Id") or msg.get("List-Unsubscribe"):
        return "mailing list"
    local = from_address.split("@")[0]
    if (
        local in ("mailer-daemon", "postmaster")
        or str(msg.get_content_type()) == "multipart/report"
    ):
        return "bounce"
    if re.fullmatch(r"no[-_.]?reply|do[-_.]?not[-_.]?reply", local):
        return "no-reply sender"
    return None


def _body(msg: EmailMessage) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    content = part.get_content()
    text = content if isinstance(content, str) else ""
    if part.get_content_type() == "text/html":
        text = html_to_text(text)
    return text.replace("\r\n", "\n").strip()


def parse_email(raw: bytes, *, fallback_id: str) -> ParsedEmail:
    """Parse raw RFC 5322 bytes. `fallback_id` is used when the email has no Message-ID
    (a stable value from the mailbox, so re-imports are still recognised)."""
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    assert isinstance(msg, EmailMessage)
    name, address = parseaddr(str(msg.get("From", "")))
    address = address.strip().lower()
    message_id = (MSGID.findall(str(msg.get("Message-ID", ""))) or [None])[0]
    if message_id is None:
        digest = hashlib.sha256(fallback_id.encode() + raw[:4096]).hexdigest()[:32]
        message_id = f"<{digest}@imported.local-crm>"
    in_reply_to = (MSGID.findall(str(msg.get("In-Reply-To", ""))) or [None])[0]
    try:
        date = parsedate_to_datetime(str(msg["Date"])) if msg.get("Date") else None
        if date is not None and date.tzinfo is None:
            date = date.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        date = None
    attachments = [
        Attachment(
            filename=part.get_filename() or "attachment",
            content_type=part.get_content_type(),
            size=len(part.get_payload(decode=True) or b""),
        )
        for part in msg.iter_attachments()
        if isinstance(part, EmailMessage)
    ]
    return ParsedEmail(
        message_id=message_id,
        subject=str(msg.get("Subject", "")).strip() or "(no subject)",
        from_address=address,
        from_name=name.strip() or None,
        to=[a.lower() for _, a in getaddresses([str(v) for v in msg.get_all("To", [])]) if a],
        cc=[a.lower() for _, a in getaddresses([str(v) for v in msg.get_all("Cc", [])]) if a],
        date=date,
        in_reply_to=in_reply_to,
        references=MSGID.findall(str(msg.get("References", ""))),
        text=_body(msg),
        attachments=attachments,
        automatic=_automatic_reason(msg, address),
    )


# Lines that start the quoted history in common mail clients.
_QUOTE_HEADERS = [
    re.compile(r"^On .{3,200}wrote:\s*$", re.I),  # Gmail, Apple Mail, Thunderbird
    re.compile(r"^-{2,}\s*Original Message\s*-{2,}\s*$", re.I),  # Outlook
    re.compile(r"^-{2,}\s*Forwarded message\s*-{2,}\s*$", re.I),
    re.compile(r"^From: .+$"),  # Outlook "From: … Sent: …" block
    re.compile(r"^_{10,}\s*$"),  # Outlook separator line
]


def strip_quoted(text: str) -> str:
    """The new part of a reply, without the quoted conversation below it.
    Returns the original text if stripping would leave nothing."""
    kept: list[str] = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if any(p.match(stripped) for p in _QUOTE_HEADERS):
            # "From:" only counts as a quote header if a Sent:/Date: line follows soon.
            if stripped.startswith("From:") and not any(
                re.match(r"^(Sent|Date):", lines[j].strip())
                for j in range(i + 1, min(i + 4, len(lines)))
            ):
                kept.append(line)
                continue
            break
        if stripped.startswith(">"):
            continue
        kept.append(line)
    result = "\n".join(kept).strip()
    return result or text.strip()


def case_number_in(subject: str) -> int | None:
    match = CASE_TOKEN.search(subject)
    return int(match.group(1)) if match else None


def reply_subject(subject: str, case_number: int) -> str:
    """ "Re: <subject> [Case N]" without piling up "Re: Re:" or repeating the token."""
    base = CASE_TOKEN.sub("", subject).strip()
    base = re.sub(r"^((re|fwd?|aw)\s*:\s*)+", "", base, flags=re.I).strip() or "Your request"
    return f"Re: {base} [Case {case_number}]"
