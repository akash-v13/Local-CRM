"""Talking to mail servers: IMAP to read an inbox, SMTP to send replies.

`MailTransport` is the seam: services only use these three methods, and
tests replace the whole thing with a fake. `ImapSmtpTransport` is the real
implementation on the standard library (imaplib, smtplib).

Safety:
- Mail servers must resolve to public addresses (the same check connectors
  use), unless listed in EMAIL_ALLOWED_HOSTS (e.g. the local test server).
- TLS is required (implicit SSL or STARTTLS); `none` only works when
  EMAIL_ALLOW_INSECURE is on (local development).
- Reading uses BODY.PEEK so messages aren't marked read unless the inbox is
  set to `mark_as_read`.
"""

import imaplib
import re
import smtplib
import ssl
from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from typing import Literal, Protocol

from app.security.ssrf import UnsafeUrlError, check_host, resolve_host

Security = Literal["ssl", "starttls", "none"]


class MailError(Exception):
    """A mail server problem, with a message that's safe to show to the business."""


@dataclass(frozen=True)
class MailServer:
    host: str
    port: int
    security: Security


@dataclass(frozen=True)
class MailAccount:
    """Everything needed to connect (password already decrypted; never log this)."""

    address: str
    username: str
    password: str
    imap: MailServer
    smtp: MailServer
    folder: str = "INBOX"


@dataclass(frozen=True)
class FetchedMessage:
    uid: int
    raw: bytes


@dataclass(frozen=True)
class FetchResult:
    uid_validity: int
    messages: list[FetchedMessage]
    folder_count: int


@dataclass(frozen=True)
class ConnectionCheck:
    imap_ok: bool
    smtp_ok: bool
    imap_detail: str
    smtp_detail: str


class MailTransport(Protocol):
    def fetch(
        self,
        account: MailAccount,
        *,
        uid_validity: int | None,
        after_uid: int | None,
        since: datetime,
        limit: int,
        mark_as_read: bool,
    ) -> FetchResult:
        """New messages, oldest first: UIDs above `after_uid` when `uid_validity` still
        matches, otherwise everything received since `since`."""
        ...

    def send(self, account: MailAccount, message: EmailMessage) -> None: ...

    def test(self, account: MailAccount) -> ConnectionCheck: ...


@dataclass(frozen=True)
class TransportSettings:
    allowed_hosts: Collection[str]
    allow_insecure: bool
    timeout: float
    resolve: Callable[[str, int], list[str]] = resolve_host


class ImapSmtpTransport:
    def __init__(self, settings: TransportSettings) -> None:
        self.settings = settings

    # ----- safety -----------------------------------------------------------------------

    def _check(self, server: MailServer) -> None:
        if server.security == "none" and not self.settings.allow_insecure:
            raise MailError(f"{server.host}: a secure connection (SSL or STARTTLS) is required.")
        try:
            check_host(
                server.host,
                server.port,
                allowed_hosts=self.settings.allowed_hosts,
                resolve=self.settings.resolve,
            )
        except UnsafeUrlError as exc:
            raise MailError(str(exc)) from exc

    # ----- IMAP -------------------------------------------------------------------------

    def _imap(self, account: MailAccount) -> imaplib.IMAP4:
        server = account.imap
        self._check(server)
        context = ssl.create_default_context()
        try:
            if server.security == "ssl":
                conn: imaplib.IMAP4 = imaplib.IMAP4_SSL(
                    server.host, server.port, ssl_context=context, timeout=self.settings.timeout
                )
            else:
                conn = imaplib.IMAP4(server.host, server.port, timeout=self.settings.timeout)
                if server.security == "starttls":
                    conn.starttls(ssl_context=context)
            conn.login(account.username, account.password)
        except imaplib.IMAP4.error as exc:
            raise MailError(f"IMAP login failed for {account.username}: {_clean(exc)}") from exc
        except (OSError, ssl.SSLError) as exc:
            raise MailError(
                f"Couldn't connect to {server.host}:{server.port} ({_clean(exc)})."
            ) from exc
        return conn

    def _select(self, conn: imaplib.IMAP4, folder: str, readonly: bool) -> tuple[int, int]:
        status, data = conn.select(_quote(folder), readonly=readonly)
        if status != "OK":
            raise MailError(f"Folder '{folder}' wasn't found.")
        count = int(data[0] or 0) if data and data[0] else 0
        _, validity = conn.response("UIDVALIDITY")
        uid_validity = int(validity[0]) if validity and validity[0] else 0
        return uid_validity, count

    def fetch(
        self,
        account: MailAccount,
        *,
        uid_validity: int | None,
        after_uid: int | None,
        since: datetime,
        limit: int,
        mark_as_read: bool,
    ) -> FetchResult:
        conn = self._imap(account)
        try:
            current_validity, count = self._select(conn, account.folder, readonly=not mark_as_read)
            if uid_validity == current_validity and after_uid is not None:
                status, data = conn.uid("SEARCH", f"UID {after_uid + 1}:*")
            else:
                status, data = conn.uid("SEARCH", f"SINCE {since.strftime('%d-%b-%Y')}")
            if status != "OK":
                raise MailError("The mail server rejected the search.")
            uids = sorted(int(u) for u in (data[0] or b"").split())
            if after_uid is not None and uid_validity == current_validity:
                uids = [u for u in uids if u > after_uid]  # "N:*" always returns the last message
            messages: list[FetchedMessage] = []
            for uid in uids[:limit]:
                status, parts = conn.uid("FETCH", str(uid), "(BODY.PEEK[])")
                raw = next(
                    (p[1] for p in parts if isinstance(p, tuple) and isinstance(p[1], bytes)), None
                )
                if status != "OK" or raw is None:
                    continue
                messages.append(FetchedMessage(uid=uid, raw=raw))
                if mark_as_read:
                    conn.uid("STORE", str(uid), "+FLAGS", "(\\Seen)")
            return FetchResult(uid_validity=current_validity, messages=messages, folder_count=count)
        except imaplib.IMAP4.error as exc:
            raise MailError(f"IMAP error: {_clean(exc)}") from exc
        except OSError as exc:
            raise MailError(f"Connection to {account.imap.host} dropped ({_clean(exc)}).") from exc
        finally:
            _logout(conn)

    # ----- SMTP -------------------------------------------------------------------------

    def _smtp(self, account: MailAccount) -> smtplib.SMTP:
        server = account.smtp
        self._check(server)
        context = ssl.create_default_context()
        try:
            if server.security == "ssl":
                conn: smtplib.SMTP = smtplib.SMTP_SSL(
                    server.host, server.port, context=context, timeout=self.settings.timeout
                )
            else:
                conn = smtplib.SMTP(server.host, server.port, timeout=self.settings.timeout)
                if server.security == "starttls":
                    conn.starttls(context=context)
            conn.login(account.username, account.password)
        except smtplib.SMTPAuthenticationError as exc:
            raise MailError(f"SMTP login failed for {account.username}: {_clean(exc)}") from exc
        except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
            raise MailError(
                f"Couldn't connect to {server.host}:{server.port} ({_clean(exc)})."
            ) from exc
        return conn

    def send(self, account: MailAccount, message: EmailMessage) -> None:
        conn = self._smtp(account)
        try:
            conn.send_message(message)
        except smtplib.SMTPRecipientsRefused as exc:
            raise MailError(f"The recipient was refused: {_clean(exc)}") from exc
        except (smtplib.SMTPException, OSError) as exc:
            raise MailError(f"Sending failed: {_clean(exc)}") from exc
        finally:
            try:
                conn.quit()
            except (smtplib.SMTPException, OSError):
                pass

    def test(self, account: MailAccount) -> ConnectionCheck:
        try:
            conn = self._imap(account)
            try:
                _, count = self._select(conn, account.folder, readonly=True)
                imap_ok, imap_detail = (
                    True,
                    f"Signed in; '{account.folder}' has {count} message(s).",
                )
            finally:
                _logout(conn)
        except MailError as exc:
            imap_ok, imap_detail = False, str(exc)
        try:
            smtp = self._smtp(account)
            smtp.quit()
            smtp_ok, smtp_detail = True, "Signed in; ready to send."
        except (MailError, smtplib.SMTPException, OSError) as exc:
            smtp_ok, smtp_detail = False, str(exc)
        return ConnectionCheck(imap_ok, smtp_ok, imap_detail, smtp_detail)


def _quote(folder: str) -> str:
    return '"' + folder.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _clean(exc: BaseException) -> str:
    """Server messages arrive as bytes reprs; make them readable and short."""
    text = str(exc)
    text = re.sub(r"b'(.*?)'", r"\1", text)
    return text[:300]


def _logout(conn: imaplib.IMAP4) -> None:
    try:
        conn.logout()
    except (imaplib.IMAP4.error, OSError):
        pass
